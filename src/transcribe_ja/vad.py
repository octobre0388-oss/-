"""発話区間の検出（VAD）による無音カット。

■ なぜ ffmpeg の silenceremove を使わないのか

silenceremove は「音量がしきい値以下の区間」を切る単純な仕組みなので、
空調音・BGM・ノイズが乗った素材では無音と判定されず、ほとんど切れない。
逆にしきい値を上げると小声の発話まで消える。
Silero VAD は「人の声かどうか」を学習済みモデルで判定するため、
BGM の上に乗った発話も正しく残せる。

■ 検出方式の優先順位

    1. Silero VAD（既定・もっとも正確）
    2. webrtcvad（軽量。torch が入らない環境向け）
    3. 音量ベースの簡易判定（最後の手段。精度は落ちるが処理は止めない）

どれも使えない場合でも、無音カットを飛ばして文字起こしは続行する。
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from .config import VadConfig
from .logging_setup import get_logger
from .segmap import EPS, Interval, normalize_intervals

logger = get_logger("vad")

#: 簡易判定のしきい値を、静かな部分と大きい部分のどこに置くか（0.0〜1.0）。
#: 0.3 なら「静かな部分から 3 割ほど上」を発話の境目とみなす。
_ENERGY_LEVEL = 0.3

#: 簡易判定のフレーム長（秒）。
_ENERGY_FRAME = 0.03


def refine_intervals(
    raw: Sequence[Interval] | Sequence[Sequence[float]],
    total_duration: float,
    *,
    min_silence_ms: int = 700,
    padding_ms: int = 200,
    min_speech_ms: int = 250,
) -> list[Interval]:
    """検出した生の発話区間を、実際に残す区間に整える。

    処理の順序に意味がある:

        1. 短すぎる発話を捨てる（咳やノイズを拾わないため）
        2. 短い無音を埋めて 1 本にまとめる（文の途中の息継ぎで切らないため）
        3. 前後に余白を付ける（語頭・語尾の欠けを防ぐため）
        4. 音声の範囲に収め、重なりを解消する

    2 の前に 3 をやると、短い発話が余白で伸びて残ってしまうため順序は変えないこと。

    Args:
        raw: 検出された発話区間（秒）。
        total_duration: 音声全体の長さ（秒）。
        min_silence_ms: これより短い無音は切り取らない。
        padding_ms: 発話区間の前後に残す余白。
        min_speech_ms: これより短い発話は捨てる。

    Returns:
        残す区間（昇順・重なりなし）。
    """
    intervals = normalize_intervals(raw)
    if not intervals:
        return []

    min_speech = min_speech_ms / 1000.0
    min_silence = min_silence_ms / 1000.0
    padding = padding_ms / 1000.0

    # 1. 短すぎる発話を捨てる
    intervals = [iv for iv in intervals if iv.duration >= min_speech - EPS]
    if not intervals:
        return []

    # 2. 短い無音でつながっている区間を結合する
    merged: list[Interval] = [intervals[0]]
    for iv in intervals[1:]:
        gap = iv.start - merged[-1].end
        if gap < min_silence - EPS:
            merged[-1] = Interval(merged[-1].start, max(merged[-1].end, iv.end))
        else:
            merged.append(iv)

    # 3. 前後に余白を付ける / 4. 範囲内に収めて重なりを解消する
    padded = [
        Interval(max(0.0, iv.start - padding), min(total_duration, iv.end + padding))
        for iv in merged
    ]
    return normalize_intervals(padded)


# --- 各エンジン -----------------------------------------------------------------


def _detect_silero(
    samples: np.ndarray, sample_rate: int, threshold: float
) -> list[Interval] | None:
    """Silero VAD で発話区間を検出する。使えない場合は None を返す。"""
    try:
        import torch  # noqa: F401  (silero_vad が内部で使う)
        from silero_vad import get_speech_timestamps, load_silero_vad
    except Exception as exc:  # pragma: no cover - 環境依存
        logger.warning("Silero VAD を読み込めませんでした: %s", exc)
        return None

    try:
        model = load_silero_vad()
        timestamps = get_speech_timestamps(
            torch.from_numpy(samples),
            model,
            sampling_rate=sample_rate,
            threshold=threshold,
            return_seconds=True,
        )
    except Exception as exc:  # pragma: no cover - 環境依存
        logger.warning("Silero VAD の実行に失敗しました: %s", exc)
        return None

    return [Interval(float(t["start"]), float(t["end"])) for t in timestamps]


def _detect_webrtc(
    samples: np.ndarray, sample_rate: int, threshold: float
) -> list[Interval] | None:
    """webrtcvad で発話区間を検出する。使えない場合は None を返す。"""
    try:
        import webrtcvad
    except Exception as exc:  # pragma: no cover - 環境依存
        logger.warning("webrtcvad を読み込めませんでした: %s", exc)
        return None

    # webrtcvad の感度は 0（緩い）〜3（厳しい）の 4 段階。
    # config の threshold(0.0〜1.0) を素直に割り当てる。
    aggressiveness = min(3, max(0, int(round(threshold * 3))))
    frame_ms = 30
    frame_len = int(sample_rate * frame_ms / 1000)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()

    try:
        vad = webrtcvad.Vad(aggressiveness)
    except Exception as exc:  # pragma: no cover
        logger.warning("webrtcvad の初期化に失敗しました: %s", exc)
        return None

    intervals: list[Interval] = []
    start: float | None = None
    total_frames = len(samples) // frame_len
    for i in range(total_frames):
        chunk = pcm[i * frame_len * 2 : (i + 1) * frame_len * 2]
        try:
            speaking = vad.is_speech(chunk, sample_rate)
        except Exception:  # pragma: no cover
            speaking = True
        t = i * frame_ms / 1000.0
        if speaking and start is None:
            start = t
        elif not speaking and start is not None:
            intervals.append(Interval(start, t))
            start = None
    if start is not None:
        intervals.append(Interval(start, total_frames * frame_ms / 1000.0))
    return intervals


def _detect_energy(samples: np.ndarray, sample_rate: int) -> list[Interval]:
    """音量ベースの簡易判定（最後の手段）。

    全体の音量分布を見て、相対的に大きい区間を発話とみなす。
    絶対値のしきい値を使わないので、録音レベルが低い素材でもある程度動く。
    """
    frame_len = max(1, int(sample_rate * _ENERGY_FRAME))
    frame_count = len(samples) // frame_len
    if frame_count == 0:
        return [Interval(0.0, len(samples) / sample_rate)] if len(samples) else []

    frames = samples[: frame_count * frame_len].reshape(frame_count, frame_len)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))

    # 中央値を基準にすると、発話が大半を占める素材で基準が発話側に寄ってしまう。
    # そこで下位 10% を静寂、上位 90% を発話の代表値とみなし、その間に線を引く。
    quiet = float(np.percentile(rms, 10))
    loud = float(np.percentile(rms, 90))
    if loud - quiet < 1e-6:
        # 音量に差が無い（ずっと無音、またはずっと一定）。切らずに全体を残す。
        return [Interval(0.0, len(samples) / sample_rate)]
    threshold = quiet + (loud - quiet) * _ENERGY_LEVEL
    speaking = rms > threshold

    intervals: list[Interval] = []
    start: int | None = None
    for i, flag in enumerate(speaking):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            intervals.append(Interval(start * _ENERGY_FRAME, i * _ENERGY_FRAME))
            start = None
    if start is not None:
        intervals.append(Interval(start * _ENERGY_FRAME, frame_count * _ENERGY_FRAME))
    return intervals


# --- 公開 API -------------------------------------------------------------------


def detect_speech_intervals(
    samples: np.ndarray, sample_rate: int, cfg: VadConfig
) -> tuple[list[Interval], str]:
    """発話区間を検出して、残す区間と使用したエンジン名を返す。

    Returns:
        (残す区間のリスト, エンジン名)。エンジン名はログとカットログに残す。
    """
    total_duration = len(samples) / float(sample_rate)
    if total_duration <= 0:
        return [], "なし"

    order = ["silero", "webrtc"] if cfg.engine == "silero" else ["webrtc", "silero"]
    raw: list[Interval] | None = None
    used = ""

    for engine in order:
        if engine == "silero":
            raw = _detect_silero(samples, sample_rate, cfg.threshold)
        else:
            raw = _detect_webrtc(samples, sample_rate, cfg.threshold)
        if raw is not None:
            used = engine
            break

    if raw is None:
        logger.warning(
            "VAD ライブラリが使えないため、音量ベースの簡易判定に切り替えます。"
        )
        raw = _detect_energy(samples, sample_rate)
        used = "簡易（音量）"

    if not raw:
        # 何も検出できなかった場合は、切らずに全体を残す（安全側）。
        logger.warning("発話区間を検出できなかったため、無音カットを行いません。")
        return [Interval(0.0, total_duration)], f"{used}（検出なしのため未カット）"

    refined = refine_intervals(
        raw,
        total_duration,
        min_silence_ms=cfg.min_silence_ms,
        padding_ms=cfg.padding_ms,
        min_speech_ms=cfg.min_speech_ms,
    )
    if not refined:
        logger.warning("整形後に区間が残らなかったため、無音カットを行いません。")
        return [Interval(0.0, total_duration)], f"{used}（整形後に残らず未カット）"

    return refined, used
