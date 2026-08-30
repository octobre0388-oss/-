"""設定ファイル (config.toml) の生成・読み込み・検証。

方針:
    * 既定値の唯一の出所は ``resources/default_config.toml``。
      コメント付きのファイルをそのままコピーするので、利用者が開いたときに
      各項目の説明が読める。
    * 読み込みは標準ライブラリの tomllib を使う（Python 3.11 以降）。
    * 利用者のファイルに項目が足りなくても、既定値で埋めて動かす
      （バージョンアップで項目が増えても壊れないようにするため）。
    * 値がおかしい場合は日本語で理由を説明して止める。
"""

from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .paths import app_data_dir, config_file, dictionaries_dir

RESOURCES = Path(__file__).parent / "resources"
DEFAULT_CONFIG_FILE = RESOURCES / "default_config.toml"
DICTIONARY_SOURCE = Path(__file__).parent / "chatter" / "dictionaries"

VALID_NORMALIZE = ("loudnorm", "dynaudnorm", "none")
VALID_VAD_ENGINE = ("silero", "webrtc")
VALID_CHATTER_METHOD = ("rules", "llm")
VALID_SAFETY = ("conservative", "balanced", "aggressive")
VALID_DEVICE = ("auto", "cuda", "cpu")
VALID_NUMBERS = ("arabic", "kanji", "keep")
VALID_FORMATS = ("txt", "srt", "md", "cut_log")
VALID_WHISPER_MODELS = (
    "auto",
    "tiny",
    "base",
    "small",
    "medium",
    "large-v1",
    "large-v2",
    "large-v3",
    "large-v3-turbo",
)


# --- 各セクション ---------------------------------------------------------------


@dataclass
class GeneralConfig:
    language: str = "ja"
    keep_temp: bool = False
    log_level: str = "INFO"


@dataclass
class OutputConfig:
    formats: list[str] = field(default_factory=lambda: ["txt", "srt", "md", "cut_log"])
    suffix: str = "_ja"
    open_folder_when_done: bool = True


@dataclass
class AudioConfig:
    track: int = 1
    normalize: str = "loudnorm"


@dataclass
class VadConfig:
    enabled: bool = True
    engine: str = "silero"
    min_silence_ms: int = 700
    padding_ms: int = 200
    threshold: float = 0.5
    min_speech_ms: int = 250


@dataclass
class ChatterConfig:
    enabled: bool = True
    method: str = "rules"
    prescan_model: str = "small"
    safety: str = "conservative"
    max_cut_ratio: float = 0.35
    llm_model: str = "claude-opus-5"
    rules_file: str = "chatter_ja.toml"


@dataclass
class WhisperConfig:
    model: str = "auto"
    device: str = "auto"
    compute_type: str = "auto"
    beam_size: int = 5
    initial_prompt: str = ""
    no_speech_threshold: float = 0.6
    log_prob_threshold: float = -1.0
    compression_ratio_threshold: float = 2.4
    model_dir: str = ""


@dataclass
class FormatConfig:
    remove_fillers: bool = True
    fillers_file: str = "fillers_ja.toml"
    normalize_width: bool = True
    numbers: str = "arabic"
    fix_restatements: bool = True
    fix_punctuation: bool = True
    line_width: int = 0


@dataclass
class DiarizationConfig:
    enabled: bool = False
    model: str = "pyannote/speaker-diarization-3.1"
    token_env: str = "HUGGINGFACE_TOKEN"


@dataclass
class AdvancedConfig:
    ffmpeg_path: str = ""
    ffprobe_path: str = ""
    queue_debounce_seconds: float = 1.5
    show_progress_window: bool = True
    show_notification: bool = True


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    vad: VadConfig = field(default_factory=VadConfig)
    chatter: ChatterConfig = field(default_factory=ChatterConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    format: FormatConfig = field(default_factory=FormatConfig)
    diarization: DiarizationConfig = field(default_factory=DiarizationConfig)
    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)

    # 読み込み元（GUI の「設定ファイルを開く」で使う）
    source_path: Path | None = None

    # --- 派生プロパティ ---------------------------------------------------

    @property
    def dictionaries_dir(self) -> Path:
        return dictionaries_dir()

    def wants(self, output_format: str) -> bool:
        return output_format in self.output.formats


