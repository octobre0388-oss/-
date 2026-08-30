"""コマンドラインの入り口。右クリックメニューからもここが呼ばれる。

■ 起動されたプロセスの役割分担

    1. 引数のファイルをキューに追記する（必ず最初に行う）
    2. ワーカー権（ロック）の取得を試みる
       ├─ 取れた   … 進捗ウィンドウを出し、キューを順番に処理する
       └─ 取れない … 既に別のウィンドウが処理しているので、何もせず終了

こうすることで、20 個のファイルを選んでも進捗ウィンドウは 1 つだけになる。
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path
from typing import Sequence

from . import APP_NAME, MENU_LABEL, __version__
from .config import Config, load as load_config
from .errors import CancelledByUserError, ConfigError, TranscribeJAError
from .ffmpeg_tools import Ffmpeg
from .logging_setup import current_log_file, get_logger, setup_logging
from .pipeline import process_file
from .progress import ConsoleProgress, ProgressReporter
from .queue_runner import QueueRunner

logger = get_logger("cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="transcribe_ja",
        description=f"{MENU_LABEL} - 音声・動画ファイルを日本語で文字起こしします。",
    )
    parser.add_argument("files", nargs="*", help="処理する音声・動画ファイル")
    parser.add_argument("--config", type=Path, default=None, help="設定ファイルのパス")
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="進捗ウィンドウを出さず、コンソールに進捗を表示する",
    )
    parser.add_argument(
        "--console", action="store_true", help="ログを画面にも出す（不具合調査用）"
    )
    parser.add_argument(
        "--settings", action="store_true", help="設定画面を開く"
    )
    parser.add_argument(
        "--open-config", action="store_true", help="設定ファイルをメモ帳などで開く"
    )
    parser.add_argument(
        "--open-logs", action="store_true", help="ログファイルを開く"
    )
    parser.add_argument(
        "--no-queue",
        action="store_true",
        help="キューを使わず、この場で処理する（動作確認用）",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return parser


def _show_fatal(message: str, use_gui: bool) -> None:
    """致命的なエラーを利用者に伝える。"""
    logger.error(message.replace("\n", " / "))
    if use_gui:
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(APP_NAME, message)
            root.destroy()
            return
        except Exception:  # pragma: no cover - GUI が使えない環境
            pass
    print(message, file=sys.stderr)


def _summarize(
    processed: int, failures: Sequence[tuple[Path, str]], cancelled: bool
) -> str:
    lines: list[str] = []
    if cancelled:
        lines.append("処理をキャンセルしました。")
    lines.append(f"{processed} 件のファイルを処理しました。")
    if failures:
        lines.append("")
        lines.append(f"{len(failures)} 件のファイルは処理できませんでした:")
        for path, message in failures:
            first = message.strip().splitlines()[0] if message.strip() else ""
            lines.append(f"  ・{path.name}: {first}")
        lines.append("")
        lines.append(f"詳しい内容はログをご覧ください:\n{current_log_file()}")
    return "\n".join(lines)


def process_all(
    batches, config: Config, reporter: ProgressReporter
) -> tuple[int, list[tuple[Path, str]], bool, Path | None]:
    """キューから来たファイルを順番に処理する。

    Returns:
        (成功件数, 失敗の一覧, キャンセルされたか, 最後の出力先フォルダ)
    """
    tools = Ffmpeg.locate(config.advanced.ffmpeg_path, config.advanced.ffprobe_path)

    processed = 0
    failures: list[tuple[Path, str]] = []
    cancelled = False
    last_dir: Path | None = None
    done = 0
    total = 0

    for batch in batches:
        total += len(batch)
        for path in batch:
            done += 1
            child = reporter.for_file(done, total, path.name)
            try:
                result = process_file(path, config, child, tools)
                processed += 1
                last_dir = result.output_dir
            except CancelledByUserError:
                logger.info("利用者の操作により中断しました。")
                cancelled = True
                return processed, failures, cancelled, last_dir
            except TranscribeJAError as exc:
                logger.error("処理に失敗しました: %s / %s", path, exc.message)
                failures.append((path, exc.user_message()))
            except Exception as exc:  # 想定外の例外もここで受け止める
                logger.error("想定外のエラー: %s\n%s", path, traceback.format_exc())
                failures.append(
                    (
                        path,
                        f"想定外のエラーが発生しました（{type(exc).__name__}）。\n"
                        f"ログをご確認ください:\n{current_log_file()}",
                    )
                )
    return processed, failures, cancelled, last_dir


def _notify_result(
    config: Config,
    processed: int,
    failures: Sequence[tuple[Path, str]],
    cancelled: bool,
    last_dir: Path | None,
    elapsed: float,
) -> str:
    """結果をトースト通知で知らせ、画面に出す用の要約文を返す。"""
    from .gui.notify import notify_failure, notify_success

    summary = _summarize(processed, failures, cancelled)
    if not config.advanced.show_notification:
        return summary

    if failures:
        notify_failure(summary)
    elif processed and not cancelled:
        notify_success(processed, last_dir or Path.cwd(), elapsed)
    return summary


def _run_with_gui(runner, config: Config) -> int:
    """進捗ウィンドウを出しながら処理する。

    tkinter が使えない環境では、コンソール表示に切り替える
    （pythonw から起動されていると画面には何も出ないが、
    ログと通知は残るので「無反応で終わる」状態を避けられる）。
    """
    import threading

    from .gui.progress_window import ProgressWindow

    reporter = ProgressReporter(None)
    try:
        window = ProgressWindow(on_cancel=reporter.cancel)
    except Exception as exc:
        logger.warning("進捗ウィンドウを開けなかったため、画面なしで処理します: %s", exc)
        return _run_console(runner, config)

    reporter.set_callback(window.post)

    outcome: dict[str, object] = {}
    started = time.time()

    def _work() -> None:
        try:
            outcome["result"] = process_all(runner.iter_batches(), config, reporter)
        except TranscribeJAError as exc:
            outcome["fatal"] = exc.user_message()
        except Exception:
            logger.error("ワーカーで想定外のエラー:\n%s", traceback.format_exc())
            outcome["fatal"] = (
                f"想定外のエラーが発生しました。\nログをご確認ください:\n{current_log_file()}"
            )
        finally:
            window.post_done()

    thread = threading.Thread(target=_work, name="transcribe-worker", daemon=True)
    thread.start()
    window.mainloop()
    thread.join(timeout=5)

    fatal = outcome.get("fatal")
    if isinstance(fatal, str):
        if config.advanced.show_notification:
            from .gui.notify import notify_failure

            notify_failure(fatal)
        _show_fatal(fatal, use_gui=True)
        return 1

    result = outcome.get("result")
    if not isinstance(result, tuple):
        return 1
    processed, failures, cancelled, last_dir = result

    summary = _notify_result(
        config, processed, failures, cancelled, last_dir, time.time() - started
    )
    if failures:
        _show_fatal(summary, use_gui=True)
    return 0 if not failures else 1


def _run_console(runner, config: Config) -> int:
    """コンソールに進捗を出しながら処理する（動作確認・自動化用）。"""
    reporter = ProgressReporter(ConsoleProgress().update)
    started = time.time()
    try:
        processed, failures, cancelled, last_dir = process_all(
            runner.iter_batches(), config, reporter
        )
    except TranscribeJAError as exc:
        if config.advanced.show_notification:
            from .gui.notify import notify_failure

            notify_failure(exc.user_message())
        _show_fatal(exc.user_message(), use_gui=False)
        return 1

    elapsed = time.time() - started
    summary = _notify_result(config, processed, failures, cancelled, last_dir, elapsed)
    print(summary)
    print(f"所要時間: {elapsed:.1f} 秒")
    return 0 if not failures else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    use_gui = not args.no_gui

    # --- 設定の読み込み ---------------------------------------------------
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        _show_fatal(exc.user_message(), use_gui)
        return 2

    setup_logging(config.general.log_level, to_console=args.console or args.no_gui)
    logger.info("起動しました（%s %s / 引数 %d 件）", APP_NAME, __version__, len(args.files))

    if not config.advanced.show_progress_window:
        use_gui = False

    # --- 単発の操作 -------------------------------------------------------
    if args.open_config:
        from .gui.settings_window import open_config_file

        print(f"設定ファイル: {open_config_file()}")
        return 0

    if args.open_logs:
        from .gui.settings_window import open_in_editor

        open_in_editor(current_log_file())
        print(f"ログファイル: {current_log_file()}")
        return 0

    if args.settings or not args.files:
        if not args.files and not args.settings:
            logger.info("ファイルが指定されなかったため、設定画面を表示します。")
        try:
            from .gui.settings_window import show_settings_window

            show_settings_window()
        except Exception as exc:
            logger.warning("設定画面を開けませんでした: %s", exc)
            from .gui.settings_window import open_config_file

            print(f"設定ファイル: {open_config_file()}")
        return 0

    # --- ファイルの処理 ---------------------------------------------------
    files = [Path(f) for f in args.files]

    if args.no_queue:
        # キューを介さず、この場で処理する（テスト・自動化向け）
        runner = _SingleBatch(files)
        return _run_console(runner, config) if not use_gui else _run_with_gui(runner, config)

    runner = QueueRunner(debounce_seconds=config.advanced.queue_debounce_seconds)
    try:
        runner.enqueue(files)
    except OSError as exc:
        _show_fatal(
            f"処理待ちリストに書き込めませんでした。\n{exc}\n\n"
            "【対処方法】\nディスクの空き容量と、フォルダへの書き込み権限をご確認ください。",
            use_gui,
        )
        return 2

    if not runner.become_worker():
        # 既に別のプロセスが処理中。ここで静かに終了することで、
        # 複数ファイル選択時に大量のウィンドウが開くのを防ぐ。
        logger.info("既に処理中のウィンドウがあるため、このプロセスは終了します。")
        return 0

    try:
        return _run_with_gui(runner, config) if use_gui else _run_console(runner, config)
    finally:
        runner.release()


class _SingleBatch:
    """--no-queue 用に、1 バッチだけを返す簡易ランナー。"""

    def __init__(self, files: Sequence[Path]) -> None:
        self._files = list(files)

    def iter_batches(self):
        yield self._files

    def release(self) -> None:
        pass
