"""Bounded research collection manifests for Warrigal acquisition."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse


RESOURCE_STATUSES = {
    "inventoried",
    "acquired",
    "verified",
    "failed",
    "needs_review",
}

LEAD_STATUSES = {
    "lead",
    "needs_review",
}


@dataclass
class ManifestResource:
    """One explicitly bounded resource belonging to a collection manifest."""

    url: str
    media_type: str
    expected_size_bytes: int | None = None
    status: str = "inventoried"
    object_id: str | None = None
    acquisition_id: str | None = None
    sha256: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _validate_http_url(self.url, "resource url")

        if not self.media_type.strip():
            raise ValueError("resource media_type must not be empty")

        if (
            self.expected_size_bytes is not None
            and self.expected_size_bytes < 0
        ):
            raise ValueError(
                "resource expected_size_bytes must be non-negative or None"
            )

        if self.status not in RESOURCE_STATUSES:
            raise ValueError(
                f"unsupported resource status: {self.status}"
            )

        if self.sha256 is not None:
            digest = self.sha256.lower()
            if len(digest) != 64 or any(
                character not in "0123456789abcdef"
                for character in digest
            ):
                raise ValueError(
                    "resource sha256 must be a 64-character hexadecimal digest"
                )


@dataclass
class ManifestLead:
    """A potential research direction outside the bounded resource inventory."""

    locator: str
    relationship: str
    status: str = "lead"
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.locator.strip():
            raise ValueError("lead locator must not be empty")

        if not self.relationship.strip():
            raise ValueError("lead relationship must not be empty")

        if self.status not in LEAD_STATUSES:
            raise ValueError(
                f"unsupported lead status: {self.status}"
            )


@dataclass
class CollectionManifest:
    """Human- and machine-readable plan for a bounded research collection."""

    manifest_id: str
    name: str
    description: str
    discovery_provenance: dict[str, Any]
    resources: list[ManifestResource] = field(default_factory=list)
    leads: list[ManifestLead] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.manifest_id.strip():
            raise ValueError("manifest_id must not be empty")

        if not self.name.strip():
            raise ValueError("manifest name must not be empty")

        if not self.description.strip():
            raise ValueError("manifest description must not be empty")

        seen_urls: set[str] = set()

        for resource in self.resources:
            resource.validate()

            if resource.url in seen_urls:
                raise ValueError(
                    f"duplicate resource url in manifest: {resource.url}"
                )

            seen_urls.add(resource.url)

        for lead in self.leads:
            lead.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    def to_json(self) -> str:
        """Serialize deterministically for review, versioning, and hashing."""

        return json.dumps(
            self.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ) + "\n"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CollectionManifest:
        manifest = cls(
            manifest_id=data["manifest_id"],
            name=data["name"],
            description=data["description"],
            discovery_provenance=dict(
                data.get("discovery_provenance", {})
            ),
            resources=[
                ManifestResource(**resource)
                for resource in data.get("resources", [])
            ],
            leads=[
                ManifestLead(**lead)
                for lead in data.get("leads", [])
            ],
            metadata=dict(data.get("metadata", {})),
        )
        manifest.validate()
        return manifest

    @classmethod
    def from_json(cls, text: str) -> CollectionManifest:
        data = json.loads(text)

        if not isinstance(data, dict):
            raise ValueError("manifest JSON root must be an object")

        return cls.from_dict(data)


def _validate_http_url(value: str, label: str) -> None:
    parsed = urlparse(value)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            f"{label} must be an absolute HTTP or HTTPS URL"
        )