# --- 読み込み -------------------------------------------------------------------


def _coerce(value: Any, expected: Any, where: str) -> Any:
    """TOML の値を dataclass のフィールド型に合わせる。

    型が違う場合は ConfigError にする（例: 数値であるべき所に文字列）。
    """
    if isinstance(expected, bool):
        if isinstance(value, bool):
            return value
        raise ConfigError(
            f"設定 [{where}] には true または false を指定してください（現在: {value!r}）。"
        )
    if isinstance(expected, int) and not isinstance(expected, bool):
        if isinstance(value, bool):
            raise ConfigError(f"設定 [{where}] には数値を指定してください（現在: {value!r}）。")
        if isinstance(value, (int, float)):
            return int(value)
        raise ConfigError(f"設定 [{where}] には数値を指定してください（現在: {value!r}）。")
    if isinstance(expected, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"設定 [{where}] には数値を指定してください（現在: {value!r}）。")
        return float(value)
    if isinstance(expected, str):
        if isinstance(value, str):
            return value
        raise ConfigError(f"設定 [{where}] には文字列を指定してください（現在: {value!r}）。")
    if isinstance(expected, list):
        if isinstance(value, list):
            return list(value)
        raise ConfigError(f"設定 [{where}] にはリストを指定してください（現在: {value!r}）。")
    return value


def _fill_section(section_obj: Any, data: dict[str, Any], section_name: str) -> None:
    """dict の内容を dataclass インスタンスに反映する（未知のキーは無視）。"""
    known = {f.name for f in fields(section_obj)}
    for key, value in data.items():
        if key not in known:
            # 将来のバージョンの項目や打ち間違い。壊さずに読み飛ばす。
            continue
        current = getattr(section_obj, key)
        setattr(section_obj, key, _coerce(value, current, f"{section_name}] の [{key}"))


def _check(condition: bool, message: str, hint: str | None = None) -> None:
    if not condition:
        raise ConfigError(message, hint=hint)


def validate(config: Config) -> None:
    """設定値の妥当性を確認する。おかしければ日本語で理由を説明して止める。"""
    open_hint = "設定ファイルを開いて、該当する行を修正してください。"

    _check(
        config.audio.normalize in VALID_NORMALIZE,
        f"[audio] normalize の値が不正です: {config.audio.normalize!r}\n"
        f"指定できるのは {', '.join(VALID_NORMALIZE)} です。",
        open_hint,
    )
    _check(config.audio.track >= 1, "[audio] track は 1 以上にしてください。", open_hint)

    _check(
        config.vad.engine in VALID_VAD_ENGINE,
        f"[vad] engine の値が不正です: {config.vad.engine!r}\n"
        f"指定できるのは {', '.join(VALID_VAD_ENGINE)} です。",
        open_hint,
    )
    _check(config.vad.min_silence_ms >= 0, "[vad] min_silence_ms は 0 以上にしてください。", open_hint)
    _check(config.vad.padding_ms >= 0, "[vad] padding_ms は 0 以上にしてください。", open_hint)
    _check(
        0.0 <= config.vad.threshold <= 1.0,
        "[vad] threshold は 0.0〜1.0 の範囲で指定してください。",
        open_hint,
    )

    _check(
        config.chatter.method in VALID_CHATTER_METHOD,
        f"[chatter] method の値が不正です: {config.chatter.method!r}\n"
        f"指定できるのは {', '.join(VALID_CHATTER_METHOD)} です。",
        open_hint,
    )
    _check(
        config.chatter.safety in VALID_SAFETY,
        f"[chatter] safety の値が不正です: {config.chatter.safety!r}\n"
        f"指定できるのは {', '.join(VALID_SAFETY)} です。",
        open_hint,
    )
    _check(
        0.0 <= config.chatter.max_cut_ratio <= 1.0,
        "[chatter] max_cut_ratio は 0.0〜1.0 の範囲で指定してください。",
        open_hint,
    )

    _check(
        config.whisper.model in VALID_WHISPER_MODELS,
        f"[whisper] model の値が不正です: {config.whisper.model!r}\n"
        f"指定できるのは {', '.join(VALID_WHISPER_MODELS)} です。",
        open_hint,
    )
    _check(
        config.whisper.device in VALID_DEVICE,
        f"[whisper] device の値が不正です: {config.whisper.device!r}\n"
        f"指定できるのは {', '.join(VALID_DEVICE)} です。",
        open_hint,
    )
    _check(config.whisper.beam_size >= 1, "[whisper] beam_size は 1 以上にしてください。", open_hint)

    _check(
        config.format.numbers in VALID_NUMBERS,
        f"[format] numbers の値が不正です: {config.format.numbers!r}\n"
        f"指定できるのは {', '.join(VALID_NUMBERS)} です。",
        open_hint,
    )

    unknown_formats = [f for f in config.output.formats if f not in VALID_FORMATS]
    _check(
        not unknown_formats,
        f"[output] formats に不明な種類が含まれています: {', '.join(unknown_formats)}\n"
        f"指定できるのは {', '.join(VALID_FORMATS)} です。",
        open_hint,
    )
    _check(
        bool(config.output.formats),
        "[output] formats が空です。出力するファイルを 1 つ以上指定してください。",
        open_hint,
    )

    _check(
        config.advanced.queue_debounce_seconds >= 0,
        "[advanced] queue_debounce_seconds は 0 以上にしてください。",
        open_hint,
    )


