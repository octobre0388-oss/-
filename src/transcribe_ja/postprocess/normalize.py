"""表記の統一（全角・半角、空白、数字）。

■ 方針

    英数字        : 半角に統一（「ＡＢＣ１２３」→「ABC123」）
    カタカナ      : 全角に統一（半角カナは読みにくいため）
    記号          : 日本語の文章に合わせる（「，．」→「、。」）
    空白          : 日本語どうしの間の空白は削除、英単語の間は残す
    数字          : config の [format] numbers に従って算用数字か漢数字に揃える
"""

from __future__ import annotations

import re
import unicodedata

from .dictionaries import NumberDictionary

#: 全角英数字を半角にする変換表（記号は別扱いにするので含めない）。
_FULLWIDTH_ALNUM = str.maketrans(
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
    "０１２３４５６７８９",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789",
)

#: 日本語の文章として自然な記号に揃える対応表。
_SYMBOLS = {
    "，": "、",
    "．": "。",
    "｡": "。",
    "､": "、",
    "，": "、",
    "!": "！",
    "?": "？",
    "＇": "'",
    "＂": '"',
    "～": "〜",
}

#: 日本語の文字（この文字どうしの間にある空白は削除する）。
_JP_CHAR = r"[ぁ-んァ-ヶー一-龥々〆〇、。！？「」『』（）・：；]"

_HALFWIDTH_KANA = re.compile(r"[｡-ﾟ]+")

_KANJI_DIGITS = {
    "〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_KANJI_UNITS = {"十": 10, "百": 100, "千": 1000}
_KANJI_BIG_UNITS = {"万": 10**4, "億": 10**8, "兆": 10**12}
_KANJI_NUMBER_CHARS = "".join(_KANJI_DIGITS) + "".join(_KANJI_UNITS) + "".join(_KANJI_BIG_UNITS)

_ARABIC_TO_KANJI = str.maketrans("0123456789", "〇一二三四五六七八九")


def normalize_text(text: str) -> str:
    """全角・半角と空白を整える。"""
    if not text:
        return text

    # 半角カタカナだけを全角に直す（英数字は NFKC を通すと壊れる場合があるので個別に）
    text = _HALFWIDTH_KANA.sub(lambda m: unicodedata.normalize("NFKC", m.group()), text)

    text = text.translate(_FULLWIDTH_ALNUM)
    for src, dest in _SYMBOLS.items():
        text = text.replace(src, dest)

    # 日本語の文章中の半角カンマ・ピリオドを句読点に直す
    text = re.sub(rf"(?<={_JP_CHAR}),", "、", text)
    text = re.sub(rf"(?<={_JP_CHAR})\.(?![0-9])", "。", text)

    # 全角スペースを半角に寄せてから、空白を整理する
    text = text.replace("　", " ")
    text = re.sub(r"[ \t]+", " ", text)
    # 日本語どうしの間の空白は不要
    text = re.sub(rf"(?<={_JP_CHAR}) (?={_JP_CHAR})", "", text)
    # 句読点の前後の空白も不要
    text = re.sub(r"\s+([、。！？」）])", r"\1", text)
    text = re.sub(r"([「（])\s+", r"\1", text)

    return text.strip()


# --- 数字表記の統一 -------------------------------------------------------------


def kanji_to_int(text: str) -> int | None:
    """漢数字の文字列を整数に変換する（「三十五」→ 35）。

    変換できない並びの場合は None を返す。
    """
    if not text:
        return None

    total = 0
    section = 0
    current = 0
    seen_digit = False

    for char in text:
        if char in _KANJI_DIGITS:
            current = _KANJI_DIGITS[char]
            seen_digit = True
        elif char in _KANJI_UNITS:
            unit = _KANJI_UNITS[char]
            section += (current if current else 1) * unit
            current = 0
            seen_digit = True
        elif char in _KANJI_BIG_UNITS:
            unit = _KANJI_BIG_UNITS[char]
            section += current
            if section == 0:
                section = 1
            total += section * unit
            section = 0
            current = 0
            seen_digit = True
        else:
            return None

    if not seen_digit:
        return None
    return total + section + current


def int_to_kanji(value: int) -> str:
    """整数を漢数字にする（35 →「三十五」）。

    1 兆未満は位取り表記、それ以上は 1 文字ずつの表記にする。
    """
    if value == 0:
        return "〇"
    if value < 0:
        return "マイナス" + int_to_kanji(-value)
    if value >= 10**16:
        return str(value).translate(_ARABIC_TO_KANJI)

    def under_10000(n: int) -> str:
        result = ""
        for unit_value, unit_char in ((1000, "千"), (100, "百"), (10, "十")):
            digit, n = divmod(n, unit_value)
            if digit:
                result += ("" if digit == 1 else "一二三四五六七八九"[digit - 1]) + unit_char
        if n:
            result += "一二三四五六七八九"[n - 1]
        return result

    result = ""
    for unit_value, unit_char in ((10**12, "兆"), (10**8, "億"), (10**4, "万")):
        chunk, value = divmod(value, unit_value)
        if chunk:
            result += under_10000(chunk) + unit_char
    if value:
        result += under_10000(value)
    return result


def _to_arabic(text: str, dictionary: NumberDictionary) -> str:
    """漢数字を算用数字に直す（助数詞が続く場合のみ）。

    「三ページ」→「3ページ」、「一般」→「一般」（変換しない）
    """
    counters = [c for c in dictionary.counters if c]
    if not counters:
        return text
    counter_pattern = "|".join(sorted((re.escape(c) for c in counters), key=len, reverse=True))
    pattern = re.compile(rf"([{_KANJI_NUMBER_CHARS}]+)(?={counter_pattern})")

    def replace(match: re.Match[str]) -> str:
        # 除外語（「一般」など）に該当する位置なら触らない
        for word in dictionary.exclude:
            if word and text.startswith(word, match.start()):
                return match.group(0)
        value = kanji_to_int(match.group(1))
        return str(value) if value is not None else match.group(0)

    return pattern.sub(replace, text)


def _to_kanji(text: str) -> str:
    """算用数字を漢数字に直す。

    小数や時刻（3.5、10:30）は読み替えると分かりにくくなるため触らない。
    """

    def replace(match: re.Match[str]) -> str:
        start, end = match.span()
        before = text[start - 1] if start > 0 else ""
        after = text[end] if end < len(text) else ""
        # 空文字列は `in` 判定で常に真になるため、必ず存在確認を先に行う
        if (before and before in ".:,-/") or (after and after in ".:,-/"):
            return match.group(0)
        try:
            return int_to_kanji(int(match.group(0)))
        except ValueError:  # pragma: no cover - 桁が極端に大きい場合
            return match.group(0)

    return re.sub(r"\d+", replace, text)


def convert_numbers(text: str, mode: str, dictionary: NumberDictionary) -> str:
    """数字表記を統一する。

    Args:
        mode: "arabic"（算用数字）/ "kanji"（漢数字）/ それ以外は無変換。
    """
    if not text:
        return text
    if mode == "arabic":
        return _to_arabic(text, dictionary)
    if mode == "kanji":
        return _to_kanji(text)
    return text
