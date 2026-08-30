"""複数ファイル選択時の単一インスタンス制御のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from transcribe_ja.queue_runner import FileLock, QueueRunner


@pytest.fixture()
def キュー置き場(tmp_path: Path) -> Path:
    return tmp_path / "queue"


def _runner(directory: Path) -> QueueRunner:
    return QueueRunner(debounce_seconds=0.01, directory=directory)


def test_最初のプロセスだけがワーカーになる(キュー置き場):
    第一 = _runner(キュー置き場)
    第二 = _runner(キュー置き場)
    try:
        assert 第一.become_worker() is True
        assert 第二.become_worker() is False
    finally:
        第一.release()
        第二.release()


def test_ワーカーが終われば次のプロセスが担当できる(キュー置き場):
    第一 = _runner(キュー置き場)
    第二 = _runner(キュー置き場)
    assert 第一.become_worker() is True
    第一.release()
    try:
        assert 第二.become_worker() is True
    finally:
        第二.release()


def test_複数プロセスの登録が一つのバッチにまとまる(キュー置き場):
    """右クリックで複数選択したときの本命の挙動。"""
    プロセス = [_runner(キュー置き場) for _ in range(5)]
    for i, runner in enumerate(プロセス):
        runner.enqueue([f"/tmp/音声{i}.mp3"])

    ワーカー = プロセス[0]
    assert ワーカー.become_worker() is True
    assert all(p.become_worker() is False for p in プロセス[1:])

    try:
        batches = list(ワーカー.iter_batches())
    finally:
        ワーカー.release()

    assert len(batches) == 1, "1 つのバッチにまとまっていない"
    assert len(batches[0]) == 5
    assert [p.name for p in batches[0]] == [f"音声{i}.mp3" for i in range(5)]


def test_同じファイルを二重に登録しても一度だけ処理する(キュー置き場):
    runner = _runner(キュー置き場)
    runner.enqueue(["/tmp/同じ.mp3", "/tmp/同じ.mp3"])
    assert runner.become_worker()
    try:
        batches = list(runner.iter_batches())
    finally:
        runner.release()
    assert len(batches[0]) == 1


def test_キューが空ならバッチは返らない(キュー置き場):
    runner = _runner(キュー置き場)
    assert runner.become_worker()
    try:
        assert list(runner.iter_batches()) == []
    finally:
        runner.release()


def test_あとから追加されたファイルも拾われる(キュー置き場):
    """ワーカーが動き出したあとに登録されたファイルを取りこぼさないこと。"""
    ワーカー = _runner(キュー置き場)
    ワーカー.enqueue(["/tmp/最初.mp3"])
    assert ワーカー.become_worker()

    後発 = _runner(キュー置き場)
    集めた: list[str] = []
    try:
        for batch in ワーカー.iter_batches():
            集めた.extend(p.name for p in batch)
            if "最初.mp3" in 集めた and "後から.mp3" not in 集めた:
                後発.enqueue(["/tmp/後から.mp3"])
    finally:
        ワーカー.release()

    assert 集めた == ["最初.mp3", "後から.mp3"]


def test_壊れた行があっても他のファイルは処理される(キュー置き場):
    runner = _runner(キュー置き場)
    runner.enqueue(["/tmp/正常.mp3"])
    queue_file = キュー置き場 / "pending.jsonl"
    with queue_file.open("a", encoding="utf-8") as fp:
        fp.write("これはJSONではない\n")

    assert runner.become_worker()
    try:
        batches = list(runner.iter_batches())
    finally:
        runner.release()
    assert [p.name for p in batches[0]] == ["正常.mp3"]


def test_ロックは解放できる(tmp_path):
    lock = FileLock(tmp_path / "test.lock")
    assert lock.acquire() is True
    別のロック = FileLock(tmp_path / "test.lock")
    assert 別のロック.acquire() is False
    lock.release()
    assert 別のロック.acquire() is True
    別のロック.release()
