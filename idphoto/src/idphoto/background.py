"""S6 — 배경 분리와 스튜디오 배경 합성.

배경을 단색으로 채우면 즉시 '합성 티'가 난다. 실제 사진관 배경은 심리스
페이퍼에 조명이 떨어지면서 생기는 미세한 방사형 그라데이션을 갖는다.
이 한 가지 디테일이 체감 품질을 크게 바꾼다.

매팅은 두 경로다:
  1. 배경이 이미 균일하면 색 거리로 매트를 뽑는다 (생성물에 적합, 빠르고 정확)
  2. 아니면 GrabCut 으로 인물 영역을 추정한다 (업로드 셀카용, 경계가 거칠다)

머리카락 경계까지 정확히 뽑으려면 BiRefNet(MIT) 같은 매팅 모델이 필요하다.
상용 가능하므로 프로덕션에서는 교체할 것 — 여기서는 가중치 없이 돌아가는
베이스라인을 둔다.
"""
from __future__ import annotations

import cv2
import numpy as np

from .geometry import FaceGeometry

#: 사진관 배경 프리셋 — (중심색 BGR, 가장자리 배율)
#:
#: 가장자리 배율은 방사형 폴오프의 세기다. 1.0 이면 완전히 평탄하다.
#:
#: 처음에는 0.88~0.93 으로 잡았는데(그라데이션이 '합성 티'를 지운다는 판단),
#: 레퍼런스 서비스 출력을 실측해 보니 훨씬 평탄했다:
#:   좌우 가장자리 L* 세로 프로파일 252~254 (어깨선 위 구간 전체)
#:   a*, b* 편차 +0.0, +1.0 — 사실상 순수 무채색
#: 45mm 높이에 걸쳐 L* 2 만큼 떨어지는 정도이므로 배율로 환산하면 0.99 수준이다.
#: 실측에 맞춰 낮췄다. 과한 그라데이션이 오히려 합성 티를 낸다.
BACKDROPS: dict[str, tuple[tuple[int, int, int], float]] = {
    "white":      ((252, 253, 253), 0.990),   # 레퍼런스 실측값에 맞춘 기본값
    "light_gray": ((236, 236, 235), 0.984),
    "soft_blue":  ((238, 231, 223), 0.980),   # BGR — 연한 블루그레이
    "warm_gray":  ((233, 235, 238), 0.984),
}


def studio_backdrop(size: tuple[int, int], preset: str = "light_gray",
                    focus: tuple[float, float] | None = None) -> np.ndarray:
    """심리스 페이퍼 + 방사형 폴오프 배경을 만든다.

    size 는 (w, h). focus 는 광원이 떨어지는 중심(0..1 정규화 좌표).
    """
    w, h = size
    color, edge = BACKDROPS.get(preset, BACKDROPS["light_gray"])
    fx, fy = focus or (0.5, 0.42)          # 인물 머리 뒤쪽이 가장 밝다

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx / w) - fx) ** 2 + ((yy / h) - fy) ** 2)
    d /= max(d.max(), 1e-6)
    gain = (1.0 - (1.0 - edge) * d ** 1.35)[..., None]

    bg = np.array(color, np.float32) * gain
    return np.clip(bg, 0, 255).astype(np.uint8)


