"""부위별 마스크 — 프로 리터칭은 전역 처리가 아니라 부위별 처리다.

전문 리터처는 얼굴 전체에 같은 보정을 걸지 않는다. 다크서클은 밝히고,
턱선은 어둡게 하고, 공막의 붉은기만 빼고, 치아의 노란기만 뺀다.
그 '어디에'를 결정하는 것이 이 모듈이다.

MediaPipe 478점 랜드마크가 있으면 정확한 폴리곤을, 없으면 기하 근사를 쓴다.
다크서클·팔자주름처럼 랜드마크 인덱스가 불확실한 부위는 신뢰할 수 있는
앵커(눈 윤곽, 입꼬리, 코끝)에서 기하적으로 만든다 — 인덱스를 추측하는 것보다
견고하다.
"""
from __future__ import annotations

import cv2
import numpy as np

from .geometry import FaceGeometry

# --- 신뢰 가능한 MediaPipe FaceMesh 인덱스 ---
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397,
             365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58,
             132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
EYE_L = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
EYE_R = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
IRIS_R = [469, 470, 471, 472]
IRIS_L = [474, 475, 476, 477]
IRIS_R_CENTER, IRIS_L_CENTER = 468, 473
BROW_L = [276, 283, 282, 295, 285, 300, 293, 334, 296, 336]
BROW_R = [46, 53, 52, 65, 55, 70, 63, 105, 66, 107]
LIPS_OUTER = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270,
              269, 267, 0, 37, 39, 40, 185]
LIPS_INNER = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310,
              311, 312, 13, 82, 81, 80, 191]
CHIN, FOREHEAD_TOP, NOSE_TIP, NOSE_BRIDGE = 152, 10, 1, 168
MOUTH_CORNER_R, MOUTH_CORNER_L = 61, 291


def _has(pts, idx) -> bool:
    return bool(pts) and len(pts) > max(idx)


def _fill(shape, points, grow: float = 1.0, convex: bool = True) -> np.ndarray:
    m = np.zeros(shape[:2], np.uint8)
    p = np.asarray(points, np.float32)
    if len(p) < 3:
        return m
    if grow != 1.0:
        p = p.mean(axis=0) + (p - p.mean(axis=0)) * grow
    p = p.astype(np.int32)
    cv2.fillConvexPoly(m, cv2.convexHull(p), 255) if convex \
        else cv2.fillPoly(m, [p], 255)
    return m


def _feather(m: np.ndarray, frac: float = 0.012) -> np.ndarray:
    k = max(3, int(min(m.shape[:2]) * frac)) | 1
    return cv2.GaussianBlur(m, (k, k), 0)


def _poly(shape, pts, idx, grow: float = 1.0) -> np.ndarray:
    if not _has(pts, idx):
        return np.zeros(shape[:2], np.uint8)
    return _fill(shape, [pts[i] for i in idx], grow)


# ---------- 기본 부위 ----------

def face_oval(shape, geo: FaceGeometry) -> np.ndarray:
    if _has(geo.landmarks, FACE_OVAL):
        return _poly(shape, geo.landmarks, FACE_OVAL)
    m = np.zeros(shape[:2], np.uint8)
    x, y, w, h = geo.box
    cv2.ellipse(m, (int(x + w / 2), int(y + h / 2)),
                (int(w * 0.45), int(h * 0.52)), 0, 0, 360, 255, -1)
    return m


def skin(shape, geo: FaceGeometry, feather: float = 0.012) -> np.ndarray:
    """피부. 눈·눈썹·입술은 뺀다 — 이곳들을 매끄럽게 하면 얼굴이 뭉개진다."""
    m = face_oval(shape, geo)
    pts = geo.landmarks
    if _has(pts, FACE_OVAL):
        for idx, grow in ((EYE_L, 1.5), (EYE_R, 1.5), (BROW_L, 1.4),
                          (BROW_R, 1.4), (LIPS_OUTER, 1.12)):
            m = cv2.subtract(m, _poly(shape, pts, idx, grow))
    return _feather(m, feather)


