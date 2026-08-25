from __future__ import annotations

import json
import sqlite3

from warrigal.models import (
    Batch,
    Collection,
    Job,
    Node,
    Source,
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