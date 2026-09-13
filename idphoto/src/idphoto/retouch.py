"""S7 — 리터칭 레이어. 사진관 리터처 워크플로를 단계 순서까지 그대로 옮겼다.

순서가 결과를 바꾼다. 업계 표준 순서는 다음과 같고, 이 모듈은 그대로 따른다.

  1. 색보정 (화이트밸런스)      — 모든 판단의 기준을 먼저 세운다
  2. 잡티 제거 (힐링)           — 스무딩 '전에' 개별 잡티를 지운다
  3. 주파수 분리                — 저주파(색 얼룩)만 고르고 질감은 남긴다
  4. 닷지 & 번                  — 부위별로 입체감을 되살린다
  5. 눈                         — 홍채 또렷함, 공막 붉은기
  6. 치아                       — 노란기만 뺀다
  7. 선택적 디테일 샤프닝       — 눈·눈썹·입술에만
  8. 그레이딩
  9. 출력 샤프닝                — 반드시 보정이 끝난 뒤
 10. 그레인                     — 반드시 마지막

전역 스무딩을 쓰지 않는 것이 핵심이다. 2번에서 잡티만 골라 지우기 때문에
3번을 약하게 걸어도 되고, 그래야 모공·솜털·잔주름이 살아남는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from . import blemish, regions
from .geometry import FaceGeometry


@dataclass(frozen=True)
class RetouchSettings:
    """각 단계 0..1. 0 이면 그 단계는 실행되지 않는다."""

    white_balance: float = 0.60     # 1. 배경 기준 중성화
    blemish: float = 0.85           # 2. 잡티 힐링 강도
    blemish_sensitivity: float = 0.50
    preserve_moles: bool = True     #    점·주근깨 보존
    redness: float = 0.20           #    홍조 완화 (실측 근거로 하향)
    skin_even: float = 0.35         # 3. 저주파 톤 고르기 (힐링이 있으니 약하게)
    under_eye: float = 0.40         # 4. 다크서클 밝히기
    nasolabial: float = 0.25        #    팔자주름 그림자 완화
    contour: float = 0.30           #    T존 하이라이트 + 턱선 음영
    local_contrast: float = 0.25    #    국소 대비
    sclera: float = 0.40            # 5. 흰자 붉은기
    iris_clarity: float = 0.45      #    홍채 또렷함
    teeth: float = 0.35             # 6. 치아 노란기
    detail_sharpen: float = 0.40    # 7. 눈·눈썹·입술 디테일
    grade: float = 0.40             # 8. 컬러 그레이딩
    output_sharpen: float = 0.35    # 9. 출력 샤프닝
    grain: float = 0.35             # 10. 필름 그레인

    @classmethod
    def from_intensity(cls, t: float) -> "RetouchSettings":
        """사용자 '보정 강도' 슬라이더 0..1 → 전체 설정.

        t=0 은 전 단계가 0 이다. 사용자가 0 을 골랐으면 사진에 손대지 않는다.

        항목마다 상한이 다르다. 잡티 제거는 세게 걸어도 자연스럽지만
        (원래 없던 것을 지우는 일이므로), 윤곽 보정은 조금만 넘겨도 얼굴이
        바뀌므로 상한을 낮게 묶었다.
        """
        t = float(np.clip(t, 0.0, 1.0))
        return cls(
            white_balance=0.80 * t, blemish=1.00 * t, blemish_sensitivity=0.50,
            # 레퍼런스 출력은 입력 대비 Δa* +0.0 — 붉은기를 거의 건드리지 않았다.
            # 상한 0.65 는 그보다 훨씬 공격적이었으므로 0.30 으로 낮춘다.
            redness=0.30 * t, skin_even=0.50 * t,
            under_eye=0.55 * t, nasolabial=0.35 * t, contour=0.40 * t,
            local_contrast=0.35 * t,
            sclera=0.55 * t, iris_clarity=0.60 * t, teeth=0.50 * t,
            detail_sharpen=0.55 * t, grade=0.60 * t,
            output_sharpen=0.45 * t, grain=0.45 * t)

    @classmethod
    def for_generated(cls, t: float = 0.5) -> "RetouchSettings":
        """생성 이미지용.

        생성물은 이미 피부가 매끄럽게 나오므로 스무딩을 더 걸 이유가 없다.
        반대로 디지털적으로 평탄해서 그레인 하한이 필요하고, 잡티도 거의
        없으므로 힐링 민감도를 낮춰 없는 잡티를 만들어내지 않게 한다.
        """
        s = cls.from_intensity(t)
        return cls(**{**s.__dict__,
                      "skin_even": s.skin_even * 0.5,
                      "blemish_sensitivity": 0.35,
                      "grain": max(0.25, s.grain)})

    @classmethod
    def senior(cls, t: float = 0.5) -> "RetouchSettings":
        """50대 이상. 주름을 지우면 나이가 지워지고, 그러면 본인이 아니게 된다.

        잡티(검버섯이 아닌 일시적 홍조)는 그대로 다루되, 주름에 직접 닿는
        단계(팔자주름·저주파 스무딩)를 크게 눌러 둔다.
        """
        s = cls.from_intensity(t)
        return cls(**{**s.__dict__,
                      "skin_even": min(s.skin_even, 0.20),
                      "nasolabial": min(s.nasolabial, 0.12),
                      "under_eye": min(s.under_eye, 0.30),
                      "blemish_sensitivity": 0.35})

    @classmethod
    def natural(cls, t: float = 0.5) -> "RetouchSettings":
        """'보정한 티 안 나게' 프리셋. 잡티만 지우고 형태는 건드리지 않는다."""
        s = cls.from_intensity(t)
        return cls(**{**s.__dict__,
                      "under_eye": s.under_eye * 0.4, "nasolabial": 0.0,
                      "contour": 0.0, "local_contrast": s.local_contrast * 0.4})


@dataclass
class RetouchReport:
    blemishes: blemish.BlemishReport = field(default_factory=blemish.BlemishReport)
    stages: list[str] = field(default_factory=list)
    wb_shift: tuple[float, float] = (0.0, 0.0)

    def summary(self) -> str:
        return f"{self.blemishes.summary()} · 적용 단계 {len(self.stages)}개"


# ---------- 헬퍼 ----------

def _blend(base: np.ndarray, layer: np.ndarray, mask: np.ndarray,
           amount: float) -> np.ndarray:
    if amount <= 0:
        return base
    a = (mask.astype(np.float32) / 255.0 * float(np.clip(amount, 0, 1)))[..., None]
    return (base.astype(np.float32) * (1 - a)
            + layer.astype(np.float32) * a).clip(0, 255).astype(np.uint8)


def _unsharp(bgr: np.ndarray, sigma: float, strength: float) -> np.ndarray:
    return cv2.addWeighted(bgr, 1 + strength,
                           cv2.GaussianBlur(bgr, (0, 0), sigma), -strength, 0)


# ---------- 1. 색보정 ----------

def neutralize(bgr: np.ndarray, amount: float = 0.6) -> tuple[np.ndarray, tuple]:
    """배경(스튜디오 페이퍼)을 중성으로 맞춰 전체 색 캐스트를 제거한다.

    증명사진은 배경이 무채색이어야 하므로, 배경의 색 편차가 곧 조명의
    색 캐스트다. 이걸 먼저 잡아야 이후 피부톤 판단이 신뢰할 수 있다.
    """
    if amount <= 0:
        return bgr, (0.0, 0.0)
    h, w = bgr.shape[:2]
    k = max(4, min(h, w) // 25)
    corners = [bgr[:k, :k], bgr[:k, -k:]]
    ref = np.concatenate([c.reshape(-1, 3) for c in corners])

    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    ref_lab = cv2.cvtColor(ref.reshape(-1, 1, 3), cv2.COLOR_BGR2LAB
                           ).astype(np.float32).reshape(-1, 3)
    da = float(np.median(ref_lab[:, 1])) - 128.0
    db = float(np.median(ref_lab[:, 2])) - 128.0

    # --- 이 보정을 걸어도 되는 상황인지 먼저 확인한다 ---
    #
    # 배경이 스튜디오 페이퍼일 때만 '배경 = 무채색'이 성립한다. 배경에 색이
    # 있는 사진(야외, 컬러 벽, 업로드 셀카)에 그대로 걸면 그 색을 조명
    # 캐스트로 오인해 얼굴색을 통째로 밀어 버린다. 실측에서 이 경우
    # 단독으로 Δcos -0.082 가 났다 — 가드 예산의 1.6배다.
    #
    # 두 가지를 본다: 모서리들끼리 일관적인가, 그리고 이미 거의 무채색인가.
    spread = float(np.median(np.abs(ref_lab[:, 1:] - np.array([128 + da, 128 + db]))))
    if spread > 6.0:                       # 배경이 균일하지 않다
        return bgr, (0.0, 0.0)
    if abs(da) > 12.0 or abs(db) > 12.0:   # 배경이 애초에 유채색이다
        return bgr, (0.0, 0.0)
    if abs(da) < 0.4 and abs(db) < 0.4:    # 이미 중성이다
        return bgr, (0.0, 0.0)

    # 남은 경우에도 이동량에 상한을 둔다 — 한 단계가 예산을 다 쓰지 않도록
    amt = float(np.clip(amount, 0, 1))
    da = float(np.clip(da * amt, -6.0, 6.0))
    db = float(np.clip(db * amt, -6.0, 6.0))
    lab[:, :, 1] -= da
    lab[:, :, 2] -= db
    out = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
    return out, (round(da, 2), round(db, 2))


# ---------- 3. 주파수 분리 ----------

def even_skin(bgr: np.ndarray, mask: np.ndarray, amount: float) -> np.ndarray:
    """저주파만 고르고 고주파 텍스처는 그대로 되돌린다."""
    if amount <= 0:
        return bgr
    r = max(2.0, min(bgr.shape[:2]) / 90.0)
    low = cv2.GaussianBlur(bgr, (0, 0), r)
    high = bgr.astype(np.int16) - low.astype(np.int16)
    d = int(max(5, min(bgr.shape[:2]) / 45)) | 1
    low_even = cv2.bilateralFilter(low, d, 45, 45)
    merged = np.clip(low_even.astype(np.int16) + high, 0, 255).astype(np.uint8)
    return _blend(bgr, merged, mask, amount)


# ---------- 4. 닷지 & 번 ----------

def _lift(bgr: np.ndarray, mask: np.ndarray, stops: float,
          amount: float) -> np.ndarray:
    """마스크 영역의 밝기를 stops 만큼 올리거나(양수) 내린다(음수)."""
    if amount <= 0 or abs(stops) < 1e-4:
        return bgr
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    w = (mask.astype(np.float32) / 255.0) * float(np.clip(amount, 0, 1))
    lab[:, :, 0] = np.clip(lab[:, :, 0] * (1 + stops * w), 0, 255)
    return cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)


def brighten_under_eye(bgr, geo, amount):
    """다크서클. 지우지 않고 그림자만 들어 올린다 — 완전히 없애면 평면이 된다."""
    return _lift(bgr, regions.under_eye(bgr.shape, geo), 0.11, amount)


def soften_nasolabial(bgr, geo, amount):
    """팔자주름 그림자 완화. 주름 자체는 남긴다."""
    return _lift(bgr, regions.nasolabial(bgr.shape, geo), 0.07, amount)


def contour(bgr: np.ndarray, geo: FaceGeometry, amount: float) -> np.ndarray:
    """T존은 밝게, 턱선은 어둡게 — 리터처의 닷지&번 대응."""
    if amount <= 0:
        return bgr
    out = _lift(bgr, regions.t_zone(bgr.shape, geo), 0.055, amount)
    return _lift(out, regions.jaw_contour(bgr.shape, geo), -0.075, amount)


def local_contrast(bgr: np.ndarray, mask: np.ndarray, amount: float) -> np.ndarray:
    if amount <= 0:
        return bgr
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[:, :, 0]
    r = max(3.0, min(bgr.shape[:2]) / 22.0)
    lab[:, :, 0] = np.clip(L + (L - cv2.GaussianBlur(L, (0, 0), r)) * 0.55, 0, 255)
    out = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)
    return _blend(bgr, out, mask, amount)


# ---------- 5. 눈 ----------

def treat_eyes(bgr: np.ndarray, geo: FaceGeometry, sclera_amt: float,
               iris_amt: float) -> np.ndarray:
    """공막은 붉은기만 빼고, 홍채는 또렷하게.

    공막을 밝히지 않는다. 흰자를 하얗게 태우는 것이 아마추어 보정의
    가장 흔한 실수이고, 즉시 가짜 티가 난다.
    """
    out = bgr
    if sclera_amt > 0:
        m = regions.sclera(bgr.shape, geo)
        if m.any():
            lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB).astype(np.float32)
            w = (m.astype(np.float32) / 255.0) * float(np.clip(sclera_amt, 0, 1))
            lab[:, :, 1] = lab[:, :, 1] - (lab[:, :, 1] - 128.0) * 0.45 * w
            lab[:, :, 0] = np.clip(lab[:, :, 0] * (1 + 0.02 * w), 0, 250)
            out = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)

    if iris_amt > 0:
        m = regions.iris(bgr.shape, geo)
        if m.any():
            sigma = max(0.8, geo.eye_distance / 90.0)
            out = _blend(out, _unsharp(out, sigma, 0.75), m, iris_amt)
    return out


# ---------- 6. 치아 ----------

def whiten_teeth(bgr: np.ndarray, geo: FaceGeometry, amount: float) -> np.ndarray:
    """노란기(b*)만 빼고 아주 약하게 밝힌다. 회색으로 만들면 병약해 보인다."""
    if amount <= 0:
        return bgr
    m = regions.teeth(bgr.shape, geo)
    if not m.any():
        return bgr
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    w = (m.astype(np.float32) / 255.0) * float(np.clip(amount, 0, 1))
    lab[:, :, 2] = lab[:, :, 2] - (lab[:, :, 2] - 128.0) * 0.40 * w   # 노란기 -
    lab[:, :, 0] = np.clip(lab[:, :, 0] * (1 + 0.05 * w), 0, 252)     # 밝기 +
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


# ---------- 7. 선택적 디테일 ----------

def sharpen_details(bgr: np.ndarray, geo: FaceGeometry, amount: float) -> np.ndarray:
    """눈·눈썹·입술 라인에만 샤프닝. 피부에 걸면 모공이 튀어 거칠어진다."""
    if amount <= 0:
        return bgr
    m = np.zeros(bgr.shape[:2], np.uint8)
    for layer in (regions.eyes(bgr.shape, geo), regions.brows(bgr.shape, geo),
                  regions.lips(bgr.shape, geo)):
        m = cv2.max(m, layer)
    if not m.any():
        return bgr
    sigma = max(0.8, min(bgr.shape[:2]) / 420.0)
    return _blend(bgr, _unsharp(bgr, sigma, 0.65), m, amount)


# ---------- 8~10. 마감 ----------

def grade(bgr: np.ndarray, amount: float) -> np.ndarray:
    """한국 증명사진 관행: 약간 쿨한 화이트밸런스 + 하이라이트는 살짝 웜."""
    if amount <= 0:
        return bgr
    f = bgr.astype(np.float32)
    luma = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)[..., None] / 255.0
    cool = np.array([1.030, 1.004, 0.986], np.float32)
    warm = np.array([0.985, 1.000, 1.022], np.float32)
    out = np.clip(f * (cool * (1 - luma) + warm * luma), 0, 255).astype(np.uint8)
    return cv2.addWeighted(bgr, 1 - amount, out, amount, 0)


def output_sharpen(bgr: np.ndarray, amount: float) -> np.ndarray:
    """인쇄용 출력 샤프닝. 반드시 모든 보정이 끝난 뒤에 건다."""
    if amount <= 0:
        return bgr
    sigma = max(0.6, min(bgr.shape[:2]) / 700.0)
    return _unsharp(bgr, sigma, 0.55 * float(np.clip(amount, 0, 1)))


_GRAIN_REF_PX = 531
_GRAIN_MAX_SIGMA = 2.0


def add_grain(bgr: np.ndarray, amount: float, seed: int | None = None) -> np.ndarray:
    """모노크롬 그레인. 세기를 해상도에 비례시킨다."""
    amount = float(np.clip(amount, 0, 1))
    if amount <= 0:
        return bgr
    scale = max(bgr.shape[:2]) / _GRAIN_REF_PX
    sigma = _GRAIN_MAX_SIGMA * amount * max(0.6, min(2.0, scale))
    noise = np.random.default_rng(seed).normal(
        0, sigma, bgr.shape[:2]).astype(np.float32)[..., None]
    return np.clip(bgr.astype(np.float32) + noise, 0, 255).astype(np.uint8)


# ---------- 전체 ----------

def apply(bgr: np.ndarray, geo: FaceGeometry,
          settings: RetouchSettings | None = None,
          seed: int | None = None,
          report: bool = False):
    """프로 워크플로 순서대로 전 단계를 적용한다."""
    s = settings or RetouchSettings()
    rep = RetouchReport()

    def mark(name):
        rep.stages.append(name)

    out = bgr
    if s.white_balance > 0:
        out, rep.wb_shift = neutralize(out, s.white_balance)
        if rep.wb_shift != (0.0, 0.0):
            mark("white_balance")

    if s.blemish > 0:
        out, rep.blemishes = blemish.clean(
            out, geo, amount=s.blemish, sensitivity=s.blemish_sensitivity,
            preserve_moles=s.preserve_moles)
        mark("blemish")
    if s.redness > 0:
        out = blemish.reduce_redness(out, geo, s.redness); mark("redness")

    skin_m = regions.skin(out.shape, geo)
    if s.skin_even > 0:
        out = even_skin(out, skin_m, s.skin_even); mark("skin_even")

    if s.under_eye > 0:
        out = brighten_under_eye(out, geo, s.under_eye); mark("under_eye")
    if s.nasolabial > 0:
        out = soften_nasolabial(out, geo, s.nasolabial); mark("nasolabial")
    if s.contour > 0:
        out = contour(out, geo, s.contour); mark("contour")
    if s.local_contrast > 0:
        out = local_contrast(out, skin_m, s.local_contrast); mark("local_contrast")

    if s.sclera > 0 or s.iris_clarity > 0:
        out = treat_eyes(out, geo, s.sclera, s.iris_clarity); mark("eyes")
    if s.teeth > 0:
        out = whiten_teeth(out, geo, s.teeth); mark("teeth")
    if s.detail_sharpen > 0:
        out = sharpen_details(out, geo, s.detail_sharpen); mark("detail_sharpen")

    if s.grade > 0:
        out = grade(out, s.grade); mark("grade")
    if s.output_sharpen > 0:
        out = output_sharpen(out, s.output_sharpen); mark("output_sharpen")
    if s.grain > 0:
        out = add_grain(out, s.grain, seed); mark("grain")

    return (out, rep) if report else out


def apply_within_budget(bgr: np.ndarray, geo: FaceGeometry,
                        measure: "callable", *,
                        settings: RetouchSettings | None = None,
                        budget: float = 0.05, seed: int | None = None,
                        steps: tuple[float, ...] = (1.0, 0.7, 0.45, 0.25),
                        ) -> tuple[np.ndarray, RetouchReport, float, float]:
    """아이덴티티 예산 안에서 최대한 강하게 보정한다.

    리터처도 마지막에 "아직 이 사람으로 보이나"를 확인한다. 그걸 자동화한
    것이 이 함수다. 전체 강도를 100%로 걸어 보고, 유사도 손실이 예산을
    넘으면 70% → 45% → 25% 로 물러선다.

    measure(image) -> Δcos (음수). 임베딩 모델을 이 모듈에 끌어들이지 않기
    위해 콜러블로 받는다.

    반환: (이미지, 리포트, 실제 Δcos, 적용된 배율)
    """
    s = settings or RetouchSettings()
    fields = {k: v for k, v in s.__dict__.items()}
    scalable = [k for k, v in fields.items()
                if isinstance(v, float) and k != "blemish_sensitivity"]

    best = None
    for factor in steps:
        cfg = RetouchSettings(**{**fields,
                                 **{k: fields[k] * factor for k in scalable}})
        out, rep = apply(bgr, geo, cfg, seed=seed, report=True)
        delta = measure(out)
        if best is None:
            best = (out, rep, delta, factor)
        if delta >= -abs(budget):
            return out, rep, delta, factor
        best = (out, rep, delta, factor)      # 더 약한 쪽이 항상 낫다
    return best
