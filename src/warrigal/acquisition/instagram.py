from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class InstagramProfile:
    username: str
    user_id: int
    full_name: str
    biography: str
    is_private: bool
    post_count: int


@dataclass(frozen=True)
class InstagramPost:
    shortcode: str
    url: str
    date_utc: datetime
    typename: str
    caption: str



def discover_profile_posts(
    profile: object,
    *,
    max_posts: int = 3,
) -> list[InstagramPost]:
    """Normalize a bounded number of posts from an existing profile."""
    if max_posts < 0:
        raise ValueError("max_posts must be non-negative")

    if max_posts == 0:
        return []

    posts = []
    for post in profile.get_posts():
        posts.append(post_from_instaloader(post))
        if len(posts) >= max_posts:
            break

    return posts

def profile_from_instaloader(profile: object) -> InstagramProfile:
    """Normalize an Instaloader profile without performing network requests."""
    return InstagramProfile(
        username=profile.username,
        user_id=profile.userid,
        full_name=profile.full_name,
        biography=profile.biography,
        is_private=profile.is_private,
        post_count=profile.mediacount,
    )


def post_from_instaloader(post: object) -> InstagramPost:
    """Normalize an Instaloader post without performing network requests."""
    return InstagramPost(
        shortcode=post.shortcode,
        url=f"https://www.instagram.com/p/{post.shortcode}/",
        date_utc=post.date_utc,
        typename=post.typename,
        caption=post.caption or "",
    )



def instagram_caption_to_passages(
    post: InstagramPost,
    *,
    object_id: str,
    acquisition_id: str,
):
    """Create a searchable passage preserving the caption's source range."""
    from warrigal.models import Passage

    if not post.caption.strip():
        return []

    return [
        Passage(
            object_id=object_id,
            acquisition_id=acquisition_id,
            passage_index=0,
            text=post.caption,
            source_url=post.url,
            source_title=post.shortcode,
            metadata={
                "shortcode": post.shortcode,
                "source_field": "post.caption",
                "source_start_char": 0,
                "source_end_char": len(post.caption),
                "evidence_kind": "normalized_metadata_snapshot",
            },
        )
    ]

def persist_instagram_post(
    post: InstagramPost,
    *,
    repository,
    object_store,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str | None = None,
):
    """Persist a canonical metadata snapshot using shared acquisition."""
    import json
    from dataclasses import asdict
    from warrigal.acquisition.service import AcquisitionService
    from warrigal.models import Source

    payload = {
        "schema": "warrigal.instagram.post.v1",
        "post": {
            **asdict(post),
            "date_utc": post.date_utc.isoformat(),
        },
    }
    data = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")

    source_record = Source(
        source_type="instagram_post",
        locator=post.url,
        title=post.shortcode,
        metadata={
            "shortcode": post.shortcode,
            "typename": post.typename,
            "date_utc": post.date_utc.isoformat(),
            "evidence_kind": "normalized_metadata_snapshot",
        },
    )
    repository.save_source(source_record)

    acquisition = AcquisitionService(repository, object_store).acquire_bytes(
        data=data,
        source_id=source_record.source_id,
        job_id=job_id,
        node_id=node_id,
        batch_id=batch_id,
        method="instagram_metadata_snapshot",
        mime_type="application/json",
        original_filename=f"{post.shortcode}.json",
        collection_id=collection_id,
        metadata={
            "shortcode": post.shortcode,
            "evidence_kind": "normalized_metadata_snapshot",
        },
    )

    if not repository.object_has_passages(acquisition.object_id):
        for passage in instagram_caption_to_passages(
            post,
            object_id=acquisition.object_id,
            acquisition_id=acquisition.acquisition_id,
        ):
            repository.save_passage(passage)

    return acquisition


def persist_instagram_evidence_file(
    path,
    *,
    source_url: str,
    evidence_kind: str,
    repository,
    object_store,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str | None = None,
):
    """Preserve exact exported evidence bytes through shared acquisition."""
    import mimetypes
    from pathlib import Path
    from warrigal.acquisition.service import AcquisitionService
    from warrigal.models import Source

    evidence_path = Path(path)
    data = evidence_path.read_bytes()
    mime_type, _ = mimetypes.guess_type(evidence_path.name)

    source_record = Source(
        source_type="instagram",
        locator=source_url,
        title=evidence_path.name,
        metadata={
            "evidence_kind": evidence_kind,
            "original_filename": evidence_path.name,
        },
    )
    repository.save_source(source_record)

    return AcquisitionService(repository, object_store).acquire_bytes(
        data=data,
        source_id=source_record.source_id,
        job_id=job_id,
        node_id=node_id,
        batch_id=batch_id,
        method="instagram_evidence_file",
        mime_type=mime_type or "application/octet-stream",
        original_filename=evidence_path.name,
        collection_id=collection_id,
        metadata={
            "evidence_kind": evidence_kind,
            "source_url": source_url,
        },
    )




