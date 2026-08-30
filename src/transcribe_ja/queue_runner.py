"""複数ファイル選択時に、プロセスが大量に立ち上がるのを防ぐ仕組み。

■ 何が問題か

Windows のシェルは、複数のファイルを選んで右クリックメニューを実行すると
**ファイルの数だけコマンドを起動する**。20 個選べば 20 個のプロセスが同時に
立ち上がり、それぞれが文字起こしモデルを読み込もうとしてメモリを食い尽くす。

■ どう解決するか

    起動 → キューファイルに自分の担当ファイルを 1 行追記
         → ロックの取得を試みる
            ├─ 取れた   … 自分がワーカーになる。少し待ってからキューを順に処理
            └─ 取れない … 既にワーカーがいる。何もせず終了（一瞬で消える）

ロックには OS のファイルロック（Windows: msvcrt / その他: fcntl）を使う。
プロセスが異常終了しても OS が自動的に解放するため、ロックが残り続けない。

■ デバウンス

シェルは 20 個のプロセスを同時ではなく数百ミリ秒かけて起動する。
そのため最初のプロセスがすぐ処理を始めると、後続のファイルが別バッチになる。
ワーカーは 1〜2 秒待ってからキューを読むことで、全部を同じバッチにまとめる。
また、処理が終わったあとも一度だけ猶予時間を置いて再確認し、
取りこぼしが起きないようにしている。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from .logging_setup import get_logger
from .paths import is_windows, queue_dir

logger = get_logger("queue")

QUEUE_FILE_NAME = "pending.jsonl"
LOCK_FILE_NAME = "worker.lock"

#: キューファイルの取り込みを再試行する回数（他プロセスが書き込み中の場合用）。
_TAKE_RETRIES = 5
_TAKE_RETRY_WAIT = 0.1


class FileLock:
    """OS のファイルロックによる単一インスタンス制御。

    ``with`` ではなく :meth:`acquire` / :meth:`release` を使う。
    取得できなかった場合は False を返すだけで、例外にはしない。
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> bool:
        """ロックを試みる。取得できたら True。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as exc:
            logger.warning("ロックファイルを開けませんでした: %s", exc)
            # ロックが使えない環境では、単独プロセスとして動かす
            return True

        try:
            if is_windows():
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False

        self._fd = fd
        try:
            os.truncate(fd, 0)
            os.write(fd, f"{os.getpid()} {time.time():.0f}".encode())
        except OSError:
            pass
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            if is_windows():
                import msvcrt

                os.lseek(self._fd, 0, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None


@dataclass
class QueueRunner:
    """キューへの追加と、ワーカーとしての取り出しを担当する。"""

    debounce_seconds: float = 1.5
    directory: Path | None = None

    def __post_init__(self) -> None:
        self._dir = Path(self.directory) if self.directory else queue_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._queue_file = self._dir / QUEUE_FILE_NAME
        self._lock = FileLock(self._dir / LOCK_FILE_NAME)

    # --- 追加 -------------------------------------------------------------

    def enqueue(self, paths: Sequence[Path | str]) -> int:
        """処理したいファイルをキューに追記する。

        ロックの取得より **先に** 呼ぶこと。そうしないと、
        ワーカーが処理を終えた直後に追記されたファイルを取りこぼす。
        """
        written = 0
        try:
            with self._queue_file.open("a", encoding="utf-8") as fp:
                for path in paths:
                    record = {"path": str(Path(path).resolve()), "at": time.time()}
                    fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                    written += 1
        except OSError as exc:
            logger.error("キューに書き込めませんでした: %s", exc)
            raise
        logger.info("キューに %d 件を追加しました", written)
        return written

    # --- ワーカー ---------------------------------------------------------

    def become_worker(self) -> bool:
        """ワーカーになれるか試す。False なら別のプロセスが処理中。"""
        acquired = self._lock.acquire()
        logger.info("ワーカー権の取得: %s", "成功" if acquired else "失敗（既に処理中）")
        return acquired

    def release(self) -> None:
        self._lock.release()

    def _take_all(self) -> list[Path]:
        """キューの内容をすべて取り出し、キューを空にする。

        追記中の他プロセスと衝突しないよう、いったん別名に移してから読む。
        """
        if not self._queue_file.exists():
            return []

        staging = self._dir / f"processing_{os.getpid()}.jsonl"
        for attempt in range(_TAKE_RETRIES):
            try:
                os.replace(self._queue_file, staging)
                break
            except FileNotFoundError:
                return []
            except OSError:
                # 他プロセスが書き込み中。少し待って再試行する。
                if attempt == _TAKE_RETRIES - 1:
                    logger.warning("キューファイルを取り込めませんでした（次の周回で再試行します）")
                    return []
                time.sleep(_TAKE_RETRY_WAIT)

        paths: list[Path] = []
        seen: set[str] = set()
        try:
            for line in staging.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    raw = str(record["path"])
                except (json.JSONDecodeError, KeyError, TypeError):
                    logger.warning("キューの行を解釈できませんでした: %s", line[:120])
                    continue
                if raw in seen:
                    continue  # 同じファイルが二重に登録された場合は 1 回だけ処理する
                seen.add(raw)
                paths.append(Path(raw))
        except OSError as exc:
            logger.error("キューを読み込めませんでした: %s", exc)
        finally:
            staging.unlink(missing_ok=True)

        return paths

    def iter_batches(self) -> Iterator[list[Path]]:
        """処理すべきファイルのまとまりを順に返す。

        最初にデバウンス時間だけ待つことで、シェルが次々に起動してくる
        プロセスの登録を待ち合わせ、1 つのバッチにまとめる。
        """
        grace_used = False
        while True:
            time.sleep(self.debounce_seconds)
            batch = self._take_all()
            if batch:
                grace_used = False
                yield batch
                continue

            if grace_used:
                logger.info("キューが空になりました。ワーカーを終了します。")
                return
            # 一度だけ猶予をとって、取りこぼしがないか確認する
            grace_used = True
