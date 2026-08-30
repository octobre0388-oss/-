"""完了時の Windows トースト通知。

クリックすると出力先フォルダが開くようにしている。
通知ライブラリが無い / 通知が無効な環境でも、処理そのものは成功扱いにする
（通知が出せないことは失敗ではない）。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .. import APP_NAME, MENU_LABEL
from ..logging_setup import get_logger
from ..paths import is_windows

logger = get_logger("notify")

_APP_ID = "TranscribeJA"


def open_folder(path: Path) -> None:
    """フォルダをエクスプローラーで開く。"""
    target = path if path.is_dir() else path.parent
    try:
        if is_windows():
            os.startfile(str(target))  # type: ignore[attr-defined]
        else:  # 開発時の確認用
            subprocess.run(["xdg-open", str(target)], check=False)
    except OSError as exc:
        logger.warning("フォルダを開けませんでした: %s (%s)", target, exc)


def show_toast(title: str, message: str, folder: Path | None = None) -> bool:
    """トースト通知を出す。成功したら True。

    Args:
        title: 通知の見出し。
        message: 本文。
        folder: クリック時に開くフォルダ。
    """
    if not is_windows():
        logger.info("通知（Windows 以外のため表示せず）: %s / %s", title, message)
        return False

    try:
        from winotify import Notification
    except ImportError:
        logger.info("winotify が無いため通知を表示しません: %s", title)
        return False

    try:
        toast = Notification(
            app_id=_APP_ID,
            title=title,
            msg=message,
            duration="short",
            # クリックすると出力先フォルダが開く
            launch=str(folder) if folder else "",
        )
        if folder is not None:
            toast.add_actions(label="フォルダを開く", launch=str(folder))
        toast.show()
        return True
    except Exception as exc:  # pragma: no cover - 環境依存
        logger.warning("通知の表示に失敗しました: %s", exc)
        return False


def notify_success(count: int, folder: Path, elapsed: float | None = None) -> None:
    """処理完了の通知。"""
    detail = f"{count} 件のファイルを処理しました。"
    if elapsed is not None:
        minutes, seconds = divmod(int(elapsed), 60)
        detail += f"（所要 {minutes}分{seconds}秒）"
    show_toast(f"{MENU_LABEL} が完了しました", detail, folder)


def notify_failure(message: str) -> None:
    """処理失敗の通知。"""
    first_line = message.strip().splitlines()[0] if message.strip() else "エラーが発生しました。"
    show_toast(f"{APP_NAME}: 処理に失敗しました", first_line)
