"""設定の簡易編集画面と、「設定ファイルを開く」機能。

すべての項目を GUI で編集できるようにすると画面が複雑になるため、
よく変更する項目だけをここに置き、細かい調整は設定ファイルを直接開いてもらう。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .. import APP_NAME
from ..config import (
    VALID_CHATTER_METHOD,
    VALID_NUMBERS,
    VALID_SAFETY,
    VALID_WHISPER_MODELS,
    ensure_config_file,
)
from ..logging_setup import current_log_file, get_logger
from ..paths import app_data_dir, dictionaries_dir, is_windows

logger = get_logger("settings")


def open_in_editor(path: Path) -> None:
    """テキストファイルを既定のアプリ（メモ帳など）で開く。"""
    try:
        if is_windows():
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:  # 開発時の確認用
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError as exc:
        logger.warning("ファイルを開けませんでした: %s (%s)", path, exc)


def open_config_file() -> Path:
    """設定ファイルを（必要なら作成してから）開く。"""
    path = ensure_config_file()
    open_in_editor(path)
    return path


def show_settings_window() -> None:
    """よく使う設定だけを編集できる簡易画面を表示する。

    値は TOML の該当行を書き換える形で保存する（コメントを保つため）。
    """
    import tkinter as tk
    from tkinter import messagebox, ttk

    config_path = ensure_config_file()
    original = config_path.read_text(encoding="utf-8")

    root = tk.Tk()
    root.title(f"{APP_NAME} の設定")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=16)
    frame.grid(row=0, column=0)

    def _current(section: str, key: str, default: str) -> str:
        """TOML の指定セクションから `key = 値` を読み取る。

        `enabled` のように複数のセクションに同じ名前がある項目を
        取り違えないよう、必ずセクションを指定する。
        """
        return _read_value(original, section, key, default)

    # (表示名, セクション, キー, 選択肢, 既定値)
    rows = [
        ("文字起こしモデル", "whisper", "model", list(VALID_WHISPER_MODELS), "auto"),
        ("雑談カットの方式", "chatter", "method", list(VALID_CHATTER_METHOD), "rules"),
        ("雑談カットの安全度", "chatter", "safety", list(VALID_SAFETY), "conservative"),
        ("数字の表記", "format", "numbers", list(VALID_NUMBERS), "arabic"),
    ]

    variables: dict[str, tk.Variable] = {
        f"{section}.{key}": tk.StringVar(value=_current(section, key, default))
        for _, section, key, _, default in rows
    }
    variables["chatter.enabled"] = tk.BooleanVar(
        value=_current("chatter", "enabled", "true") == "true"
    )
    variables["vad.enabled"] = tk.BooleanVar(
        value=_current("vad", "enabled", "true") == "true"
    )

    for index, (label, section, key, values, _default) in enumerate(rows):
        ttk.Label(frame, text=label).grid(row=index, column=0, sticky="w", pady=4)
        ttk.Combobox(
            frame,
            textvariable=variables[f"{section}.{key}"],
            values=values,
            state="readonly",
            width=22,
        ).grid(row=index, column=1, sticky="w", pady=4)

    ttk.Checkbutton(
        frame, text="無音部分をカットする", variable=variables["vad.enabled"]
    ).grid(row=len(rows), column=0, columnspan=2, sticky="w", pady=(8, 0))
    ttk.Checkbutton(
        frame, text="不要な雑談部分をカットする", variable=variables["chatter.enabled"]
    ).grid(row=len(rows) + 1, column=0, columnspan=2, sticky="w", pady=(0, 4))

    def _save() -> None:
        text = original
        for _, section, key, _values, _default in rows:
            value = str(variables[f"{section}.{key}"].get())
            text = _replace_value(text, section, key, f'"{value}"')
        for section in ("vad", "chatter"):
            flag = "true" if variables[f"{section}.enabled"].get() else "false"
            text = _replace_value(text, section, "enabled", flag)
        config_path.write_text(text, encoding="utf-8")
        messagebox.showinfo(APP_NAME, "設定を保存しました。")
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=len(rows) + 2, column=0, columnspan=2, sticky="e", pady=(12, 0))
    ttk.Button(
        buttons, text="設定ファイルを開く", command=lambda: open_in_editor(config_path)
    ).grid(row=0, column=0, padx=4)
    ttk.Button(
        buttons, text="判定辞書を開く", command=lambda: open_in_editor(dictionaries_dir())
    ).grid(row=0, column=1, padx=4)
    ttk.Button(
        buttons, text="ログを開く", command=lambda: open_in_editor(current_log_file())
    ).grid(row=0, column=2, padx=4)
    ttk.Button(buttons, text="保存", command=_save).grid(row=0, column=3, padx=4)

    ttk.Label(
        frame,
        text=f"設定の保存先: {app_data_dir()}",
        foreground="#555555",
    ).grid(row=len(rows) + 3, column=0, columnspan=2, sticky="w", pady=(12, 0))

    root.mainloop()


def _iter_sections(text: str):
    """TOML を「セクション名, 行番号, 行」の順に走査する。"""
    section = ""
    for index, line in enumerate(text.splitlines(keepends=True)):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
        yield section, index, line


def _is_key_line(line: str, key: str) -> bool:
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return False
    return stripped.startswith(f"{key} ") or stripped.startswith(f"{key}=")


def _read_value(text: str, section: str, key: str, default: str) -> str:
    """指定セクションの値を読み取る（見つからなければ既定値）。"""
    for current_section, _index, line in _iter_sections(text):
        if current_section == section and _is_key_line(line, key):
            return line.split("=", 1)[1].strip().strip('"')
    return default


def _replace_value(text: str, section: str, key: str, new_value: str) -> str:
    """指定セクションの `key = 値` の行だけを書き換える。

    コメント行と、他セクションの同名キーには触らない。
    """
    lines = text.splitlines(keepends=True)
    for current_section, index, line in _iter_sections(text):
        if current_section != section or not _is_key_line(line, key):
            continue
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        newline = "\n" if line.endswith("\n") else ""
        lines[index] = f"{indent}{key} = {new_value}{newline}"
        break
    return "".join(lines)
