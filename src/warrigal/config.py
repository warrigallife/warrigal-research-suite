"""Central configuration for Warrigal paths and local tool locations."""

from __future__ import annotations

import os
import tomllib
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


def _optional_path(name: str, default: str | None = None) -> Path | None:
    value = os.environ.get(name)
    selected = value if value is not None else default
    return Path(selected).expanduser() if selected else None


def _load_local_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Warrigal configuration must be a TOML table: {path}")
    return payload


def load_config(config_file: Path | None = None) -> WarrigalConfig:
    """Load environment overrides while preserving Warrigal's current defaults."""

    config_file = config_file or Path("warrigal.local.toml")
    local = _load_local_file(config_file)
    paths = local.get("paths", {})
    tools = local.get("tools", {})
    models = local.get("models", {})
    archive_root = _path_from_env(
        "WARRIGAL_ARCHIVE_ROOT",
        Path(paths.get("archive_root", Path.home() / "Desktop" / "INFORMATION_ARCHIVE")).expanduser(),
    )
    return WarrigalConfig(
        archive_root=archive_root,
        runtime_root=_path_from_env(
            "WARRIGAL_RUNTIME_ROOT",
            Path(paths.get("runtime_root", archive_root / "SYSTEM" / "WARRIGAL" / "runtime")).expanduser(),
        ),
        database_path=_path_from_env(
            "WARRIGAL_DATABASE_PATH",
            Path(paths.get("database_path", Path("workspace") / "warrigal.db")).expanduser(),
        ),
        object_store_path=_path_from_env(
            "WARRIGAL_OBJECT_STORE",
            Path(paths.get("object_store_path", Path("archive") / "objects")).expanduser(),
        ),
        ffmpeg=os.environ.get("WARRIGAL_FFMPEG", tools.get("ffmpeg", "ffmpeg")),
        ffprobe=os.environ.get("WARRIGAL_FFPROBE", tools.get("ffprobe", "ffprobe")),
        whisper=os.environ.get("WARRIGAL_WHISPER", tools.get("whisper", "whisper-cli")),
        llama=os.environ.get("WARRIGAL_LLAMA", tools.get("llama", "llama-cli")),
        qpdf=os.environ.get("WARRIGAL_QPDF", tools.get("qpdf", "qpdf")),
        whisper_model=_optional_path("WARRIGAL_WHISPER_MODEL", models.get("whisper")),
        qwen_model=_optional_path("WARRIGAL_QWEN_MODEL", models.get("qwen")),
        qwen_projector=_optional_path("WARRIGAL_QWEN_PROJECTOR", models.get("qwen_projector")),
    )


CONFIG = load_config()
