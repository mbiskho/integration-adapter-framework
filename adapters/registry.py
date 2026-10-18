from __future__ import annotations

from typing import Callable

from .base import Adapter

_REGISTRY: dict[str, type[Adapter]] = {}


def register(type_name: str) -> Callable[[type[Adapter]], type[Adapter]]:
    def wrap(cls: type[Adapter]) -> type[Adapter]:
        if type_name in _REGISTRY:
            raise ValueError(f"adapter type {type_name!r} registered twice")
        _REGISTRY[type_name] = cls
        return cls
    return wrap


def build(name: str, config: dict) -> Adapter:
    from . import connectors  # noqa: F401  (importing registers the built-in connectors)

    type_name = config.get("type")
    if type_name not in _REGISTRY:
        raise KeyError(f"unknown adapter type {type_name!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[type_name](name, config)
