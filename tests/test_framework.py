import httpx
import pytest

from adapters.base import HttpAdapter, Record
from adapters.checkpoint import FileCheckpoints
from adapters.run import sync


class Demo(HttpAdapter):
    def pages(self, since):
        yield from self.paginate_cursor("/items", params={"updated_after": since})

    def to_record(self, item):
        return Record("demo", "item", str(item["id"]), item["updated_at"], {})


def make(handler, **cfg):
    return Demo("demo", {"base_url": "https://api.test", "rate_per_second": 0, "max_retries": 3, **cfg},
                transport=httpx.MockTransport(handler))


def test_cursor_pagination_follows_until_empty_cursor():
    pages = {None: ([1, 2], "c1"), "c1": ([3], None)}

    def handler(req):
        items, nxt = pages[req.url.params.get("cursor")]
        return httpx.Response(200, json={"data": [{"id": i, "updated_at": f"2026-01-0{i}"} for i in items],
                                         "next_cursor": nxt})

    assert [len(p) for p in make(handler).pages(None)] == [2, 1]


def test_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"data": [], "next_cursor": None})

    list(make(handler).pages(None))
    assert calls["n"] == 3


def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(httpx.HTTPStatusError):
        list(make(lambda req: httpx.Response(503)).pages(None))


def test_checkpoint_advances_per_page_and_resumes(tmp_path):
    seen_since = []

    def handler(req):
        seen_since.append(req.url.params.get("updated_after"))
        return httpx.Response(200, json={"data": [{"id": 1, "updated_at": "2026-03-01"},
                                                  {"id": 2, "updated_at": "2026-03-05"}], "next_cursor": None})

    cps = FileCheckpoints(tmp_path / "cp.json")
    written = []
    assert sync(make(handler), cps, written.extend) == 2
    assert cps.get("demo") == "2026-03-05"
    sync(make(handler), FileCheckpoints(tmp_path / "cp.json"), written.extend)
    assert seen_since == [None, "2026-03-05"]  # second run resumed from the saved checkpoint
