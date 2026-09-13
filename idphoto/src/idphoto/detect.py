"""S1 — 얼굴 검출 및 랜드마크.

두 단계로 나뉜다:
  1. YuNet (Apache-2.0)  : 검출 + 5점 랜드마크. 항상 사용 가능.
  2. 랜드마크 보강        : 턱끝·정수리 좌표를 채운다. 세 가지 전략이 있고
                           환경에 따라 사용 가능한 것을 고른다.

정수리(crown)는 머리카락을 포함해야 하므로 랜드마크 모델만으로는 원리적으로
알 수 없다. 배경이 균일한 스튜디오 이미지에서는 전경 매트가 훨씬 정확하므로,
matte 전략을 우선하고 랜드마크 외삽은 폴백으로 둔다.
"""
from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np

from .geometry import FaceGeometry, Point

MODELS_DIR = Path(os.environ.get(
    "IDPHOTO_MODELS", Path(__file__).resolve().parents[2] / "models"))

# 성인 두상 인체계측 근사: (정수리~턱) / (이마 상단 랜드마크~턱) ≈ 1.25
# 머리숱·헤어스타일에 따라 실제로는 1.15~1.45로 흔들린다. matte 전략을 항상 우선할 것.
_CROWN_RATIO = 1.25

# MediaPipe FaceMesh 인덱스
_MP_CHIN = 152
_MP_BROW_TOP = 10
_MP_IRIS_R = 468
_MP_IRIS_L = 473


class FaceDetector:
    """YuNet 검출기 래퍼."""

    def __init__(self, model_path: Path | None = None, score_threshold: float = 0.6):
        self.model_path = Path(model_path or MODELS_DIR / "yunet_2023mar.onnx")
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"{self.model_path} 없음 — scripts/fetch_models.sh 를 먼저 실행하세요")
        self._net = cv2.FaceDetectorYN.create(
            str(self.model_path), "", (320, 320), score_threshold, 0.3, 5000)

    def detect(self, bgr: np.ndarray) -> list[FaceGeometry]:
        h, w = bgr.shape[:2]
        self._net.setInputSize((w, h))
        _, raw = self._net.detect(bgr)
        if raw is None:
            return []
        out = []
        for row in raw:
            f = row.astype(float)
            out.append(FaceGeometry(
                box=(f[0], f[1], f[2], f[3]),
                right_eye=(f[4], f[5]), left_eye=(f[6], f[7]),
                nose=(f[8], f[9]),
                mouth_right=(f[10], f[11]), mouth_left=(f[12], f[13]),
                score=f[14], raw=row,
            ))
        out.sort(key=lambda g: g.box[2] * g.box[3], reverse=True)
        return out


