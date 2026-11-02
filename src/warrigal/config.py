"""Central configuration for Warrigal paths and local tool locations."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


# Online Search provider defaults. Defined here (not in online_search.py)
# because `WarrigalConfig`'s dataclass field defaults need them eagerly,
# and this keeps config.py the single source of truth for every default
# that participates in the env-var/local-file precedence pattern.
DEFAULT_SEARXNG_INSTANCE_URL = "https://searx.be"
DEFAULT_ONLINE_SEARCH_PROVIDER = "searxng"


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def _optional_str(name: str, default: str | None = None) -> str | None:
    """Same env-var-first, local-file-fallback precedence as
    `_optional_path`, for plain string values (e.g. API keys) that
    should not be turned into a `Path`."""

    value = os.environ.get(name)
    return value if value is not None else default


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
    # Defaulted (unlike the fields above) so existing code that already
    # constructs `WarrigalConfig(...)` directly - e.g. test fixtures -
    # keeps working unchanged; `load_config()` below always sets it
    # explicitly via the same env-var/local-file precedence as the rest.
    brave_api_key: str | None = None
    # Identical env-var-first, local-file-fallback precedence as
    # `brave_api_key` - see `warrigal.online_search.search_tavily`.
    tavily_api_key: str | None = None
    # Account-free Online Search default. Same env-var-first,
    # local-file-fallback precedence as `brave_api_key`, but with a
    # built-in public-instance default instead of `None`, since no
    # account/key is required for this path. See `warrigal.online_search`.
    searxng_instance_url: str = DEFAULT_SEARXNG_INSTANCE_URL
    online_search_provider: str = DEFAULT_ONLINE_SEARCH_PROVIDER


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
    search = local.get("search", {})
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
        brave_api_key=_optional_str("WARRIGAL_BRAVE_API_KEY", search.get("brave_api_key")),
        tavily_api_key=_optional_str("WARRIGAL_TAVILY_API_KEY", search.get("tavily_api_key")),
        searxng_instance_url=os.environ.get(
            "WARRIGAL_SEARXNG_URL",
            search.get("searxng_instance_url", DEFAULT_SEARXNG_INSTANCE_URL),
        ),
        online_search_provider=os.environ.get(
            "WARRIGAL_ONLINE_SEARCH_PROVIDER",
            search.get("provider", DEFAULT_ONLINE_SEARCH_PROVIDER),
        ),
    )


CONFIG = load_config()
