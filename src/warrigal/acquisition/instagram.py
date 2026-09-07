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
