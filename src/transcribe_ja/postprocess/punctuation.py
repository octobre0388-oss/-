"""句読点の整形。フィラー除去などで生じた不自然な句読点を掃除する。"""

from __future__ import annotations

import re

#: 連続した読点・句点をまとめる規則。
_RULES: list[tuple[re.Pattern[str], str]] = [
    # 「、、、」→「、」
    (re.compile(r"、{2,}"), "、"),
    (re.compile(r"。{2,}"), "。"),
    # 「、。」→「。」、「。、」→「。」
    (re.compile(r"、+(?=[。！？])"), ""),
    (re.compile(r"(?<=[。！？])、+"), ""),
    # 句読点の前の空白
    (re.compile(r"[ \t]+(?=[、。！？])"), ""),
    # 行頭の読点
    (re.compile(r"^[、。，,]+\s*"), ""),
    # 括弧の直後の読点
    (re.compile(r"(?<=「)、+"), ""),
    # 「！。」「？。」のような重複
    (re.compile(r"(?<=[！？])。+"), ""),
]


def fix_punctuation(text: str) -> str:
    """句読点を整える。"""
    if not text:
        return text

    result = text
    for pattern, replacement in _RULES:
        result = pattern.sub(replacement, result)

    result = result.strip()
    # 末尾に残った読点は句点に変える（文の途中で切れた印象を避ける）
    if result.endswith("、"):
        result = result[:-1] + "。"
    return result


def ensure_sentence_end(text: str) -> str:
    """段落の最後に句点が無ければ補う（段落単位で呼ぶこと）。

    セグメント単位で呼ぶと、文の途中で句点が入ってしまうので注意。
    """
    if not text:
        return text
    if text[-1] in "。！？!?」』）)…":
        return text
    return text + "。"
