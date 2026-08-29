from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Create a human-readable Warrigal identifier."""
    return f"WRG-{prefix}-{uuid4().hex.upper()}"


@dataclass
class Node:
    """A machine or Warrigal installation that performs acquisitions."""

    name: str
    node_id: str = field(default_factory=lambda: new_id("NODE"))
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Batch:
    """A group of acquisitions that can be moved between Warrigal nodes."""

    node_id: str
    label: str | None = None
    batch_id: str = field(default_factory=lambda: new_id("BATCH"))
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Job:
    """A research or acquisition task given to Warrigal."""

    name: str
    node_id: str
    batch_id: str | None = None
    job_id: str = field(default_factory=lambda: new_id("JOB"))
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Source:
    """The external or local location from which material was obtained."""

    source_type: str
    locator: str
    source_id: str = field(default_factory=lambda: new_id("SRC"))
    final_locator: str | None = None
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Object:
    """An immutable object identified by the exact bytes Warrigal acquired."""

    sha256: str
    size_bytes: int
    mime_type: str | None = None
    original_filename: str | None = None
    object_id: str = field(default_factory=lambda: new_id("OBJ"))
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Acquisition:
    """The event connecting a source, job and resulting Warrigal object."""

    source_id: str
    object_id: str
    job_id: str
    node_id: str
    batch_id: str | None = None
    method: str = "unknown"
    status: str = "success"
    http_status: int | None = None
    error: str | None = None
    acquisition_id: str = field(default_factory=lambda: new_id("ACQ"))
    acquired_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Collection:
    """A named research corpus containing Warrigal objects."""

    name: str
    description: str | None = None
    collection_id: str = field(default_factory=lambda: new_id("COL"))
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class StorageLocation:
    """A known physical or logical location containing an object."""

    object_id: str
    location_type: str
    path: str
    node_id: str | None = None
    storage_id: str = field(default_factory=lambda: new_id("STORE"))
    verified_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Passage:
    """A persistent searchable passage derived from a Warrigal acquisition."""

    object_id: str
    acquisition_id: str
    passage_index: int
    text: str
    source_url: str | None = None
    source_title: str | None = None
    passage_id: str = field(default_factory=lambda: new_id("PASSAGE"))
    created_at: datetime = field(default_factory=utc_now)