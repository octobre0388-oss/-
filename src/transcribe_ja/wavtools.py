"""16kHz / モノラル / PCM 16bit の WAV を読み書き・切り貼りする。

■ なぜ ffmpeg ではなく自前で切るのか

無音カットや雑談カットは「残す区間をつなぎ合わせる」処理だが、
ffmpeg の filter_complex で数百区間を連結すると、コマンドが極端に長くなり、
区間境界のフレーム丸めによって数十ミリ秒のずれが積み重なる。
すでに 16kHz モノラル PCM に変換済みなら、Python 側でサンプル単位に
切り貼りするほうが正確で速く、しかも SegmentMap の時刻と完全に一致する。

■ サンプルグリッドへのスナップ

秒（float）で表された区間をサンプル番号（整数）に丸めると、
SegmentMap が持つ時刻と実際の音声長がわずかにずれる。
これを防ぐため、切る前に :func:`snap_intervals` で区間をサンプル境界へ
丸め、その結果から SegmentMap を作る。こうすると
「SegmentMap の processed_duration」＝「実際に出力した音声の長さ」になる。
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from .errors import FfmpegFailedError
from .segmap import Interval, SegmentMap, normalize_intervals

#: 本ツールが内部で扱う音声の仕様。faster-whisper / Silero VAD の要求に合わせている。
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # bytes = 16bit


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """PCM16 モノラル WAV を float32 (-1.0〜1.0) の配列として読み込む。

    Returns:
        (サンプル配列, サンプリングレート)

    Raises:
        FfmpegFailedError: WAV として読めない、または想定外の形式の場合。
    """
    try:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
    except (wave.Error, OSError, EOFError) as exc:
        raise FfmpegFailedError(
            f"変換後の音声ファイルを読み込めませんでした。\n{path}\n（{exc}）"
        ) from exc

    if width != SAMPLE_WIDTH:
        raise FfmpegFailedError(
            f"想定外の音声形式です（16bit ではなく {width * 8}bit）。"
        )

    data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        # 念のため。抽出時にモノラル化しているので通常ここは通らない。
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def write_wav(path: Path, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    """float32 配列を PCM16 モノラル WAV として書き出す。"""
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
    except (wave.Error, OSError) as exc:
        raise FfmpegFailedError(
            f"音声ファイルを書き出せませんでした。\n{path}\n（{exc}）"
        ) from exc


def duration_of(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    return len(samples) / float(sample_rate)


def snap_intervals(
    intervals: Iterable[Sequence[float] | Interval],
    total_duration: float,
    sample_rate: int = SAMPLE_RATE,
) -> list[Interval]:
    """区間をサンプル境界に丸め、音声の範囲内に収める。

    SegmentMap を作る前に必ずこれを通すと、地図と実際の音声長が一致する。
    """
    total_samples = int(round(total_duration * sample_rate))
    snapped: list[Interval] = []
    for iv in normalize_intervals(intervals):
        start = max(0, min(int(round(iv.start * sample_rate)), total_samples))
        end = max(0, min(int(round(iv.end * sample_rate)), total_samples))
        if end - start <= 0:
            continue
        snapped.append(Interval(start / sample_rate, end / sample_rate))
    return normalize_intervals(snapped)


def cut_by_map(
    samples: np.ndarray, segment_map: SegmentMap, sample_rate: int = SAMPLE_RATE
) -> np.ndarray:
    """SegmentMap が「残す」とした区間だけを取り出してつなげる。

    区間はサンプル境界に丸められている前提（:func:`snap_intervals` を通すこと）。
    """
    if segment_map.is_empty():
        return np.zeros(0, dtype=np.float32)

    pieces: list[np.ndarray] = []
    for iv in segment_map.kept:
        start = max(0, int(round(iv.start * sample_rate)))
        end = min(len(samples), int(round(iv.end * sample_rate)))
        if end > start:
            pieces.append(samples[start:end])
    if not pieces:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(pieces)


def build_map(
    intervals: Iterable[Sequence[float] | Interval],
    total_duration: float,
    sample_rate: int = SAMPLE_RATE,
) -> SegmentMap:
    """残す区間から、サンプル境界に丸めた SegmentMap を作る。"""
    snapped = snap_intervals(intervals, total_duration, sample_rate)
    return SegmentMap(snapped, source_duration=total_duration)


def make_tone(
    duration: float,
    frequency: float = 440.0,
    sample_rate: int = SAMPLE_RATE,
    amplitude: float = 0.3,
) -> np.ndarray:
    """テスト用の正弦波を作る。"""
    t = np.arange(int(duration * sample_rate), dtype=np.float32) / sample_rate
    return (amplitude * np.sin(2 * np.pi * frequency * t)).astype(np.float32)


def make_silence(duration: float, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """テスト用の無音を作る。"""
    return np.zeros(int(duration * sample_rate), dtype=np.float32)
