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

# 성인 두상 인체계측 근사: (머리카락 제외 머리 최상부~턱) / (이마 상단 랜드마크~턱) ≈ 1.25
# 이 비율은 두개골 기준이므로 머리카락 부피에 영향받지 않는다 — 외교부 여권
# 규정이 요구하는 '머리 길이'를 재는 데 쓴다.
_SKULL_RATIO = 1.25

# MediaPipe FaceMesh 인덱스
_MP_CHIN = 152
_MP_BROW_TOP = 10
_MP_IRIS_R = 468
_MP_IRIS_L = 473


#: 검출을 수행할 최대 이미지 긴 변(px).
#:
#: YuNet 은 큰 이미지에서 정확도가 급격히 떨어진다. 실측(2026-09-13, 사용자
#: 실사진 1932x2576):
#:
#:   원본 2576px → 검출 점수 0.63, 같은 사람 두 장의 SFace 유사도 0.012
#:   축소 1600px → 검출 점수 0.92, 같은 사람 두 장의 SFace 유사도 0.830
#:
#: 랜드마크가 부정확해지면 SFace 의 alignCrop 이 얼굴을 잘못 정렬하고,
#: 임베딩이 통째로 망가진다. 요즘 휴대폰 사진은 3000~4000px 이므로 실사용
#: 업로드는 거의 전부 이 구간에 들어간다.
#:
#: 그래서 검출은 축소본에서 하고 좌표만 원본 스케일로 되돌린다. 이후 정렬·
#: 크롭·리터칭은 원본 해상도에서 이루어지므로 화질 손실이 없다.
DETECT_MAX_PX = 1280


class FaceDetector:
    """YuNet 검출기 래퍼. 검출은 정규화된 해상도에서, 좌표는 원본 기준으로."""

    def __init__(self, model_path: Path | None = None, score_threshold: float = 0.6,
                 max_detect_px: int = DETECT_MAX_PX):
        self.model_path = Path(model_path or MODELS_DIR / "yunet_2023mar.onnx")
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"{self.model_path} 없음 — scripts/fetch_models.sh 를 먼저 실행하세요")
        self.max_detect_px = max_detect_px
        self._net = cv2.FaceDetectorYN.create(
            str(self.model_path), "", (320, 320), score_threshold, 0.3, 5000)

    def detect(self, bgr: np.ndarray) -> list[FaceGeometry]:
        h, w = bgr.shape[:2]
        longest = max(h, w)
        scale = 1.0
        work = bgr
        if self.max_detect_px and longest > self.max_detect_px:
            scale = self.max_detect_px / longest
            work = cv2.resize(bgr, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_AREA)

        wh, ww = work.shape[:2]
        self._net.setInputSize((ww, wh))
        _, raw = self._net.detect(work)
        if raw is None:
            return []

        inv = 1.0 / scale
        out = []
        for row in raw:
            f = row.astype(np.float32).copy()
            # 0..13 = 박스(4) + 5점 랜드마크(10). 14 = 점수이므로 건드리지 않는다.
            f[:14] *= inv
            d = f.astype(float)
            out.append(FaceGeometry(
                box=(d[0], d[1], d[2], d[3]),
                right_eye=(d[4], d[5]), left_eye=(d[6], d[7]),
                nose=(d[8], d[9]),
                mouth_right=(d[10], d[11]), mouth_left=(d[12], d[13]),
                score=d[14], raw=f,          # 원본 좌표계 — alignCrop 이 그대로 쓴다
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

    def close(self) -> None:
        """명시적으로 닫는다. 닫은 뒤에는 annotate 가 폴백으로 동작한다.

        인터프리터 종료 시점의 정리는 여기서 하지 않는다 — MediaPipe 의
        __del__ 이 어차피 한 번 더 닫으려 하고, 그때는 내부 실행기가 이미
        내려가 있어 예외가 난다. 그 소음은 cli 에서 unraisable 훅으로 거른다.
        """
        lm, self._lm = self._lm, None
        self.available = False
        if lm is not None:
            try:
                lm.close()
            except Exception:
                pass

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


def skull_top_from_landmarks(geo: FaceGeometry) -> Point | None:
    """이마 상단 랜드마크에서 인체계측 비율로 머리 최상부(머리카락 제외)를 외삽.

    랜드마크는 머리카락을 보지 않으므로, 이 외삽값은 원리적으로 두개골
    기준이다. 규정상 머리 길이 측정에는 이것이 맞고, 프레임에 머리카락이
    들어가는지 확인할 때는 crown_from_matte 쪽을 써야 한다.
    """
    if geo.chin is None:
        return None
    if geo.landmarks and len(geo.landmarks) > _MP_BROW_TOP:
        brow = geo.landmarks[_MP_BROW_TOP]
    else:
        # 랜드마크가 없으면 박스 상단을 이마 상단 대용으로 쓴다
        brow = (geo.face_axis_x, geo.box[1])
    chin_y = geo.chin[1]
    return (geo.face_axis_x, chin_y - (chin_y - brow[1]) * _SKULL_RATIO)


def crown_from_matte(bgr: np.ndarray, geo: FaceGeometry,
                     tol: int = 26) -> Point | None:
    """배경이 균일한 이미지에서 전경 최상단(=머리카락 최상부)을 찾는다.

    이미지 네 모서리에서 배경색을 추정하고, 얼굴 중심 열 밴드에서 배경과
    충분히 다른 첫 행을 정수리로 본다. 생성된 스튜디오 사진에 잘 맞는다.
    반환 실패 시 None — 배경이 균일하지 않다는 뜻이다.
    """
    from .background import sample_backdrop

    h, w = bgr.shape[:2]
    bg, _ = sample_backdrop(bgr, tol)
    if bg is None:                     # 균일 배경이 아니다
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

            # 두 지점을 따로 구한다. 머리카락 최상부는 프레임 적합성에,
            # 두개골 최상부는 규정상 머리 길이 측정에 쓴다.
            skull = skull_top_from_landmarks(geo)
            if skull is not None:
                geo.skull_top, geo.skull_top_source = skull, "landmark"

            hair = crown_from_matte(bgr, geo) if self.prefer_matte else None
            if hair is not None:
                geo.crown, geo.crown_source = hair, "matte"
            elif skull is not None:
                # 매트를 못 뽑으면 머리카락 최상부를 알 수 없다. 두개골 기준값을
                # 대신 쓰되 출처를 남겨, 규격 리포트에서 신뢰도를 낮게 표시한다.
                geo.crown, geo.crown_source = skull, "landmark"
        return faces
