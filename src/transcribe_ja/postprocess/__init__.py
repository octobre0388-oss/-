"""文字起こし結果を、日本語として読みやすい形に整える。

処理の順序には意味がある:

    1. フィラー除去    「えー、あの、これは」→「、これは」
    2. 言い直しの整理  「これは、これはですね」→「これはですね」
    3. 表記の統一      全角英数字を半角に、数字表記を揃える
    4. 句読点の整形    1 と 2 で生じた「、、」や行頭の読点を掃除する

4 を最後に置くのは、前段の除去で不自然な句読点が生まれるため。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from ..config import FormatConfig
from ..logging_setup import get_logger
from .dictionaries import FillerDictionary, NumberDictionary, load_fillers, load_numbers
from .fillers import remove_fillers
from .normalize import normalize_text, convert_numbers
from .punctuation import fix_punctuation
from .restate import fix_restatements

logger = get_logger("postprocess")

__all__ = [
    "format_text",
    "format_segments",
    "FillerDictionary",
    "NumberDictionary",
    "load_fillers",
    "load_numbers",
    "remove_fillers",
    "normalize_text",
    "convert_numbers",
    "fix_punctuation",
    "fix_restatements",
]


def format_text(
    text: str,
    cfg: FormatConfig,
    fillers: FillerDictionary | None = None,
    numbers: NumberDictionary | None = None,
) -> str:
    """1 つのテキストに、設定に従った整形をすべて適用する。"""
    result = text

    if cfg.remove_fillers:
        result = remove_fillers(result, fillers or FillerDictionary())

    if cfg.fix_restatements:
        result = fix_restatements(result)

    if cfg.normalize_width:
        result = normalize_text(result)

    if cfg.numbers != "keep":
        result = convert_numbers(result, cfg.numbers, numbers or NumberDictionary())

    if cfg.fix_punctuation:
        result = fix_punctuation(result)

    return result.strip()


def format_segments(segments: Sequence, cfg: FormatConfig, dictionaries_dir=None) -> list:
    """セグメントの一覧に整形を適用する（テキストが空になったものは除く）。

    Args:
        segments: ``text`` 属性を持つデータクラスの列（OutputSegment など）。
        cfg: [format] セクションの設定。
        dictionaries_dir: 辞書ファイルの置き場。省略時は既定の場所。

    Returns:
        整形後のセグメント（元のオブジェクトは変更しない）。
    """
    fillers = load_fillers(dictionaries_dir, cfg.fillers_file)
    numbers = load_numbers(dictionaries_dir)

    formatted = []
    for segment in segments:
        text = format_text(segment.text, cfg, fillers, numbers)
        if not text:
            # 整形の結果、中身がフィラーだけだったセグメントは落とす
            continue
        formatted.append(replace(segment, text=text))
    return formatted
