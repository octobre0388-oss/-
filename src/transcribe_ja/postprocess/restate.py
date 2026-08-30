"""言い直しの整理。

    「これは、これはですね」               → 「これはですね」
    「つまり、つまり結論は」               → 「つまり結論は」
    「そうですね、そうですね」             → 「そうですね」
    「資料の3ページ目の、3ページ目の予算」 → 「資料の3ページ目の予算」

読点で区切られた前後の断片を見て、次の 2 つの形を整理する。

    (a) 前の断片が、後ろの断片の先頭と一致する（丸ごと言い直した）
        → 前の断片を落とす
    (b) 前の断片の末尾と、後ろの断片の先頭が重なっている（途中から言い直した）
        → 重なった分を前から削り、読点を取って 1 つにつなぐ

短い一致は偶然のこともあるため、いずれも一定の文字数以上を要求する。
"""

from __future__ import annotations

import re

#: 前の断片が丸ごと繰り返されたとみなす最小文字数。
MIN_MATCH_LENGTH = 2

#: 断片の末尾と先頭が重なっているとみなす最小文字数。
#: 短くすると「赤いの、赤いのじゃない方」のような正当な表現まで壊れやすくなる。
MIN_OVERLAP_LENGTH = 3

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
    # 読点を取って直前とつなぐ断片には True を立てる
    result: list[str] = []
    joined: list[bool] = []

    for chunk in chunks:
        stripped = chunk.strip()
        merge = False
        if result and stripped:
            previous = result[-1].strip()
            if len(previous) >= MIN_MATCH_LENGTH and (
                stripped.startswith(previous) or previous == stripped
            ):
                # (a) 直前の断片は、この断片の言いかけだったとみなして落とす
                result.pop()
                merge = joined.pop() if joined else False
            else:
                overlap = _overlap_length(previous, stripped)
                if overlap:
                    # (b) 重なった分を前から削り、読点を取ってつなぐ
                    result[-1] = result[-1].rstrip()[: len(previous) - overlap]
                    merge = True
        result.append(chunk)
        joined.append(merge)

    rebuilt = result[0] if result else ""
    for chunk, merge in zip(result[1:], joined[1:]):
        rebuilt += chunk if merge else "、" + chunk
    return rebuilt + trailing


def _overlap_length(previous: str, following: str) -> int:
    """previous の末尾と following の先頭が重なっている長さを返す（無ければ 0）。"""
    limit = min(len(previous), len(following))
    for length in range(limit, MIN_OVERLAP_LENGTH - 1, -1):
        if previous.endswith(following[:length]):
            return length
    return 0


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
