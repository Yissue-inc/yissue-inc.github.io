"""S9 — 생성 결과 QA, 스코어링, 다양성 선발.

이 모듈이 이 서비스의 상업적 핵심이다. 사용자는 40장 중 5장만 본다.
무엇을 보여주지 '않을지'가 곧 품질이다.

두 단계로 나뉜다:
  1. 하드 게이트 — 하나라도 실패하면 사용자에게 절대 노출하지 않는다.
  2. 소프트 스코어 — 통과한 후보를 가중 합산으로 줄 세우고, 겹치지 않게 뽑는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .config import QAConfig
from .framing import FramingResult
from .geometry import FaceGeometry


@dataclass
class Candidate:
    """생성 후보 한 장."""

    variant_id: str
    image: np.ndarray                      # 규격 크롭 완료된 BGR
    preset: dict = field(default_factory=dict)   # 의상/배경/헤어 등
    model: str = ""                        # 이 후보를 만든 생성 모델
    face: FaceGeometry | None = None
    embedding: np.ndarray | None = None
    framing: FramingResult | None = None

    # 채워지는 값
    id_cos: float = 0.0
    quality: float = 0.0
    spec_score: float = 0.0
    aesthetic: float = 0.0
    neutrality: float = 0.0
    skin_delta_L: float = 0.0
    skin_chroma_shift: float = 0.0
    score: float = 0.0
    rejected: str | None = None            # 탈락 사유 (None이면 통과)

    # 리터칭 진단 — 예산 가드가 실제로 물러섰는지 추적한다
    retouch_delta: float = 0.0
    retouch_factor: float = 1.0
    blemishes_removed: int = 0


def _skin_lab(bgr: np.ndarray, geo: FaceGeometry) -> tuple[float, float, float]:
    """얼굴 중앙부(볼·이마)의 CIE Lab 중앙값. L* 은 0..100 스케일."""
    x, y, w, h = geo.box
    x0, y0 = int(x + w * 0.25), int(y + h * 0.30)
    x1, y1 = int(x + w * 0.75), int(y + h * 0.75)
    patch = bgr[max(0, y0):y1, max(0, x0):x1]
    if patch.size == 0:
        return (0.0, 0.0, 0.0)
    lab = cv2.cvtColor(patch, cv2.COLOR_BGR2LAB)
    return (float(np.median(lab[:, :, 0])) * 100.0 / 255.0,
            float(np.median(lab[:, :, 1])) - 128.0,
            float(np.median(lab[:, :, 2])) - 128.0)


def _skin_L(bgr: np.ndarray, geo: FaceGeometry) -> float:
    """얼굴 중앙부의 CIE L* 중앙값(0..100)."""
    return _skin_lab(bgr, geo)[0]


# 규격 크롭(413x531)을 256px로 맞춰 잰 라플라시안 분산의 실측 범위
# (2026-09-13, out/lena_id_kr.png 기준):
#   정상 459 / 블러 k=3 294, k=5 208, k=9 91 / 30% 축소후 확대 159 / 과샤프닝 1139
# 뭉개짐과 과도한 샤프닝(헤일로)은 둘 다 생성물의 실제 아티팩트이므로 양쪽을 벌점한다.
_SHARP_GOOD = (250.0, 800.0)
_SHARP_FLOOR, _SHARP_CEIL = 60.0, 1600.0


def _sharpness_score(bgr: np.ndarray) -> float:
    """0..1 밴드 스코어. 너무 흐려도, 너무 날카로워도 떨어진다."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if max(gray.shape) != 256:
        s = 256 / max(gray.shape)
        gray = cv2.resize(gray, None, fx=s, fy=s,
                         interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    v = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    lo, hi = _SHARP_GOOD
    if lo <= v <= hi:
        return 1.0
    if v < lo:
        return float(np.clip((v - _SHARP_FLOOR) / (lo - _SHARP_FLOOR), 0.0, 1.0))
    return float(np.clip((_SHARP_CEIL - v) / (_SHARP_CEIL - hi), 0.0, 1.0))


def _eye_symmetry(geo: FaceGeometry) -> float:
    """0..1. 양쪽 눈이 코 중심선 기준으로 대칭인가. 생성 아티팩트 탐지."""
    if geo.eye_distance < 1e-6:
        return 0.0
    dr = abs(geo.nose[0] - geo.right_eye[0])
    dl = abs(geo.left_eye[0] - geo.nose[0])
    return float(1.0 - min(1.0, abs(dr - dl) / geo.eye_distance))


def _neutrality(geo: FaceGeometry) -> float:
    """0..1. 정면·수평·중립 표정에 가까울수록 높다."""
    yaw = 1.0 - min(1.0, abs(geo.yaw_proxy) / 0.20)
    pitch = 1.0 - min(1.0, abs(geo.pitch_proxy) / 0.12)
    roll = 1.0 - min(1.0, abs(geo.roll_deg) / 8.0)
    return float(0.45 * yaw + 0.35 * pitch + 0.20 * roll)


def _spec_score(fr: FramingResult | None) -> float:
    """규격 적합도 0..1. 머리 길이가 허용 범위 중앙에 가까울수록 높다."""
    if fr is None:
        return 0.0
    lo, hi = fr.spec.head_min_mm, fr.spec.head_max_mm
    mid, half = (lo + hi) / 2, (hi - lo) / 2
    if half <= 0:
        return 1.0
    inside = 1.0 - min(1.0, abs(fr.head_mm - mid) / half)
    return float(inside * (1.0 - min(1.0, fr.out_of_frame * 20)))


def evaluate(cand: Candidate, reference: np.ndarray,
             ref_skin: float | tuple[float, float, float],
             cfg: QAConfig | None = None) -> Candidate:
    """후보 하나를 채점한다. 하드 게이트 실패 시 rejected 를 채운다."""
    cfg = cfg or QAConfig()

    if cand.face is None:
        cand.rejected = "얼굴 검출 실패"
        return cand
    if cand.embedding is None:
        cand.rejected = "임베딩 없음"
        return cand

    cand.id_cos = float(np.dot(cand.embedding, reference))
    cand.quality = _sharpness_score(cand.image)
    cand.spec_score = _spec_score(cand.framing)
    cand.neutrality = _neutrality(cand.face)
    sym = _eye_symmetry(cand.face)
    cand.aesthetic = float(0.5 * sym + 0.3 * cand.quality + 0.2 * cand.neutrality)
    ref_lab = ref_skin if isinstance(ref_skin, tuple) else (ref_skin, 0.0, 0.0)
    L, a, b = _skin_lab(cand.image, cand.face)
    cand.skin_delta_L = L - ref_lab[0]
    cand.skin_chroma_shift = float(np.hypot(a - ref_lab[1], b - ref_lab[2])) \
        if isinstance(ref_skin, tuple) else 0.0

    # --- 하드 게이트 ---
    if cand.id_cos < cfg.tau_id:
        cand.rejected = f"유사도 미달 ({cand.id_cos:.3f} < {cfg.tau_id})"
    elif cand.framing is not None and not cand.framing.head_in_range:
        cand.rejected = f"규격 이탈 (머리 {cand.framing.head_mm:.1f}mm)"
    elif sym < 0.55:
        cand.rejected = f"얼굴 비대칭 아티팩트 (대칭도 {sym:.2f})"
    elif cand.skin_chroma_shift > cfg.max_skin_chroma_shift:
        cand.rejected = f"피부 색조 이동 과다 (Δchroma {cand.skin_chroma_shift:.1f})"
    elif abs(cand.skin_delta_L) > cfg.max_skin_delta_L:
        cand.rejected = f"피부 밝기 이동 극단 (ΔL* {cand.skin_delta_L:+.1f})"

    cand.score = (cfg.w_identity * cand.id_cos
                  + cfg.w_quality * cand.quality
                  + cfg.w_spec * cand.spec_score
                  + cfg.w_aesthetic * cand.aesthetic
                  + cfg.w_neutral * cand.neutrality)
    return cand


def _preset_distance(a: dict, b: dict) -> float:
    """프리셋 조합이 얼마나 다른가 0..1. 같은 옷·같은 배경이면 0에 가깝다."""
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    return sum(1.0 for k in keys if a.get(k) != b.get(k)) / len(keys)


def select(cands: list[Candidate], n: int, cfg: QAConfig | None = None) -> list[Candidate]:
    """MMR 다양성 선발.

    점수순으로만 뽑으면 상위 5장이 전부 같은 정장·같은 배경이 되어 만족도가
    떨어진다. 점수와 '이미 뽑은 것들과의 차이'를 lambda로 섞는다.
    """
    cfg = cfg or QAConfig()
    pool = sorted((c for c in cands if c.rejected is None),
                  key=lambda c: c.score, reverse=True)
    if not pool:
        return []

    chosen = [pool.pop(0)]
    while pool and len(chosen) < n:
        best_i, best_v = 0, -1e9
        for i, c in enumerate(pool):
            novelty = min(_preset_distance(c.preset, s.preset) for s in chosen)
            v = cfg.mmr_lambda * c.score + (1 - cfg.mmr_lambda) * novelty
            if v > best_v:
                best_i, best_v = i, v
        chosen.append(pool.pop(best_i))
    return chosen


def summarize(cands: list[Candidate]) -> dict:
    """대시보드용 집계. 유사도 분포가 좌측 이동하면 모델·프롬프트 회귀 신호다."""
    passed = [c for c in cands if c.rejected is None]
    cos = np.array([c.id_cos for c in cands]) if cands else np.array([0.0])
    reasons: dict[str, int] = {}
    for c in cands:
        if c.rejected:
            reasons[c.rejected.split(" (")[0]] = reasons.get(c.rejected.split(" (")[0], 0) + 1
    per_model: dict[str, dict] = {}
    for c in cands:
        m = per_model.setdefault(c.model or "-", {"n": 0, "passed": 0, "cos": []})
        m["n"] += 1
        m["passed"] += c.rejected is None
        m["cos"].append(c.id_cos)
    for m in per_model.values():
        arr = np.array(m.pop("cos") or [0.0])
        m["pass_rate"] = round(m["passed"] / m["n"], 3) if m["n"] else 0.0
        m["id_cos_mean"] = round(float(arr.mean()), 4)
        m["id_cos_max"] = round(float(arr.max()), 4)

    return {
        "generated": len(cands),
        "by_model": per_model,
        "passed": len(passed),
        "pass_rate": len(passed) / len(cands) if cands else 0.0,
        "id_cos_mean": float(cos.mean()),
        "id_cos_p10": float(np.percentile(cos, 10)),
        "id_cos_max": float(cos.max()),
        "reject_reasons": reasons,
    }
