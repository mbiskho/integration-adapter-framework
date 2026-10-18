from __future__ import annotations

import os
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator

import httpx


@dataclass(frozen=True)
class Record:
    """The one shape every adapter produces. Downstream upserts on (source, kind, external_id)."""

    source: str
    kind: str
    external_id: str
    updated_at: str  # ISO 8601; the incremental-sync cursor
    data: dict[str, Any] = field(default_factory=dict)


class Adapter(ABC):
    def __init__(self, name: str, config: dict[str, Any]):
        self.name = name
        self.config = config

    @abstractmethod
    def pages(self, since: str | None) -> Iterator[list[dict]]:
        """Yield raw items one page at a time, oldest changes first where the API allows."""

    @abstractmethod
    def to_record(self, item: dict) -> Record: ...

    def secret(self, key: str) -> str:
        """Config names an env var (`<key>_env`); the value never lives in a file."""
        var = self.config.get(f"{key}_env")
        if not var or not os.environ.get(var):
            raise RuntimeError(f"{self.name}: set {var or key + '_env'} in the environment")
        return os.environ[var]


class RateLimiter:
    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second if per_second > 0 else 0
        self.next_at = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        if now < self.next_at:
            time.sleep(self.next_at - now)
        self.next_at = max(now, self.next_at) + self.interval


class HttpAdapter(Adapter):
    RETRY_STATUS = {429, 500, 502, 503, 504}

    def __init__(self, name: str, config: dict[str, Any], transport: httpx.BaseTransport | None = None):
        super().__init__(name, config)
        self.client = httpx.Client(base_url=config["base_url"], timeout=30, transport=transport)
        self.limiter = RateLimiter(config.get("rate_per_second", 5))
        self.max_retries = config.get("max_retries", 5)
        self._token: tuple[str, float] | None = None

    # ---- auth ----
    def auth_headers(self) -> dict[str, str]:
        auth = self.config.get("auth", {})
        kind = auth.get("type", "none")
        if kind == "api_key":
            return {auth.get("header", "X-API-Key"): self.secret("api_key")}
        if kind == "oauth2_client_credentials":
            if not self._token or self._token[1] < time.time() + 60:  # refresh a minute early
                r = self.client.post(auth["token_url"], data={
                    "grant_type": "client_credentials",
                    "client_id": auth["client_id"],
                    "client_secret": self.secret("client_secret"),
                    **({"scope": auth["scope"]} if "scope" in auth else {}),
                })
                r.raise_for_status()
                body = r.json()
                self._token = (body["access_token"], time.time() + body.get("expires_in", 3600))
            return {"Authorization": f"Bearer {self._token[0]}"}
        return {}

    # ---- requests ----
    def get(self, path: str, params: dict | None = None) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            self.limiter.wait()
            r = self.client.get(path, params=params, headers=self.auth_headers())
            if r.status_code == 401 and self._token and attempt == 0:
                self._token = None  # token revoked early: refresh once
                continue
            if r.status_code not in self.RETRY_STATUS or attempt == self.max_retries:
                r.raise_for_status()
                return r
            retry_after = r.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else min(30, 0.5 * 2**attempt)
            time.sleep(delay * (0.5 + random.random() / 2))
        raise RuntimeError("unreachable")

    # ---- pagination styles ----
    def paginate_cursor(self, path: str, params: dict | None = None, items_key: str = "data",
                        cursor_key: str = "next_cursor", cursor_param: str = "cursor") -> Iterator[list[dict]]:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        while True:
            body = self.get(path, params).json()
            yield body.get(items_key, [])
            cursor = body.get(cursor_key)
            if not cursor:
                return
            params[cursor_param] = cursor

    def paginate_pages(self, path: str, params: dict | None = None, items_key: str = "results",
                       page_param: str = "page", size: int = 100) -> Iterator[list[dict]]:
        page = 1
        while True:
            items = self.get(path, {**(params or {}), page_param: page, "per_page": size}).json().get(items_key, [])
            if not items:
                return
            yield items
            if len(items) < size:
                return
            page += 1

    def paginate_link_header(self, path: str, params: dict | None = None) -> Iterator[list[dict]]:
        url: str | None = path
        while url:
            r = self.get(url, params)
            yield r.json()
            url, params = r.links.get("next", {}).get("url"), None