class InstagramProfileIngestionResult(list):
    """Successful post results with explicit per-post failures."""

    def __init__(self):
        super().__init__()
        self.failures = []
        self.attempted = 0

    @property
    def succeeded(self):
        return len(self)

    @property
    def failed(self):
        return len(self.failures)



def ingest_instagram_profile(
    profile, *, downloader, repository, object_store,
    job_id: str, node_id: str, batch_id: str,
    collection_id: str | None = None, max_posts: int = 3,
    resume: bool = False,
):
    if max_posts < 0:
        raise ValueError("max_posts must be non-negative")

    results = InstagramProfileIngestionResult()
    results.skipped = 0
    if max_posts == 0:
        return results

    profile_username = profile.username.lower()

    for index, raw_post in enumerate(profile.get_posts()):
        if index >= max_posts:
            break

        shortcode = getattr(raw_post, "shortcode", None)

        if resume and shortcode:
            checkpoint = repository.get_instagram_post_checkpoint(
                profile_username, shortcode, 1
            )
            if checkpoint is not None:
                results.skipped += 1
                continue

        results.attempted += 1
        try:
            result = ingest_instagram_post(
                raw_post,
                downloader=downloader,
                repository=repository,
                object_store=object_store,
                job_id=job_id,
                node_id=node_id,
                batch_id=batch_id,
                collection_id=collection_id,
            )

            if shortcode and repository is not None:
                snapshot = result.get("snapshot") if isinstance(result, dict) else None
                evidence = result.get("evidence") if isinstance(result, dict) else None
                if snapshot is not None and evidence is not None:
                    existing = repository.get_instagram_post_checkpoint(
                        profile_username, shortcode, 1
                    )
                    if existing is None:
                        repository.save_instagram_post_checkpoint(
                            profile_username=profile_username,
                            shortcode=shortcode,
                            contract_version=1,
                            snapshot_acquisition_id=snapshot.acquisition_id,
                            evidence_acquisition_ids=[
                                item.acquisition_id for item in evidence
                            ],
                        )
        except Exception as exc:
            results.failures.append({
                "shortcode": shortcode,
                "source_url": (
                    f"https://www.instagram.com/p/{shortcode}/"
                    if shortcode else None
                ),
                "error_type": type(exc).__name__,
                "message": str(exc),
            })
            continue

        results.append(result)

    return results

def ingest_instagram_post(
    raw_post,
    *,
    downloader,
    repository,
    object_store,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str | None = None,
):
    """Export one resolved post and preserve its evidence and searchable caption."""
    from pathlib import Path
    from tempfile import TemporaryDirectory

    post = post_from_instaloader(raw_post)
    kwargs = {
        "repository": repository,
        "object_store": object_store,
        "job_id": job_id,
        "node_id": node_id,
        "batch_id": batch_id,
        "collection_id": collection_id,
    }

    with TemporaryDirectory(prefix="warrigal-instagram-") as temporary:
        root = Path(temporary)
        target = "post"
        original_dirname_pattern = getattr(downloader, "dirname_pattern", None)
        if original_dirname_pattern is not None:
            downloader.dirname_pattern = str(root / "{target}")

        try:
            downloader.download_post(raw_post, target=target)
        finally:
            if original_dirname_pattern is not None:
                downloader.dirname_pattern = original_dirname_pattern

        files = sorted(path for path in root.rglob("*") if path.is_file())
        if not files:
            raise RuntimeError("Instagram export produced no evidence files.")

        evidence = []
        for path in files:
            name = path.name.lower()
            if name.endswith((".json", ".json.xz")):
                kind = "instaloader_metadata"
            elif name.endswith((".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov")):
                kind = "instagram_media"
            else:
                kind = "instaloader_export"

            evidence.append(
                persist_instagram_evidence_file(
                    path,
                    source_url=post.url,
                    evidence_kind=kind,
                    **kwargs,
                )
            )

        snapshot = persist_instagram_post(post, **kwargs)

    return {
        "post": post,
        "snapshot": snapshot,
        "evidence": evidence,
    }
