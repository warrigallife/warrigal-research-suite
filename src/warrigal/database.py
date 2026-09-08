from __future__ import annotations

import sqlite3
from pathlib import Path


DEFAULT_DATABASE_PATH = Path("workspace/warrigal.db")


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    label TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (node_id) REFERENCES nodes(node_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    node_id TEXT NOT NULL,
    batch_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (node_id) REFERENCES nodes(node_id),
    FOREIGN KEY (batch_id) REFERENCES batches(batch_id)
);

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    locator TEXT NOT NULL,
    final_locator TEXT,
    title TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS objects (
    object_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL,
    mime_type TEXT,
    original_filename TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS acquisitions (
    acquisition_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    batch_id TEXT,
    method TEXT NOT NULL,
    status TEXT NOT NULL,
    http_status INTEGER,
    error TEXT,
    acquired_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (source_id) REFERENCES sources(source_id),
    FOREIGN KEY (object_id) REFERENCES objects(object_id),
    FOREIGN KEY (job_id) REFERENCES jobs(job_id),
    FOREIGN KEY (node_id) REFERENCES nodes(node_id),
    FOREIGN KEY (batch_id) REFERENCES batches(batch_id)
);

CREATE TABLE IF NOT EXISTS passages (
    passage_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL,
    acquisition_id TEXT NOT NULL,
    passage_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    source_url TEXT,
    source_title TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (object_id) REFERENCES objects(object_id),
    FOREIGN KEY (acquisition_id) REFERENCES acquisitions(acquisition_id),
    UNIQUE (acquisition_id, passage_index)
);

CREATE INDEX IF NOT EXISTS idx_passages_object
ON passages(object_id);

CREATE INDEX IF NOT EXISTS idx_passages_acquisition
ON passages(acquisition_id);

CREATE TABLE IF NOT EXISTS collections (
    collection_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_objects (
    collection_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (collection_id, object_id),
    FOREIGN KEY (collection_id) REFERENCES collections(collection_id),
    FOREIGN KEY (object_id) REFERENCES objects(object_id)
);

CREATE TABLE IF NOT EXISTS storage_locations (
    storage_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL,
    location_type TEXT NOT NULL,
    path TEXT NOT NULL,
    node_id TEXT,
    verified_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (object_id) REFERENCES objects(object_id),
    FOREIGN KEY (node_id) REFERENCES nodes(node_id)
);

CREATE INDEX IF NOT EXISTS idx_sources_locator
ON sources(locator);

CREATE INDEX IF NOT EXISTS idx_objects_sha256
ON objects(sha256);

CREATE INDEX IF NOT EXISTS idx_acquisitions_source
ON acquisitions(source_id);

CREATE INDEX IF NOT EXISTS idx_acquisitions_job
ON acquisitions(job_id);

CREATE TABLE IF NOT EXISTS instagram_post_checkpoints (
    profile_username TEXT NOT NULL,
    shortcode TEXT NOT NULL,
    contract_version INTEGER NOT NULL,
    snapshot_acquisition_id TEXT NOT NULL,
    evidence_acquisition_ids_json TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    PRIMARY KEY (profile_username, shortcode, contract_version),
    FOREIGN KEY (snapshot_acquisition_id)
        REFERENCES acquisitions(acquisition_id)
);

CREATE INDEX IF NOT EXISTS idx_instagram_checkpoints_profile
ON instagram_post_checkpoints(profile_username);
"""


def connect(database_path: Path = DEFAULT_DATABASE_PATH) -> sqlite3.Connection:
    """Open the Warrigal database and enable foreign-key enforcement."""

    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")

    return connection


def initialize_database(
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> sqlite3.Connection:
    """Create the Warrigal database schema if it does not already exist."""

    connection = connect(database_path)
    connection.executescript(SCHEMA)

    passage_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(passages)")
    }

    if "metadata_json" not in passage_columns:
        connection.execute(
            """
            ALTER TABLE passages
            ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'
            """
        )

    connection.commit()

    return connection