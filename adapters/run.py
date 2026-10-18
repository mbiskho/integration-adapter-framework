"""Sync every adapter in a customer config, resuming from checkpoints.

    python -m adapters.run config/acme.yaml [--full] [--out records.jsonl]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Callable, Iterable

import yaml

from .base import Adapter, Record
from .checkpoint import FileCheckpoints
from .registry import build


def sync(adapter: Adapter, checkpoints: FileCheckpoints, sink: Callable[[Iterable[Record]], None],
         full: bool = False) -> int:
    since = None if full else checkpoints.get(adapter.name)
    total = 0
    for page in adapter.pages(since):
        records = [adapter.to_record(item) for item in page]
        if not records:
            continue
        sink(records)  # write the page first...
        total += len(records)
        newest = max(r.updated_at for r in records)
        if since is None or newest > since:
            since = newest
            checkpoints.set(adapter.name, since)  # ...then advance the checkpoint
    return total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--out", default="records.jsonl")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(open(a.config))
    checkpoints = FileCheckpoints(cfg.get("checkpoint_file", ".checkpoints.json"))

    with open(a.out, "a") as fh:
        def sink(records: Iterable[Record]) -> None:
            for r in records:
                fh.write(json.dumps(asdict(r)) + "\n")
            fh.flush()

        for name, conf in cfg["adapters"].items():
            n = sync(build(name, conf), checkpoints, sink, a.full)
            print(f"{name}: {n} records (checkpoint {checkpoints.get(name)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
