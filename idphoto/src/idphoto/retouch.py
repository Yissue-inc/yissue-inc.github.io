"""S7 — 리터칭 레이어.

전문 리터처의 손작업을 알고리즘화한다. 가장 중요한 원칙 하나:
**고주파(모공·솜털·잔주름)를 보존한다.** 여기를 뭉개면 즉시 'AI 티'가 난다.
주파수 분리로 저주파(피부톤·음영)만 고르고, 텍스처는 그대로 둔다.

모든 단계는 0..1 강도를 받는다. 사용자 '보정 강도' 슬라이더에 그대로 매핑된다.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .geometry import FaceGeometry
from .masks import eye_mask, skin_mask


@dataclass(frozen=True)
class RetouchSettings:
    """0 = 무보정. 기본값은 의도적으로 보수적이다 — 과보정이 이탈의 최대 원인."""

    skin_even: float = 0.55        # 저주파 톤 고르기
    dodge_burn: float = 0.30       # 입체감
    eye_clarity: float = 0.35      # 눈 또렷함 (공막 과백화 금지)
    grade: float = 0.40            # 컬러 그레이딩
    grain: float = 0.35            # 필름 그레인 (디지털 평탄함 제거)

    @classmethod
    def from_intensity(cls, t: float) -> "RetouchSettings":
        """사용자 '보정 강도' 슬라이더 0..1 → 전체 설정.

        t=0 은 모든 항목이 0 이다. 사용자가 0 을 골랐으면 사진에 손대지 않는다.
        """
        t = float(np.clip(t, 0.0, 1.0))
        return cls(skin_even=0.75 * t, dodge_burn=0.45 * t,
                   eye_clarity=0.50 * t, grade=0.60 * t, grain=0.45 * t)

    @classmethod
    def for_generated(cls, t: float = 0.5) -> "RetouchSettings":
        """생성 이미지용. 그레인 하한을 둔다.

        생성물은 디지털적으로 너무 평탄해서, 보정을 전혀 하지 않아도 약간의
        그레인이 있어야 촬영물처럼 보인다. 사용자가 올린 원본 사진에는
        적용하지 않는다 — 거기엔 이미 촬영 노이즈가 있다.
        """
        s = cls.from_intensity(t)
        return cls(skin_even=s.skin_even, dodge_burn=s.dodge_burn,
                   eye_clarity=s.eye_clarity, grade=s.grade,
                   grain=max(0.25, s.grain))

    @classmethod
    def senior(cls, t: float = 0.5) -> "RetouchSettings":
        """50대 이상 프리셋. 주름을 지우면 '다른 사람'이 된다."""
        s = cls.from_intensity(t)
        return cls(skin_even=min(s.skin_even, 0.35), dodge_burn=s.dodge_burn * 0.7,
                   eye_clarity=s.eye_clarity, grade=s.grade, grain=s.grain)


def _blend(base: np.ndarray, layer: np.ndarray, mask: np.ndarray,
           amount: float) -> np.ndarray:
    """mask(0..255) × amount 비율로 layer 를 base 위에 섞는다."""
    if amount <= 0:
        return base
    a = (mask.astype(np.float32) / 255.0 * float(np.clip(amount, 0, 1)))[..., None]
    return (base.astype(np.float32) * (1 - a) + layer.astype(np.float32) * a
            ).clip(0, 255).astype(np.uint8)


def even_skin(bgr: np.ndarray, mask: np.ndarray, amount: float) -> np.ndarray:
    """주파수 분리 — 저주파만 고르고 고주파 텍스처는 그대로 되돌린다."""
    if amount <= 0:
        return bgr
    r = max(2.0, min(bgr.shape[:2]) / 90.0)
    low = cv2.GaussianBlur(bgr, (0, 0), r)
    high = bgr.astype(np.int16) - low.astype(np.int16)      # 텍스처 (부호 있음)

    # 저주파를 엣지 보존 필터로 고른다 — 얼룩·홍조·톤 불균일이 사라진다
    d = int(max(5, min(bgr.shape[:2]) / 45)) | 1
    low_even = cv2.bilateralFilter(low, d, 45, 45)

    merged = np.clip(low_even.astype(np.int16) + high, 0, 255).astype(np.uint8)
    return _blend(bgr, merged, mask, amount)


def dodge_and_burn(bgr: np.ndarray, mask: np.ndarray, amount: float) -> np.ndarray:
    """국소 명암으로 입체감. 광대·콧대·턱선이 살아난다."""
    if amount <= 0:
        return bgr
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[:, :, 0]
    r = max(3.0, min(bgr.shape[:2]) / 22.0)
    local = cv2.GaussianBlur(L, (0, 0), r)
    lab[:, :, 0] = np.clip(L + (L - local) * 0.55, 0, 255)
    out = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)
    return _blend(bgr, out, mask, amount)


def clarify_eyes(bgr: np.ndarray, geo: FaceGeometry, amount: float) -> np.ndarray:
    """눈 또렷하게. 공막을 하얗게 태우지 않는다 — 즉시 가짜 티가 난다."""
    if amount <= 0:
        return bgr
    m = eye_mask(bgr.shape, geo)
    sharp = cv2.addWeighted(bgr, 1.45, cv2.GaussianBlur(bgr, (0, 0), 1.2), -0.45, 0)
    hsv = cv2.cvtColor(sharp, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] *= 0.90          # 채도 -10%
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.05, 0, 253)   # 밝기 +5%, 클리핑 금지
    layer = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    return _blend(bgr, layer, m, amount)


def grade(bgr: np.ndarray, amount: float) -> np.ndarray:
    """한국 증명사진 관행: 약간 쿨한 화이트밸런스 + 하이라이트는 살짝 웜."""
    if amount <= 0:
        return bgr
    f = bgr.astype(np.float32)
    luma = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)[..., None] / 255.0
    cool = np.array([1.030, 1.004, 0.986], np.float32)     # B, G, R 게인
    warm = np.array([0.985, 1.000, 1.022], np.float32)
    gain = cool * (1 - luma) + warm * luma
    out = np.clip(f * gain, 0, 255).astype(np.uint8)
    return cv2.addWeighted(bgr, 1 - amount, out, amount, 0)


#: 그레인 세기를 정한 기준 해상도(긴 변, px)와 그 해상도에서의 최대 sigma.
#: 증명사진 출력(413x531 @300dpi)에서 육안으로 '필름 질감'이 느껴지되
#: 노이즈로 읽히지는 않는 상한이 sigma≈2.0 이다.
_GRAIN_REF_PX = 531
_GRAIN_MAX_SIGMA = 2.0


def add_grain(bgr: np.ndarray, amount: float, seed: int | None = None) -> np.ndarray:
    """모노크롬 그레인. 생성물 특유의 디지털 평탄함을 지운다.

    세기를 해상도에 비례시킨다. 같은 sigma 라도 작은 이미지에서는 훨씬
    거칠게 보이기 때문에, 고정값을 쓰면 규격 크롭(413px)에서 노이즈가 튄다.
    """
    amount = float(np.clip(amount, 0, 1))
    if amount <= 0:
        return bgr
    scale = max(bgr.shape[:2]) / _GRAIN_REF_PX
    sigma = _GRAIN_MAX_SIGMA * amount * max(0.6, min(2.0, scale))
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, sigma, bgr.shape[:2]).astype(np.float32)[..., None]
    return np.clip(bgr.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def apply(bgr: np.ndarray, geo: FaceGeometry,
          settings: RetouchSettings | None = None,
          seed: int | None = None) -> np.ndarray:
    """전체 리터칭 파이프라인. 순서가 중요하다 — 그레인은 반드시 마지막."""
    s = settings or RetouchSettings()
    m = skin_mask(bgr.shape, geo)
    out = even_skin(bgr, m, s.skin_even)
    out = dodge_and_burn(out, m, s.dodge_burn)
    out = clarify_eyes(out, geo, s.eye_clarity)
    out = grade(out, s.grade)
    return add_grain(out, s.grain, seed)
