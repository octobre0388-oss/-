"""画面まわり（進捗ウィンドウ・通知・設定画面）。

tkinter は Python に標準で付いてくるため、追加インストールが要らない。
GUI が使えない環境（tkinter が無い、画面が無い）でも本体が動くように、
各モジュールは import 失敗を握りつぶさず、呼び出し側で分岐できる形にしている。
"""

from __future__ import annotations


def gui_available() -> bool:
    """tkinter が使えるかどうか。"""
    try:
        import tkinter  # noqa: F401
    except Exception:
        return False
    return True
