"""想定エラーを日本語のわかりやすいメッセージに変換する。

このモジュールの方針:
    * 利用者に見せるメッセージは必ず日本語で、「何が起きたか」と「どうすればよいか」を書く。
    * 技術的な詳細（例外の型やスタックトレース）はログにだけ残し、画面には出さない。
"""

from __future__ import annotations


class TranscribeJAError(Exception):
    """本ツールが想定している業務エラーの基底クラス。

    Attributes:
        message: 利用者向けの日本語メッセージ（1 行目に要約、2 行目以降に対処法）。
        hint: 対処方法。指定するとメッセージの末尾に追記される。
    """

    default_message = "処理中にエラーが発生しました。"

    def __init__(self, message: str | None = None, *, hint: str | None = None) -> None:
        self.message = message or self.default_message
        self.hint = hint
        super().__init__(self.message)

    def user_message(self) -> str:
        """進捗ウィンドウやログに出すための整形済みメッセージを返す。"""
        if self.hint:
            return f"{self.message}\n\n【対処方法】\n{self.hint}"
        return self.message


class InputFileNotFoundError(TranscribeJAError):
    default_message = "指定されたファイルが見つかりませんでした。"


class UnsupportedFileError(TranscribeJAError):
    default_message = "このファイル形式には対応していません。"


class NoAudioTrackError(TranscribeJAError):
    default_message = "このファイルには音声トラックが含まれていませんでした。"


class FfmpegNotFoundError(TranscribeJAError):
    default_message = "音声変換に必要な ffmpeg が見つかりませんでした。"


class FfmpegFailedError(TranscribeJAError):
    default_message = "音声の変換処理に失敗しました。"


class ModelDownloadError(TranscribeJAError):
    default_message = "文字起こしモデルのダウンロードに失敗しました。"


class DiskSpaceError(TranscribeJAError):
    default_message = "ディスクの空き容量が不足しています。"


class PathTooLongError(TranscribeJAError):
    default_message = "ファイルのパスが長すぎるため処理できませんでした。"


class NoSpeechDetectedError(TranscribeJAError):
    default_message = "音声の中から人の話し声を検出できませんでした。"


class CancelledByUserError(TranscribeJAError):
    """利用者がキャンセルボタンを押した場合。エラー扱いだが通知は穏やかに行う。"""

    default_message = "処理をキャンセルしました。"


class ConfigError(TranscribeJAError):
    default_message = "設定ファイルの内容に問題があります。"


class DependencyMissingError(TranscribeJAError):
    default_message = "必要なライブラリがインストールされていません。"


# --- 定型のヒント文（複数箇所から使うのでここに集約する） -----------------------

HINT_REINSTALL_FFMPEG = (
    "install.ps1 をもう一度実行すると ffmpeg を自動で用意します。\n"
    "うまくいかない場合は https://www.gyan.dev/ffmpeg/builds/ から\n"
    "「ffmpeg-release-essentials.zip」を入手し、中の ffmpeg.exe と ffprobe.exe を\n"
    "本ツールの tools フォルダに置いてください。"
)

HINT_NETWORK = (
    "インターネットに接続されているか確認してから、もう一度お試しください。\n"
    "社内ネットワークでプロキシをお使いの場合は、管理者にご確認ください。"
)

HINT_DISK_SPACE = (
    "不要なファイルを削除して空き容量を増やしてから、もう一度お試しください。\n"
    "文字起こしには元ファイルの 2〜3 倍程度の一時領域が必要です。"
)

HINT_LONG_PATH = (
    "ファイルをデスクトップなど階層の浅い場所にコピーしてからお試しください。\n"
    "フォルダ名を短くすることでも解消できます。"
)

HINT_NO_AUDIO = (
    "動画ファイルの場合、映像のみで音声が入っていない可能性があります。\n"
    "別の再生ソフトで音が出るかご確認ください。"
)
