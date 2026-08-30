"""結果ファイルの書き出し（txt / srt / md / cut_log）。

■ 時刻の扱い

ここに渡ってくるセグメントの時刻は、すでに :class:`SegmentMap` によって
**元ファイルの時間軸**に変換済みであること。
このモジュールは変換を行わない（変換漏れをここで隠さないため）。

■ 上書きしない

同名のファイルが既にある場合は ``会議_ja(2).txt`` のように連番を付ける。
利用者が前回の結果を失わないようにするため、上書きは決してしない。
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from .logging_setup import get_logger
from .paths import sanitize_stem, unique_path

logger = get_logger("writers")

#: 段落を分ける無音の長さ（秒）。これ以上間が空いたら段落を変える。
PARAGRAPH_GAP = 2.0

#: 1 段落が長くなりすぎたときに強制的に改段落する文字数。
PARAGRAPH_MAX_CHARS = 300

#: Markdown の見出しを作る間隔（秒）。5 分ごとに見出しを立てる。
HEADING_INTERVAL = 300.0

#: 字幕 1 行あたりの目安文字数。日本語字幕の慣例に合わせる。
SRT_LINE_CHARS = 20


@dataclass
class OutputSegment:
    """出力用のセグメント。時刻は必ず元ファイル基準。"""

    start: float
    end: float
    text: str
    speaker: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class CutEntry:
    """カットした区間 1 件分の記録。時刻は元ファイル基準。"""

    start: float
    end: float
    reason: str
    text: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class OutputMeta:
    """出力ファイルの冒頭に書く情報。"""

    source_name: str = ""
    source_duration: float = 0.0
    processed_duration: float = 0.0
    model_description: str = ""
    vad_engine: str = ""
    chatter_method: str = ""
    silence_removed: float = 0.0
    chatter_removed: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)


# --- 時刻の表記 -----------------------------------------------------------------


def format_timestamp_srt(seconds: float) -> str:
    """SRT 形式（00:01:23,456）の時刻文字列。"""
    seconds = max(0.0, seconds)
    total_ms = int(round(seconds * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_timestamp_readable(seconds: float) -> str:
    """人が読む用の時刻（1:23:45 または 23:45）。"""
    seconds = max(0.0, seconds)
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_span(start: float, end: float) -> str:
    return f"{format_timestamp_readable(start)}〜{format_timestamp_readable(end)}"


def format_minutes(seconds: float) -> str:
    """「3分12秒」形式。削除量の説明に使う。"""
    seconds = max(0.0, seconds)
    minutes, secs = divmod(int(round(seconds)), 60)
    if minutes:
        return f"{minutes}分{secs}秒"
    return f"{secs}秒"


# --- 段落の組み立て -------------------------------------------------------------


def group_paragraphs(segments: Sequence[OutputSegment]) -> list[list[OutputSegment]]:
    """間の空き具合と長さを見て、セグメントを段落にまとめる。"""
    paragraphs: list[list[OutputSegment]] = []
    current: list[OutputSegment] = []
    length = 0

    for i, seg in enumerate(segments):
        if current:
            gap = seg.start - segments[i - 1].end
            speaker_changed = seg.speaker != segments[i - 1].speaker
            if gap >= PARAGRAPH_GAP or length >= PARAGRAPH_MAX_CHARS or speaker_changed:
                paragraphs.append(current)
                current = []
                length = 0
        current.append(seg)
        length += len(seg.text)

    if current:
        paragraphs.append(current)
    return paragraphs


def _paragraph_text(paragraph: Sequence[OutputSegment], line_width: int = 0) -> str:
    speaker = paragraph[0].speaker
    body = "".join(seg.text for seg in paragraph).strip()
    if speaker:
        body = f"{speaker}: {body}"
    if line_width and line_width > 0:
        return "\n".join(textwrap.wrap(body, width=line_width)) or body
    return body


# --- 各形式の書き出し -----------------------------------------------------------


def render_txt(
    segments: Sequence[OutputSegment], meta: OutputMeta, line_width: int = 0
) -> str:
    """整形済みの読みやすい本文。"""
    lines: list[str] = []
    if meta.source_name:
        lines.append(f"# {meta.source_name}")
        lines.append(
            f"（{meta.created_at:%Y-%m-%d %H:%M} 作成 / 収録時間 "
            f"{format_timestamp_readable(meta.source_duration)}）"
        )
        lines.append("")

    for paragraph in group_paragraphs(segments):
        text = _paragraph_text(paragraph, line_width)
        if text:
            lines.append(text)
            lines.append("")

    if not segments:
        lines.append("（文字起こしできる発話が見つかりませんでした）")

    return "\n".join(lines).rstrip() + "\n"


#: 行頭に置いてはいけない文字（日本語組版の禁則処理）。
#: これらが行頭に来ると「3ペー / ジ目」のように読みにくくなる。
LINE_HEAD_FORBIDDEN = "ーぁぃぅぇぉっゃゅょャュョッ、。，．・？！」』）】〕》"


def _apply_kinsoku(lines: list[str]) -> list[str]:
    """行頭に来てはいけない文字を、前の行の末尾へ送る。"""
    fixed = list(lines)
    for index in range(1, len(fixed)):
        while fixed[index] and fixed[index][0] in LINE_HEAD_FORBIDDEN and fixed[index - 1]:
            fixed[index - 1] += fixed[index][0]
            fixed[index] = fixed[index][1:]
    return [line for line in fixed if line]


def _wrap_subtitle(text: str, width: int = SRT_LINE_CHARS, max_lines: int = 2) -> str:
    """字幕らしく短い行に折り返す。長すぎる場合は 2 行に収める。"""
    text = text.strip()
    if len(text) <= width:
        return text
    wrapped = textwrap.wrap(text, width=width)
    if len(wrapped) > max_lines:
        # 3 行以上になる場合は、2 行に均等分割する（字幕は 2 行までが読みやすい）
        half = (len(text) + 1) // 2
        wrapped = [text[:half], text[half:]]
    return "\n".join(_apply_kinsoku(wrapped))


def render_srt(segments: Sequence[OutputSegment]) -> str:
    """字幕ファイル。時刻は元ファイルのタイムコード基準。"""
    blocks: list[str] = []
    previous_end = 0.0
    for i, seg in enumerate(segments, start=1):
        start = max(seg.start, previous_end)
        end = max(seg.end, start + 0.2)  # 表示時間が 0 にならないようにする
        previous_end = end
        text = _wrap_subtitle(seg.text)
        if seg.speaker:
            text = f"{seg.speaker}: {text}"
        blocks.append(
            f"{i}\n"
            f"{format_timestamp_srt(start)} --> {format_timestamp_srt(end)}\n"
            f"{text}\n"
        )
    return "\n".join(blocks)


def render_md(segments: Sequence[OutputSegment], meta: OutputMeta) -> str:
    """タイムスタンプ付きの見出し構成。"""
    lines: list[str] = [f"# {meta.source_name or '文字起こし'}", ""]
    lines.append(f"- 作成日時: {meta.created_at:%Y-%m-%d %H:%M}")
    if meta.source_duration:
        lines.append(f"- 収録時間: {format_timestamp_readable(meta.source_duration)}")
    if meta.model_description:
        lines.append(f"- 文字起こし: {meta.model_description}")
    if meta.silence_removed:
        lines.append(f"- 無音カット: {format_minutes(meta.silence_removed)}")
    if meta.chatter_removed:
        lines.append(f"- 雑談カット: {format_minutes(meta.chatter_removed)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    if not segments:
        lines.append("（文字起こしできる発話が見つかりませんでした）")
        return "\n".join(lines) + "\n"

    current_heading = -1.0
    for paragraph in group_paragraphs(segments):
        start = paragraph[0].start
        block = int(start // HEADING_INTERVAL) * HEADING_INTERVAL
        if block != current_heading:
            current_heading = block
            lines.append(
                f"## {format_timestamp_readable(block)} 〜 "
                f"{format_timestamp_readable(block + HEADING_INTERVAL)}"
            )
            lines.append("")
        stamp = format_timestamp_readable(start)
        lines.append(f"**[{stamp}]** {_paragraph_text(paragraph)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_cut_log(entries: Sequence[CutEntry], meta: OutputMeta) -> str:
    """カットした区間の記録。時刻はすべて元ファイル基準。"""
    lines: list[str] = [
        "=" * 64,
        f"カット記録: {meta.source_name}",
        f"作成日時: {meta.created_at:%Y-%m-%d %H:%M}",
        "=" * 64,
        "",
        "この記録に書かれている時刻は、すべて【元ファイル】の時刻です。",
        "元の音声・動画を再生して、実際に不要な部分だったかを確認できます。",
        "",
        f"収録時間        : {format_timestamp_readable(meta.source_duration)}",
        f"処理後の長さ    : {format_timestamp_readable(meta.processed_duration)}",
        f"無音カット      : {format_minutes(meta.silence_removed)}"
        + (f"（{meta.vad_engine}）" if meta.vad_engine else ""),
        f"雑談カット      : {format_minutes(meta.chatter_removed)}"
        + (f"（{meta.chatter_method}）" if meta.chatter_method else ""),
        "",
    ]

    if meta.source_duration > 0:
        removed = meta.source_duration - meta.processed_duration
        lines.append(
            f"合計で {format_minutes(removed)} "
            f"（全体の {removed / meta.source_duration * 100:.1f}%）を取り除きました。"
        )
        lines.append("")

    lines.append("-" * 64)
    lines.append("削除した区間の一覧")
    lines.append("-" * 64)
    lines.append("")

    chatter_entries = [e for e in entries if e.text or e.reason != "無音"]
    if not entries:
        lines.append("（削除した区間はありません）")
    else:
        for entry in entries:
            lines.append(f"[{format_span(entry.start, entry.end)}] ({format_minutes(entry.duration)})")
            lines.append(f"  理由: {entry.reason}")
            if entry.text:
                lines.append(f"  内容: {entry.text}")
            lines.append("")

    if chatter_entries:
        lines.append("-" * 64)
        lines.append("※ 誤って削除された部分があった場合は、config.toml の")
        lines.append("   [chatter] enabled = false にすると雑談カットを止められます。")
        lines.append("   特定の表現だけ残したい場合は、判定辞書")
        lines.append("   （dictionaries\\chatter_ja.toml）から該当する表現を削除してください。")

    return "\n".join(lines).rstrip() + "\n"


# --- ファイルへの書き出し -------------------------------------------------------


@dataclass
class WrittenFile:
    kind: str
    path: Path


def write_outputs(
    destination_dir: Path,
    source_stem: str,
    suffix: str,
    formats: Iterable[str],
    segments: Sequence[OutputSegment],
    cut_entries: Sequence[CutEntry],
    meta: OutputMeta,
    line_width: int = 0,
) -> list[WrittenFile]:
    """設定で指定された形式のファイルを書き出す。

    Args:
        destination_dir: 出力先（元ファイルと同じフォルダ）。
        source_stem: 元ファイル名（拡張子なし）。
        suffix: 付与する接尾辞（既定 "_ja"）。
        formats: "txt" / "srt" / "md" / "cut_log" の並び。

    Returns:
        書き出したファイルの一覧。
    """
    stem = f"{sanitize_stem(source_stem)}{suffix}"
    written: list[WrittenFile] = []
    wanted = list(formats)

    renderers: list[tuple[str, str, str]] = [
        ("txt", ".txt", ""),
        ("srt", ".srt", ""),
        ("md", ".md", ""),
        ("cut_log", ".txt", "_cut_log"),
    ]

    for kind, extension, extra in renderers:
        if kind not in wanted:
            continue
        if kind == "txt":
            content = render_txt(segments, meta, line_width)
        elif kind == "srt":
            content = render_srt(segments)
        elif kind == "md":
            content = render_md(segments, meta)
        else:
            content = render_cut_log(cut_entries, meta)

        path = unique_path(destination_dir, f"{stem}{extra}", extension)
        # BOM 付き UTF-8 にしておくと、メモ帳や Excel で開いても文字化けしない。
        encoding = "utf-8-sig" if kind in ("txt", "cut_log") else "utf-8"
        path.write_text(content, encoding=encoding, newline="\r\n")
        logger.info("書き出しました: %s", path)
        written.append(WrittenFile(kind=kind, path=path))

    return written
