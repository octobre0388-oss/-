"""不要な雑談部分のカット（2 パス構成）。

    パス1（下読み）: 小型モデルで高速に粗い文字起こしを行い、時刻付きの
                     セグメント一覧を得る
    判定           : ルールベース（既定）または LLM で本編／不要を分類
    カット         : 不要と判定した区間を音声から取り除き、セグメントマップに反映

■ 安全装置

    1. 既定の安全度は "conservative"（迷ったら残す）
    2. [chatter] max_cut_ratio を超える量は切らない。超えた場合は
       確信度の低い判定から順に「残す」へ戻す
    3. 切った区間は必ずカットログに残す（元ファイルの時刻・理由・本文）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from .. import wavtools
from ..config import Config
from ..logging_setup import get_logger
from ..progress import ProgressReporter, Stage
from ..segmap import Interval, SegmentMap, normalize_intervals
from ..transcribe import TranscriptSegment, transcribe_samples
from ..writers import CutEntry
from .rules import Judgement, judge_segments, load_rules

logger = get_logger("chatter")

__all__ = ["ChatterResult", "cut_chatter", "select_cuts", "complement_intervals"]


@dataclass
class ChatterResult:
    """雑談カットの結果。"""

    samples: np.ndarray
    total_map: SegmentMap
    cut_entries: list[CutEntry] = field(default_factory=list)
    method: str = "無効"
    removed_duration: float = 0.0


def complement_intervals(
    cut: Sequence[Interval], total_duration: float
) -> list[Interval]:
    """カットする区間の「残り」（＝残す区間）を求める。"""
    kept: list[Interval] = []
    cursor = 0.0
    for interval in normalize_intervals(cut):
        if interval.start - cursor > 0:
            kept.append(Interval(cursor, interval.start))
        cursor = max(cursor, interval.end)
    if total_duration - cursor > 0:
        kept.append(Interval(cursor, total_duration))
    return kept


def select_cuts(
    judgements: Sequence[Judgement], total_duration: float, max_cut_ratio: float
) -> list[Judgement]:
    """カットする判定を選ぶ（削りすぎないよう上限を適用する）。

    合計が上限を超える場合、点数の低い（＝確信の弱い）判定から順に取り消す。
    誤判定で本編が丸ごと消える事故を防ぐための安全装置。
    """
    candidates = [j for j in judgements if j.unnecessary]
    if not candidates or total_duration <= 0:
        return []

    limit = total_duration * max_cut_ratio
    total = sum(j.segment.duration for j in candidates)
    if total <= limit:
        return sorted(candidates, key=lambda j: j.segment.start)

    # 点数の高い順に、上限に収まるところまで採用する
    accepted: list[Judgement] = []
    used = 0.0
    for judgement in sorted(candidates, key=lambda j: (-j.score, j.segment.start)):
        if used + judgement.segment.duration > limit:
            continue
        accepted.append(judgement)
        used += judgement.segment.duration

    logger.warning(
        "雑談カットが上限（%.0f%%）を超えたため、%d 件中 %d 件だけを削除します。",
        max_cut_ratio * 100,
        len(candidates),
        len(accepted),
    )
    return sorted(accepted, key=lambda j: j.segment.start)


def _prescan(
    samples: np.ndarray,
    sample_rate: int,
    config: Config,
    reporter: ProgressReporter,
) -> list[TranscriptSegment]:
    """パス1: 小型モデルで粗く文字起こしする。"""
    duration = wavtools.duration_of(samples, sample_rate)

    def _on_progress(fraction: float, count: int) -> None:
        reporter.report(Stage.PRESCAN, f"{count} 件", fraction)

    return transcribe_samples(
        samples,
        config.whisper,
        language=config.general.language,
        model_size=config.chatter.prescan_model,
        # 下読みは速度優先。細かい時刻は本番で取り直す。
        beam_size=1,
        word_timestamps=False,
        total_duration=duration,
        on_progress=_on_progress,
    )


def _judge(
    segments: Sequence[TranscriptSegment], config: Config, total_duration: float
) -> tuple[list[Judgement], str]:
    """設定に従って判定を行い、判定結果と使用した方式名を返す。"""
    if config.chatter.method == "llm":
        from . import llm

        result = llm.classify(segments, config.chatter)
        if result is not None:
            return result, f"AI 判定（{config.chatter.llm_model}）"
        logger.info("AI 判定が使えないため、ルールベース判定に切り替えます。")

    rules = load_rules(config.dictionaries_dir, config.chatter.rules_file)
    judgements = judge_segments(
        segments, rules, config.chatter.safety, total_duration=total_duration
    )
    return judgements, f"ルールベース判定（安全度: {config.chatter.safety}）"


def cut_chatter(
    samples: np.ndarray,
    sample_rate: int,
    config: Config,
    silence_map: SegmentMap,
    reporter: ProgressReporter,
) -> ChatterResult:
    """不要な雑談部分を検出してカットする。

    Args:
        samples: 無音カット済みの音声。
        sample_rate: サンプリングレート。
        config: 設定。
        silence_map: 無音カットのセグメントマップ（元ファイル ← 無音除去後）。
        reporter: 進捗の報告先。

    Returns:
        カット後の音声と、元ファイルまで戻せる合成済みマップ。
    """
    duration = wavtools.duration_of(samples, sample_rate)
    if duration <= 0:
        return ChatterResult(samples=samples, total_map=silence_map, method="対象なし")

    # --- パス1: 下読み ---------------------------------------------------
    segments = _prescan(samples, sample_rate, config, reporter)
    if not segments:
        logger.info("下読みで発話が見つからなかったため、雑談カットは行いません。")
        return ChatterResult(samples=samples, total_map=silence_map, method="発話なし")

    # --- 判定 -------------------------------------------------------------
    reporter.report(Stage.CHATTER, f"{len(segments)} 件")
    judgements, method = _judge(segments, config, duration)
    selected = select_cuts(judgements, duration, config.chatter.max_cut_ratio)

    if not selected:
        logger.info("不要と判定された区間はありませんでした（%s）", method)
        return ChatterResult(samples=samples, total_map=silence_map, method=method)

    # --- カット -----------------------------------------------------------
    cut_intervals = [j.segment.as_interval() for j in selected]
    kept = complement_intervals(cut_intervals, duration)
    chatter_map = wavtools.build_map(kept, duration, sample_rate)
    new_samples = wavtools.cut_by_map(samples, chatter_map, sample_rate)

    # 無音カットと合成して、元ファイルの時間軸まで戻せるようにする
    total_map = silence_map.then(chatter_map)

    # --- カットログ（時刻は必ず元ファイル基準に変換する） ------------------
    entries: list[CutEntry] = []
    for judgement in selected:
        for span in silence_map.split_to_source(
            judgement.segment.start, judgement.segment.end
        ):
            entries.append(
                CutEntry(
                    start=span.start,
                    end=span.end,
                    reason=f"雑談・不要と判定（{judgement.reason_text()}）",
                    text=judgement.segment.text,
                )
            )

    removed = chatter_map.removed_duration
    logger.info(
        "雑談カット（%s）: %d 区間 / %.1f 秒を削除しました（全体の %.1f%%）",
        method,
        len(selected),
        removed,
        chatter_map.removed_ratio * 100,
    )

    return ChatterResult(
        samples=new_samples,
        total_map=total_map,
        cut_entries=entries,
        method=method,
        removed_duration=removed,
    )
