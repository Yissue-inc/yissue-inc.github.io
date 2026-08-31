"""피부 측정 어댑터.

⚠️ 설계 원칙: 측정 벤더는 반드시 이 인터페이스 뒤에 둡니다.
   벤더 교체(Perfect Corp ↔ Haut.AI ↔ 룰루랩 ↔ 자체 모델)가 반나절 작업이 되도록.

지표는 모두 "고민의 정도" 0.0~1.0 으로 정규화합니다 (높을수록 그 고민이 큼).
톤(tone)만 예외적으로 '밝기 관련 관심도'로 해석합니다.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field

METRICS = [
    "dryness",      # 건조
    "redness",      # 홍조
    "oiliness",     # 유분/번들거림
    "pore",         # 모공
    "texture",      # 결/각질
    "wrinkle",      # 주름
    "pigmentation", # 색소/기미
    "dark_circle",  # 다크서클
    "acne",         # 트러블
    "tone",         # 톤 균일도 관심
]


@dataclass
class Measurement:
    metrics: dict[str, float]
    quality: float = 1.0          # 촬영 품질 0~1. 낮으면 학습에서 제외
    analyzer: str = "mock"
    analyzer_version: str = "0.1"
    image_ref: str | None = None  # 기본은 None — 원본 이미지 미저장이 기본 정책

    def top_concerns(self, k: int = 3) -> list[tuple[str, float]]:
        return sorted(self.metrics.items(), key=lambda kv: -kv[1])[:k]


class SkinAnalyzer:
    """모든 측정 백엔드가 구현해야 하는 인터페이스."""

    name = "base"

    def analyze(self, frames: dict[str, object] | None = None, *, hint: str | None = None) -> Measurement:
        raise NotImplementedError


class MockSkinAnalyzer(SkinAnalyzer):
    """하드웨어 없이 전체 플로우를 돌리기 위한 가짜 측정기.

    `hint`(고객 페르소나 문자열)로 시드를 고정해, 같은 사람이면 같은 값이 나오게 합니다.
    """

    name = "mock"

    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)

    def analyze(self, frames=None, *, hint: str | None = None) -> Measurement:
        rng = self._rng
        if hint:
            h = int(hashlib.sha256(hint.encode()).hexdigest()[:8], 16)
            rng = random.Random(h)
        metrics = {m: round(min(1.0, max(0.0, rng.betavariate(2, 4))), 3) for m in METRICS}
        return Measurement(metrics=metrics, quality=round(rng.uniform(0.8, 1.0), 3), analyzer=self.name)


class LocalHeuristicAnalyzer(SkinAnalyzer):
    """카메라 + OpenCV 만으로 계산하는 '정직한' 로컬 폴백.

    네트워크가 끊겨도 세션이 끝까지 돌아야 하므로 반드시 하나는 있어야 합니다.
    실제 구현 스케치 (opencv-python, mediapipe 필요):

        import cv2, numpy as np, mediapipe as mp
        # 1) MediaPipe Face Mesh 로 ROI(이마/양볼/코/턱) 마스크 생성
        # 2) 화이트밸런스: 프레임 모서리 컬러체커 패치로 게인 보정
        # 3) 지표 산출
        lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB).astype(float)
        L, a, b = lab[...,0]*100/255, lab[...,1]-128, lab[...,2]-128
        ita = np.degrees(np.arctan2(L.mean()-50, b.mean()))       # 피부톤
        redness = float(np.clip(a.mean()/20, 0, 1))               # 홍조
        spec = (frame_normal.astype(float) - frame_crosspol.astype(float))
        oiliness = float((spec.mean(axis=2) > 25).mean())         # 정반사 하이라이트 비율
        texture = float(np.clip(cv2.Laplacian(gray_parpol, cv2.CV_64F).var()/800, 0, 1))
        # 모공: LoG 블롭 검출 개수/면적,  주름: 방향성 Gabor 응답 등
    """

    name = "local_heuristic"

    def analyze(self, frames=None, *, hint=None) -> Measurement:
        raise NotImplementedError(
            "W7~W8 과제: 촬영 부스 구축 후 구현. 그 전까지는 MockSkinAnalyzer 를 사용하세요."
        )


class ApiSkinAnalyzer(SkinAnalyzer):
    """외부 피부 분석 API 어댑터 (Perfect Corp / Haut.AI / Revieve / 룰루랩 등).

    구현 시 체크리스트:
      - 이미지 국외 이전이 발생하는지 확인 → 발생하면 국외이전 별도 동의 필요
      - 응답 지표명을 반드시 METRICS 로 매핑(정규화)해서 내부 스키마를 오염시키지 말 것
      - 타임아웃 3초 + 실패 시 LocalHeuristicAnalyzer 로 폴백
      - analyzer_version 을 로그에 남길 것 (벤더가 모델을 바꾸면 지표가 튑니다)
    """

    name = "vendor_api"

    def __init__(self, endpoint: str, api_key: str, mapping: dict[str, str] | None = None,
                 fallback: SkinAnalyzer | None = None, timeout: float = 3.0):
        self.endpoint, self.api_key = endpoint, api_key
        self.mapping = mapping or {}
        self.fallback = fallback or MockSkinAnalyzer()
        self.timeout = timeout

    def analyze(self, frames=None, *, hint=None) -> Measurement:
        raise NotImplementedError(
            "벤더 계약 후 구현. 지금은 fallback 을 직접 호출하세요: analyzer.fallback.analyze(...)"
        )
