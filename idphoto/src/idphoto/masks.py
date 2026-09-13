"""얼굴 영역 마스크 — 리터칭이 건드릴 곳과 건드리면 안 될 곳을 가른다."""
from __future__ import annotations

import cv2
import numpy as np

from .geometry import FaceGeometry

# MediaPipe FaceMesh 표준 인덱스
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397,
             365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58,
             132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
EYE_L = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
EYE_R = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
BROW_L = [276, 283, 282, 295, 285, 300, 293, 334, 296, 336]
BROW_R = [46, 53, 52, 65, 55, 70, 63, 105, 66, 107]
LIPS = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 308, 324, 318,
        402, 317, 14, 87, 178, 88, 95]


def _poly(shape, pts, idx, grow: float = 1.0) -> np.ndarray:
    m = np.zeros(shape[:2], np.uint8)
    if not pts or max(idx) >= len(pts):
        return m
    p = np.array([pts[i] for i in idx], dtype=np.float32)
    if grow != 1.0:
        c = p.mean(axis=0)
        p = c + (p - c) * grow
    cv2.fillConvexPoly(m, cv2.convexHull(p.astype(np.int32)), 255)
    return m


def skin_mask(shape, geo: FaceGeometry, feather: int = 0) -> np.ndarray:
    """피부 마스크 (0..255). 눈·눈썹·입술은 제외한다.

    랜드마크가 없으면 얼굴 박스 안 타원으로 폴백한다 — 정밀도는 떨어지지만
    리터칭 강도가 낮으면 실사용상 큰 차이가 없다.
    """
    h, w = shape[:2]
    pts = geo.landmarks

    if pts and len(pts) > max(FACE_OVAL):
        m = _poly(shape, pts, FACE_OVAL)
        for idx, grow in ((EYE_L, 1.45), (EYE_R, 1.45),
                          (BROW_L, 1.35), (BROW_R, 1.35), (LIPS, 1.15)):
            m = cv2.subtract(m, _poly(shape, pts, idx, grow))
    else:
        m = np.zeros((h, w), np.uint8)
        x, y, bw, bh = geo.box
        cv2.ellipse(m, (int(x + bw / 2), int(y + bh / 2)),
                    (int(bw * 0.42), int(bh * 0.48)), 0, 0, 360, 255, -1)

    if feather <= 0:
        feather = max(3, int(min(h, w) * 0.012)) | 1
    return cv2.GaussianBlur(m, (feather | 1, feather | 1), 0)


def eye_mask(shape, geo: FaceGeometry) -> np.ndarray:
    """눈 영역 (0..255). 공막 채도 억제와 미세 샤프닝에 쓴다."""
    pts = geo.landmarks
    if pts and len(pts) > max(EYE_L):
        m = cv2.add(_poly(shape, pts, EYE_L, 1.12), _poly(shape, pts, EYE_R, 1.12))
    else:
        m = np.zeros(shape[:2], np.uint8)
        r = max(3, int(geo.eye_distance * 0.28))
        for e in (geo.right_eye, geo.left_eye):
            cv2.circle(m, (int(e[0]), int(e[1])), r, 255, -1)
    k = max(3, int(min(shape[:2]) * 0.006)) | 1
    return cv2.GaussianBlur(m, (k, k), 0)
