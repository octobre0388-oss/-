"""進捗の通知とキャンセルの受け渡し。

pipeline（処理の本体）と GUI を直接つながないための薄い層。
GUI が無い状態（コマンドライン実行やテスト）でも同じコードが動くように、
既定では標準出力に出すだけの実装を使う。
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from .errors import CancelledByUserError


class Stage(Enum):
    """処理の工程。進捗ウィンドウの表示文字列をここで一元管理する。"""

    PREPARING = "準備中"
    EXTRACTING = "音声抽出中"
    VAD = "無音カット中"
    PRESCAN = "下読み中"
    CHATTER = "雑談部分の判定中"
    TRANSCRIBING = "文字起こし中"
    DIARIZING = "話者分離中"
    FORMATTING = "整形中"
    WRITING = "書き出し中"
    DONE = "完了"


@dataclass
class ProgressEvent:
    """進捗 1 件分。

    Attributes:
        stage: 現在の工程。
        detail: 「3/12 件」のような補足。空でもよい。
        fraction: 工程内の進み具合（0.0〜1.0）。不明なら None。
        file_index: 何ファイル目か（1 始まり）。
        file_total: 全部で何ファイルか。
        file_name: 処理中のファイル名。
    """

    stage: Stage
    detail: str = ""
    fraction: float | None = None
    file_index: int = 1
    file_total: int = 1
    file_name: str = ""

    def message(self) -> str:
        """画面に出す 1 行のメッセージを組み立てる。"""
        head = self.stage.value
        if self.file_total > 1:
            head = f"[{self.file_index}/{self.file_total}] {head}"
        if self.detail:
            head = f"{head}（{self.detail}）"
        return head


class ProgressSink(Protocol):
    """進捗の受け取り手（GUI など）が満たすべきインターフェース。"""

    def update(self, event: ProgressEvent) -> None: ...


class ProgressReporter:
    """処理側から進捗を報告し、キャンセル要求を確認するための窓口。

    スレッド安全。GUI スレッドからキャンセルフラグを立て、
    処理スレッドが :meth:`check_cancelled` で拾う。
    """

    def __init__(
        self,
        callback: Callable[[ProgressEvent], None] | None = None,
        *,
        file_index: int = 1,
        file_total: int = 1,
        file_name: str = "",
    ) -> None:
        self._callback = callback
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self.file_index = file_index
        self.file_total = file_total
        self.file_name = file_name
        self.last_event: ProgressEvent | None = None

    def set_callback(self, callback: Callable[[ProgressEvent], None] | None) -> None:
        """報告先をあとから差し替える。

        進捗ウィンドウは「キャンセル時に呼ぶ関数」としてこのレポーターを必要とし、
        レポーターは「進捗の届け先」としてウィンドウを必要とする。
        相互参照になるため、レポーターを先に作り、あとからここで結び付ける。
        """
        self._callback = callback

    # --- 進捗 -----------------------------------------------------------

    def report(
        self,
        stage: Stage,
        detail: str = "",
        fraction: float | None = None,
    ) -> None:
        """現在の工程を報告する。ここでキャンセル要求も確認する。

        Raises:
            CancelledByUserError: 利用者がキャンセルを押していた場合。
        """
        self.check_cancelled()
        event = ProgressEvent(
            stage=stage,
            detail=detail,
            fraction=fraction,
            file_index=self.file_index,
            file_total=self.file_total,
            file_name=self.file_name,
        )
        with self._lock:
            self.last_event = event
        if self._callback is not None:
            self._callback(event)

    def for_file(self, index: int, total: int, name: str) -> "ProgressReporter":
        """ファイル情報だけを差し替えた子レポーターを作る（キャンセルは共有）。"""
        child = ProgressReporter(
            self._callback, file_index=index, file_total=total, file_name=name
        )
        child._cancel = self._cancel  # キャンセルフラグは全ファイルで共有する
        return child

    # --- キャンセル -----------------------------------------------------

    def cancel(self) -> None:
        """キャンセルを要求する（GUI スレッドから呼ばれる）。"""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check_cancelled(self) -> None:
        """キャンセルされていれば例外を投げる。時間のかかるループ内で呼ぶ。"""
        if self._cancel.is_set():
            raise CancelledByUserError()


class ConsoleProgress:
    """コマンドラインから実行したときの進捗表示。"""

    def __init__(self, stream=None) -> None:
        self._stream = stream or sys.stdout
        self._last = ""

    def update(self, event: ProgressEvent) -> None:
        message = event.message()
        if event.fraction is not None:
            message = f"{message} {event.fraction * 100:5.1f}%"
        if message == self._last:
            return
        self._last = message
        print(message, file=self._stream, flush=True)


def null_reporter() -> ProgressReporter:
    """進捗を捨てるレポーター（テスト用）。"""
    return ProgressReporter(None)
