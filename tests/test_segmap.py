"""セグメントマップの単体テスト（本プロジェクトで最も重要なテスト）。

ここが壊れると、出力される字幕の時刻が元動画とずれる。
境界値・合成・往復変換をしつこく検証する。
"""

from __future__ import annotations

import random

import pytest

from transcribe_ja.segmap import EPS, Interval, SegmentMap, normalize_intervals


# --- normalize_intervals ---------------------------------------------------


def test_正規化は昇順に並べ替える():
    result = normalize_intervals([(30, 40), (0, 10)])
    assert [(i.start, i.end) for i in result] == [(0, 10), (30, 40)]


def test_正規化は重なった区間を結合する():
    result = normalize_intervals([(0, 10), (5, 20)])
    assert [(i.start, i.end) for i in result] == [(0, 20)]


def test_正規化は接した区間を結合する():
    result = normalize_intervals([(0, 10), (10, 20)])
    assert [(i.start, i.end) for i in result] == [(0, 20)]


def test_正規化は長さゼロの区間を捨てる():
    assert normalize_intervals([(5, 5), (0, 3)]) == [Interval(0, 3)]


def test_正規化は負の開始時刻をゼロに丸める():
    assert normalize_intervals([(-3, 4)]) == [Interval(0, 4)]


def test_終了が開始より前の区間はエラー():
    with pytest.raises(ValueError):
        Interval(10, 5)


# --- 基本的な時刻変換 -------------------------------------------------------


@pytest.fixture()
def 二区間マップ() -> SegmentMap:
    """元 60 秒のうち 0-5 秒と 20-30 秒だけを残したマップ（後の長さは 15 秒）。"""
    return SegmentMap([(0, 5), (20, 30)], source_duration=60)


def test_カットなしなら時刻はそのまま(二区間マップ):
    ident = SegmentMap.identity(100)
    for t in (0, 0.5, 33.3, 100):
        assert ident.to_source(t) == pytest.approx(t)


def test_最初の区間内は元の時刻と一致する(二区間マップ):
    assert 二区間マップ.to_source(0) == pytest.approx(0)
    assert 二区間マップ.to_source(3) == pytest.approx(3)


def test_二つ目の区間は削除分だけずれる(二区間マップ):
    # 後の 5 秒 = 元の 20 秒、後の 10 秒 = 元の 25 秒
    assert 二区間マップ.to_source(6) == pytest.approx(21)
    assert 二区間マップ.to_source(10) == pytest.approx(25)
    assert 二区間マップ.to_source(15) == pytest.approx(30)


def test_継ぎ目は開始と終了で解釈が変わる(二区間マップ):
    """カットの継ぎ目（後の 5 秒）は、開始時刻なら 20 秒、終了時刻なら 5 秒。"""
    assert 二区間マップ.to_source(5, prefer="start") == pytest.approx(20)
    assert 二区間マップ.to_source(5, prefer="end") == pytest.approx(5)


def test_範囲外の時刻は端に丸められる(二区間マップ):
    assert 二区間マップ.to_source(-5) == pytest.approx(0)
    assert 二区間マップ.to_source(999, prefer="end") == pytest.approx(30)


def test_先頭に無音がある場合(二区間マップ):
    m = SegmentMap([(12, 20)], source_duration=40)
    assert m.to_source(0) == pytest.approx(12)
    assert m.to_source(8, prefer="end") == pytest.approx(20)


def test_区間が空なら変換は失敗する():
    m = SegmentMap([], source_duration=30)
    assert m.is_empty()
    with pytest.raises(ValueError):
        m.to_source(0)


# --- 統計情報 ---------------------------------------------------------------


def test_削除量と削除率(二区間マップ):
    assert 二区間マップ.processed_duration == pytest.approx(15)
    assert 二区間マップ.removed_duration == pytest.approx(45)
    assert 二区間マップ.removed_ratio == pytest.approx(0.75)


def test_削除区間には末尾も含まれる(二区間マップ):
    gaps = [(g.start, g.end) for g in 二区間マップ.removed_intervals()]
    assert gaps == [(5, 20), (30, 60)]


def test_元の長さが未指定なら最後の区間の終端になる():
    m = SegmentMap([(0, 5), (20, 30)])
    assert m.source_duration == pytest.approx(30)
    assert m.removed_duration == pytest.approx(15)


def test_元の長さがゼロでも削除率は計算できる():
    assert SegmentMap([], source_duration=0).removed_ratio == 0.0


# --- 区間の変換 -------------------------------------------------------------


def test_区間変換はカットをまたぐと削除部分も含む(二区間マップ):
    start, end = 二区間マップ.to_source_span(4, 6)
    assert start == pytest.approx(4)
    assert end == pytest.approx(21)


def test_分解はカットをまたぐと複数区間になる(二区間マップ):
    parts = [(p.start, p.end) for p in 二区間マップ.split_to_source(4, 6)]
    assert parts == [(4, 5), (20, 21)]


def test_分解は区間内に収まれば一本(二区間マップ):
    parts = [(p.start, p.end) for p in 二区間マップ.split_to_source(6, 8)]
    assert parts == [(21, 23)]


def test_長さゼロの区間は分解結果が空(二区間マップ):
    assert 二区間マップ.split_to_source(5, 5) == []


def test_分解は範囲外を切り詰める(二区間マップ):
    parts = [(p.start, p.end) for p in 二区間マップ.split_to_source(-10, 999)]
    assert parts == [(0, 5), (20, 30)]


# --- 合成（2 段階カット） ---------------------------------------------------