def eyes(shape, geo: FaceGeometry) -> np.ndarray:
    pts = geo.landmarks
    if _has(pts, EYE_L):
        m = cv2.add(_poly(shape, pts, EYE_L), _poly(shape, pts, EYE_R))
    else:
        m = np.zeros(shape[:2], np.uint8)
        r = max(3, int(geo.eye_distance * 0.26))
        for e in (geo.right_eye, geo.left_eye):
            cv2.circle(m, (int(e[0]), int(e[1])), r, 255, -1)
    return _feather(m, 0.005)


def iris(shape, geo: FaceGeometry) -> np.ndarray:
    """홍채. 또렷하게 만들 대상 — 공막과 반드시 구분해야 한다."""
    pts = geo.landmarks
    if _has(pts, IRIS_L):
        m = cv2.add(_poly(shape, pts, IRIS_R), _poly(shape, pts, IRIS_L))
    else:
        m = np.zeros(shape[:2], np.uint8)
        r = max(2, int(geo.eye_distance * 0.11))
        for e in (geo.right_eye, geo.left_eye):
            cv2.circle(m, (int(e[0]), int(e[1])), r, 255, -1)
    return _feather(m, 0.004)


def sclera(shape, geo: FaceGeometry) -> np.ndarray:
    """흰자. 붉은기만 뺀다. 하얗게 태우면 즉시 가짜 티가 난다."""
    e = eyes(shape, geo).astype(np.int16)
    i = cv2.dilate(iris(shape, geo), np.ones((3, 3), np.uint8)).astype(np.int16)
    return np.clip(e - i, 0, 255).astype(np.uint8)


def lips(shape, geo: FaceGeometry) -> np.ndarray:
    return _feather(_poly(shape, geo.landmarks, LIPS_OUTER), 0.006)


def teeth(shape, geo: FaceGeometry) -> np.ndarray:
    """입 안쪽. 입을 다물고 있으면 거의 비어 있다 — 그 경우 보정도 없다."""
    return _feather(_poly(shape, geo.landmarks, LIPS_INNER), 0.004)


def brows(shape, geo: FaceGeometry) -> np.ndarray:
    pts = geo.landmarks
    if not _has(pts, BROW_L):
        return np.zeros(shape[:2], np.uint8)
    return _feather(cv2.add(_poly(shape, pts, BROW_R), _poly(shape, pts, BROW_L)), 0.006)


# ---------- 기하 유도 부위 ----------

def under_eye(shape, geo: FaceGeometry) -> np.ndarray:
    """다크서클. 눈 윤곽을 아래로 밀어 만든 띠.

    랜드마크 인덱스를 추측하는 대신 눈 폴리곤에서 유도한다. 눈 자체와
    겹치는 부분은 빼서, 밝히기가 눈으로 번지지 않게 한다.
    """
    pts = geo.landmarks
    if not _has(pts, EYE_L):
        return np.zeros(shape[:2], np.uint8)

    band = np.zeros(shape[:2], np.uint8)
    for idx in (EYE_R, EYE_L):
        p = np.array([pts[i] for i in idx], np.float32)
        h = p[:, 1].max() - p[:, 1].min()
        if h < 2:
            continue
        shifted = p + np.array([0.0, h * 0.85], np.float32)
        widened = shifted.mean(axis=0) + (shifted - shifted.mean(axis=0)) * \
            np.array([1.05, 1.7], np.float32)
        band = cv2.add(band, _fill(shape, widened))

    band = cv2.subtract(band, cv2.dilate(eyes(shape, geo),
                                         np.ones((5, 5), np.uint8)))
    return _feather(band, 0.022)


