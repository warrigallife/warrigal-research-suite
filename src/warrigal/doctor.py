"""Read-only installation and archive diagnostics for Warrigal."""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from warrigal.config import CONFIG, WarrigalConfig


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    detail: str
    required: bool = True


def _path_check(name: str, path: Path, *, kind: str, required: bool) -> DoctorCheck:
    exists = path.is_dir() if kind == "directory" else path.is_file()
    if exists:
        target = path.resolve() if path.is_symlink() else path
        suffix = f" -> {target}" if path.is_symlink() else ""
        return DoctorCheck(name, "OK", f"{path}{suffix}", required)
    return DoctorCheck(name, "MISSING", str(path), required)


def collect_checks(
    config: WarrigalConfig = CONFIG,
    *,
    module_finder: Callable[[str], object | None] = importlib.util.find_spec,
    executable_finder: Callable[[str], str | None] = shutil.which,
) -> tuple[DoctorCheck, ...]:
    """Inspect configuration without creating paths or changing the archive."""

    checks: list[DoctorCheck] = []
    checks.append(_path_check("Archive root", config.archive_root, kind="directory", required=True))
    checks.append(_path_check("Runtime root", config.runtime_root, kind="directory", required=True))
    checks.append(_path_check("Database", config.database_path, kind="file", required=True))
    checks.append(_path_check("Object store", config.object_store_path, kind="directory", required=True))

    for display, module in (
        ("Python: certifi", "certifi"),
        ("Python: crawlee", "crawlee"),
        ("Python: pypdf", "pypdf"),
        ("Python: yt-dlp", "yt_dlp"),
    ):
        found = module_finder(module) is not None
        checks.append(DoctorCheck(display, "OK" if found else "MISSING", module, True))

    for display, executable, required in (
        ("ffmpeg", config.ffmpeg, True),
        ("ffprobe", config.ffprobe, True),
        ("whisper.cpp", config.whisper, False),
        ("llama.cpp", config.llama, False),
        ("qpdf", config.qpdf, False),
    ):
        resolved = executable_finder(executable)
        checks.append(DoctorCheck(
            display,
            "OK" if resolved else "MISSING",
            resolved or executable,
            required,
        ))

    for display, path in (
        ("Whisper model", config.whisper_model),
        ("Qwen model", config.qwen_model),
        ("Qwen projector", config.qwen_projector),
    ):
        if path is None:
            checks.append(DoctorCheck(display, "NOT CONFIGURED", "environment variable not set", False))
        else:
            checks.append(_path_check(display, path, kind="file", required=False))

    return tuple(checks)


def run_doctor(config: WarrigalConfig = CONFIG) -> int:
    checks = collect_checks(config)
    print("=== WARRIGAL DOCTOR ===")
    for check in checks:
        requirement = "required" if check.required else "optional"
        print(f"{check.status:14} {check.name:20} [{requirement}] {check.detail}")
    missing_required = [check for check in checks if check.required and check.status != "OK"]
    print()
    if missing_required:
        print(f"RESULT: ATTENTION REQUIRED ({len(missing_required)} required checks missing)")
        return 1
    print("RESULT: CORE READY")
    return 0


def main() -> int:
    return run_doctor()


if __name__ == "__main__":
    raise SystemExit(main())