def load_defaults() -> dict[str, Any]:
    """同梱の既定 config を dict として読み込む。"""
    with DEFAULT_CONFIG_FILE.open("rb") as fp:
        return tomllib.load(fp)


def ensure_config_file() -> Path:
    """設定ファイルが無ければ既定値で作成し、そのパスを返す。"""
    target = config_file()
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DEFAULT_CONFIG_FILE, target)
    return target


def ensure_dictionaries() -> Path:
    """判定辞書を利用者が編集できる場所へコピーする（既にあれば触らない）。"""
    target_dir = dictionaries_dir()
    if DICTIONARY_SOURCE.is_dir():
        for src in DICTIONARY_SOURCE.glob("*.toml"):
            dest = target_dir / src.name
            if not dest.exists():
                shutil.copyfile(src, dest)
    return target_dir


def from_dict(data: dict[str, Any], source_path: Path | None = None) -> Config:
    """dict から Config を組み立てる（未指定の項目は既定値のまま）。"""
    config = Config(source_path=source_path)
    for f in fields(config):
        if not is_dataclass(getattr(config, f.name)):
            continue
        section_data = data.get(f.name)
        if section_data is None:
            continue
        if not isinstance(section_data, dict):
            raise ConfigError(f"設定の [{f.name}] セクションの書き方が正しくありません。")
        _fill_section(getattr(config, f.name), section_data, f.name)
    return config


def load(path: Path | None = None) -> Config:
    """設定を読み込む。ファイルが無ければ既定値で作成してから読む。

    Raises:
        ConfigError: TOML として壊れている、または値が不正な場合。
    """
    target = Path(path) if path else ensure_config_file()
    ensure_dictionaries()

    # 既定値を土台にして、利用者のファイルで上書きする。
    config = from_dict(load_defaults())
    config.source_path = target

    try:
        with target.open("rb") as fp:
            user_data = tomllib.load(fp)
    except FileNotFoundError:
        user_data = {}
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"設定ファイルの書式が正しくありません。\n{target}\n（{exc}）",
            hint=(
                "設定ファイルを開いて、書き間違いを直してください。\n"
                "元に戻したい場合は、このファイルを削除すると次回起動時に\n"
                "既定の設定で作り直されます。"
            ),
        ) from exc
    except OSError as exc:
        raise ConfigError(f"設定ファイルを読み込めませんでした。\n{target}\n（{exc}）") from exc

    for f in fields(config):
        section = getattr(config, f.name)
        if is_dataclass(section) and f.name in user_data:
            section_data = user_data[f.name]
            if not isinstance(section_data, dict):
                raise ConfigError(f"設定の [{f.name}] セクションの書き方が正しくありません。")
            _fill_section(section, section_data, f.name)

    validate(config)
    return config


def config_location_note() -> str:
    """利用者に案内するための設定ファイルの場所（メッセージ用）。"""
    return f"設定ファイル: {config_file()}\nログ: {app_data_dir() / 'logs'}"
