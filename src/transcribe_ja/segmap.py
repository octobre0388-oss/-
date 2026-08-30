"""セグメントマップ: 「加工後の音声の時刻」を「元ファイルの時刻」へ戻す。

■ なぜ必要か

本ツールは音声を 2 段階で切り詰める。

    元ファイル      0 ─────────────────────────────── 60:00
                        ↓ 無音カット（VAD）
    無音除去後      0 ──────────────────── 42:00
                        ↓ 雑談カット
    本編のみ        0 ──────────── 35:00      ← Whisper が時刻を返すのはこの軸

このまま出力すると、字幕の 10:00 が元動画の 10:00 と一致せず使い物にならない。
そこで「どの区間を残したか」を記録した SegmentMap を各段で作り、
``then()`` で合成して、最後に必ず元ファイルの時間軸へ戻す。

■ 用語

    source（元）    : 入力ファイルの時間軸。出力に書く時刻は必ずこちら。
    processed（後） : カット後の音声の時間軸。外に出してはいけない。
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

#: 浮動小数の比較に使う許容誤差（1 マイクロ秒）。音声の時刻としては十分細かい。
EPS = 1e-6

Prefer = Literal["start", "end"]


@dataclass(frozen=True)
class Interval:
    """時間区間 [start, end)。単位は秒。"""

    start: float
    end: float

    def __post_init__(self) -> None:
        if self.end < self.start - EPS:
            raise ValueError(f"区間の終了が開始より前です: start={self.start}, end={self.end}")

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def overlaps(self, other: "Interval") -> bool:
        return self.start < other.end - EPS and other.start < self.end - EPS


def normalize_intervals(intervals: Iterable[Sequence[float] | Interval]) -> list[Interval]:
    """区間の列を「昇順・重なりなし・長さ 0 を除去」した正規形に直す。

    VAD や雑談判定の出力は重なったり順不同だったりしうるので、
    SegmentMap を作る前に必ずここを通す。
    """
    items: list[Interval] = []
    for iv in intervals:
        if isinstance(iv, Interval):
            start, end = iv.start, iv.end
        else:
            start, end = float(iv[0]), float(iv[1])
        start = max(0.0, start)
        if end - start <= EPS:
            continue
        items.append(Interval(start, end))

    items.sort(key=lambda i: (i.start, i.end))

    merged: list[Interval] = []
    for iv in items:
        if merged and iv.start <= merged[-1].end + EPS:
            # 接している / 重なっている区間は 1 本にまとめる
            last = merged[-1]
            merged[-1] = Interval(last.start, max(last.end, iv.end))
        else:
            merged.append(iv)
    return merged


class SegmentMap:
    """残した区間の列と、それに基づく時刻変換。

    Args:
        kept: 残した区間。**この SegmentMap の入力側（source）の時間軸**で表す。
        source_duration: 元の音声の全長（秒）。削除率の計算と、末尾の
            削除区間の算出に使う。省略時は最後の区間の終端とみなす。
    """

    __slots__ = ("_kept", "_offsets", "_source_duration")

    def __init__(
        self,
        kept: Iterable[Sequence[float] | Interval],
        source_duration: float | None = None,
    ) -> None:
        self._kept: list[Interval] = normalize_intervals(kept)

        # _offsets[i] = kept[i] が加工後の時間軸で始まる位置
        offsets: list[float] = []
        acc = 0.0
        for iv in self._kept:
            offsets.append(acc)
            acc += iv.duration
        self._offsets = offsets

        last_end = self._kept[-1].end if self._kept else 0.0
        if source_duration is None:
            self._source_duration = last_end
        else:
            self._source_duration = max(float(source_duration), last_end)

    # --- 基本情報 -------------------------------------------------------------

    @classmethod
    def identity(cls, duration: float) -> "SegmentMap":
        """何もカットしていないマップ（全区間を残す）。"""
        return cls([(0.0, duration)], source_duration=duration)

    @property
    def kept(self) -> tuple[Interval, ...]:
        return tuple(self._kept)

    @property
    def source_duration(self) -> float:
        """入力側（元）の全長。"""
        return self._source_duration

    @property
    def processed_duration(self) -> float:
        """カット後の全長。"""
        return sum(iv.duration for iv in self._kept)

    @property
    def removed_duration(self) -> float:
        return max(0.0, self._source_duration - self.processed_duration)

    @property
    def removed_ratio(self) -> float:
        """削除された割合（0.0〜1.0）。元が長さ 0 のときは 0.0。"""
        if self._source_duration <= EPS:
            return 0.0
        return self.removed_duration / self._source_duration

    def is_empty(self) -> bool:
        return not self._kept

    def __repr__(self) -> str:  # pragma: no cover - デバッグ用
        return (
            f"SegmentMap(区間数={len(self._kept)}, "
            f"元={self._source_duration:.2f}s, 後={self.processed_duration:.2f}s, "
            f"削除率={self.removed_ratio:.1%})"
        )

    # --- 削除された区間 -------------------------------------------------------

    def removed_intervals(self) -> list[Interval]:
        """削除した区間を元の時間軸で返す（先頭・間・末尾すべて）。"""
        gaps: list[Interval] = []
        cursor = 0.0
        for iv in self._kept:
            if iv.start - cursor > EPS:
                gaps.append(Interval(cursor, iv.start))
            cursor = iv.end
        if self._source_duration - cursor > EPS:
            gaps.append(Interval(cursor, self._source_duration))
        return gaps

    # --- 時刻変換（このクラスの主目的） ---------------------------------------

    def to_source(self, processed_time: float, prefer: Prefer = "start") -> float:
        """カット後の時刻を、元ファイルの時刻に変換する。

        Args:
            processed_time: カット後の音声における秒数。
            prefer: 区間の継ぎ目にちょうど当たったときの解釈。

                * ``"start"``: 次の区間の先頭とみなす（発話の開始時刻に使う）
                * ``"end"``: 前の区間の末尾とみなす（発話の終了時刻に使う）

                例えば「0〜5 秒」と「20〜30 秒」を残した場合、カット後の 5 秒は
                元の 5 秒（前の区間の終わり）でも 20 秒（次の区間の始まり）でも
                ありうる。字幕の開始時刻なら 20 秒、終了時刻なら 5 秒が正しい。

        Returns:
            元ファイルにおける秒数。

        Raises:
            ValueError: 残した区間が 1 つも無い場合。
        """
        if not self._kept:
            raise ValueError("残った区間がないため、時刻を元ファイルに変換できません。")

        t = min(max(processed_time, 0.0), self.processed_duration)

        if prefer == "start":
            idx = bisect.bisect_right(self._offsets, t + EPS) - 1
        else:
            idx = bisect.bisect_left(self._offsets, t - EPS) - 1
        idx = min(max(idx, 0), len(self._kept) - 1)

        iv = self._kept[idx]
        local = t - self._offsets[idx]
        local = min(max(local, 0.0), iv.duration)
        return iv.start + local

    def to_source_span(self, start: float, end: float) -> tuple[float, float]:
        """カット後の区間を、元ファイル上の 1 つの区間（開始・終了）に変換する。

        カットをまたぐ場合、戻り値の区間には削除された部分も含まれる。
        字幕として「元動画のここからここまで」を示す用途ではこれが自然。
        削除部分を含めたくない場合は :meth:`split_to_source` を使う。
        """
        src_start = self.to_source(start, prefer="start")
        src_end = self.to_source(end, prefer="end")
        if src_end < src_start:
            # 継ぎ目にまたがるごく短い区間で起こりうる。潰れないよう最小幅を確保する。
            src_end = src_start
        return src_start, src_end

    def split_to_source(self, start: float, end: float) -> list[Interval]:
        """カット後の区間を、元ファイル上の「実際に音があった区間」の列に分解する。

        カットをまたぐ場合は複数に分かれる。合成やカットログの生成に使う。
        """
        if end - start <= EPS or not self._kept:
            return []
        lo = min(max(start, 0.0), self.processed_duration)
        hi = min(max(end, 0.0), self.processed_duration)
        if hi - lo <= EPS:
            return []

        result: list[Interval] = []
        idx = max(0, bisect.bisect_right(self._offsets, lo + EPS) - 1)
        for i in range(idx, len(self._kept)):
            iv = self._kept[i]
            seg_start = self._offsets[i]
            seg_end = seg_start + iv.duration
            if seg_start >= hi - EPS:
                break
            a = max(lo, seg_start)
            b = min(hi, seg_end)
            if b - a > EPS:
                result.append(Interval(iv.start + (a - seg_start), iv.start + (b - seg_start)))
        return result

    # --- 合成 -----------------------------------------------------------------

    def then(self, later: "SegmentMap") -> "SegmentMap":
        """自分の出力時間軸の上で定義された ``later`` を続けて適用した合成マップ。

        使い方::

            vad_map = SegmentMap(発話区間, 元の長さ)          # 元 -> 無音除去後
            chatter_map = SegmentMap(本編区間, 無音除去後の長さ)  # 無音除去後 -> 本編のみ
            total = vad_map.then(chatter_map)                # 元 -> 本編のみ

        ``total.to_source(t)`` は本編のみの時刻を一気に元ファイルの時刻へ戻す。
        """
        if self.is_empty() or later.is_empty():
            return SegmentMap([], source_duration=self._source_duration)

        combined: list[Interval] = []
        for iv in later.kept:
            combined.extend(self.split_to_source(iv.start, iv.end))
        # normalize_intervals が接した区間を結合する。両マップとも時刻の順序を
        # 保つ（単調増加）ため、結合しても対応関係は崩れない。
        return SegmentMap(combined, source_duration=self._source_duration)
