"""整形に使う辞書ファイル（利用者が編集できる TOML）の読み込み。

辞書は %APPDATA%\\TranscribeJA\\dictionaries\\ に置かれ、初回起動時に
同梱の既定辞書がコピーされる。利用者はこれを開いて語を足し引きできる。
ファイルが壊れていたり無かったりしても、既定値で動き続ける
（辞書の書き間違いで文字起こしができなくなるのは困るため）。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..logging_setup import get_logger

logger = get_logger("postprocess.dict")

_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "chatter" / "dictionaries"


@dataclass
class FillerDictionary:
    """フィラー除去に使う語の一覧。"""

    always: list[str] = field(default_factory=list)
    boundary: list[str] = field(default_factory=list)
    sentence_head: list[str] = field(default_factory=list)
    repeated_aizuchi: list[str] = field(default_factory=list)
    keep: list[str] = field(default_factory=list)


@dataclass
class NumberDictionary:
    """数字表記の統一に使う助数詞と除外語。"""

    counters: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


def _read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as fp:
            return tomllib.load(fp)
    except FileNotFoundError:
        return {}
    except (tomllib.TOMLDecodeError, OSError) as exc:
        logger.warning("辞書ファイルを読めませんでした（既定値を使います）: %s (%s)", path, exc)
        return {}


def _string_list(data: dict, key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if isinstance(v, str) and v]


def _resolve(directory: Path | None, filename: str) -> Path:
    """利用者の辞書 → 同梱の既定辞書 の順に探す。"""
    if directory is not None:
        candidate = Path(directory) / filename
        if candidate.is_file():
            return candidate
    return _DEFAULT_DIR / filename


def load_fillers(directory: Path | None = None, filename: str = "fillers_ja.toml") -> FillerDictionary:
    data = _read_toml(_resolve(directory, filename))
    return FillerDictionary(
        always=_string_list(data, "always"),
        boundary=_string_list(data, "boundary"),
        sentence_head=_string_list(data, "sentence_head"),
        repeated_aizuchi=_string_list(data, "repeated_aizuchi"),
        keep=_string_list(data, "keep"),
    )


def load_numbers(directory: Path | None = None, filename: str = "numbers_ja.toml") -> NumberDictionary:
    data = _read_toml(_resolve(directory, filename))
    return NumberDictionary(
        counters=_string_list(data, "counters"),
        exclude=_string_list(data, "exclude"),
    )
