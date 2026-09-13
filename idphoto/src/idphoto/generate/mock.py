"""API 키 없이 전체 파이프라인을 돌리기 위한 스탠드인 프로바이더.

**의상을 갈아입히지는 못한다.** 생성 모델이 하는 일 중 이 어댑터가 대신할 수
있는 것은 배경 교체와 조명 근사뿐이다. 그러나 그것만으로도 하류 단계 전부
(규격 크롭 · 리터칭 · 유사도 게이트 · 랭킹 · 메타데이터)를 실제 이미지로
검증할 수 있고, 키가 생기면 이 어댑터만 갈아끼우면 된다.

프리셋마다 배경·조명·크롭을 달리하고 시드로 미세 변주를 주므로, MMR 다양성
선발과 QA 분포도 의미 있게 동작한다.
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from ..background import BACKDROPS, alpha_matte, composite, key_light
from ..detect import FaceAnalyzer
from .base import GenerationRequest, GenerationResult


class MockProvider:
    name = "mock"
    model = "composite-baseline"

    def __init__(self, analyzer: FaceAnalyzer | None = None, **_):
        self._analyzer = analyzer or FaceAnalyzer()

    def generate(self, req: GenerationRequest) -> GenerationResult:
        t0 = time.perf_counter()
        rng = np.random.default_rng(req.seed)

        src = req.references[rng.integers(0, len(req.references))] \
            if req.references else None
        if src is None:
            return GenerationResult(None, self.name, self.model, req.preset,
                                    req.seed, error="참조 이미지 없음")

        faces = self._analyzer.analyze(src)
        if not faces:
            return GenerationResult(None, self.name, self.model, req.preset,
                                    req.seed, error="참조 이미지에서 얼굴 검출 실패")
        geo = faces[0]

        alpha, method = alpha_matte(src, geo)
        backdrop = req.preset.backdrop if req.preset.backdrop in BACKDROPS else "light_gray"
        out = composite(src, alpha, backdrop)

        # 프리셋·시드에 따른 변주 — 조명 각도와 세기를 흔든다
        angle = 45.0 + float(rng.normal(0, 12))
        amount = 0.30 + float(rng.uniform(-0.08, 0.12))
        out = key_light(out, alpha, amount=amount, angle_deg=angle)

        return GenerationResult(
            image=out, provider=self.name, model=self.model, preset=req.preset,
            seed=req.seed, latency_ms=(time.perf_counter() - t0) * 1000,
            cost_usd=0.0,
            meta={"matte": method, "key_angle": round(angle, 1),
                  "key_amount": round(amount, 3),
                  "note": "의상 변경 없음 — 배경·조명만 합성한 스탠드인"},
        )
