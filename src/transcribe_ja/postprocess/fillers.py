"""フィラー（「えー」「あのー」など）の除去。

■ 慎重に消すための工夫

「あの」「その」「ちょっと」は、フィラーにも普通の言葉にもなる。
    フィラー : 「あの、これはですね」
    普通の語 : 「あの人に聞いてください」

そこで、これらは **直後に読点・句点・空白が続くときだけ** 消す。
一方「あのー」「えーと」のように長音符が付いた形はフィラー以外に使われないため、
どこにあっても消す。

さらに、消したくない言い回しは辞書の keep に書いておける。
"""

from __future__ import annotations

import re

from .dictionaries import FillerDictionary

#: 語の区切りとみなす文字（この後ろにフィラーがあると判断する）。
_DELIMITERS = "、。，．,.！？!?・「」（）()　 \t"

#: keep の保護に使う一時的な目印（通常の文章には現れない文字）。
_PLACEHOLDER = "\x00{}\x00"


def _protect(text: str, phrases: list[str]) -> tuple[str, list[str]]:
    """除去したくない言い回しを一時的に伏せ字に置き換える。"""
    saved: list[str] = []
    for phrase in sorted(phrases, key=len, reverse=True):
        if not phrase or phrase not in text:
            continue
        token = _PLACEHOLDER.format(len(saved))
        text = text.replace(phrase, token)
        saved.append(phrase)
    return text, saved


def _restore(text: str, saved: list[str]) -> str:
    for index, phrase in enumerate(saved):
        text = text.replace(_PLACEHOLDER.format(index), phrase)
    return text


def _remove_always(text: str, words: list[str]) -> str:
    """どこにあっても消す語を除去する（長い語から順に処理する）。"""
    for word in sorted(words, key=len, reverse=True):
        if word:
            text = text.replace(word, "")
    return text


def _remove_boundary(text: str, words: list[str]) -> str:
    """直後に区切り文字が来るときだけ消す語を除去する。

    「あの、これは」→「これは」、「あの人」→「あの人」（消さない）
    """
    delimiters = re.escape(_DELIMITERS)
    for word in sorted(words, key=len, reverse=True):
        if not word:
            continue
        # 前も区切り（または文頭）であることを求めることで、
        # 「まあまあ」の後半だけ消えるといった中途半端な削除を防ぐ。
        # 直後に区切り文字が 1 つ以上続く場合（または文末）だけ削除する。
        # ここを "0 個以上" にすると「あの人」の「あの」まで消えてしまう。
        pattern = re.compile(
            rf"(?:(?<=^)|(?<=[{delimiters}]))"
            rf"{re.escape(word)}"
            rf"(?:[{delimiters}]+|$)"
        )
        text = pattern.sub("", text)
    return text


def _remove_sentence_head(text: str, words: list[str]) -> str:
    """文頭にあるときだけ消す語を除去する。"""
    for word in sorted(words, key=len, reverse=True):
        if not word:
            continue
        pattern = re.compile(
            rf"(?:(?<=^)|(?<=[。！？!?\n]))\s*{re.escape(word)}[、。，,\s]+"
        )
        text = pattern.sub("", text)
    return text


def _collapse_aizuchi(text: str, words: list[str]) -> str:
    """繰り返された相槌を 1 回にまとめる。

    「はい、はい、はい」→「はい」
    """
    for word in sorted(words, key=len, reverse=True):
        if not word:
            continue
        escaped = re.escape(word)
        pattern = re.compile(rf"{escaped}(?:[、。，,\s]*{escaped})+")
        text = pattern.sub(word, text)
    return text


def remove_fillers(text: str, dictionary: FillerDictionary) -> str:
    """テキストからフィラーを取り除く。

    Args:
        text: 元のテキスト。
        dictionary: 除去に使う辞書。

    Returns:
        フィラーを取り除いたテキスト（句読点の掃除は punctuation 側で行う）。
    """
    if not text:
        return text

    protected, saved = _protect(text, dictionary.keep)
    protected = _collapse_aizuchi(protected, dictionary.repeated_aizuchi)
    protected = _remove_always(protected, dictionary.always)
    protected = _remove_boundary(protected, dictionary.boundary)
    protected = _remove_sentence_head(protected, dictionary.sentence_head)
    return _restore(protected, saved).strip()
