"""얼굴 계측 — '같은 사람인가'를 임베딩과 독립적으로 검증한다.

임베딩 유사도(SFace)만으로는 부족하다. 생성 모델이 턱을 깎고 눈을 키워도
유사도는 꽤 높게 유지되는 경우가 많다 — 임베딩은 사람을 구분하도록 학습됐지
성형 여부를 잡도록 학습되지 않았기 때문이다.

그래서 골격 비율을 직접 잰다. 이 비율들은 **조명·표정·화질이 변해도 유지되고,
얼굴 형태를 건드리면 즉시 변한다.** 미화 등급에서 무엇을 허용하고 무엇을
금지할지를 가르는 선이 바로 여기다.

  허용(미화) — 피부, 조명, 정돈, 의상, 톤
  금지(양쪽) — 골격 비율, 이목구비 크기, 나이대

모든 비율은 **양안 거리(interocular)로 정규화**한다. 인체계측의 표준 방식이고,
크롭 배율과 무관해진다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .geometry import FaceGeometry
from .regions import (CHIN, FACE_OVAL, FOREHEAD_TOP, IRIS_L_CENTER,
                      IRIS_R_CENTER, MOUTH_CORNER_L, MOUTH_CORNER_R, NOSE_TIP)

# 눈 모서리 (안쪽, 바깥쪽)
_EYE_R_OUTER, _EYE_R_INNER = 33, 133
_EYE_L_INNER, _EYE_L_OUTER = 362, 263
# 눈 상·하
_EYE_R_TOP, _EYE_R_BOT = 159, 145
_EYE_L_TOP, _EYE_L_BOT = 386, 374


@dataclass
class Morphometry:
    """양안 거리로 정규화한 얼굴 비율. 전부 무차원."""

    face_height: float          # 이마 상단 ~ 턱
    face_width_eye: float       # 눈높이에서의 얼굴 폭 (광대)
    face_width_mouth: float     # 입높이에서의 얼굴 폭 (턱/볼)
    mouth_width: float
    eye_width_mean: float
    eye_aperture: float         # 눈 세로 / 눈 가로 — 눈 크기 비율
    nose_length: float          # 눈 중점 ~ 코끝
    lower_face: float           # 코끝 ~ 턱 / 얼굴 높이
    jaw_taper: float            # 입높이 폭 / 눈높이 폭 — 갸름함

    def as_dict(self) -> dict[str, float]:
        return {k: round(v, 4) for k, v in self.__dict__.items()}


#: 각 비율이 '같은 사람'으로 볼 수 있는 상대 변화 허용치.
#:
#: 같은 사람을 다른 날·다른 카메라로 찍어도 랜드마크 추정 오차로 몇 % 는
#: 흔들린다. 아래 값은 그 잡음 위에 있으면서, 눈에 띄는 성형은 잡는 선이다.
#: 실사진으로 재보정할 것 — 현재는 랜드마크 추정 오차 관찰에 근거한 초기값.
TOLERANCE: dict[str, float] = {
    "face_height": 0.06,
    "face_width_eye": 0.06,
    "face_width_mouth": 0.07,
    "mouth_width": 0.08,
    "eye_width_mean": 0.07,
    "eye_aperture": 0.12,      # 눈 뜬 정도는 표정으로도 변한다 — 느슨하게
    "nose_length": 0.07,
    "lower_face": 0.06,
    "jaw_taper": 0.06,         # 갸름하게 깎는 것을 잡는 핵심 지표
}

#: 미화 등급에서도 절대 넘으면 안 되는 비율. 이걸 넘으면 다른 얼굴이다.
INVIOLABLE = ("face_width_eye", "face_width_mouth", "jaw_taper",
              "eye_width_mean", "nose_length", "lower_face")


def _pt(pts, i) -> np.ndarray:
    return np.array(pts[i], dtype=float)


def _oval_width_at(pts, y: float) -> float:
    """얼굴 윤곽선이 높이 y 에서 갖는 가로 폭."""
    oval = np.array([pts[i] for i in FACE_OVAL], dtype=float)
    band = max(4.0, float(np.ptp(oval[:, 1])) * 0.06)
    sel = oval[np.abs(oval[:, 1] - y) <= band]
    if len(sel) < 2:                      # 밴드에 점이 없으면 넓혀서 재시도
        sel = oval[np.abs(oval[:, 1] - y) <= band * 3]
    return float(np.ptp(sel[:, 0])) if len(sel) >= 2 else 0.0


def measure(geo: FaceGeometry) -> Morphometry | None:
    """478점 랜드마크에서 비율을 잰다. 랜드마크가 없으면 None."""
    pts = geo.landmarks
    if not pts or len(pts) <= max(IRIS_L_CENTER, _EYE_L_OUTER, max(FACE_OVAL)):
        return None

    ir, il = _pt(pts, IRIS_R_CENTER), _pt(pts, IRIS_L_CENTER)
    iod = float(np.linalg.norm(il - ir))
    if iod < 1e-6:
        return None

    chin, brow = _pt(pts, CHIN), _pt(pts, FOREHEAD_TOP)
    nose = _pt(pts, NOSE_TIP)
    eye_mid = (ir + il) / 2
    mouth_y = float((_pt(pts, MOUTH_CORNER_R)[1] + _pt(pts, MOUTH_CORNER_L)[1]) / 2)

    def eye_metrics(outer, inner, top, bot):
        w = float(np.linalg.norm(_pt(pts, outer) - _pt(pts, inner)))
        h = float(np.linalg.norm(_pt(pts, top) - _pt(pts, bot)))
        return w, (h / w if w > 1e-6 else 0.0)

    wr, ar = eye_metrics(_EYE_R_OUTER, _EYE_R_INNER, _EYE_R_TOP, _EYE_R_BOT)
    wl, al = eye_metrics(_EYE_L_OUTER, _EYE_L_INNER, _EYE_L_TOP, _EYE_L_BOT)

    face_h = float(abs(chin[1] - brow[1]))
    w_eye = _oval_width_at(pts, float(eye_mid[1]))
    w_mouth = _oval_width_at(pts, mouth_y)

    return Morphometry(
        face_height=face_h / iod,
        face_width_eye=w_eye / iod,
        face_width_mouth=w_mouth / iod,
        mouth_width=float(np.linalg.norm(
            _pt(pts, MOUTH_CORNER_L) - _pt(pts, MOUTH_CORNER_R))) / iod,
        eye_width_mean=(wr + wl) / 2 / iod,
        eye_aperture=(ar + al) / 2,
        nose_length=float(abs(nose[1] - eye_mid[1])) / iod,
        lower_face=(float(abs(chin[1] - nose[1])) / face_h) if face_h > 1e-6 else 0.0,
        jaw_taper=(w_mouth / w_eye) if w_eye > 1e-6 else 0.0,
    )


@dataclass
class MorphDelta:
    """참조 대비 비율 변화. 값은 상대 변화율(부호 있음)."""

    deltas: dict[str, float]
    violations: list[str]          # 허용치를 넘은 항목
    inviolable_hits: list[str]     # 그중 미화 등급에서도 금지된 항목
    max_abs: float

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def shape_preserved(self) -> bool:
        """미화 등급 기준 — 골격이 유지됐는가."""
        return not self.inviolable_hits

    def summary(self) -> str:
        if self.ok:
            return f"골격 유지 (최대 편차 {self.max_abs * 100:.1f}%)"
        worst = max(self.deltas.items(), key=lambda kv: abs(kv[1]))
        return (f"골격 변형 {len(self.violations)}항목 — "
                f"{worst[0]} {worst[1] * 100:+.1f}%")


def compare(ref: Morphometry, cand: Morphometry,
            tolerance: dict[str, float] | None = None,
            scale: float = 1.0) -> MorphDelta:
    """참조와 후보의 비율을 비교한다.

    scale 은 허용치 배율이다. 미화 등급은 표정·정돈 변화가 크므로 1.0 보다
    넉넉하게 주되, INVIOLABLE 항목은 배율을 적용하지 않는다 — 골격은
    등급과 무관하게 고정이다.
    """
    tol = tolerance or TOLERANCE
    deltas, violations, hits = {}, [], []

    for key, ref_v in ref.as_dict().items():
        cand_v = getattr(cand, key)
        if abs(ref_v) < 1e-6:
            continue
        d = (cand_v - ref_v) / abs(ref_v)
        deltas[key] = round(d, 4)

        limit = tol.get(key, 0.10)
        if key not in INVIOLABLE:
            limit *= scale
        if abs(d) > limit:
            violations.append(key)
            if key in INVIOLABLE:
                hits.append(key)

    return MorphDelta(deltas=deltas, violations=violations,
                      inviolable_hits=hits,
                      max_abs=max((abs(v) for v in deltas.values()), default=0.0))


def silhouette_taper(bgr: np.ndarray, geo: FaceGeometry) -> float | None:
    """전경 실루엣의 (입높이 폭 / 눈높이 폭). 얼굴 깎기를 잡는 주 지표.

    랜드마크 대신 **실제 화소**로 잰다. MediaPipe 랜드마크는 얼굴 모델을
    피팅하므로 기하 왜곡에 스스로 강건하고, 그래서 깎인 턱을 잘 못 잡는다.
    실측(턱을 20% 깎았을 때): 랜드마크 기준 taper 변화 -3.0%,
    실루엣 기준 -6.8% — 실루엣이 2.3배 민감하다.

    배경이 균일해야 매트가 나온다. 실패하면 None — 그때는 이 검사를 건너뛰고
    사람이 봐야 한다.
    """
    from .background import alpha_matte

    alpha, _ = alpha_matte(bgr, geo)
    fg = alpha > 0.5
    if not fg.any() or not geo.landmarks:
        return None

    ir = np.array(geo.landmarks[IRIS_R_CENTER], float)
    il = np.array(geo.landmarks[IRIS_L_CENTER], float)
    iod = float(np.linalg.norm(il - ir))
    if iod < 1e-6:
        return None

    def width_at(y: float, band: int = 3) -> float:
        rows = fg[max(0, int(y) - band):int(y) + band + 1]
        w = [float(np.ptp(np.flatnonzero(r))) for r in rows if r.any()]
        return float(np.median(w)) if w else 0.0

    w_eye = width_at(geo.eye_mid[1])
    w_mouth = width_at((geo.landmarks[MOUTH_CORNER_R][1]
                        + geo.landmarks[MOUTH_CORNER_L][1]) / 2)
    return (w_mouth / w_eye) if w_eye > 1e-6 else None


#: 실루엣 taper 의 상대 변화 허용치.
#: 실측에서 턱 20% 깎기가 -6.8% 를 냈으므로, 그보다 아래에 둔다.
#: 미세한 깎기(6~12%)는 이 검사로도 확실히 잡히지 않는다 — 가이드 참조.
SILHOUETTE_TAPER_TOLERANCE = 0.045


def reference(geos: list[FaceGeometry]) -> Morphometry | None:
    """참조 사진들의 중앙값 비율. 한 장의 랜드마크 오차를 평균으로 누른다."""
    ms = [m for m in (measure(g) for g in geos) if m is not None]
    if not ms:
        return None
    keys = ms[0].as_dict().keys()
    return Morphometry(**{k: float(np.median([getattr(m, k) for m in ms]))
                          for k in keys})
