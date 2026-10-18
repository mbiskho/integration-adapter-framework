from __future__ import annotations

import json
import os
from pathlib import Path


class FileCheckpoints:
    """adapter name → last updated_at seen. Written atomically so a crash can't corrupt it."""

    def __init__(self, path: str | Path = ".checkpoints.json"):
        self.path = Path(path)
        self.state: dict[str, str] = json.loads(self.path.read_text()) if self.path.exists() else {}

    def get(self, name: str) -> str | None:
        return self.state.get(name)

    def set(self, name: str, cursor: str) -> None:
        self.state[name] = cursor
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2))
        os.replace(tmp, self.path)
