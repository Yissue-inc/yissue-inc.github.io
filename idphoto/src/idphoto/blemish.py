"""잡티 제거 — 힐링 브러시의 알고리즘 대응.

전역 스무딩과의 결정적 차이: **잡티만 골라 지우고 나머지 피부는 손대지 않는다.**
전문 리터처가 주파수 분리보다 먼저 힐링을 하는 이유도 같다. 전역으로 뭉개면
잡티와 함께 모공·솜털이 사라지고, 그게 'AI 티'의 정체다.

여드름과 점을 구분한다:
  - 여드름·홍조 = 붉다(a* 상승) + 작다 + 일시적      → 제거
  - 점·주근깨   = 어둡다(L 하강) + 붉지 않다 + 영구적 → **보존**

점을 지우면 본인을 식별하는 특징이 사라진다. 기본값은 보존이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .geometry import FaceGeometry
from .regions import skin


#: 피부 면적 대비 제거 가능한 최대 비율.
#:
#: 검출기는 완벽하지 않고, 기질(필름 그레인, 저조도 노이즈)에 따라 오검출이
#: 늘어난다. 임계값만으로는 그 피해가 무한정 커질 수 있으므로 총량에 상한을
#: 둔다. 점수가 높은 후보부터 채우다가 상한에서 멈춘다 — 확실한 잡티는 지우고
#: 애매한 것은 남기는 쪽으로 자동으로 기운다.
DEFAULT_MAX_AREA_FRAC = 0.015


@dataclass
class BlemishReport:
    count: int = 0
    area_frac: float = 0.0          # 피부 면적 대비 제거 면적
    preserved_moles: int = 0
    capped: int = 0                 # 면적 상한에 걸려 남겨둔 후보 수
    sizes: list[int] = field(default_factory=list)

    def summary(self) -> str:
        tail = f", 상한으로 {self.capped}개 보류" if self.capped else ""
        return (f"잡티 {self.count}개 제거 (피부의 {self.area_frac * 100:.2f}%), "
                f"점 {self.preserved_moles}개 보존{tail}")


def _split(bgr: np.ndarray, sigma: float):
    low = cv2.GaussianBlur(bgr, (0, 0), sigma)
    return low, bgr.astype(np.int16) - low.astype(np.int16)


def detect(bgr: np.ndarray, geo: FaceGeometry, *,
           sensitivity: float = 0.5,
           preserve_moles: bool = True,
           max_area_frac: float = DEFAULT_MAX_AREA_FRAC,
           ) -> tuple[np.ndarray, BlemishReport]:
    """잡티 마스크(0..255)와 리포트를 돌려준다."""
    h, w = bgr.shape[:2]
    skin_m = skin(bgr.shape, geo)
    skin_bin = skin_m > 110
    report = BlemishReport()
    if not skin_bin.any():
        return np.zeros((h, w), np.uint8), report

    face_w = max(8.0, geo.box[2])
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    L, A = lab[:, :, 0], lab[:, :, 1]

    # 잡티 크기 대역: 얼굴 폭의 0.8%~6%. 이보다 작으면 모공, 크면 그림자다.
    lo_px = max(2.0, face_w * 0.008)
    hi_px = max(lo_px + 2.0, face_w * 0.060)

    # 모폴로지 black-hat / top-hat 으로 '잡티 크기'의 얼룩만 추출한다.
    #
    # DoG 밴드패스를 먼저 시도했으나 재현율이 0.5에서 멈췄다. 가우시안은
    # 등방 저역통과라, 잡티 주변의 밝은 피부까지 함께 흐려 대비를 깎는다.
    # black-hat(닫힘 - 원본)은 구조요소보다 작은 어두운 구조만 정확히
    # 남기므로 얼룩 추출에는 이쪽이 정석이다.
    #
    #   black-hat(L)  → 주변보다 어두운 작은 점
    #   top-hat(a*)   → 주변보다 붉은 작은 점
    se_px = max(3, int(round(hi_px))) | 1
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (se_px, se_px))
    dark = cv2.morphologyEx(L, cv2.MORPH_BLACKHAT, se)
    red = cv2.morphologyEx(A, cv2.MORPH_TOPHAT, se)

    # 모공·필름 그레인 크기의 잡음을 걷어낸다
    if lo_px > 2.0:
        k = max(0.6, lo_px * 0.30)
        dark = cv2.GaussianBlur(dark, (0, 0), k)
        red = cv2.GaussianBlur(red, (0, 0), k)

    def zscore(x: np.ndarray) -> np.ndarray:
        """MAD 기반 로버스트 z-score.

        표준편차 대신 MAD를 쓰는 이유: 잡티 자체가 분포의 꼬리라서,
        표준편차로 정규화하면 잡티가 많은 얼굴일수록 분모가 커져
        잡티가 덜 검출되는 역전이 일어난다.
        """
        v = x[skin_bin]
        med = float(np.median(v))
        mad = float(np.median(np.abs(v - med)))
        scale = mad * 1.4826 if mad > 1e-6 else (float(np.std(v)) or 1.0)
        return np.clip((x - med) / scale, -8.0, 8.0)

    dark_n, red_n = zscore(dark), zscore(red)
    # 붉은기에 가중 — 여드름 신호
    score = 0.45 * dark_n + 0.55 * red_n
    # 임계값은 시그마 단위. 민감도 0.5 → 2.0σ (합성 스윕으로 보정, F1 기준).
    thr = 3.2 - 2.4 * float(np.clip(sensitivity, 0, 1))

    cand = ((score > thr) & skin_bin).astype(np.uint8)
    k = np.ones((3, 3), np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, k)
    cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE, k)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(cand, 8)
    mask = np.zeros((h, w), np.uint8)
    min_a, max_a = np.pi * (lo_px / 2) ** 2, np.pi * (hi_px / 2) ** 2

    accepted = []          # (평균 점수, 라벨, 면적)
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        bw, bh = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        if not (min_a <= area <= max_a):
            continue
        if max(bw, bh) > hi_px * 1.8:                 # 길쭉한 것은 주름·머리카락
            continue
        if min(bw, bh) == 0 or max(bw, bh) / min(bw, bh) > 3.2:
            continue

        blob = labels == i
        if preserve_moles:
            # 붉지 않으면서(z<1.2) 뚜렷하게 어두우면(z>2.0) 점으로 본다
            if float(red_n[blob].mean()) < 1.2 and float(dark_n[blob].mean()) > 2.0:
                report.preserved_moles += 1
                continue
        accepted.append((float(score[blob].mean()), i, area))

    # 확신이 큰 것부터 면적 상한까지만 채운다
    skin_area = float(skin_bin.sum())
    budget = max_area_frac * skin_area
    used = 0.0
    for conf, i, area in sorted(accepted, reverse=True):
        if used + area > budget:
            report.capped += 1
            continue
        mask[labels == i] = 255
        report.sizes.append(area)
        used += area

    report.count = len(report.sizes)
    report.area_frac = used / skin_area if skin_area else 0.0
    r = max(1, int(round(lo_px * 0.5))) | 1
    return cv2.dilate(mask, np.ones((r, r), np.uint8)), report


def heal(bgr: np.ndarray, mask: np.ndarray, geo: FaceGeometry,
         amount: float = 1.0) -> np.ndarray:
    """잡티 영역을 주변 텍스처로 메운다.

    저주파(색 얼룩)는 인페인팅으로 지우고, 고주파(모공 질감)는 주변의
    중앙값으로 대체한다. 고주파를 0으로 만들면 그 자리만 매끈해져
    '수정한 티'가 나므로, 질감의 통계를 유지하는 것이 중요하다.
    """
    if amount <= 0 or not mask.any():
        return bgr

    face_w = max(8.0, geo.box[2])
    sigma = max(1.5, face_w * 0.012)
    low, high = _split(bgr, sigma)

    r = max(3, int(round(face_w * 0.03))) | 1
    low_fixed = cv2.inpaint(low, mask, r, cv2.INPAINT_TELEA)

    kmed = max(3, int(round(face_w * 0.02))) | 1
    kmed = min(kmed, 31)
    high_med = cv2.medianBlur((high + 128).clip(0, 255).astype(np.uint8),
                              kmed).astype(np.int16) - 128

    m = (mask.astype(np.float32) / 255.0 * float(np.clip(amount, 0, 1)))[..., None]
    high_fixed = high * (1 - m) + high_med * m
    merged = np.clip(low_fixed.astype(np.float32) * m
                     + low.astype(np.float32) * (1 - m) + high_fixed, 0, 255)
    return merged.astype(np.uint8)


def reduce_redness(bgr: np.ndarray, geo: FaceGeometry,
                   amount: float = 0.5) -> np.ndarray:
    """홍조 완화. Lab a* 채널에서 피부 중앙값 위로 튀는 부분만 눌러 준다.

    채도를 전역으로 낮추면 얼굴이 창백해진다. 붉은 쪽 편차만 압축해야
    혈색은 남기고 홍조만 빠진다.
    """
    if amount <= 0:
        return bgr
    skin_m = skin(bgr.shape, geo)
    sel = skin_m > 110
    if not sel.any():
        return bgr

    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    A = lab[:, :, 1]
    med = float(np.median(A[sel]))
    excess = np.clip(A - med, 0, None)

    w = (skin_m.astype(np.float32) / 255.0) * float(np.clip(amount, 0, 1))
    # 계수 0.55 는 과했다 — 단독으로 Δcos -0.048 을 냈다(가드 예산 0.05의 대부분).
    # 0.30 이면 홍조는 눈에 띄게 빠지면서 아이덴티티 비용이 1/3 이하로 준다.
    lab[:, :, 1] = A - excess * 0.30 * w
    return cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)


def clean(bgr: np.ndarray, geo: FaceGeometry, *, amount: float = 1.0,
          sensitivity: float = 0.5, preserve_moles: bool = True,
          max_area_frac: float = DEFAULT_MAX_AREA_FRAC,
          ) -> tuple[np.ndarray, BlemishReport]:
    """검출 + 힐링을 한 번에."""
    mask, report = detect(bgr, geo, sensitivity=sensitivity,
                          preserve_moles=preserve_moles,
                          max_area_frac=max_area_frac)
    return heal(bgr, mask, geo, amount), report
