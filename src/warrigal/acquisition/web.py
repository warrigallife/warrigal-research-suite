from __future__ import annotations

from dataclasses import dataclass
import ssl
from urllib.request import Request, urlopen

import certifi

@dataclass
class WebResponse:
    """Raw result of a public web acquisition."""

    requested_url: str
    final_url: str
    status: int
    content_type: str | None
    data: bytes


class WebFetcher:
    """Acquire raw bytes from a public HTTP/HTTPS resource."""

    def __init__(
        self,
        user_agent: str = "WarrigalResearchSuite/0.1",
        timeout: float = 30.0,
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.ssl_context = ssl.create_default_context(
    cafile=certifi.where()
)

    def fetch(self, url: str) -> WebResponse:
        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
            },
        )

        
        with urlopen(
            request,
            timeout=self.timeout,
            context=self.ssl_context,
        ) as response:
            data = response.read()

            return WebResponse(
                requested_url=url,
                final_url=response.geturl(),
                status=response.status,
                content_type=response.headers.get_content_type(),
                data=data,
            )