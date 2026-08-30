"""雑談カットの判定と安全装置のテスト。"""

from __future__ import annotations

import pytest

from transcribe_ja.chatter import complement_intervals, select_cuts
from transcribe_ja.chatter.rules import Judgement, judge_segments, load_rules
from transcribe_ja.transcribe import TranscriptSegment


@pytest.fixture(scope="module")
def 辞書():
    return load_rules()


def _判定(segments, 辞書, safety="conservative", total=None):
    return judge_segments(segments, 辞書, safety, total or segments[-1].end)


def test_冒頭の機材確認は不要と判定される(辞書):
    segments = [
        TranscriptSegment(0, 6, "お疲れ様です。聞こえてますか、マイク大丈夫ですか。"),
        TranscriptSegment(6, 40, "では議題です。資料の3ページ目の予算について検討します。"),
    ]
    judgements = _判定(segments, 辞書, total=40)
    assert judgements[0].unnecessary is True
    assert judgements[1].unnecessary is False


def test_本編を示す語があれば残る(辞書):
    segments = [
        TranscriptSegment(0, 5, "お疲れ様です。資料の確認をお願いしたいです。"),
    ]
    judgements = _判定(segments, 辞書, total=5)
    assert judgements[0].unnecessary is False


def test_安全度で判定が変わる(辞書):
    """同じ点数でも、しきい値の違いで残す／切るが変わること。"""
    # 会議の途中にある挨拶だけの発話（根拠が 1 つだけなので点数は中程度）
    segments = [TranscriptSegment(50, 55, "お疲れ様です。")]

    scores = {}
    decisions = {}
    for safety in ("conservative", "balanced", "aggressive"):
        judgement = _判定(segments, 辞書, safety, 100)[0]
        scores[safety] = judgement.score
        decisions[safety] = judgement.unnecessary

    # 点数は安全度によらず同じ（変わるのはしきい値だけ）
    assert len(set(scores.values())) == 1
    assert decisions["conservative"] is False, "既定では迷ったら残すこと"
    assert decisions["aggressive"] is True


def test_笑い声だけの区間は不要寄りに判定される(辞書):
    segments = [TranscriptSegment(10, 12, "ははは。")]
    judgements = _判定(segments, 辞書, "aggressive", 100)
    assert judgements[0].unnecessary is True


def test_判定理由が記録される(辞書):
    segments = [TranscriptSegment(0, 4, "お疲れ様です。聞こえてますか。")]
    judgement = _判定(segments, 辞書, total=100)[0]
    assert "挨拶" in judgement.reason_text()
    assert "機材" in judgement.reason_text()


def test_点数は0から1の範囲に収まる(辞書):
    segments = [
        TranscriptSegment(0, 3, "お疲れ様です。聞こえてますか。今日は暑いですね。失礼します。"),
        TranscriptSegment(3, 60, "資料の議題について決定事項を報告します。"),
    ]
    for judgement in _判定(segments, 辞書, total=60):
        assert 0.0 <= judgement.score <= 1.0


def test_辞書が空なら何も切らない():
    from transcribe_ja.chatter.rules import RuleSet

    segments = [TranscriptSegment(0, 5, "お疲れ様です。")]
    judgements = judge_segments(segments, RuleSet(), "conservative", 5)
    assert not any(j.unnecessary for j in judgements)


# --- 安全装置 ---------------------------------------------------------------


def _候補(*spans):
    return [
        Judgement(i, TranscriptSegment(s, e, "x"), score, [], True)
        for i, (s, e, score) in enumerate(spans)
    ]


def test_上限内なら全部カットされる():
    candidates = _候補((0, 10, 0.9), (20, 25, 0.9))
    assert len(select_cuts(candidates, 100, 0.35)) == 2


def test_上限を超えると点数の低いものから外れる():
    candidates = _候補((0, 30, 0.95), (40, 70, 0.60))
    selected = select_cuts(candidates, 100, 0.35)
    assert len(selected) == 1
    assert selected[0].score == pytest.approx(0.95)


def test_上限がゼロなら何も切らない():
    assert select_cuts(_候補((0, 10, 0.9)), 100, 0.0) == []


def test_選ばれた区間は時刻順に並ぶ():
    candidates = _候補((50, 55, 0.9), (10, 15, 0.8))
    selected = select_cuts(candidates, 1000, 1.0)
    assert [j.segment.start for j in selected] == [10, 50]


# --- 残す区間の計算 ---------------------------------------------------------


def test_カットの残りが残す区間になる():
    kept = complement_intervals([(10, 20), (40, 50)], 60)
    assert [(i.start, i.end) for i in kept] == [(0, 10), (20, 40), (50, 60)]


def test_先頭からカットする場合():
    kept = complement_intervals([(0, 10)], 30)
    assert [(i.start, i.end) for i in kept] == [(10, 30)]


def test_末尾までカットする場合():
    kept = complement_intervals([(20, 30)], 30)
    assert [(i.start, i.end) for i in kept] == [(0, 20)]


def test_全部カットすると残らない():
    assert complement_intervals([(0, 30)], 30) == []


def test_カットが無ければ全部残る():
    kept = complement_intervals([], 30)
    assert [(i.start, i.end) for i in kept] == [(0, 30)]


def test_重なったカットもまとめて扱える():
    kept = complement_intervals([(10, 25), (20, 30)], 40)
    assert [(i.start, i.end) for i in kept] == [(0, 10), (30, 40)]
