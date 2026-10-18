"""Example: a REST CRM with OAuth2 client credentials and cursor pagination."""

from __future__ import annotations

from typing import Iterator

from ..base import HttpAdapter, Record
from ..registry import register


@register("rest_crm")
class RestCRM(HttpAdapter):
    def pages(self, since: str | None) -> Iterator[list[dict]]:
        yield from self.paginate_cursor(
            self.config.get("path", "/v2/accounts"),
            params={"updated_after": since, "sort": "updated_at", "limit": 200},
        )

    def to_record(self, item: dict) -> Record:
        return Record(
            source=self.name,
            kind="account",
            external_id=str(item["id"]),
            updated_at=item["updated_at"],
            data={
                "name": item.get("name"),
                "tier": item.get("tier"),
                "owner_email": (item.get("owner") or {}).get("email"),
                "country": item.get("billing_country"),
            },
        )
