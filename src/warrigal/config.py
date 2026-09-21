"""Central configuration for Warrigal paths and local tool locations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


@dataclass(frozen=True)
class WarrigalConfig:
    """Resolved local configuration without creating or modifying anything."""

    archive_root: Path
    runtime_root: Path
    database_path: Path
    object_store_path: Path
    ffmpeg: str
    ffprobe: str
    whisper: str
    llama: str
    qpdf: str
    whisper_model: Path | None
    qwen_model: Path | None
    qwen_projector: Path | None


def _optional_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


def load_config() -> WarrigalConfig:
    """Load environment overrides while preserving Warrigal's current defaults."""

    archive_root = _path_from_env(
        "WARRIGAL_ARCHIVE_ROOT",
        Path.home() / "Desktop" / "INFORMATION_ARCHIVE",
    )
    return WarrigalConfig(
        archive_root=archive_root,
        runtime_root=_path_from_env(
            "WARRIGAL_RUNTIME_ROOT",
            archive_root / "SYSTEM" / "WARRIGAL" / "runtime",
        ),
        database_path=_path_from_env(
            "WARRIGAL_DATABASE_PATH",
            Path("workspace") / "warrigal.db",
        ),
        object_store_path=_path_from_env(
            "WARRIGAL_OBJECT_STORE",
            Path("archive") / "objects",
        ),
        ffmpeg=os.environ.get("WARRIGAL_FFMPEG", "ffmpeg"),
        ffprobe=os.environ.get("WARRIGAL_FFPROBE", "ffprobe"),
        whisper=os.environ.get("WARRIGAL_WHISPER", "whisper-cli"),
        llama=os.environ.get("WARRIGAL_LLAMA", "llama-cli"),
        qpdf=os.environ.get("WARRIGAL_QPDF", "qpdf"),
        whisper_model=_optional_path("WARRIGAL_WHISPER_MODEL"),
        qwen_model=_optional_path("WARRIGAL_QWEN_MODEL"),
        qwen_projector=_optional_path("WARRIGAL_QWEN_PROJECTOR"),
    )


CONFIG = load_config()