class MediaPipeLandmarker:
    """478점 랜드마크. 턱끝을 정확히 준다. libEGL/libGLESv2 런타임이 필요하다."""

    available: bool

    def __init__(self, model_path: Path | None = None):
        self.model_path = Path(model_path or MODELS_DIR / "face_landmarker.task")
        self._lm = None
        self.available = False
        if not self.model_path.exists():
            return
        try:
            from mediapipe.tasks.python import BaseOptions, vision
            self._vision = vision
            self._lm = vision.FaceLandmarker.create_from_options(
                vision.FaceLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(self.model_path)),
                    num_faces=1, output_face_blendshapes=False))
            self.available = True
        except Exception:          # 런타임 라이브러리 부재 등 — 폴백으로 넘어간다
            self._lm = None

    def annotate(self, bgr: np.ndarray, geo: FaceGeometry) -> bool:
        """geo.chin / geo.landmarks 를 채운다. 성공하면 True."""
        if not self.available:
            return False
        import mediapipe as mp
        h, w = bgr.shape[:2]
        img = mp.Image(image_format=mp.ImageFormat.SRGB,
                       data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        res = self._lm.detect(img)
        if not res.face_landmarks:
            return False
        pts = [(p.x * w, p.y * h) for p in res.face_landmarks[0]]
        geo.landmarks = pts
        geo.chin = pts[_MP_CHIN]
        if len(pts) > _MP_IRIS_L:                 # 홍채 중심이 5점 눈보다 정확하다
            geo.right_eye = pts[_MP_IRIS_R]
            geo.left_eye = pts[_MP_IRIS_L]
        return True


def estimate_chin_from_box(geo: FaceGeometry) -> Point:
    """랜드마커가 없을 때의 턱끝 근사.

    YuNet 박스 하단은 턱끝보다 약간 위에 걸리는 경향이 있어, 눈-입 거리로
    보정한다. 오차가 크므로 게이팅 통과용이며 최종 크롭에는 권장하지 않는다.
    """
    mouth_mid_y = (geo.mouth_right[1] + geo.mouth_left[1]) / 2
    eye_to_mouth = mouth_mid_y - geo.eye_mid[1]
    return (geo.face_axis_x, mouth_mid_y + eye_to_mouth * 0.72)


def crown_from_landmarks(geo: FaceGeometry) -> Point | None:
    """이마 상단 랜드마크에서 인체계측 비율로 정수리를 외삽."""
    if geo.chin is None:
        return None
    if geo.landmarks and len(geo.landmarks) > _MP_BROW_TOP:
        brow = geo.landmarks[_MP_BROW_TOP]
    else:
        # 랜드마크가 없으면 박스 상단을 이마 상단 대용으로 쓴다
        brow = (geo.face_axis_x, geo.box[1])
    chin_y = geo.chin[1]
    return (geo.face_axis_x, chin_y - (chin_y - brow[1]) * _CROWN_RATIO)


def crown_from_matte(bgr: np.ndarray, geo: FaceGeometry,
                     tol: int = 26) -> Point | None:
    """배경이 균일한 이미지에서 전경 최상단(=머리카락 끝)을 찾는다.

    이미지 네 모서리에서 배경색을 추정하고, 얼굴 중심 열 밴드에서 배경과
    충분히 다른 첫 행을 정수리로 본다. 생성된 스튜디오 사진에 잘 맞는다.
    반환 실패 시 None — 배경이 균일하지 않다는 뜻이다.
    """
    h, w = bgr.shape[:2]
    k = max(4, min(h, w) // 40)
    corners = np.concatenate([
        bgr[:k, :k].reshape(-1, 3), bgr[:k, -k:].reshape(-1, 3),
        bgr[-k:, :k].reshape(-1, 3), bgr[-k:, -k:].reshape(-1, 3)])
    bg = np.median(corners, axis=0)
    # 모서리들끼리 서로 많이 다르면 균일 배경이 아니다
    if float(np.median(np.abs(corners - bg))) > tol:
        return None

    band = max(8, int(geo.box[2] * 0.35))
    cx = int(round(geo.face_axis_x))
    x0, x1 = max(0, cx - band), min(w, cx + band)
    if x1 <= x0:
        return None

    strip = bgr[:, x0:x1].astype(np.int16)
    diff = np.abs(strip - bg.astype(np.int16)).max(axis=2)    # (h, band)
    fg_frac = (diff > tol).mean(axis=1)                        # 행별 전경 비율

    eye_row = int(geo.eye_mid[1])
    rows = np.flatnonzero(fg_frac[:eye_row] > 0.30)
    if rows.size == 0:
        return None
    return (geo.face_axis_x, float(rows[0]))


class FaceAnalyzer:
    """검출 + 랜드마크 보강을 묶은 진입점."""

    def __init__(self, models_dir: Path | None = None, prefer_matte: bool = True):
        self.detector = FaceDetector(
            (models_dir or MODELS_DIR) / "yunet_2023mar.onnx" if models_dir else None)
        self.landmarker = MediaPipeLandmarker(
            (models_dir / "face_landmarker.task") if models_dir else None)
        self.prefer_matte = prefer_matte

    @property
    def landmarker_available(self) -> bool:
        return self.landmarker.available

    def analyze(self, bgr: np.ndarray) -> list[FaceGeometry]:
        faces = self.detector.detect(bgr)
        for geo in faces[:1]:          # 랜드마커는 가장 큰 얼굴에만 (비용)
            if not self.landmarker.annotate(bgr, geo):
                geo.chin = estimate_chin_from_box(geo)

            crown = crown_from_matte(bgr, geo) if self.prefer_matte else None
            if crown is not None:
                geo.crown, geo.crown_source = crown, "matte"
            else:
                lm_crown = crown_from_landmarks(geo)
                if lm_crown is not None:
                    geo.crown, geo.crown_source = lm_crown, "landmark"
        return faces
