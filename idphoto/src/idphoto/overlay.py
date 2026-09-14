"""정렬 비교 — 골격이 바뀌었는지 사람이 확인하기 위한 도구.

품질 기준 §5 가 요구하는 검사다. 유사도로도 계측으로도 6~12% 수준의 미세한
얼굴 깎기는 확실히 잡히지 않으므로, 그 구간은 사람이 봐야 한다. 다만 두
사진을 그냥 나란히 놓고 보면 조명·표정·크기 차이 때문에 판단이 흐려진다.

그래서 **양안 중심을 정확히 맞춘 뒤** 윤곽선만 겹쳐 보여준다. 눈 위치와
양안 거리가 동일해지면 남는 차이는 얼굴 형태뿐이다.
"""
from __future__ import annotations

import cv2
import numpy as np

from .geometry import FaceGeometry
from .regions import FACE_OVAL, IRIS_L_CENTER, IRIS_R_CENTER

REF_COLOR = (90, 170, 80)      # 초록 — 원본
CAND_COLOR = (60, 90, 230)     # 빨강 — 후보


def _irises(geo: FaceGeometry) -> tuple[np.ndarray, np.ndarray] | None:
    pts = geo.landmarks
    if not pts or len(pts) <= IRIS_L_CENTER:
        return None
    return (np.array(pts[IRIS_R_CENTER], float),
            np.array(pts[IRIS_L_CENTER], float))


def align_to(src: np.ndarray, src_geo: FaceGeometry,
             dst_geo: FaceGeometry, size: tuple[int, int]
             ) -> tuple[np.ndarray, np.ndarray] | None:
    """src 를 dst 의 눈 위치에 맞춘다. (정렬된 이미지, 2x3 행렬) 반환.

    양안 두 점으로 닮음변환을 만든다 — 회전·축척·평행이동만 쓰고 형태는
    건드리지 않으므로, 정렬 후에 남는 윤곽 차이는 진짜 형태 차이다.
    """
    a, b = _irises(src_geo) or (None, None)
    c, d = _irises(dst_geo) or (None, None)
    if a is None or c is None:
        return None

    v1, v2 = b - a, d - c
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return None

    scale = n2 / n1
    ang = np.arctan2(v2[1], v2[0]) - np.arctan2(v1[1], v1[0])
    cos_a, sin_a = np.cos(ang) * scale, np.sin(ang) * scale
    m = np.array([[cos_a, -sin_a, 0.0], [sin_a, cos_a, 0.0]])
    mid_src, mid_dst = (a + b) / 2, (c + d) / 2
    m[0, 2] = mid_dst[0] - (m[0, 0] * mid_src[0] + m[0, 1] * mid_src[1])
    m[1, 2] = mid_dst[1] - (m[1, 0] * mid_src[0] + m[1, 1] * mid_src[1])

    warped = cv2.warpAffine(src, m, size, flags=cv2.INTER_LANCZOS4,
                            borderMode=cv2.BORDER_REPLICATE)
    return warped, m


def _oval(geo: FaceGeometry, m: np.ndarray | None = None) -> np.ndarray | None:
    pts = geo.landmarks
    if not pts or len(pts) <= max(FACE_OVAL):
        return None
    p = np.array([pts[i] for i in FACE_OVAL], np.float32)
    if m is not None:
        p = (p @ m[:, :2].T) + m[:, 2]
    return p.astype(np.int32)


def compare(ref_img: np.ndarray, ref_geo: FaceGeometry,
            cand_img: np.ndarray, cand_geo: FaceGeometry) -> np.ndarray:
    """3단 비교 이미지. 원본 | 후보 | 윤곽 겹침.

    3번 패널이 핵심이다. 후보 위에 원본 윤곽(초록)과 후보 윤곽(빨강)을
    함께 그린다. 턱선에서 초록이 빨강 바깥에 있으면 얼굴이 깎인 것이다.
    """
    h, w = cand_img.shape[:2]
    aligned = align_to(ref_img, ref_geo, cand_geo, (w, h))
    if aligned is None:
        return np.hstack([cv2.resize(ref_img, (w, h)), cand_img])
    ref_warp, m = aligned

    panel = cand_img.copy()
    ref_oval = _oval(ref_geo, m)
    cand_oval = _oval(cand_geo)
    if ref_oval is not None:
        cv2.polylines(panel, [ref_oval], True, REF_COLOR, max(2, w // 260),
                      cv2.LINE_AA)
    if cand_oval is not None:
        cv2.polylines(panel, [cand_oval], True, CAND_COLOR, max(2, w // 260),
                      cv2.LINE_AA)

    label_h = max(26, h // 18)
    out = []
    for img, text in ((ref_warp, "REFERENCE (aligned)"),
                      (cand_img, "CANDIDATE"),
                      (panel, "OVERLAY  green=ref  red=cand")):
        tile = np.vstack([img, np.full((label_h, w, 3), 250, np.uint8)])
        cv2.putText(tile, text, (8, h + int(label_h * 0.72)),
                    cv2.FONT_HERSHEY_SIMPLEX, max(0.4, w / 780),
                    (40, 40, 40), 1, cv2.LINE_AA)
        out.append(tile)

    gap = np.full((out[0].shape[0], 10, 3), 250, np.uint8)
    strip = out[0]
    for t in out[1:]:
        strip = np.hstack([strip, gap, t])
    return strip