def sample_backdrop(bgr: np.ndarray, tol: int = 26) -> tuple[np.ndarray | None, float]:
    """증명사진의 배경색을 추정한다. (배경 BGR, 일관성) — 실패 시 (None, spread).

    **아래쪽 모서리를 쓰면 안 된다.** 제대로 구도가 잡힌 증명사진은 어깨가
    하단 가장자리까지 닿으므로, 아래 모서리에 있는 것은 배경이 아니라 옷이다.
    실측(인핸즈 출력): 네 모서리 전부 → 일관성 116(허용치 26의 4배, 추정 실패),
    위쪽 모서리만 → 일관성 0.0~0.5(완벽).

    위쪽 모서리와 어깨선 위 좌우 띠만 본다.
    """
    h, w = bgr.shape[:2]
    k = max(4, min(h, w) // 40)
    side = max(3, int(w * 0.04))
    upper = int(h * 0.45)                      # 어깨선보다 확실히 위

    patches = [bgr[:k, :k].reshape(-1, 3), bgr[:k, -k:].reshape(-1, 3),
               bgr[:upper, :side].reshape(-1, 3), bgr[:upper, -side:].reshape(-1, 3)]
    ref = np.concatenate(patches)
    bg = np.median(ref, axis=0)
    spread = float(np.median(np.abs(ref - bg)))
    return (bg if spread <= tol else None), spread


def matte_uniform(bgr: np.ndarray, tol: int = 26) -> np.ndarray | None:
    """배경이 균일할 때 색 거리로 알파 매트를 뽑는다. 실패 시 None."""
    bg, _ = sample_backdrop(bgr, tol)
    if bg is None:
        return None

    diff = np.abs(bgr.astype(np.int16) - bg.astype(np.int16)).max(axis=2)
    alpha = np.clip((diff.astype(np.float32) - tol) / (tol * 1.6), 0, 1)

    # 가장 큰 연결 성분만 남긴다 — 배경 얼룩이 전경으로 잡히는 것을 막는다
    solid = (alpha > 0.5).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(solid, 8)
    if n > 1:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        alpha = alpha * (labels == largest)
    return cv2.GaussianBlur(alpha, (0, 0), max(1.0, min(h, w) / 400))


def matte_grabcut(bgr: np.ndarray, geo: FaceGeometry, iters: int = 4) -> np.ndarray:
    """얼굴 위치로부터 인물 영역을 추정한다. 경계가 거칠어 폴백용이다."""
    h, w = bgr.shape[:2]
    x, y, bw, bh = geo.box
    mask = np.full((h, w), cv2.GC_PR_BGD, np.uint8)

    # 머리~어깨를 확실한 전경으로, 프레임 가장자리를 확실한 배경으로 둔다
    cx = x + bw / 2
    head = (int(max(0, cx - bw * 0.9)), int(max(0, y - bh * 0.6)),
            int(min(w, cx + bw * 0.9)), int(min(h, y + bh * 1.25)))
    body = (int(max(0, cx - bw * 1.9)), int(min(h, y + bh * 1.0)),
            int(min(w, cx + bw * 1.9)), h)
    mask[head[1]:head[3], head[0]:head[2]] = cv2.GC_PR_FGD
    mask[body[1]:body[3], body[0]:body[2]] = cv2.GC_PR_FGD
    mask[int(y + bh * 0.1):int(y + bh * 0.8),
         int(x + bw * 0.2):int(x + bw * 0.8)] = cv2.GC_FGD
    m = max(2, int(min(h, w) * 0.02))
    mask[:m, :] = mask[-m:, :] = mask[:, :m] = mask[:, -m:] = cv2.GC_BGD

    try:
        cv2.grabCut(bgr, mask, None, np.zeros((1, 65), np.float64),
                    np.zeros((1, 65), np.float64), iters, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return np.ones((h, w), np.float32)

    alpha = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1.0, 0.0)
    return cv2.GaussianBlur(alpha.astype(np.float32), (0, 0),
                            max(1.0, min(h, w) / 260))


def alpha_matte(bgr: np.ndarray, geo: FaceGeometry) -> tuple[np.ndarray, str]:
    """가능한 최선의 매트를 고른다. (alpha 0..1, 사용한 방법) 반환."""
    a = matte_uniform(bgr)
    if a is not None:
        return a, "uniform"
    return matte_grabcut(bgr, geo), "grabcut"


def composite(bgr: np.ndarray, alpha: np.ndarray, preset: str = "light_gray",
              spill_suppress: float = 0.35) -> np.ndarray:
    """전경을 스튜디오 배경 위에 올린다.

    경계 화소에는 원래 배경색이 배어 있다(spill). 반투명 영역의 채도를
    낮춰 색 번짐을 줄인다 — 이걸 안 하면 초록 벽 앞에서 찍은 사진의
    머리카락 가장자리가 초록빛으로 남는다.
    """
    h, w = bgr.shape[:2]
    bg = studio_backdrop((w, h), preset)
    a = alpha[..., None].astype(np.float32)

    fg = bgr.astype(np.float32)
    if spill_suppress > 0:
        edge = (a * (1 - a) * 4.0).clip(0, 1)        # 경계에서 1, 내부/외부에서 0
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)[..., None]
        fg = fg * (1 - edge * spill_suppress) + gray * (edge * spill_suppress)

    return np.clip(fg * a + bg.astype(np.float32) * (1 - a), 0, 255).astype(np.uint8)


def key_light(bgr: np.ndarray, alpha: np.ndarray, amount: float = 0.35,
              angle_deg: float = 45.0) -> np.ndarray:
    """45도 키라이트 근사. 소프트박스가 만드는 완만한 밝기 기울기를 흉내낸다.

    물리 기반 리라이팅이 아니다. 제대로 하려면 IC-Light(Apache-2.0)를
    붙여야 하며, 프로덕션에서는 그렇게 할 것.
    """
    if amount <= 0:
        return bgr
    h, w = bgr.shape[:2]
    t = np.deg2rad(angle_deg)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    proj = ((xx / w - 0.5) * np.cos(t) + (yy / h - 0.5) * np.sin(t))
    gain = 1.0 + amount * 0.30 * np.tanh(-proj * 2.2)      # 키 쪽이 밝다
    gain = (gain * alpha + (1 - alpha))[..., None]          # 배경은 건드리지 않는다
    return np.clip(bgr.astype(np.float32) * gain, 0, 255).astype(np.uint8)
