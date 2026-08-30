"""ffmpeg / ffprobe の探索と実行。

■ PATH に依存しない探索順序

    1. config.toml の [advanced] ffmpeg_path / ffprobe_path（手動指定）
    2. 環境変数 TRANSCRIBE_JA_FFMPEG / TRANSCRIBE_JA_FFPROBE
    3. 本ツールに同梱された tools フォルダ（install.ps1 が配置する）
    4. %APPDATA%\\TranscribeJA\\tools
    5. PATH（最後の手段）

install.ps1 が 3 に置くので、利用者の PATH を汚さずに動く。

■ 黒いウィンドウを出さない

Windows で pythonw から subprocess を起動すると、既定ではコンソールウィンドウが
一瞬表示される。CREATE_NO_WINDOW を付けてこれを抑止している。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from .errors import (
    FfmpegFailedError,
    FfmpegNotFoundError,
    NoAudioTrackError,
    HINT_NO_AUDIO,
    HINT_REINSTALL_FFMPEG,
)
from .logging_setup import get_logger
from .paths import app_data_dir, extended_path, is_windows

logger = get_logger("ffmpeg")

#: Windows でコンソールウィンドウを出さないためのフラグ。
CREATE_NO_WINDOW = 0x08000000

#: ffmpeg の実行が終わらない場合の保険（秒）。長時間の動画も考慮して長めにとる。
DEFAULT_TIMEOUT = 60 * 60 * 6

#: 抽出後の音声仕様
TARGET_SAMPLE_RATE = 16000

#: ラウドネス正規化のフィルタ定義。
#: loudnorm は放送基準 (EBU R128) の -16 LUFS に揃える。
NORMALIZE_FILTERS = {
    "loudnorm": "loudnorm=I=-16:TP=-1.5:LRA=11",
    "dynaudnorm": "dynaudnorm=f=250:g=15:p=0.9",
    "none": "",
}


def _repo_root() -> Path:
    """リポジトリ（インストール先）のルート。src/transcribe_ja/ から 2 つ上。"""
    return Path(__file__).resolve().parents[2]


def _tool_search_dirs() -> list[Path]:
    return [
        _repo_root() / "tools",
        app_data_dir() / "tools",
    ]


def _executable_names(base: str) -> list[str]:
    return [f"{base}.exe", base] if is_windows() else [base]


def _find_in_dir(directory: Path, base: str) -> Path | None:
    """フォルダ以下から実行ファイルを探す（bin/ の中に入っている配布物に対応）。"""
    if not directory.is_dir():
        return None
    for name in _executable_names(base):
        direct = directory / name
        if direct.is_file():
            return direct
    for name in _executable_names(base):
        try:
            for found in sorted(directory.rglob(name)):
                if found.is_file():
                    return found
        except OSError:
            continue
    return None


def find_executable(base: str, configured: str = "") -> Path:
    """ffmpeg / ffprobe の実行ファイルを探す。

    Args:
        base: "ffmpeg" または "ffprobe"。
        configured: config.toml で指定されたパス（空文字なら未指定）。

    Raises:
        FfmpegNotFoundError: どこにも見つからない場合。
    """
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return candidate
        raise FfmpegNotFoundError(
            f"設定ファイルで指定された {base} が見つかりません。\n{candidate}",
            hint="config.toml の [advanced] の設定を空欄にすると自動で探します。",
        )

    env_value = os.environ.get(f"TRANSCRIBE_JA_{base.upper()}")
    if env_value and Path(env_value).is_file():
        return Path(env_value)

    for directory in _tool_search_dirs():
        found = _find_in_dir(directory, base)
        if found is not None:
            return found

    from_path = shutil.which(base)
    if from_path:
        return Path(from_path)

    raise FfmpegNotFoundError(
        f"音声の変換に必要な {base} が見つかりませんでした。",
        hint=HINT_REINSTALL_FFMPEG,
    )


@dataclass
class Ffmpeg:
    """ffmpeg / ffprobe の場所を保持し、実行を担当する。"""

    ffmpeg: Path
    ffprobe: Path

    @classmethod
    def locate(cls, ffmpeg_path: str = "", ffprobe_path: str = "") -> "Ffmpeg":
        found = cls(
            ffmpeg=find_executable("ffmpeg", ffmpeg_path),
            ffprobe=find_executable("ffprobe", ffprobe_path),
        )
        logger.info("ffmpeg: %s", found.ffmpeg)
        logger.info("ffprobe: %s", found.ffprobe)
        return found

    # --- 実行 -----------------------------------------------------------

    def _run(
        self,
        args: Sequence[str],
        *,
        timeout: int = DEFAULT_TIMEOUT,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        logger.debug("実行: %s", " ".join(args))
        try:
            return subprocess.run(
                list(args),
                capture_output=capture,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                creationflags=CREATE_NO_WINDOW if is_windows() else 0,
            )
        except FileNotFoundError as exc:
            raise FfmpegNotFoundError(hint=HINT_REINSTALL_FFMPEG) from exc
        except subprocess.TimeoutExpired as exc:
            raise FfmpegFailedError(
                "音声の変換に時間がかかりすぎたため中断しました。",
                hint="ファイルが壊れていないか、極端に長くないかご確認ください。",
            ) from exc

    # --- 情報取得 -------------------------------------------------------

    def probe(self, media_path: Path) -> "MediaInfo":
        """ffprobe でメディア情報を取得する。"""
        args = [
            str(self.ffprobe),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            extended_path(media_path),
        ]
        result = self._run(args, timeout=120)
        if result.returncode != 0:
            detail = (result.stderr or "").strip().splitlines()
            tail = detail[-1] if detail else ""
            raise FfmpegFailedError(
                f"ファイルの情報を読み取れませんでした。\n{media_path.name}\n（{tail}）",
                hint=(
                    "ファイルが壊れているか、対応していない形式の可能性があります。\n"
                    "別の再生ソフトで開けるかご確認ください。"
                ),
            )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise FfmpegFailedError("ファイル情報の解析に失敗しました。") from exc
        return MediaInfo.from_probe(data, media_path)

    # --- 音声抽出 -------------------------------------------------------

    def extract_audio(
        self,
        media_path: Path,
        destination: Path,
        *,
        audio_index: int = 0,
        normalize: str = "loudnorm",
        total_duration: float | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> Path:
        """音声を 16kHz / モノラル / PCM16 の WAV として取り出す。

        Args:
            media_path: 入力ファイル（音声でも動画でもよい）。
            destination: 出力先の WAV。
            audio_index: 何本目の音声トラックか（0 始まり）。
            normalize: "loudnorm" / "dynaudnorm" / "none"。
            total_duration: 進捗率の計算に使う全体の長さ（秒）。
            on_progress: 0.0〜1.0 の進捗を受け取るコールバック。

        Note:
            loudnorm は音量を変えるだけで長さは変えないため、
            この WAV の時間軸は元ファイルの時間軸とそのまま対応する。
            （タイムスタンプの基準がここでずれないことが重要）
        """
        destination.parent.mkdir(parents=True, exist_ok=True)

        args = [
            str(self.ffmpeg),
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            extended_path(media_path),
            "-map",
            f"0:a:{audio_index}",
            "-vn",
            "-sn",
            "-dn",
            "-ac",
            "1",
            "-ar",
            str(TARGET_SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
        ]
        filter_expr = NORMALIZE_FILTERS.get(normalize, NORMALIZE_FILTERS["loudnorm"])
        if filter_expr:
            args += ["-af", filter_expr]
        if on_progress is not None:
            args += ["-progress", "pipe:1", "-nostats"]
        args.append(extended_path(destination))

        if on_progress is None or not total_duration:
            result = self._run(args)
            if result.returncode != 0:
                self._raise_extract_error(media_path, result.stderr or "")
        else:
            self._run_with_progress(args, total_duration, on_progress, media_path)

        if not destination.exists() or destination.stat().st_size == 0:
            raise FfmpegFailedError(
                f"音声を取り出せませんでした。\n{media_path.name}",
                hint=HINT_NO_AUDIO,
            )
        return destination

    def _run_with_progress(
        self,
        args: Sequence[str],
        total_duration: float,
        on_progress: Callable[[float], None],
        media_path: Path,
    ) -> None:
        """ffmpeg の -progress 出力を読みながら進捗を通知する。"""
        try:
            process = subprocess.Popen(
                list(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW if is_windows() else 0,
            )
        except FileNotFoundError as exc:
            raise FfmpegNotFoundError(hint=HINT_REINSTALL_FFMPEG) from exc

        assert process.stdout is not None
        try:
            for line in process.stdout:
                line = line.strip()
                if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                    value = line.split("=", 1)[1]
                    if value.isdigit():
                        # out_time_us / out_time_ms はどちらもマイクロ秒で出力される
                        # （ffmpeg の歴史的な仕様。名前に惑わされないこと）
                        seconds = int(value) / 1_000_000
                        on_progress(min(1.0, seconds / total_duration))
        finally:
            process.stdout.close()
            stderr = process.stderr.read() if process.stderr else ""
            if process.stderr:
                process.stderr.close()
            returncode = process.wait()

        if returncode != 0:
            self._raise_extract_error(media_path, stderr)
        on_progress(1.0)

    @staticmethod
    def _raise_extract_error(media_path: Path, stderr: str) -> None:
        """ffmpeg の英語エラーを、わかりやすい日本語メッセージに翻訳する。"""
        text = stderr or ""
        tail = [ln for ln in text.strip().splitlines() if ln.strip()]
        last = tail[-1] if tail else ""

        lowered = text.lower()
        if "does not contain any stream" in lowered or "stream map" in lowered:
            raise NoAudioTrackError(
                f"このファイルには指定された音声トラックがありませんでした。\n{media_path.name}",
                hint=(
                    "config.toml の [audio] track の番号をご確認ください。\n"
                    "1 本目を使う場合は track = 1 です。\n" + HINT_NO_AUDIO
                ),
            )
        if "no space left" in lowered:
            from .errors import DiskSpaceError, HINT_DISK_SPACE

            raise DiskSpaceError(hint=HINT_DISK_SPACE)
        if "permission denied" in lowered:
            raise FfmpegFailedError(
                f"ファイルにアクセスできませんでした。\n{media_path.name}",
                hint=(
                    "そのファイルを他のソフトで開いていないかご確認ください。\n"
                    "また、フォルダへの書き込み権限が必要です。"
                ),
            )
        if "invalid data found" in lowered or "moov atom not found" in lowered:
            raise FfmpegFailedError(
                f"ファイルが壊れているため読み込めませんでした。\n{media_path.name}",
                hint="録画が正常に終了していない可能性があります。別の再生ソフトで確認してください。",
            )
        raise FfmpegFailedError(
            f"音声の変換に失敗しました。\n{media_path.name}\n（{last}）",
            hint="詳しい内容はログファイルに記録されています。",
        )


# --- メディア情報 ---------------------------------------------------------------


@dataclass
class AudioStream:
    """音声トラック 1 本分の情報。"""

    audio_index: int  # 音声トラックの中での番号（0 始まり）
    codec: str = ""
    language: str = ""
    title: str = ""
    channels: int = 0

    def label(self) -> str:
        """設定画面やログで見せる説明文。"""
        parts = [f"トラック {self.audio_index + 1}"]
        if self.title:
            parts.append(self.title)
        if self.language:
            parts.append(f"言語:{self.language}")
        if self.codec:
            parts.append(self.codec)
        if self.channels:
            parts.append(f"{self.channels}ch")
        return " / ".join(parts)


@dataclass
class MediaInfo:
    """入力ファイルの情報。"""

    path: Path
    duration: float = 0.0
    audio_streams: list[AudioStream] = field(default_factory=list)
    has_video: bool = False

    @classmethod
    def from_probe(cls, data: dict, media_path: Path) -> "MediaInfo":
        duration = 0.0
        fmt = data.get("format") or {}
        try:
            duration = float(fmt.get("duration", 0.0) or 0.0)
        except (TypeError, ValueError):
            duration = 0.0

        audio_streams: list[AudioStream] = []
        has_video = False
        audio_counter = 0
        for stream in data.get("streams", []) or []:
            codec_type = stream.get("codec_type")
            if codec_type == "video":
                # サムネイル画像（mp3 のジャケット等）は映像扱いしない
                if stream.get("disposition", {}).get("attached_pic"):
                    continue
                has_video = True
            elif codec_type == "audio":
                tags = stream.get("tags") or {}
                audio_streams.append(
                    AudioStream(
                        audio_index=audio_counter,
                        codec=str(stream.get("codec_name") or ""),
                        language=str(tags.get("language") or ""),
                        title=str(tags.get("title") or ""),
                        channels=int(stream.get("channels") or 0),
                    )
                )
                audio_counter += 1

                if duration <= 0:
                    try:
                        duration = max(duration, float(stream.get("duration") or 0.0))
                    except (TypeError, ValueError):
                        pass

        return cls(
            path=media_path,
            duration=duration,
            audio_streams=audio_streams,
            has_video=has_video,
        )

    def require_audio(self, track_number: int) -> int:
        """指定された 1 始まりのトラック番号を、0 始まりの索引に変換して返す。

        音声が無い場合や、指定番号が範囲外の場合は日本語エラーにする。
        """
        if not self.audio_streams:
            raise NoAudioTrackError(
                f"このファイルには音声が含まれていませんでした。\n{self.path.name}",
                hint=HINT_NO_AUDIO,
            )
        index = track_number - 1
        if index < 0 or index >= len(self.audio_streams):
            available = "\n".join(f"  ・{s.label()}" for s in self.audio_streams)
            raise NoAudioTrackError(
                f"音声トラック {track_number} は存在しません。\n"
                f"このファイルの音声トラックは次のとおりです:\n{available}",
                hint="config.toml の [audio] track を上記の番号に合わせてください。",
            )
        return index


def format_duration(seconds: float) -> str:
    """秒数を「1時間23分45秒」の形式にする（ログとメッセージ用）。"""
    seconds = max(0.0, seconds)
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}時間{minutes}分{secs}秒"
    if minutes:
        return f"{minutes}分{secs}秒"
    return f"{secs}秒"
