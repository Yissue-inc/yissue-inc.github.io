"""S0 — 입력 품질 게이팅.

결과는 '거절'이 아니라 '코칭'으로 쓴다. 사용자에게는 무엇이 문제인지와
무엇을 하면 되는지를 한국어로 돌려준다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .config import GateConfig
from .geometry import FaceGeometry

REJECT, WARN, OK = "reject", "warn", "ok"

# MediaPipe FaceMesh 눈 랜드마크 (상, 하, 안쪽 모서리, 바깥쪽 모서리)
_EYE_R = (159, 145, 133, 33)
_EYE_L = (386, 374, 362, 263)


@dataclass
class Check:
    key: str
    label: str
    value: float
    level: str
    message: str = ""


@dataclass
class GateResult:
    usable: bool
    score: float                       # 0..1 — 종합 유용성
    checks: list[Check] = field(default_factory=list)
    face: FaceGeometry | None = None

    @property
    def rejects(self) -> list[Check]:
        return [c for c in self.checks if c.level == REJECT]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.level == WARN]

    def coaching(self) -> list[str]:
        """사용자에게 보여줄 문장. 거절 사유를 먼저, 그다음 경고."""
        return [c.message for c in self.rejects + self.warnings if c.message]


#: 선명도를 측정하기 전에 얼굴 ROI를 맞추는 기준 크기(긴 변, px).
_SHARPNESS_CANON_PX = 256


def _lap_var(gray: np.ndarray) -> float:
    """얼굴 ROI를 기준 크기로 리사이즈한 뒤 라플라시안 분산을 잰다.

    리사이즈 없이 재면 값이 얼굴 픽셀 수에 함께 움직여, 작게 찍힌 선명한
    얼굴과 크게 찍힌 흐린 얼굴을 구분할 수 없다. 기준 크기로 맞춰야
    '이 얼굴이 얼마나 또렷한가'만 남는다. 확대는 없던 디테일을 만들지
    않으므로, 원본보다 작은 얼굴은 확대된 만큼 값이 낮게 나온다 — 의도된
    동작이다(작고 흐린 얼굴은 실제로 쓸 수 없다).
    """
    if gray.size == 0:
        return 0.0
    longest = max(gray.shape)
    if longest != _SHARPNESS_CANON_PX:
        s = _SHARPNESS_CANON_PX / longest
        gray = cv2.resize(gray, None, fx=s, fy=s,
                          interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _ear(pts: list, idx: tuple[int, int, int, int]) -> float | None:
    """Eye Aspect Ratio — 세로/가로. 눈을 감으면 0에 가까워진다."""
    if not pts or max(idx) >= len(pts):
        return None
    up, low, inner, outer = (np.array(pts[i], dtype=float) for i in idx)
    horiz = np.linalg.norm(outer - inner)
    return float(np.linalg.norm(up - low) / horiz) if horiz > 1e-6 else None


def _face_roi(bgr: np.ndarray, geo: FaceGeometry, pad: float = 0.12):
    h, w = bgr.shape[:2]
    x, y, bw, bh = geo.box
    px, py = bw * pad, bh * pad
    x0, y0 = max(0, int(x - px)), max(0, int(y - py))
    x1, y1 = min(w, int(x + bw + px)), min(h, int(y + bh + py))
    return bgr[y0:y1, x0:x1]


def evaluate(bgr: np.ndarray, faces: list[FaceGeometry],
             cfg: GateConfig | None = None) -> GateResult:
    cfg = cfg or GateConfig()
    checks: list[Check] = []

    if not faces:
        return GateResult(False, 0.0, [Check(
            "face_count", "얼굴 검출", 0, REJECT,
            "얼굴을 찾지 못했습니다. 얼굴이 정면으로 보이는 사진을 올려 주세요.")])

    if len(faces) > 1:
        checks.append(Check(
            "face_count", "얼굴 수", len(faces), WARN,
            f"사진에 얼굴이 {len(faces)}개 있습니다. 가장 큰 얼굴을 사용합니다 — "
            "본인만 나온 사진이면 결과가 더 정확합니다."))

    geo = faces[0]
    roi = _face_roi(bgr, geo)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.size else None

    # --- 얼굴 크기 ---
    short = min(geo.box[2], geo.box[3])
    checks.append(_band(
        "face_size", "얼굴 크기", short,
        reject_below=cfg.face_min_px, warn_below=cfg.face_warn_px,
        reject_msg="얼굴이 너무 작게 나왔습니다. 더 가까이서 찍은 사진을 올려 주세요.",
        warn_msg="얼굴이 작아 디테일이 부족할 수 있습니다. 더 가까운 사진이 있으면 함께 올려 주세요."))

    # --- 선명도 ---
    if gray is not None and gray.size:
        sharp = _lap_var(gray)
        checks.append(_band(
            "sharpness", "선명도", sharp,
            reject_below=cfg.sharpness_reject, warn_below=cfg.sharpness_warn,
            reject_msg="사진이 흔들렸거나 초점이 맞지 않습니다. 다른 사진을 올려 주세요.",
            warn_msg="사진이 다소 흐립니다. 더 선명한 사진이 있으면 결과가 좋아집니다."))

        # --- 노출 ---
        luma = float(gray.mean())
        level = REJECT if not (cfg.luma_low - 20 <= luma <= cfg.luma_high + 20) else (
            WARN if not (cfg.luma_low <= luma <= cfg.luma_high) else OK)
        checks.append(Check("exposure", "노출", luma, level,
                            "" if level == OK else
                            ("너무 어둡습니다. 밝은 곳에서 찍은 사진을 올려 주세요."
                             if luma < cfg.luma_low else
                             "너무 밝아 얼굴 디테일이 날아갔습니다. 역광을 피해 주세요.")))

    # --- 포즈 ---
    checks.append(_band(
        "yaw", "좌우 각도", abs(geo.yaw_proxy),
        reject_above=cfg.yaw_reject, warn_above=cfg.yaw_warn,
        reject_msg="고개가 옆으로 돌아가 있습니다. 정면을 본 사진을 올려 주세요.",
        warn_msg="고개가 약간 돌아가 있습니다. 정면 사진이면 더 자연스럽습니다."))
    checks.append(_band(
        "pitch", "상하 각도", abs(geo.pitch_proxy),
        reject_above=cfg.pitch_reject, warn_above=cfg.pitch_warn,
        reject_msg="고개가 위 또는 아래로 많이 기울어 있습니다. 카메라를 눈높이에 두고 찍어 주세요.",
        warn_msg="고개가 약간 숙여지거나 들려 있습니다."))
    checks.append(_band(
        "roll", "기울기", abs(geo.roll_deg),
        reject_above=cfg.roll_reject_deg, warn_above=cfg.roll_warn_deg,
        reject_msg="사진이 많이 기울어 있습니다.",
        warn_msg="사진이 약간 기울어 있습니다. 자동으로 수평을 맞춥니다."))

    # --- 눈 뜬 정도 ---
    ears = [e for e in (_ear(geo.landmarks, _EYE_R), _ear(geo.landmarks, _EYE_L))
            if e is not None]
    if ears:
        checks.append(_band(
            "eyes_open", "눈 뜬 정도", min(ears),
            reject_below=cfg.ear_reject, warn_below=cfg.ear_warn,
            reject_msg="눈을 감은 것으로 보입니다. 눈을 뜬 사진을 올려 주세요.",
            warn_msg="눈이 조금 감겨 있습니다."))

    # --- 안경 반사 ---
    glare = _eye_glare(bgr, geo)
    if glare is not None:
        checks.append(_band(
            "glare", "안경 반사", glare, warn_above=cfg.glare_warn,
            warn_msg="안경에 빛 반사가 있습니다. 반사가 없는 사진이면 눈이 또렷하게 나옵니다."))

    rejects = [c for c in checks if c.level == REJECT]
    return GateResult(usable=not rejects, score=_score(checks),
                      checks=checks, face=geo)


def _eye_glare(bgr: np.ndarray, geo: FaceGeometry) -> float | None:
    h, w = bgr.shape[:2]
    r = geo.eye_distance * 0.45
    if r < 3:
        return None
    fracs = []
    for (ex, ey) in (geo.right_eye, geo.left_eye):
        x0, y0 = max(0, int(ex - r)), max(0, int(ey - r))
        x1, y1 = min(w, int(ex + r)), min(h, int(ey + r))
        patch = bgr[y0:y1, x0:x1]
        if patch.size:
            fracs.append(float((patch.max(axis=2) >= 250).mean()))
    return max(fracs) if fracs else None


def _band(key: str, label: str, value: float, *,
          reject_below: float | None = None, warn_below: float | None = None,
          reject_above: float | None = None, warn_above: float | None = None,
          reject_msg: str = "", warn_msg: str = "") -> Check:
    if reject_below is not None and value < reject_below:
        return Check(key, label, value, REJECT, reject_msg)
    if reject_above is not None and value > reject_above:
        return Check(key, label, value, REJECT, reject_msg)
    if warn_below is not None and value < warn_below:
        return Check(key, label, value, WARN, warn_msg)
    if warn_above is not None and value > warn_above:
        return Check(key, label, value, WARN, warn_msg)
    return Check(key, label, value, OK)


def _score(checks: list[Check]) -> float:
    if not checks:
        return 0.0
    weight = {OK: 1.0, WARN: 0.55, REJECT: 0.0}
    return sum(weight[c.level] for c in checks) / len(checks)