def test_合成の基本():
    """元 60 秒 → 無音カットで 15 秒 → 雑談カットで 8 秒、という 2 段階。"""
    vad = SegmentMap([(0, 5), (20, 30)], source_duration=60)
    # 無音除去後の 2〜10 秒だけを本編とする
    chatter = SegmentMap([(2, 10)], source_duration=15)
    total = vad.then(chatter)

    assert [(i.start, i.end) for i in total.kept] == [(2, 5), (20, 25)]
    assert total.processed_duration == pytest.approx(8)
    assert total.source_duration == pytest.approx(60)
    # 本編のみの 0 秒 = 元の 2 秒、本編のみの 3 秒 = 元の 20 秒
    assert total.to_source(0) == pytest.approx(2)
    assert total.to_source(3, prefer="start") == pytest.approx(20)
    assert total.to_source(3, prefer="end") == pytest.approx(5)


def test_合成は段階的に適用したものと一致する():
    """total.to_source(t) == vad.to_source(chatter.to_source(t)) であること。"""
    vad = SegmentMap([(3, 11), (25, 40), (50, 55)], source_duration=70)
    chatter = SegmentMap([(1, 6), (9, 20)], source_duration=vad.processed_duration)
    total = vad.then(chatter)

    for i in range(0, int(total.processed_duration * 10)):
        t = i / 10
        expected = vad.to_source(chatter.to_source(t))
        assert total.to_source(t) == pytest.approx(expected, abs=1e-6)


def test_恒等マップとの合成は元のまま():
    vad = SegmentMap([(2, 8), (12, 20)], source_duration=30)
    ident = SegmentMap.identity(vad.processed_duration)
    assert vad.then(ident).kept == vad.kept


def test_空マップとの合成は空になる():
    vad = SegmentMap([(0, 10)], source_duration=20)
    empty = SegmentMap([], source_duration=10)
    assert vad.then(empty).is_empty()
    assert empty.then(vad).is_empty()


def test_合成は結合法則を満たす():
    """(a then b) then c と a then (b then c) が一致すること。"""
    a = SegmentMap([(0, 10), (15, 40)], source_duration=50)
    b = SegmentMap([(2, 8), (12, 30)], source_duration=a.processed_duration)
    c = SegmentMap([(1, 5), (7, 18)], source_duration=b.processed_duration)

    left = a.then(b).then(c)
    right = a.then(b.then(c))
    assert [(i.start, i.end) for i in left.kept] == pytest.approx(
        [(i.start, i.end) for i in right.kept]
    )


def test_三段合成でも元の時刻に戻せる():
    a = SegmentMap([(5, 25), (30, 60)], source_duration=90)
    b = SegmentMap([(0, 10), (15, 45)], source_duration=a.processed_duration)
    c = SegmentMap([(3, 30)], source_duration=b.processed_duration)
    total = a.then(b).then(c)

    for i in range(0, int(total.processed_duration)):
        expected = a.to_source(b.to_source(c.to_source(float(i))))
        assert total.to_source(float(i)) == pytest.approx(expected, abs=1e-6)


# --- ランダムデータによる往復検証 -------------------------------------------


def _ランダムマップ(rng: random.Random, source_duration: float) -> SegmentMap:
    """source_duration の中からランダムに区間を選んだマップを作る。"""
    kept = []
    cursor = rng.uniform(0, 3)
    while cursor < source_duration:
        length = rng.uniform(0.5, 8)
        end = min(cursor + length, source_duration)
        if end - cursor > 0.1:
            kept.append((cursor, end))
        cursor = end + rng.uniform(0.1, 5)
    return SegmentMap(kept, source_duration=source_duration)


@pytest.mark.parametrize("seed", range(30))
def test_変換結果は必ず残した区間の中に収まる(seed: int):
    """どんな時刻を変換しても、削除した区間の時刻が返ってきてはいけない。"""
    rng = random.Random(seed)
    m = _ランダムマップ(rng, 120.0)
    if m.is_empty():
        pytest.skip("区間が空になったケース")

    for _ in range(100):
        t = rng.uniform(0, m.processed_duration)
        src = m.to_source(t)
        assert any(
            iv.start - EPS <= src <= iv.end + EPS for iv in m.kept
        ), f"変換結果 {src} が残した区間の外にある"


@pytest.mark.parametrize("seed", range(30))
def test_変換は単調増加する(seed: int):
    """後の時刻が進めば、元の時刻も必ず進む（逆行しない）。"""
    rng = random.Random(seed)
    m = _ランダムマップ(rng, 120.0)
    if m.is_empty():
        pytest.skip("区間が空になったケース")

    times = sorted(rng.uniform(0, m.processed_duration) for _ in range(50))
    converted = [m.to_source(t) for t in times]
    assert converted == sorted(converted)


@pytest.mark.parametrize("seed", range(20))
def test_合成マップは段階適用と一致する(seed: int):
    rng = random.Random(seed)
    a = _ランダムマップ(rng, 100.0)
    if a.is_empty():
        pytest.skip("区間が空になったケース")
    b = _ランダムマップ(rng, a.processed_duration)
    if b.is_empty():
        pytest.skip("区間が空になったケース")

    total = a.then(b)
    if total.is_empty():
        pytest.skip("合成結果が空になったケース")

    for _ in range(50):
        t = rng.uniform(0, total.processed_duration)
        assert total.to_source(t) == pytest.approx(a.to_source(b.to_source(t)), abs=1e-6)


@pytest.mark.parametrize("seed", range(20))
def test_残した区間の合計と加工後の長さが一致する(seed: int):
    rng = random.Random(seed)
    m = _ランダムマップ(rng, 100.0)
    assert m.processed_duration == pytest.approx(sum(iv.duration for iv in m.kept))
    assert m.processed_duration + m.removed_duration == pytest.approx(m.source_duration)
