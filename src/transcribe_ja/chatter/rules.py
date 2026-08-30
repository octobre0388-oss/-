"""ルールベースの雑談判定（既定・オフライン）。

各セグメントに点数を付け、合計が安全度ごとのしきい値を超えたら「不要」とする。
点数の内訳は判定理由としてカットログに残るので、あとから納得感を確認できる。

■ 安全側に倒す工夫

    * 本編を示す語（「資料」「議題」「決定」など）が含まれていれば大きく減点する
    * 長いセグメントは本編の可能性が高いとみなして減点する
    * 既定のしきい値（conservative = 0.80）は、複数の根拠が重ならないと
      超えられない値にしてある（例: 挨拶 0.50 だけでは切られない）
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from ..logging_setup import get_logger
from ..transcribe import TranscriptSegment

logger = get_logger("chatter.rules")

_DEFAULT_DICT = Path(__file__).resolve().parent / "dictionaries" / "chatter_ja.toml"

#: 判定理由を日本語で表示するための対応表。
CATEGORY_LABELS = {
    "greeting": "挨拶",
    "equipment": "機材・接続の確認",
    "smalltalk": "雑談",
    "closing": "締めの挨拶",
    "laughter_only": "笑い声のみ",
    "aizuchi_only": "相槌のみ",
    "low_density": "発話密度が低い",
    "near_edges": "冒頭・末尾",
    "short_fragment": "短い断片",
    "long_segment": "長い発話（本編の可能性）",
    "main_topic": "本編を示す語を含む",
}


@dataclass
class RuleSet:
    """判定に使うしきい値・重み・表現の一覧。"""

    thresholds: dict[str, float] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)
    patterns: dict[str, list[str]] = field(default_factory=dict)

    def threshold_for(self, safety: str) -> float:
        return float(self.thresholds.get(safety, self.thresholds.get("conservative", 0.8)))

    def weight(self, key: str, default: float = 0.0) -> float:
        return float(self.weights.get(key, default))

    def number(self, key: str, default: float) -> float:
        return float(self.thresholds.get(key, default))


def load_rules(directory: Path | None = None, filename: str = "chatter_ja.toml") -> RuleSet:
    """判定辞書を読み込む。読めない場合は同梱の既定辞書を使う。"""
    candidates = []
    if directory is not None:
        candidates.append(Path(directory) / filename)
    candidates.append(_DEFAULT_DICT)

    for path in candidates:
        if not path.is_file():
            continue
        try:
            with path.open("rb") as fp:
                data = tomllib.load(fp)
        except (tomllib.TOMLDecodeError, OSError) as exc:
            logger.warning("判定辞書を読めませんでした（次の候補を試します）: %s (%s)", path, exc)
            continue
        return RuleSet(
            thresholds={k: float(v) for k, v in (data.get("thresholds") or {}).items()},
            weights={k: float(v) for k, v in (data.get("weights") or {}).items()},
            patterns={
                k: [str(x) for x in v]
                for k, v in (data.get("patterns") or {}).items()
                if isinstance(v, list)
            },
        )

    logger.warning("判定辞書が見つかりませんでした。雑談カットは行いません。")
    return RuleSet()


@dataclass
class Judgement:
    """1 セグメントに対する判定結果。"""

    index: int
    segment: TranscriptSegment
    score: float
    reasons: list[str] = field(default_factory=list)
    unnecessary: bool = False

    def reason_text(self) -> str:
        """カットログに書く理由文。"""
        if not self.reasons:
            return "不要と判定"
        return "、".join(self.reasons)


def _matches(text: str, patterns: Sequence[str]) -> list[str]:
    return [p for p in patterns if p and p in text]


def _is_only(text: str, patterns: Sequence[str]) -> bool:
    """テキストが、指定した語と記号だけで構成されているか。"""
    stripped = re.sub(r"[\s、。！？!?・…「」（）()]", "", text)
    if not stripped:
        return True
    remaining = stripped
    for pattern in sorted(patterns, key=len, reverse=True):
        cleaned = re.sub(r"[\s、。！？!?・…「」（）()]", "", pattern)
        if cleaned:
            remaining = remaining.replace(cleaned, "")
    return not remaining


def judge_segments(
    segments: Sequence[TranscriptSegment],
    rules: RuleSet,
    safety: str = "conservative",
    total_duration: float | None = None,
) -> list[Judgement]:
    """全セグメントを判定して、点数と理由を付けて返す。"""
    if not segments:
        return []

    duration = total_duration or (segments[-1].end if segments else 0.0)
    edge_ratio = rules.number("edge_ratio", 0.10)
    head_limit = duration * edge_ratio
    tail_limit = duration * (1.0 - edge_ratio)
    low_density_cps = rules.number("low_density_cps", 1.5)
    long_seconds = rules.number("long_segment_seconds", 20.0)
    short_seconds = rules.number("short_segment_seconds", 2.0)
    threshold = rules.threshold_for(safety)

    results: list[Judgement] = []
    for index, segment in enumerate(segments):
        text = segment.text
        score = 0.0
        reasons: list[str] = []

        for category in ("greeting", "equipment", "smalltalk", "closing"):
            hits = _matches(text, rules.patterns.get(category, []))
            if hits:
                score += rules.weight(category)
                reasons.append(f"{CATEGORY_LABELS[category]}（{hits[0]}）")

        if rules.patterns.get("laughter") and _is_only(text, rules.patterns["laughter"]):
            score += rules.weight("laughter_only")
            reasons.append(CATEGORY_LABELS["laughter_only"])
        elif rules.patterns.get("aizuchi") and _is_only(text, rules.patterns["aizuchi"]):
            score += rules.weight("aizuchi_only")
            reasons.append(CATEGORY_LABELS["aizuchi_only"])

        if segment.char_per_second < low_density_cps:
            score += rules.weight("low_density")
            reasons.append(CATEGORY_LABELS["low_density"])

        if segment.start <= head_limit or segment.end >= tail_limit:
            score += rules.weight("near_edges")
            reasons.append(CATEGORY_LABELS["near_edges"])

        if segment.duration <= short_seconds:
            score += rules.weight("short_fragment")

        # --- 残す方向に働く要素 ---
        if segment.duration >= long_seconds:
            score += rules.weight("long_segment")

        main_hits = _matches(text, rules.patterns.get("main_topic", []))
        if main_hits:
            score += rules.weight("main_topic")
            reasons.append(f"※{CATEGORY_LABELS['main_topic']}（{main_hits[0]}）")

        score = max(0.0, min(1.0, score))
        results.append(
            Judgement(
                index=index,
                segment=segment,
                score=score,
                reasons=reasons,
                unnecessary=score >= threshold,
            )
        )

    return results
