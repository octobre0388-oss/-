"""処理中の進捗を表示するウィンドウ（tkinter）。

■ 設計

    * 処理は別スレッドで動かし、GUI はメインスレッドで動かす
      （tkinter は他スレッドから触ると不安定になるため）
    * 処理スレッドからの進捗は queue.Queue 経由で渡し、
      GUI 側が ``after()`` で定期的に取り出す
    * キャンセルボタンは ProgressReporter のフラグを立てるだけ。
      実際の中断は処理側が区切りのよい所で行う
"""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk
from typing import Callable

from .. import APP_NAME, MENU_LABEL
from ..progress import ProgressEvent

#: GUI が進捗キューを確認する間隔（ミリ秒）。
_POLL_INTERVAL_MS = 100

_WINDOW_WIDTH = 460


class ProgressWindow:
    """進捗ウィンドウ本体。

    Args:
        on_cancel: キャンセルボタンが押されたときに呼ばれる関数。
    """

    def __init__(self, on_cancel: Callable[[], None] | None = None) -> None:
        self._on_cancel = on_cancel
        self._events: queue.Queue = queue.Queue()
        self._closed = False

        self.root = tk.Tk()
        self.root.title(f"{MENU_LABEL} - {APP_NAME}")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_button)

        frame = ttk.Frame(self.root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")

        self._file_label = ttk.Label(
            frame, text="準備しています…", width=52, anchor="w", justify="left"
        )
        self._file_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self._stage_label = ttk.Label(frame, text="", width=52, anchor="w")
        self._stage_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        self._bar = ttk.Progressbar(frame, mode="indeterminate", length=_WINDOW_WIDTH - 40)
        self._bar.grid(row=2, column=0, columnspan=2, sticky="we", pady=(0, 12))
        self._bar.start(20)
        self._bar_mode = "indeterminate"

        self._note = ttk.Label(
            frame,
            text="初回は文字起こしモデルの取得に時間がかかります。",
            foreground="#555555",
            width=52,
            anchor="w",
        )
        self._note.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 10))

        self._cancel_button = ttk.Button(frame, text="キャンセル", command=self._cancel)
        self._cancel_button.grid(row=4, column=1, sticky="e")

        self._center()
        self.root.after(_POLL_INTERVAL_MS, self._poll)

    # --- 外部（処理スレッド）から呼ぶ ------------------------------------

    def post(self, event: ProgressEvent) -> None:
        """進捗を通知する（別スレッドから呼んでよい）。"""
        self._events.put(("progress", event))

    def post_message(self, text: str) -> None:
        """任意のメッセージを表示する（別スレッドから呼んでよい）。"""
        self._events.put(("message", text))

    def post_done(self) -> None:
        """処理の終了を通知してウィンドウを閉じる（別スレッドから呼んでよい）。"""
        self._events.put(("done", None))

    # --- 内部 -------------------------------------------------------------

    def _center(self) -> None:
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - width) // 2
        y = (self.root.winfo_screenheight() - height) // 3
        self.root.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _cancel(self) -> None:
        self._cancel_button.configure(state="disabled", text="キャンセルしています…")
        self._stage_label.configure(text="区切りのよいところで停止します。少々お待ちください。")
        if self._on_cancel is not None:
            self._on_cancel()

    def _on_close_button(self) -> None:
        # ×ボタンはキャンセル扱いにする（処理は止めずに閉じると混乱を招くため）
        self._cancel()

    def _set_determinate(self, fraction: float) -> None:
        if self._bar_mode != "determinate":
            self._bar.stop()
            self._bar.configure(mode="determinate", maximum=100)
            self._bar_mode = "determinate"
        self._bar.configure(value=max(0.0, min(1.0, fraction)) * 100)

    def _set_indeterminate(self) -> None:
        if self._bar_mode != "indeterminate":
            self._bar.configure(mode="indeterminate")
            self._bar.start(20)
            self._bar_mode = "indeterminate"

    def _apply(self, event: ProgressEvent) -> None:
        if event.file_name:
            prefix = ""
            if event.file_total > 1:
                prefix = f"[{event.file_index}/{event.file_total}] "
            self._file_label.configure(text=f"{prefix}{event.file_name}")
        self._stage_label.configure(text=event.message())
        if event.fraction is None:
            self._set_indeterminate()
        else:
            self._set_determinate(event.fraction)

    def _poll(self) -> None:
        if self._closed:
            return
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "progress":
                    self._apply(payload)
                elif kind == "message":
                    self._stage_label.configure(text=str(payload))
                elif kind == "done":
                    self.close()
                    return
        except queue.Empty:
            pass
        self.root.after(_POLL_INTERVAL_MS, self._poll)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def mainloop(self) -> None:
        self.root.mainloop()
