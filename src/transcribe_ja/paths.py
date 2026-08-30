"""パスに関するあらゆる面倒事をここに閉じ込める。

Windows 特有の落とし穴:
    * MAX_PATH (260 文字) 制限 -> ``\\\\?\\`` プレフィックスで回避する。
    * UNC パス (``\\\\server\\share\\...``) -> プレフィックスの付け方が異なる。
    * 日本語・空白を含むパス -> subprocess にはリストで渡し、シェルを経由させない。

Windows 以外（開発時のテスト環境）でも import できるように、OS 依存処理は
すべて ``os.name == "nt"`` で分岐させ、それ以外では素通しする。
"""

from __future__ import annotations

import os
import shutil
import unicodedata
from pathlib import Path

from . import APP_NAME
from .errors import (
    DiskSpaceError,
    PathTooLongError,
    TranscribeJAError,
    HINT_DISK_SPACE,
    HINT_LONG_PATH,
)

#: Windows の従来の最大パス長。これを超える場合は拡張プレフィックスが必要。
MAX_PATH = 260

#: 出力ファイルの連番は最大でここまで試す（これを超えるのは異常事態）。
MAX_SEQUENCE = 999


def is_windows() -> bool:
    return os.name == "nt"


# --- アプリケーションのデータ置き場 ---------------------------------------------


def app_data_dir() -> Path:
    """``%APPDATA%\\TranscribeJA`` を返す（無ければ作成する）。

    Windows 以外ではテストのために ``~/.config/TranscribeJA`` を使う。
    環境変数 ``TRANSCRIBE_JA_HOME`` が設定されていれば、そちらを最優先する
    （テストや、持ち運び用途で設定を別の場所に置きたい場合に使う）。
    """
    override = os.environ.get("TRANSCRIBE_JA_HOME")
    if override:
        base = Path(override)
    elif is_windows():
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) / APP_NAME if appdata else Path.home() / APP_NAME
    else:
        base = Path.home() / ".config" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_file() -> Path:
    return app_data_dir() / "config.toml"


def logs_dir() -> Path:
    d = app_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def queue_dir() -> Path:
    d = app_data_dir() / "queue"
    d.mkdir(parents=True, exist_ok=True)
    return d


def dictionaries_dir() -> Path:
    """利用者が編集できる判定辞書の置き場（初回に既定辞書がコピーされる）。"""
    d = app_data_dir() / "dictionaries"
    d.mkdir(parents=True, exist_ok=True)
    return d


def work_root() -> Path:
    """一時ファイルの親フォルダ。処理ごとにこの下にサブフォルダを作る。"""
    d = app_data_dir() / "work"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- 長いパス / UNC への対応 -----------------------------------------------------


def is_unc(path: os.PathLike[str] | str) -> bool:
    """``\\\\server\\share\\...`` 形式の UNC パスかどうか。"""
    s = str(path)
    return s.startswith("\\\\") and not s.startswith("\\\\?\\")


def extended_path(path: os.PathLike[str] | str) -> str:
    """必要に応じて Windows の拡張長パスプレフィックスを付けた文字列を返す。

    ffmpeg など外部プロセスに渡す直前だけで使う。Python の open() は
    Windows 10 以降なら多くの場合そのままでも動くが、外部 exe は
    MAX_PATH 制限を持つものが多いため、こちらで面倒を見る。
    """
    s = str(path)
    if not is_windows():
        return s
    if s.startswith("\\\\?\\"):
        return s
    absolute = os.path.abspath(s)
    if is_unc(absolute):
        # \\server\share\dir -> \\?\UNC\server\share\dir
        return "\\\\?\\UNC" + absolute[1:]
    return "\\\\?\\" + absolute


def ensure_path_usable(path: Path) -> None:
    """処理を始める前に、パスが原因で後段が壊れないかを確認する。

    Raises:
        PathTooLongError: 拡張プレフィックスでも救えないほど長い場合。
    """
    s = str(path)
    if not is_windows():
        return
    # 拡張プレフィックスを使えば約 32767 文字まで扱えるが、
    # 出力ファイル名（_ja.txt など）を足す余地も見ておく。
    if len(s) > 32000:
        raise PathTooLongError(hint=HINT_LONG_PATH)
    if len(s) > MAX_PATH:
        # ここでは失敗させない。extended_path() で救えるので情報として残すだけ。
        return


def ensure_free_space(directory: Path, required_bytes: int) -> None:
    """作業に必要な空き容量があるか確認する。

    Raises:
        DiskSpaceError: 空き容量が足りない場合。
    """
    try:
        usage = shutil.disk_usage(directory)
    except OSError:
        # 容量が取得できない場合は判断できないので通す（UNC などで起こりうる）。
        return
    if usage.free < required_bytes:
        need_mb = required_bytes / 1024 / 1024
        free_mb = usage.free / 1024 / 1024
        raise DiskSpaceError(
            f"ディスクの空き容量が不足しています。\n"
            f"必要な容量: 約 {need_mb:,.0f} MB / 現在の空き: 約 {free_mb:,.0f} MB",
            hint=HINT_DISK_SPACE,
        )


# --- 出力ファイル名 -------------------------------------------------------------

#: Windows でファイル名に使えない文字。
_INVALID_CHARS = '<>:"/\\|?*'


def sanitize_stem(stem: str) -> str:
    """ファイル名として安全な文字列に整える（元ファイル名を引き継ぐときに使う）。"""
    cleaned = "".join("_" if ch in _INVALID_CHARS or ord(ch) < 32 else ch for ch in stem)
    cleaned = unicodedata.normalize("NFC", cleaned).strip().rstrip(".")
    return cleaned or "output"


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    """同名ファイルがある場合に ``(2)`` ``(3)`` … と連番を付けたパスを返す。

    既存ファイルは決して上書きしない。

    Args:
        directory: 出力先フォルダ。
        stem: 拡張子を除いたファイル名（例: ``会議_ja``）。
        suffix: ``.txt`` のようにドットを含む拡張子。

    Returns:
        まだ存在しないファイルのパス。
    """
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    for i in range(2, MAX_SEQUENCE + 1):
        candidate = directory / f"{stem}({i}){suffix}"
        if not candidate.exists():
            return candidate
    raise TranscribeJAError(
        f"出力ファイル名の連番が上限（{MAX_SEQUENCE}）に達しました。",
        hint=f"{directory} にある {stem} で始まるファイルを整理してからお試しください。",
    )