def nasolabial(shape, geo: FaceGeometry) -> np.ndarray:
    """팔자주름. 콧방울에서 입꼬리로 내려가는 짧은 띠.

    코끝과 입꼬리라는 확실한 앵커 사이에 만든다. 지우는 것이 아니라
    아주 약하게 밝혀 그림자만 누그러뜨리는 용도다 — 완전히 지우면
    나이가 지워져 본인이 아니게 된다.
    """
    pts = geo.landmarks
    if not _has(pts, [NOSE_TIP, MOUTH_CORNER_L]):
        return np.zeros(shape[:2], np.uint8)

    nose = np.array(pts[NOSE_TIP], np.float32)
    m = np.zeros(shape[:2], np.uint8)
    for corner_idx in (MOUTH_CORNER_R, MOUTH_CORNER_L):
        corner = np.array(pts[corner_idx], np.float32)
        mid = (nose + corner) / 2
        span = float(np.linalg.norm(corner - nose))
        if span < 4:
            continue
        ang = float(np.degrees(np.arctan2(*(corner - nose)[::-1])))
        layer = np.zeros(shape[:2], np.uint8)
        cv2.ellipse(layer, (int(mid[0]), int(mid[1])),
                    (int(span * 0.55), max(2, int(span * 0.16))),
                    ang, 0, 360, 255, -1)
        m = cv2.add(m, layer)

    m = cv2.subtract(m, cv2.dilate(lips(shape, geo), np.ones((5, 5), np.uint8)))
    return _feather(m, 0.020)


def jaw_contour(shape, geo: FaceGeometry) -> np.ndarray:
    """턱선 바깥 띠. 아주 약하게 어둡게 해 입체감을 만든다(burn)."""
    oval = face_oval(shape, geo)
    k = max(3, int(min(shape[:2]) * 0.02)) | 1
    inner = cv2.erode(oval, np.ones((k, k), np.uint8))
    band = cv2.subtract(oval, inner)

    # 얼굴 아래쪽 절반만 — 이마 가장자리를 어둡게 하면 부자연스럽다
    if geo.chin is not None:
        cut = int((geo.eye_mid[1] + geo.chin[1]) / 2)
        band[:max(0, cut), :] = 0
    return _feather(band, 0.018)


def t_zone(shape, geo: FaceGeometry) -> np.ndarray:
    """이마 중앙 + 콧대. 하이라이트(dodge)를 얹는 곳."""
    pts = geo.landmarks
    if not _has(pts, [FOREHEAD_TOP, NOSE_TIP, CHIN]):
        return np.zeros(shape[:2], np.uint8)
    brow_y = pts[FOREHEAD_TOP][1]
    nose = pts[NOSE_TIP]
    eye_w = max(6.0, geo.eye_distance)

    m = np.zeros(shape[:2], np.uint8)
    cv2.ellipse(m, (int(geo.face_axis_x), int(brow_y + (nose[1] - brow_y) * 0.30)),
                (int(eye_w * 0.55), int(abs(nose[1] - brow_y) * 0.42)),
                0, 0, 360, 255, -1)                                  # 이마
    cv2.ellipse(m, (int(nose[0]), int((brow_y + nose[1]) / 2)),
                (max(2, int(eye_w * 0.13)), int(abs(nose[1] - brow_y) * 0.45)),
                0, 0, 360, 255, -1)                                  # 콧대
    m = cv2.bitwise_and(m, face_oval(shape, geo))
    return _feather(m, 0.030)


def hair_halo(shape, geo: FaceGeometry, alpha: np.ndarray | None = None) -> np.ndarray:
    """머리 위 잔머리 영역. 전경 매트 가장자리에서 잡는다.

    alpha 가 없으면 빈 마스크를 돌려준다 — 매트 없이 잔머리를 추측하면
    머리카락을 깎아내는 사고가 난다.
    """
    if alpha is None:
        return np.zeros(shape[:2], np.uint8)
    a = (alpha * 255).astype(np.uint8) if alpha.dtype != np.uint8 else alpha
    k = max(3, int(min(shape[:2]) * 0.012)) | 1
    edge = cv2.subtract(cv2.dilate(a, np.ones((k, k), np.uint8)),
                        cv2.erode(a, np.ones((k, k), np.uint8)))
    if geo.eye_mid is not None:
        edge[int(geo.eye_mid[1]):, :] = 0      # 눈높이 위쪽만
    return _feather(edge, 0.008)
