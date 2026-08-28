from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from warrigal.acquisition.links import extract_links
from warrigal.acquisition.web import WebFetcher, WebResponse


@dataclass
class CrawlResult:
    """Result of discovering pages from a starting URL."""

    start_url: str
    visited: list[str]
    discovered: list[str]
    responses: list[WebResponse]


class WebCrawler:
    """Discover web pages within controlled crawl boundaries."""

    def __init__(
        self,
        fetcher: WebFetcher,
        max_pages: int = 10,
        same_domain: bool = True,
    ) -> None:
        self.fetcher = fetcher
        self.max_pages = max_pages
        self.same_domain = same_domain

    def crawl(self, start_url: str) -> CrawlResult:
        visited: list[str] = []
        discovered: list[str] = []
        responses: list[WebResponse] = []
        pending = [start_url]

        start_domain = urlparse(start_url).netloc

        while pending and len(visited) < self.max_pages:
            url = pending.pop(0)

            if url in visited:
                continue

            response = self.fetcher.fetch(url)
            responses.append(response)
            visited.append(response.final_url)

            if response.content_type != "text/html":
                continue

            links = extract_links(
                response.data,
                response.final_url,
            )

            for link in links:
                if self.same_domain:
                    link_domain = urlparse(link).netloc

                    if link_domain != start_domain:
                        continue

                if link not in visited and link not in discovered:
                    discovered.append(link)
                    pending.append(link)

        return CrawlResult(
            start_url=start_url,
            visited=visited,
            discovered=discovered,
            responses=responses,
        )