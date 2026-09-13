"""S8 — 증명사진 규격 크롭.

정수리·턱끝·눈선으로부터 닮음변환(회전+등방 스케일+평행이동)을 만들어
규격 프레임에 얼굴을 앉힌다. 크롭 후에는 반드시 재검증한다 — 변환이
프레임 밖을 참조하면 가장자리가 비기 때문이다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .geometry import FaceGeometry
from .specs import PhotoSpec


@dataclass
class FramingResult:
    image: np.ndarray
    spec: PhotoSpec
    head_mm: float                 # 결과물에서 실측한 머리 길이
    top_margin_mm: float
    roll_corrected_deg: float
    out_of_frame: float            # 원본 밖을 참조한 픽셀 비율 0..1
    crown_source: str

    @property
    def head_in_range(self) -> bool:
        return self.spec.head_min_mm <= self.head_mm <= self.spec.head_max_mm

    def issues(self) -> list[str]:
        out = []
        if not self.head_in_range:
            out.append(
                f"머리 길이 {self.head_mm:.1f}mm — 규격 "
                f"{self.spec.head_min_mm:g}~{self.spec.head_max_mm:g}mm 벗어남")
        if self.out_of_frame > 0.005:
            out.append(f"프레임 밖 참조 {self.out_of_frame * 100:.1f}% — 원본 여백 부족")
        if self.crown_source == "landmark":
            out.append("정수리를 랜드마크로 외삽함 — 머리숱에 따라 오차 가능")
        elif self.crown_source == "none":
            out.append("정수리를 특정하지 못함 — 크롭 신뢰 불가")
        return out


def frame_to_spec(bgr: np.ndarray, geo: FaceGeometry, spec: PhotoSpec,
                  level_eyes: bool = True) -> FramingResult:
    if geo.crown is None or geo.chin is None:
        raise ValueError("crown/chin 좌표가 필요합니다 — FaceAnalyzer.analyze 를 먼저 호출하세요")

    out_w, out_h = spec.size_px
    ppm = spec.px_per_mm

    src_head = float(math.dist(geo.crown, geo.chin))
    if src_head < 1e-6:
        raise ValueError("머리 길이가 0입니다")

    scale = (spec.head_target_mm * ppm) / src_head
    theta = math.radians(-geo.roll_deg) if level_eyes else 0.0

    cos_t, sin_t = math.cos(theta) * scale, math.sin(theta) * scale
    # 원본의 머리 중점 -> 목표 머리 중점
    src_anchor = ((geo.crown[0] + geo.chin[0]) / 2.0,
                  (geo.crown[1] + geo.chin[1]) / 2.0)
    dst_anchor = (out_w / 2.0,
                  spec.top_margin_mm * ppm + (spec.head_target_mm * ppm) / 2.0)

    m = np.array([[cos_t, -sin_t, 0.0],
                  [sin_t,  cos_t, 0.0]], dtype=np.float64)
    m[0, 2] = dst_anchor[0] - (m[0, 0] * src_anchor[0] + m[0, 1] * src_anchor[1])
    m[1, 2] = dst_anchor[1] - (m[1, 0] * src_anchor[0] + m[1, 1] * src_anchor[1])

    out = cv2.warpAffine(bgr, m, (out_w, out_h), flags=cv2.INTER_LANCZOS4,
                         borderMode=cv2.BORDER_REPLICATE)

    coverage = cv2.warpAffine(
        np.full(bgr.shape[:2], 255, np.uint8), m, (out_w, out_h),
        flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    out_of_frame = float((coverage == 0).mean())

    crown_y, chin_y = _apply(m, geo.crown)[1], _apply(m, geo.chin)[1]
    return FramingResult(
        image=out, spec=spec,
        head_mm=abs(chin_y - crown_y) / ppm,
        top_margin_mm=crown_y / ppm,
        roll_corrected_deg=geo.roll_deg if level_eyes else 0.0,
        out_of_frame=out_of_frame,
        crown_source=geo.crown_source,
    )


def _apply(m: np.ndarray, p) -> tuple[float, float]:
    return (m[0, 0] * p[0] + m[0, 1] * p[1] + m[0, 2],
            m[1, 0] * p[0] + m[1, 1] * p[1] + m[1, 2])
