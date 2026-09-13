"""S3 — 생성 프로바이더 레지스트리."""
from __future__ import annotations

from .base import GenerationRequest, GenerationResult, Provider
from .gemini import GeminiProvider
from .mock import MockProvider

_REGISTRY: dict[str, type[Provider]] = {
    "mock": MockProvider,
    "gemini": GeminiProvider,
}


def get_provider(name: str, **kwargs) -> Provider:
    try:
        cls = _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"unknown provider {name!r}; available: {', '.join(_REGISTRY)}") from None
    return cls(**kwargs)


__all__ = ["GenerationRequest", "GenerationResult", "Provider",
           "GeminiProvider", "MockProvider", "get_provider"]
