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
    head_mm: float                 # 규격이 정한 기준(skull/hair)으로 잰 머리 길이
    hair_top_mm: float             # 프레임 상단 ~ 머리카락 최상부
    roll_corrected_deg: float
    out_of_frame: float            # 원본 밖을 참조한 픽셀 비율 0..1
    measured_from: str             # skull | hair
    crown_source: str

    #: 머리카락이 프레임 위로 잘리지 않기 위한 최소 여백(mm)
    MIN_HAIR_MARGIN_MM = 1.5

    @property
    def top_margin_mm(self) -> float:
        """하위 호환용 별칭. 머리카락 최상부까지의 여백을 뜻한다."""
        return self.hair_top_mm

    @property
    def head_in_range(self) -> bool:
        return self.spec.head_min_mm <= self.head_mm <= self.spec.head_max_mm

    @property
    def hair_fits(self) -> bool:
        return self.hair_top_mm >= self.MIN_HAIR_MARGIN_MM

    def issues(self) -> list[str]:
        out = []
        if not self.head_in_range:
            out.append(
                f"머리 길이 {self.head_mm:.1f}mm — 규격 "
                f"{self.spec.head_min_mm:g}~{self.spec.head_max_mm:g}mm 벗어남")
        if not self.hair_fits:
            out.append(
                f"머리카락 위 여백 {self.hair_top_mm:.1f}mm — "
                f"{self.MIN_HAIR_MARGIN_MM:g}mm 미만이라 머리가 잘릴 수 있음")
        if self.out_of_frame > 0.005:
            out.append(f"프레임 밖 참조 {self.out_of_frame * 100:.1f}% — 원본 여백 부족")
        if self.crown_source == "landmark":
            out.append("머리카락 최상부를 매트로 잡지 못해 두개골 추정값으로 대체함 — "
                       "머리숱이 많으면 위쪽이 잘릴 수 있음")
        elif self.crown_source == "none":
            out.append("머리 최상부를 특정하지 못함 — 크롭 신뢰 불가")
        return out


def frame_to_spec(bgr: np.ndarray, geo: FaceGeometry, spec: PhotoSpec,
                  level_eyes: bool = True) -> FramingResult:
    if geo.crown is None or geo.chin is None:
        raise ValueError("crown/chin 좌표가 필요합니다 — FaceAnalyzer.analyze 를 먼저 호출하세요")

    out_w, out_h = spec.size_px
    ppm = spec.px_per_mm

    # 규격이 정한 기준점으로 스케일을 잡는다. 여권·증명사진은 머리카락을
    # 제외한 머리 최상부 기준이므로, 머리카락 최상부로 재면 머리숱이 많은
    # 사람의 머리가 규정보다 작게 잡혀 반려된다.
    anchor_top = geo.skull_top if spec.head_measure == "skull" else geo.crown
    if anchor_top is None:
        anchor_top = geo.crown
        measured_from = "hair"
    else:
        measured_from = spec.head_measure

    src_head = float(math.dist(anchor_top, geo.chin))
    if src_head < 1e-6:
        raise ValueError("머리 길이가 0입니다")

    scale = (spec.head_target_mm * ppm) / src_head
    theta = math.radians(-geo.roll_deg) if level_eyes else 0.0

    cos_t, sin_t = math.cos(theta) * scale, math.sin(theta) * scale
    # 원본의 머리 중점 -> 목표 머리 중점
    src_anchor = ((anchor_top[0] + geo.chin[0]) / 2.0,
                  (anchor_top[1] + geo.chin[1]) / 2.0)
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

    top_y = _apply(m, anchor_top)[1]
    chin_y = _apply(m, geo.chin)[1]
    hair_y = _apply(m, geo.crown)[1]
    return FramingResult(
        image=out, spec=spec,
        head_mm=abs(chin_y - top_y) / ppm,
        hair_top_mm=hair_y / ppm,
        roll_corrected_deg=geo.roll_deg if level_eyes else 0.0,
        out_of_frame=out_of_frame,
        measured_from=measured_from,
        crown_source=geo.crown_source,
    )


def _apply(m: np.ndarray, p) -> tuple[float, float]:
    return (m[0, 0] * p[0] + m[0, 1] * p[1] + m[0, 2],
            m[1, 0] * p[0] + m[1, 1] * p[1] + m[1, 2])
