from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from warrigal.acquisition.manifest import CollectionManifest, ManifestResource


ResourceHandler = Callable[[ManifestResource], Mapping[str, Any] | None]

_SUCCESS_STATUSES = {"acquired", "archived"}


def is_successful_checkpoint_record(
    record: Mapping[str, Any] | None,
) -> bool:
    """Return whether a checkpoint record represents completed work."""
    return record is not None and record.get("status") in _SUCCESS_STATUSES


@dataclass(frozen=True)
class ManifestRunItem:
    """Outcome for one bounded manifest resource."""

    url: str
    media_type: str
    status: str
    action: str
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class ManifestRunResult:
    """Outcome of one bounded manifest run."""

    manifest_id: str
    items: tuple[ManifestRunItem, ...]

    def count(self, status: str) -> int:
        return sum(item.status == status for item in self.items)


class ManifestCheckpointStore:
    """Persist runner progress separately from the source manifest."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self, manifest_id: str) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}

        payload = json.loads(self.path.read_text(encoding="utf-8"))

        if not isinstance(payload, dict):
            raise ValueError("Manifest checkpoint must be a JSON object.")

        stored_manifest_id = payload.get("manifest_id")
        if stored_manifest_id != manifest_id:
            raise ValueError(
                "Checkpoint belongs to a different manifest: "
                f"{stored_manifest_id!r} != {manifest_id!r}"
            )

        resources = payload.get("resources", {})
        if not isinstance(resources, dict):
            raise ValueError("Checkpoint resources must be a JSON object.")

        normalized: dict[str, dict[str, Any]] = {}

        for url, record in resources.items():
            if not isinstance(url, str) or not isinstance(record, dict):
                raise ValueError("Invalid checkpoint resource record.")
            normalized[url] = dict(record)

        return normalized

    def save(
        self,
        manifest_id: str,
        resources: Mapping[str, Mapping[str, Any]],
    ) -> None:
        payload = {
            "manifest_id": manifest_id,
            "resources": {
                url: dict(record)
                for url, record in resources.items()
            },
        }

        text = json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ) + "\n"

        self.path.parent.mkdir(parents=True, exist_ok=True)

        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(self.path)


def run_collection_manifest(
    manifest: CollectionManifest,
    *,
    pdf_handler: ResourceHandler | None = None,
    zip_handler: ResourceHandler | None = None,
    checkpoint_path: str | Path | None = None,
) -> ManifestRunResult:
    """
    Process only resources explicitly contained in a validated manifest.

    The runner performs no discovery and does not mutate the manifest.
    Successful work is checkpointed after each resource so a later run
    can skip completed resources while retrying failures.
    """

    manifest.validate()

    checkpoint_store = (
        ManifestCheckpointStore(checkpoint_path)
        if checkpoint_path is not None
        else None
    )

    checkpoint = (
        checkpoint_store.load(manifest.manifest_id)
        if checkpoint_store is not None
        else {}
    )

    items: list[ManifestRunItem] = []

    for resource in manifest.resources:
        if resource.status == "verified":
            items.append(
                ManifestRunItem(
                    url=resource.url,
                    media_type=resource.media_type,
                    status="skipped_verified",
                    action="skip",
                )
            )
            continue

        previous = checkpoint.get(resource.url)

        if is_successful_checkpoint_record(previous):
            items.append(
                ManifestRunItem(
                    url=resource.url,
                    media_type=resource.media_type,
                    status="skipped_checkpoint",
                    action="skip",
                    metadata=dict(previous.get("metadata") or {}),
                )
            )
            continue

        handler: ResourceHandler | None
        success_status: str
        action: str

        if resource.media_type == "application/pdf":
            handler = pdf_handler
            success_status = "acquired"
            action = "pdf_acquisition"
        elif resource.media_type == "application/zip":
            handler = zip_handler
            success_status = "archived"
            action = "zip_archive"
        else:
            handler = None
            success_status = "needs_review"
            action = "unsupported"

        if handler is None:
            error = (
                f"No handler configured for media type "
                f"{resource.media_type!r}."
            )

            item = ManifestRunItem(
                url=resource.url,
                media_type=resource.media_type,
                status="needs_review",
                action=action,
                error=error,
            )

            checkpoint[resource.url] = {
                "media_type": resource.media_type,
                "status": item.status,
                "action": item.action,
                "metadata": {},
                "error": error,
            }

        else:
            attempt_count = int((previous or {}).get("attempt_count", 0)) + 1
            errors = list((previous or {}).get("errors") or [])

            try:
                metadata = dict(handler(resource) or {})

                item = ManifestRunItem(
                    url=resource.url,
                    media_type=resource.media_type,
                    status=success_status,
                    action=action,
                    metadata=metadata,
                )

                checkpoint[resource.url] = {
                    "media_type": resource.media_type,
                    "status": item.status,
                    "action": item.action,
                    "metadata": metadata,
                    "error": None,
                    "attempt_count": attempt_count,
                    "errors": errors,
                }

            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                errors.append(error)

                item = ManifestRunItem(
                    url=resource.url,
                    media_type=resource.media_type,
                    status="failed",
                    action=action,
                    error=error,
                )

                checkpoint[resource.url] = {
                    "media_type": resource.media_type,
                    "status": item.status,
                    "action": item.action,
                    "metadata": {},
                    "error": error,
                    "attempt_count": attempt_count,
                    "errors": errors,
                }

        items.append(item)

        if checkpoint_store is not None:
            checkpoint_store.save(
                manifest.manifest_id,
                checkpoint,
            )

    return ManifestRunResult(
        manifest_id=manifest.manifest_id,
        items=tuple(items),
    )
