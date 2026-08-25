from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


DEFAULT_OBJECT_STORE = Path("archive/objects")


@dataclass(frozen=True)
class StoredObject:
    """Result of storing an immutable object in the Warrigal archive."""

    sha256: str
    size_bytes: int
    path: Path
    already_existed: bool


class ObjectStore:
    """Content-addressed storage for immutable Warrigal objects."""

    def __init__(self, root: Path = DEFAULT_OBJECT_STORE):
        self.root = root

    @staticmethod
    def calculate_sha256(data: bytes) -> str:
        """Calculate the SHA-256 fingerprint of exact bytes."""

        return hashlib.sha256(data).hexdigest()

    def path_for_hash(self, sha256: str) -> Path:
        """Return the archive path assigned to a SHA-256 hash."""

        return (
            self.root
            / sha256[:2]
            / sha256[2:4]
            / sha256
        )

    def store_bytes(self, data: bytes) -> StoredObject:
        """Store exact bytes once and return their archive information."""

        sha256 = self.calculate_sha256(data)
        path = self.path_for_hash(sha256)

        if path.exists():
            return StoredObject(
                sha256=sha256,
                size_bytes=len(data),
                path=path,
                already_existed=True,
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

        return StoredObject(
            sha256=sha256,
            size_bytes=len(data),
            path=path,
            already_existed=False,
        )

    def read_bytes(self, sha256: str) -> bytes:
        """Read an archived object by its SHA-256 hash."""

        return self.path_for_hash(sha256).read_bytes()

    def verify(self, sha256: str) -> bool:
        """Verify that an archived object's bytes still match its hash."""

        path = self.path_for_hash(sha256)

        if not path.exists():
            return False

        actual_sha256 = self.calculate_sha256(path.read_bytes())

        return actual_sha256 == sha256