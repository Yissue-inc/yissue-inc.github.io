"""생성 프로바이더 인터페이스."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from ..prompts import Preset


@dataclass
class GenerationRequest:
    references: list[np.ndarray]        # 업로드 원본 (BGR)
    preset: Preset
    prompt: str
    seed: int | None = None
    width: int = 1024
    height: int = 1024


@dataclass
class GenerationResult:
    image: np.ndarray | None           # BGR, 실패 시 None
    provider: str
    model: str
    preset: Preset
    seed: int | None = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    error: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.image is not None and self.error is None


class Provider(Protocol):
    name: str
    model: str

    def generate(self, req: GenerationRequest) -> GenerationResult: ...
