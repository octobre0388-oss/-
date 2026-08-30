"""ログの設定。%APPDATA%\\TranscribeJA\\logs\\ にローテーション付きで保存する。

右クリック起動ではコンソールが無いため、調査の手がかりはログだけになる。
そのため「何をしようとして失敗したか」が追えるように、各工程の開始・終了と
外部コマンドの実行内容を必ず記録する。
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from .paths import logs_dir

LOG_FILE_NAME = "transcribe_ja.log"

#: 1 ファイルあたりの上限（2 MB）と世代数。合計でも 10 MB 程度に収まる。
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 5

_configured = False


def setup_logging(level: str = "INFO", *, to_console: bool = False) -> logging.Logger:
    """ロガーを初期化して、本ツールのルートロガーを返す。

    Args:
        level: "DEBUG" / "INFO" / "WARNING" / "ERROR"
        to_console: 標準エラー出力にも出すか（コマンドラインから試すとき用）。
    """
    global _configured
    logger = logging.getLogger("transcribe_ja")

    if _configured:
        return logger

    try:
        numeric_level = getattr(logging, str(level).upper())
        if not isinstance(numeric_level, int):
            raise AttributeError
    except AttributeError:
        numeric_level = logging.INFO

    logger.setLevel(numeric_level)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        log_path: Path = logs_dir() / LOG_FILE_NAME
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        # ログが書けない状況でも本体は動かす（読み取り専用プロファイルなど）。
        pass

    if to_console:
        stream = logging.StreamHandler(stream=sys.stderr)
        stream.setFormatter(formatter)
        logger.addHandler(stream)

    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    _configured = True
    return logger


def get_logger(name: str = "") -> logging.Logger:
    """モジュール用のロガーを取得する。"""
    if name:
        return logging.getLogger(f"transcribe_ja.{name}")
    return logging.getLogger("transcribe_ja")


def current_log_file() -> Path:
    return logs_dir() / LOG_FILE_NAME
