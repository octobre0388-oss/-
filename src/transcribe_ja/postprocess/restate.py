"""言い直しの整理。

    「これは、これはですね」   → 「これはですね」
    「つまり、つまり結論は」   → 「つまり結論は」
    「そうですね、そうですね」 → 「そうですね」

読点で区切られた前後の断片を見て、前が後ろの先頭部分と一致する場合、
前を「言い直しの途中」とみなして落とす。
短い断片（1 文字）は偶然の一致が多いので対象にしない。
"""

from __future__ import annotations

import re

#: この文字数以上一致していれば言い直しとみなす。
MIN_MATCH_LENGTH = 2

#: 文の区切り文字。
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?])")


def _fix_sentence(sentence: str) -> str:
    """1 文の中の言い直しを整理する。"""
    if "、" not in sentence:
        return sentence

    # 末尾の句点などは分割対象から外し、あとで戻す
    trailing = ""
    body = sentence
    while body and body[-1] in "。！？!?":
        trailing = body[-1] + trailing
        body = body[:-1]

    chunks = body.split("、")
    result: list[str] = []
    for chunk in chunks:
        stripped = chunk.strip()
        if result:
            previous = result[-1].strip()
            if (
                len(previous) >= MIN_MATCH_LENGTH
                and stripped
                and (stripped.startswith(previous) or previous == stripped)
            ):
                # 直前の断片は、この断片の言いかけだったとみなして落とす
                result.pop()
        result.append(chunk)

    return "、".join(result) + trailing


def fix_restatements(text: str) -> str:
    """テキスト全体の言い直しを整理する。"""
    if not text or "、" not in text:
        return text

    parts = _SENTENCE_SPLIT.split(text)
    fixed = [_fix_sentence(part) for part in parts]
    result = "".join(fixed)

    # 「これはこれはですね」のように読点なしで繰り返した場合も 1 度だけ整理する
    result = re.sub(r"(.{2,8}?)\1(?=[はがをにでとも])", r"\1", result)
    return result
