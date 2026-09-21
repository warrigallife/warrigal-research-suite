"""Bounded orchestration for Warrigal collection manifests."""

from dataclasses import dataclass
from pathlib import Path
from time import sleep
from typing import Callable

from warrigal.acquisition.manifest import CollectionManifest, ManifestResource
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
    retry_attempts: int = 0
    retried_resources: int = 0
    exhausted_failures: int = 0


def _manifest_with_resources(
    manifest: CollectionManifest,
    resources: tuple[ManifestResource, ...],
) -> CollectionManifest:
    """Return an immutable view containing only the supplied resources."""
    return CollectionManifest(
        manifest_id=manifest.manifest_id,
        name=manifest.name,
        description=manifest.description,
        discovery_provenance=dict(manifest.discovery_provenance),
        resources=resources,
        leads=manifest.leads,
        metadata=dict(manifest.metadata),
    )


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

    retained: list[ManifestResource] = []
    eligible: list[ManifestResource] = []

    for resource in manifest.resources:
        if resource.status == "verified":
            retained.append(resource)
            continue

        if resource.url in completed_urls:
            retained.append(resource)
            continue

        if max_resource_bytes is not None:
            if resource.expected_size_bytes is None:
                continue
            if resource.expected_size_bytes > max_resource_bytes:
                continue

        eligible.append(resource)

    # Known-size work is deliberately scheduled from smallest to largest.
    # URL is a stable tie-breaker, and unknown-size resources run last when no
    # byte ceiling is active.  This ordering is applied to both full and
    # user-selected manifests because selection is only a scope filter.
    eligible.sort(
        key=lambda resource: (
            resource.expected_size_bytes is None,
            resource.expected_size_bytes
            if resource.expected_size_bytes is not None
            else 0,
        )
    )

    if max_resources is not None:
        eligible = eligible[:max_resources]

    selected = [*retained, *eligible]

    return CollectionManifest(
        manifest_id=manifest.manifest_id,
        name=manifest.name,
        description=manifest.description,
        discovery_provenance=dict(manifest.discovery_provenance),
        resources=selected,
        leads=manifest.leads,
        metadata=dict(manifest.metadata),
    )


def run_manifest_campaign(
    manifest: CollectionManifest,
    *,
    pdf_handler: ResourceHandler | None = None,
    zip_handler: ResourceHandler | None = None,
    document_handler: ResourceHandler | None = None,
    checkpoint_path: Path | None = None,
    max_resources: int | None = None,
    max_resource_bytes: int | None = None,
    retry_failures: int = 0,
    retry_delay_seconds: float = 0.0,
    sleeper: Callable[[float], None] = sleep,
) -> ManifestCampaignResult:
    """Run a bounded acquisition campaign over an immutable manifest."""

    manifest.validate()

    if retry_failures < 0:
        raise ValueError("retry_failures must be non-negative")
    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds must be non-negative")

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

    first_run_result = run_collection_manifest(
        campaign_manifest,
        pdf_handler=pdf_handler,
        zip_handler=zip_handler,
        document_handler=document_handler,
        checkpoint_path=checkpoint_path,
    )

    items = list(first_run_result.items)
    resource_by_url = {
        resource.url: resource
        for resource in campaign_manifest.resources
    }
    retry_attempts = 0
    retried_resources = 0

    for index, first_item in enumerate(tuple(items)):
        if first_item.status != "failed":
            continue

        resource = resource_by_url[first_item.url]
        final_item = first_item

        for retry_index in range(retry_failures):
            delay = retry_delay_seconds * (2 ** retry_index)
            if delay:
                sleeper(delay)

            retry_result = run_collection_manifest(
                _manifest_with_resources(manifest, (resource,)),
                pdf_handler=pdf_handler,
                zip_handler=zip_handler,
                checkpoint_path=checkpoint_path,
            )
            final_item = retry_result.items[0]
            retry_attempts += 1

            if final_item.status != "failed":
                retried_resources += 1
                break

        items[index] = final_item

    run_result = ManifestRunResult(
        manifest_id=manifest.manifest_id,
        items=tuple(items),
    )
    exhausted_failures = run_result.count("failed")

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
        retry_attempts=retry_attempts,
        retried_resources=retried_resources,
        exhausted_failures=exhausted_failures,
    )
