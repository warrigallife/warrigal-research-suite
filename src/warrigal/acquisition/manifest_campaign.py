"""Bounded orchestration for Warrigal collection manifests."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from warrigal.acquisition.manifest import CollectionManifest
from warrigal.acquisition.manifest_runner import (
    ManifestCheckpointStore,
    ManifestRunItem,
    ManifestRunResult,
    ResourceHandler,
    is_successful_checkpoint_record,
    run_collection_manifest,
)


@dataclass(frozen=True)
class ManifestCampaignResult:
    """Result of one bounded manifest campaign invocation."""

    manifest_id: str
    attempted_limit: int | None
    selected_resources: int
    run_result: ManifestRunResult


def _select_campaign_manifest(
    manifest: CollectionManifest,
    *,
    max_resources: int | None,
    max_resource_bytes: int | None = None,
    completed_urls: frozenset[str] = frozenset(),
) -> CollectionManifest:
    """
    Build an in-memory campaign view without modifying the source manifest.

    Verified resources remain present so the runner can report them normally.
    The resource limit applies only to non-verified resources eligible for work.

    When max_resource_bytes is set, resources with an unknown expected size or
    a size above the ceiling are not selected and do not consume the resource
    limit.

    Checkpoint-completed resources remain present for runner reporting but do
    not consume the resource limit.
    """

    if max_resources is not None and max_resources < 1:
        raise ValueError("max_resources must be at least 1")

    if max_resource_bytes is not None and max_resource_bytes < 0:
        raise ValueError("max_resource_bytes must be non-negative")

    if max_resources is None and max_resource_bytes is None:
        return manifest

    selected = []
    eligible = 0

    for resource in manifest.resources:
        if resource.status == "verified":
            selected.append(resource)
            continue

        if resource.url in completed_urls:
            selected.append(resource)
            continue

        if max_resource_bytes is not None:
            if resource.expected_size_bytes is None:
                continue
            if resource.expected_size_bytes > max_resource_bytes:
                continue

        if max_resources is not None and eligible >= max_resources:
            continue

        selected.append(resource)
        eligible += 1

    return CollectionManifest(
        manifest_id=manifest.manifest_id,
        name=manifest.name,
        description=manifest.description,
        discovery_provenance=dict(manifest.discovery_provenance),
        resources=tuple(selected),
        leads=manifest.leads,
        metadata=dict(manifest.metadata),
    )


def run_manifest_campaign(
    manifest: CollectionManifest,
    *,
    pdf_handler: ResourceHandler | None = None,
    zip_handler: ResourceHandler | None = None,
    checkpoint_path: Path | None = None,
    max_resources: int | None = None,
    max_resource_bytes: int | None = None,
) -> ManifestCampaignResult:
    """Run a bounded acquisition campaign over an immutable manifest."""

    manifest.validate()

    checkpoint = (
        ManifestCheckpointStore(checkpoint_path).load(manifest.manifest_id)
        if checkpoint_path is not None
        else {}
    )
    completed_urls = frozenset(
        url
        for url, record in checkpoint.items()
        if is_successful_checkpoint_record(record)
    )

    campaign_manifest = _select_campaign_manifest(
        manifest,
        max_resources=max_resources,
        max_resource_bytes=max_resource_bytes,
        completed_urls=completed_urls,
    )

    run_result = run_collection_manifest(
        campaign_manifest,
        pdf_handler=pdf_handler,
        zip_handler=zip_handler,
        checkpoint_path=checkpoint_path,
    )

    selected_resources = sum(
        1
        for resource in campaign_manifest.resources
        if resource.status != "verified"
        and resource.url not in completed_urls
    )

    return ManifestCampaignResult(
        manifest_id=manifest.manifest_id,
        attempted_limit=max_resources,
        selected_resources=selected_resources,
        run_result=run_result,
    )
