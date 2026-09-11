from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from warrigal.models import (
    Acquisition,
    Batch,
    Collection,
    Job,
    Node,
    Object,
    Passage,
    Source,
    StorageLocation,
)


class WarrigalRepository:
    """Store and retrieve Warrigal domain records."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def save_node(self, node: Node) -> None:
        self.connection.execute(
            """
            INSERT INTO nodes (
                node_id,
                name,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (
                node.node_id,
                node.name,
                node.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def get_node(self, node_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            """
            SELECT *
            FROM nodes
            WHERE node_id = ?
            """,
            (node_id,),
        ).fetchone()

    def save_batch(self, batch: Batch) -> None:
        self.connection.execute(
            """
            INSERT INTO batches (
                batch_id,
                node_id,
                label,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                batch.batch_id,
                batch.node_id,
                batch.label,
                batch.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def save_job(self, job: Job) -> None:
        self.connection.execute(
            """
            INSERT INTO jobs (
                job_id,
                name,
                node_id,
                batch_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                job.name,
                job.node_id,
                job.batch_id,
                job.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def save_source(self, source: Source) -> None:
        self.connection.execute(
            """
            INSERT INTO sources (
                source_id,
                source_type,
                locator,
                final_locator,
                title,
                metadata_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.source_id,
                source.source_type,
                source.locator,
                source.final_locator,
                source.title,
                json.dumps(source.metadata),
                source.created_at.isoformat(),
            ),
        )
        self.connection.commit()

        
    def get_source(self, source_id: str) -> sqlite3.Row | None:
        """Return a source by its Warrigal source ID."""

        return self.connection.execute(
            """
            SELECT *
            FROM sources
            WHERE source_id = ?
            """,
            (source_id,),
        ).fetchone()    

    def save_collection(self, collection: Collection) -> None:
        self.connection.execute(
            """
            INSERT INTO collections (
                collection_id,
                name,
                description,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                collection.collection_id,
                collection.name,
                collection.description,
                collection.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def save_object(self, obj: Object) -> None:
        """Save an immutable object record."""

        self.connection.execute(
            """
            INSERT INTO objects (
                object_id,
                sha256,
                size_bytes,
                mime_type,
                original_filename,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                obj.object_id,
                obj.sha256,
                obj.size_bytes,
                obj.mime_type,
                obj.original_filename,
                obj.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def get_object(self, object_id: str) -> sqlite3.Row | None:
        """Return an object by its Warrigal object ID."""

        return self.connection.execute(
            """
            SELECT *
            FROM objects
            WHERE object_id = ?
            """,
            (object_id,),
        ).fetchone()    

    def get_object_by_hash(self, sha256: str) -> sqlite3.Row | None:
        """Find an existing object using its SHA-256 identity."""

        return self.connection.execute(
            """
            SELECT *
            FROM objects
            WHERE sha256 = ?
            """,
            (sha256,),
        ).fetchone()

    def save_acquisition(self, acquisition: Acquisition) -> None:
        """Record an acquisition event."""

        self.connection.execute(
            """
            INSERT INTO acquisitions (
                acquisition_id,
                source_id,
                object_id,
                job_id,
                node_id,
                batch_id,
                method,
                status,
                http_status,
                error,
                acquired_at,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                acquisition.acquisition_id,
                acquisition.source_id,
                acquisition.object_id,
                acquisition.job_id,
                acquisition.node_id,
                acquisition.batch_id,
                acquisition.method,
                acquisition.status,
                acquisition.http_status,
                acquisition.error,
                acquisition.acquired_at.isoformat(),
                json.dumps(acquisition.metadata),
            ),
        )
        self.connection.commit()

    def save_passage(self, passage: Passage) -> None:
        """Record a persistent searchable passage."""

        self.connection.execute(
            """
            INSERT INTO passages (
                passage_id,
                object_id,
                acquisition_id,
                passage_index,
                text,
                source_url,
                source_title,
                metadata_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                passage.passage_id,
                passage.object_id,
                passage.acquisition_id,
                passage.passage_index,
                passage.text,
                passage.source_url,
                passage.source_title,
                json.dumps(passage.metadata),
                passage.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def save_visual_observation(self, observation) -> None:
        """Persist a derived visual observation."""

        self.connection.execute(
            """
            INSERT INTO visual_observations (
                observation_id,
                frame_object_id,
                frame_acquisition_id,
                timestamp_ms,
                text,
                analyser,
                analyser_version,
                status,
                confidence,
                metadata_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation.observation_id,
                observation.frame_object_id,
                observation.frame_acquisition_id,
                observation.timestamp_ms,
                observation.text,
                observation.analyser,
                observation.analyser_version,
                observation.status,
                observation.confidence,
                json.dumps(observation.metadata),
                observation.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def get_visual_observations_for_frame(
        self,
        frame_object_id: str,
    ) -> list[sqlite3.Row]:
        """Return derived observations for one archived frame."""

        return self.connection.execute(
            """
            SELECT *
            FROM visual_observations
            WHERE frame_object_id = ?
            ORDER BY created_at
            """,
            (frame_object_id,),
        ).fetchall()

    def save_storage_location(self, storage: StorageLocation) -> None:
        """Record where an object's bytes are stored."""

        self.connection.execute(
            """
            INSERT INTO storage_locations (
                storage_id,
                object_id,
                location_type,
                path,
                node_id,
                verified_at,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                storage.storage_id,
                storage.object_id,
                storage.location_type,
                storage.path,
                storage.node_id,
                (
                    storage.verified_at.isoformat()
                    if storage.verified_at
                    else None
                ),
                json.dumps(storage.metadata),
            ),
        )
        self.connection.commit()

    def add_object_to_collection(
        self,
        collection_id: str,
        object_id: str,
    ) -> None:
        """Associate an object with a research collection."""

        added_at = datetime.now(timezone.utc).isoformat()

        self.connection.execute(
            """
            INSERT OR IGNORE INTO collection_objects (
                collection_id,
                object_id,
                added_at
            )
            VALUES (?, ?, ?)
            """,
            (
                collection_id,
                object_id,
                added_at,
            ),
        )
        self.connection.commit()

    def list_acquisitions(self) -> list[sqlite3.Row]:
        """Return all acquisitions, newest first."""

        return self.connection.execute(
            """
            SELECT *
            FROM acquisitions
            ORDER BY acquired_at DESC
            """
        ).fetchall()
    
    def get_acquisitions_for_object(
        self,
        object_id: str,
    ) -> list[sqlite3.Row]:
        """Return provenance records for an object."""

        return self.connection.execute(
            """
            SELECT *
            FROM acquisitions
            WHERE object_id = ?
            ORDER BY acquired_at
            """,
            (object_id,),
        ).fetchall()

    def get_storage_locations(
        self,
        object_id: str,
    ) -> list[sqlite3.Row]:
        """Return known storage locations for an object."""

        return self.connection.execute(
            """
            SELECT *
            FROM storage_locations
            WHERE object_id = ?
            """,
            (object_id,),
        ).fetchall()

    def object_has_passages(self, object_id: str) -> bool:
        """Return whether an object already has searchable passages."""

        row = self.connection.execute(
            """
            SELECT 1
            FROM passages
            WHERE object_id = ?
            LIMIT 1
            """,
            (object_id,),
        ).fetchone()

        return row is not None

    def list_passages(self) -> list[sqlite3.Row]:
        """Return all persistent searchable passages."""

        return self.connection.execute(
            """
            SELECT
                passage_id,
                object_id,
                acquisition_id,
                passage_index,
                text,
                source_url,
                source_title,
                metadata_json,
                created_at
            FROM passages
            ORDER BY created_at ASC, passage_index ASC
            """
        ).fetchall()


    def get_instagram_post_checkpoint(
        self,
        profile_username: str,
        shortcode: str,
        contract_version: int = 1,
    ) -> sqlite3.Row | None:
        """Return a completed Instagram post checkpoint."""

        return self.connection.execute(
            """
            SELECT *
            FROM instagram_post_checkpoints
            WHERE profile_username = ?
              AND shortcode = ?
              AND contract_version = ?
            """,
            (profile_username.lower(), shortcode, contract_version),
        ).fetchone()

    def save_instagram_post_checkpoint(
        self,
        *,
        profile_username: str,
        shortcode: str,
        snapshot_acquisition_id: str,
        evidence_acquisition_ids: list[str],
        contract_version: int = 1,
    ) -> None:
        """Record completion without replacing existing evidence."""

        if not profile_username or not shortcode:
            raise ValueError("Profile username and shortcode are required.")
        if contract_version < 1:
            raise ValueError("Contract version must be positive.")
        if not evidence_acquisition_ids:
            raise ValueError("At least one evidence acquisition is required.")

        acquisition_ids = [
            snapshot_acquisition_id,
            *evidence_acquisition_ids,
        ]
        if len(acquisition_ids) != len(set(acquisition_ids)):
            raise ValueError("Checkpoint acquisition IDs must be unique.")

        for acquisition_id in acquisition_ids:
            row = self.connection.execute(
                "SELECT 1 FROM acquisitions WHERE acquisition_id = ?",
                (acquisition_id,),
            ).fetchone()
            if row is None:
                raise ValueError(
                    f"Unknown checkpoint acquisition: {acquisition_id}"
                )

        username = profile_username.lower()
        existing = self.get_instagram_post_checkpoint(
            username, shortcode, contract_version
        )
        evidence_json = json.dumps(evidence_acquisition_ids)

        if existing is not None:
            if (
                existing["snapshot_acquisition_id"] == snapshot_acquisition_id
                and existing["evidence_acquisition_ids_json"] == evidence_json
            ):
                return
            raise ValueError(
                "Checkpoint already exists with different acquisition evidence."
            )

        completed_at = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """
            INSERT INTO instagram_post_checkpoints (
                profile_username,
                shortcode,
                contract_version,
                snapshot_acquisition_id,
                evidence_acquisition_ids_json,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                shortcode,
                contract_version,
                snapshot_acquisition_id,
                evidence_json,
                completed_at,
            ),
        )
        self.connection.commit()
