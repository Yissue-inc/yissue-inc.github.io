"""Gemini 이미지 생성/편집 어댑터.

참조 사진을 그대로 넣고 "이 사람을 증명사진으로" 지시하는 편집형(in-context)
방식이다. 별도 학습 없이 1~4장으로 동작하므로 대중 상품 원가에 맞는다.

모델 선택 (2026-09 확인):
  gemini-3-pro-image      약 $0.134/장 (1K~2K) — 프롬프트 준수·일관성 최상위
  gemini-3.1-flash-image  약 $0.067/장 (1024)  — 속도·비용 우위
  gemini-2.5-flash-image  2026-10-02 종료 예정 — 신규 사용 금지

단가는 공개 정보 기반이며 계약 전 재확인이 필요하다. 실제 청구 기준은
출력 토큰 수이므로, 이 어댑터는 응답의 usageMetadata 를 그대로 보존한다.
"""
from __future__ import annotations

import base64
import os
import time

import cv2
import numpy as np

from .base import GenerationRequest, GenerationResult

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

#: 참고용 장당 단가(USD). 청구는 토큰 기준이므로 추정치다.
PRICE_USD: dict[str, float] = {
    "gemini-3-pro-image": 0.134,
    "gemini-3.1-flash-image": 0.067,
    "gemini-3.1-flash-lite-image": 0.045,
}

DEPRECATED = {"gemini-2.5-flash-image": "2026-10-02 종료 — 3.1 flash image 로 이전"}


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: str = "gemini-3.1-flash-image",
                 api_key: str | None = None, timeout: float = 120.0,
                 max_reference_px: int = 1280, **_):
        self.model = model
        self.timeout = timeout
        self.max_reference_px = max_reference_px
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if model in DEPRECATED:
            raise ValueError(f"{model}: {DEPRECATED[model]}")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    # --- 내부 ---
    def _encode(self, bgr: np.ndarray) -> dict:
        h, w = bgr.shape[:2]
        if max(h, w) > self.max_reference_px:      # 업로드 비용 절감
            s = self.max_reference_px / max(h, w)
            bgr = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise ValueError("참조 이미지 인코딩 실패")
        return {"inline_data": {"mime_type": "image/jpeg",
                                "data": base64.b64encode(buf).decode()}}

    @staticmethod
    def _first_image(payload: dict) -> np.ndarray | None:
        for cand in payload.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                blob = part.get("inline_data") or part.get("inlineData")
                if blob and blob.get("data"):
                    raw = np.frombuffer(base64.b64decode(blob["data"]), np.uint8)
                    img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
                    if img is not None:
                        return img
        return None

    @staticmethod
    def _refusal(payload: dict) -> str | None:
        """이미지가 없을 때 왜 없는지 알아낸다 — 안전 필터가 가장 흔하다."""
        if fb := payload.get("promptFeedback", {}).get("blockReason"):
            return f"프롬프트 차단: {fb}"
        for cand in payload.get("candidates", []):
            if (fr := cand.get("finishReason")) and fr not in ("STOP", "MAX_TOKENS"):
                return f"생성 중단: {fr}"
            for part in cand.get("content", {}).get("parts", []):
                if txt := part.get("text"):
                    return f"이미지 대신 텍스트 반환: {txt[:200]}"
        return None

    # --- 공개 API ---
    def generate(self, req: GenerationRequest) -> GenerationResult:
        import requests        # 지연 임포트 — mock 경로에서는 필요 없다

        base = GenerationResult(None, self.name, self.model, req.preset, req.seed)
        if not self.configured:
            base.error = "GEMINI_API_KEY 가 설정되지 않았습니다"
            return base
        if not req.references:
            base.error = "참조 이미지 없음"
            return base

        parts = [self._encode(r) for r in req.references]
        parts.append({"text": req.prompt})
        body = {"contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"responseModalities": ["IMAGE"]}}
        if req.seed is not None:
            body["generationConfig"]["seed"] = int(req.seed)

        t0 = time.perf_counter()
        try:
            resp = requests.post(
                f"{API_ROOT}/{self.model}:generateContent",
                params={"key": self.api_key},
                json=body, timeout=self.timeout,
                headers={"Content-Type": "application/json"})
        except Exception as exc:
            base.error = f"요청 실패: {exc}"
            base.latency_ms = (time.perf_counter() - t0) * 1000
            return base

        base.latency_ms = (time.perf_counter() - t0) * 1000
        if resp.status_code != 200:
            base.error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            return base

        payload = resp.json()
        img = self._first_image(payload)
        if img is None:
            base.error = self._refusal(payload) or "응답에 이미지가 없습니다"
            return base

        base.image = img
        base.cost_usd = PRICE_USD.get(self.model, 0.0)
        base.meta = {"usage": payload.get("usageMetadata", {}),
                     "model_version": payload.get("modelVersion", "")}
        return base
