"""処理全体の流れ。1 ファイルを受け取って結果ファイルを書き出すまで。

    1. 音声抽出・正規化      ffmpeg で 16kHz / モノラル / PCM16 に
    2. 無音カット            VAD で発話区間を検出して切り詰める
    3. 不要な雑談部分のカット （chatter モジュール。設定で無効化できる）
    4. 文字起こし            faster-whisper
    5. 日本語としての整形    フィラー除去・表記統一・句読点
    6. 出力                  元ファイルと同じフォルダへ

■ 時刻の取り扱い（重要）

2 と 3 で音声が短くなるため、4 が返す時刻は「カット後の時間軸」になる。
そのままでは元動画と突き合わせられないので、各カットで作った SegmentMap を
``then()`` で合成し、6 の直前で必ず元ファイルの時刻へ戻す。
この変換は :func:`to_output_segments` の 1 箇所だけで行う。
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Sequence

import numpy as np

from . import wavtools
from .config import Config
from .errors import InputFileNotFoundError, TranscribeJAError, UnsupportedFileError
from .ffmpeg_tools import Ffmpeg, MediaInfo, format_duration
from .logging_setup import get_logger
from .paths import ensure_free_space, ensure_path_usable, work_root
from .postprocess import format_segments
from .progress import ProgressReporter, Stage
from .segmap import SegmentMap
from .transcribe import TranscriptSegment, describe_setup, transcribe_samples
from .vad import detect_speech_intervals
from .writers import CutEntry, OutputMeta, OutputSegment, WrittenFile, write_outputs

logger = get_logger("pipeline")

#: 対応する拡張子（install.ps1 が登録する拡張子と一致させること）。
SUPPORTED_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".opus",
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".ts",
}

#: 作業に必要な一時領域の見積もり（1 秒あたりのバイト数 × 安全係数）。
#: 16kHz / 16bit / モノラル = 32,000 バイト/秒。抽出前後で 2 本持つので 3 倍みておく。
_BYTES_PER_SECOND = 32_000
_SAFETY_FACTOR = 3


@dataclass
class PipelineResult:
    """1 ファイル分の処理結果。"""

    source: Path
    written: list[WrittenFile] = field(default_factory=list)
    meta: OutputMeta | None = None
    segment_count: int = 0

    @property
    def output_dir(self) -> Path:
        return self.source.parent


def to_output_segments(
    segments: Sequence[TranscriptSegment], total_map: SegmentMap
) -> list[OutputSegment]:
    """カット後の時刻を持つセグメントを、元ファイルの時刻に変換する。

    **時間軸の変換はここでしか行わない。** 出力側は変換済みの前提で動く。
    """
    if total_map.is_empty():
        return []

    result: list[OutputSegment] = []
    for segment in segments:
        start, end = total_map.to_source_span(segment.start, segment.end)
        text = segment.text.strip()
        if not text:
            continue
        result.append(
            OutputSegment(start=start, end=end, text=text, speaker=segment.speaker)
        )
    result.sort(key=lambda s: (s.start, s.end))
    return result


def build_cut_entries(
    silence_map: SegmentMap, chatter_entries: Sequence[CutEntry] = ()
) -> list[CutEntry]:
    """カットした区間の記録を組み立てる（時刻は元ファイル基準）。"""
    entries = [
        CutEntry(start=iv.start, end=iv.end, reason="無音（発話が検出されなかった区間）")
        for iv in silence_map.removed_intervals()
    ]
    entries.extend(chatter_entries)
    entries.sort(key=lambda e: e.start)
    return entries


def validate_input(path: Path) -> Path:
    """入力ファイルを確認する。問題があれば日本語のエラーにする。"""
    ensure_path_usable(path)

    if not path.exists():
        raise InputFileNotFoundError(
            f"ファイルが見つかりませんでした。\n{path}",
            hint=(
                "ファイルが移動または削除されていないかご確認ください。\n"
                "ネットワーク上のファイルの場合は、接続が切れていないかもご確認ください。"
            ),
        )
    if path.is_dir():
        raise UnsupportedFileError(
            f"フォルダは処理できません。\n{path}",
            hint="音声ファイルまたは動画ファイルを選んでください。",
        )
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        supported = " ".join(sorted(SUPPORTED_EXTENSIONS))
        raise UnsupportedFileError(
            f"対応していない拡張子です: {path.suffix}\n{path.name}",
            hint=f"対応している拡張子は次のとおりです:\n{supported}",
        )
    if path.stat().st_size == 0:
        raise UnsupportedFileError(
            f"ファイルの中身が空です。\n{path.name}",
            hint="録画・録音が正常に保存されているかご確認ください。",
        )
    return path


def process_file(
    source: Path,
    config: Config,
    reporter: ProgressReporter | None = None,
    ffmpeg: Ffmpeg | None = None,
) -> PipelineResult:
    """1 ファイルを最初から最後まで処理する。

    Args:
        source: 入力ファイル。
        config: 設定。
        reporter: 進捗の報告先。省略時は何もしない。
        ffmpeg: 探索済みの ffmpeg。複数ファイルでは使い回すと速い。

    Returns:
        書き出したファイルを含む処理結果。

    Raises:
        TranscribeJAError: 想定内のエラー（日本語メッセージ付き）。
    """
    reporter = reporter or ProgressReporter(None)
    source = validate_input(Path(source))
    reporter.report(Stage.PREPARING, source.name)

    tools = ffmpeg or Ffmpeg.locate(
        config.advanced.ffmpeg_path, config.advanced.ffprobe_path
    )
    info: MediaInfo = tools.probe(source)
    audio_index = info.require_audio(config.audio.track)
    logger.info(
        "処理開始: %s（長さ %s / 音声トラック %d本）",
        source.name,
        format_duration(info.duration),
        len(info.audio_streams),
    )

    work_dir = Path(tempfile.mkdtemp(prefix="job_", dir=work_root()))
    ensure_free_space(
        work_dir, int(max(info.duration, 1.0) * _BYTES_PER_SECOND * _SAFETY_FACTOR)
    )

    try:
        return _run_stages(source, info, audio_index, config, reporter, tools, work_dir)
    finally:
        if config.general.keep_temp:
            logger.info("一時ファイルを残しました: %s", work_dir)
        else:
            shutil.rmtree(work_dir, ignore_errors=True)


def _run_stages(
    source: Path,
    info: MediaInfo,
    audio_index: int,
    config: Config,
    reporter: ProgressReporter,
    tools: Ffmpeg,
    work_dir: Path,
) -> PipelineResult:
    # --- 1. 音声抽出・正規化 ---------------------------------------------
    reporter.report(Stage.EXTRACTING, fraction=0.0)
    wav_path = work_dir / "audio.wav"
    tools.extract_audio(
        source,
        wav_path,
        audio_index=audio_index,
        normalize=config.audio.normalize,
        total_duration=info.duration,
        on_progress=lambda f: reporter.report(Stage.EXTRACTING, fraction=f),
    )

    samples, sample_rate = wavtools.read_wav(wav_path)
    source_duration = wavtools.duration_of(samples, sample_rate)
    if abs(source_duration - info.duration) > 1.0 and info.duration > 0:
        # 音量正規化は長さを変えないはずなので、大きくずれていたら記録に残す
        logger.warning(
            "抽出後の長さが元と異なります（元 %.1fs / 抽出後 %.1fs）",
            info.duration,
            source_duration,
        )
    logger.info("音声を抽出しました: %s", format_duration(source_duration))

    # --- 2. 無音カット ----------------------------------------------------
    if config.vad.enabled:
        reporter.report(Stage.VAD)
        speech_intervals, engine = detect_speech_intervals(samples, sample_rate, config.vad)
        silence_map = wavtools.build_map(speech_intervals, source_duration, sample_rate)
        samples = wavtools.cut_by_map(samples, silence_map, sample_rate)
        logger.info(
            "無音カット（%s）: %s を削除しました（全体の %.1f%%）",
            engine,
            format_duration(silence_map.removed_duration),
            silence_map.removed_ratio * 100,
        )
    else:
        engine = "無効"
        silence_map = SegmentMap.identity(source_duration)
        logger.info("無音カットは設定で無効になっています。")

    # --- 3. 不要な雑談部分のカット ---------------------------------------
    total_map = silence_map
    chatter_entries: list[CutEntry] = []
    chatter_method = "無効"
    chatter_removed = 0.0

    if config.chatter.enabled and not silence_map.is_empty():
        from .chatter import cut_chatter

        reporter.report(Stage.PRESCAN)
        chatter_result = cut_chatter(samples, sample_rate, config, silence_map, reporter)
        samples = chatter_result.samples
        total_map = chatter_result.total_map
        chatter_entries = chatter_result.cut_entries
        chatter_method = chatter_result.method
        chatter_removed = chatter_result.removed_duration

    # --- 4. 文字起こし ----------------------------------------------------
    reporter.report(Stage.TRANSCRIBING, fraction=0.0)
    model_description = describe_setup(config.whisper)
    logger.info("文字起こし設定: %s", model_description)

    def _on_progress(fraction: float, count: int) -> None:
        reporter.report(Stage.TRANSCRIBING, f"{count} 件", fraction)

    segments = transcribe_samples(
        samples,
        config.whisper,
        language=config.general.language,
        total_duration=wavtools.duration_of(samples, sample_rate),
        on_progress=_on_progress,
    )

    # --- 5. 元ファイルの時刻へ戻して整形 ---------------------------------
    reporter.report(Stage.FORMATTING)
    output_segments = to_output_segments(segments, total_map)

    if config.diarization.enabled and output_segments:
        from .diarize import apply_speakers

        reporter.report(Stage.DIARIZING)
        # 話者分離は「抽出直後の WAV（元の時間軸）」に対して行う。
        # カット後の音声を渡すと話者と時刻がずれるので注意。
        output_segments = apply_speakers(output_segments, wav_path, config)

    output_segments = format_segments(
        output_segments, config.format, config.dictionaries_dir
    )

    # --- 6. 出力 ----------------------------------------------------------
    reporter.report(Stage.WRITING)
    meta = OutputMeta(
        source_name=source.name,
        source_duration=source_duration,
        processed_duration=total_map.processed_duration,
        model_description=model_description,
        vad_engine=engine,
        chatter_method=chatter_method,
        silence_removed=silence_map.removed_duration,
        chatter_removed=chatter_removed,
        created_at=datetime.now(),
    )
    written = write_outputs(
        destination_dir=source.parent,
        source_stem=source.stem,
        suffix=config.output.suffix,
        formats=config.output.formats,
        segments=output_segments,
        cut_entries=build_cut_entries(silence_map, chatter_entries),
        meta=meta,
        line_width=config.format.line_width,
    )

    reporter.report(Stage.DONE, f"{len(written)} ファイル")
    logger.info(
        "完了: %s（%d セグメント / %d ファイル出力）",
        source.name,
        len(output_segments),
        len(written),
    )
    return PipelineResult(
        source=source, written=written, meta=meta, segment_count=len(output_segments)
    )
