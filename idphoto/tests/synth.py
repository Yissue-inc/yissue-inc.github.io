"""잡티 검출 평가용 합성 데이터.

**국소 피부값 대비**로 섭동을 준다. 고정 RGB 색을 칠하면 안 된다 — 피부색이
칠하려는 색보다 이미 어둡거나 붉은 부위에서는 '잡티'가 오히려 밝고 덜 붉은
얼룩이 되어, 검출기가 맞게 무시했는데도 재현율이 낮게 나온다(실제로 겪었다).

여드름과 점의 정의는 blemish.py 와 같다:
  여드름 = 어둡고(ΔL<0) 붉다(Δa>0)
  점     = 어둡고(ΔL<0) 붉지 않다(Δa≈0)
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Spot:
    x: int
    y: int
    radius: int
    kind: str          # "acne" | "mole"
    dL: float
    da: float


def _local_median(lab: np.ndarray, x: int, y: int, r: int) -> np.ndarray:
    h, w = lab.shape[:2]
    p = lab[max(0, y - r * 4):min(h, y + r * 4),
            max(0, x - r * 4):min(w, x + r * 4)]
    return np.median(p.reshape(-1, 3), axis=0)


def plant(bgr: np.ndarray, skin_mask: np.ndarray, *,
          n_acne: int = 12, n_mole: int = 5, seed: int = 0,
          acne_dL: tuple[float, float] = (-26.0, -14.0),
          acne_da: tuple[float, float] = (9.0, 18.0),
          mole_dL: tuple[float, float] = (-34.0, -20.0),
          min_sep: int = 14) -> tuple[np.ndarray, list[Spot]]:
    """피부 위에 여드름과 점을 심는다. (이미지, 진리값 목록) 반환."""
    rng = np.random.default_rng(seed)
    out = bgr.copy()
    ys, xs = np.nonzero(skin_mask > 140)
    if len(ys) == 0:
        return out, []

    spots: list[Spot] = []
    for kind, count in (("acne", n_acne), ("mole", n_mole)):
        placed = 0
        for _ in range(count * 40):
            if placed >= count:
                break
            j = int(rng.integers(0, len(ys)))
            cx, cy = int(xs[j]), int(ys[j])
            if any(abs(cx - s.x) < min_sep and abs(cy - s.y) < min_sep for s in spots):
                continue
            r = int(rng.integers(3, 7))

            lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB).astype(np.float32)
            base = _local_median(lab, cx, cy, r)
            if kind == "acne":
                dL = float(rng.uniform(*acne_dL))
                da = float(rng.uniform(*acne_da))
            else:
                dL = float(rng.uniform(*mole_dL))
                da = float(rng.uniform(-1.5, 1.5))

            target = np.clip(base + np.array([dL, da, 0.0], np.float32), 0, 255)
            patch = np.zeros_like(lab)
            patch[:] = target
            m = np.zeros(out.shape[:2], np.float32)
            cv2.circle(m, (cx, cy), r, 1.0, -1)
            m = cv2.GaussianBlur(m, (0, 0), max(0.8, r * 0.35))[..., None]

            blended = lab * (1 - m) + patch * m
            out = cv2.cvtColor(np.clip(blended, 0, 255).astype(np.uint8),
                               cv2.COLOR_LAB2BGR)
            spots.append(Spot(cx, cy, r, kind, dL, da))
            placed += 1
    return out, spots


def score(spots: list[Spot], mask: np.ndarray) -> dict:
    """진리값 대비 재현율/오검출을 센다."""
    acne = [s for s in spots if s.kind == "acne"]
    mole = [s for s in spots if s.kind == "mole"]
    hit = lambda s: bool(mask[s.y, s.x] > 0)
    tp = sum(hit(s) for s in acne)
    mole_hit = sum(hit(s) for s in mole)
    return {
        "acne_total": len(acne), "acne_found": tp,
        "recall": tp / len(acne) if acne else 0.0,
        "mole_total": len(mole), "mole_removed": mole_hit,
        "mole_preserved": len(mole) - mole_hit,
    }


def score_full(spots: list[Spot], mask: np.ndarray, skin: np.ndarray) -> dict:
    """재현율 + 오검출까지. 오검출은 진리값과 겹치지 않는 연결성분 수로 센다."""
    import cv2 as _cv
    base = score(spots, mask)
    n, labels, stats, _ = _cv.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    matched = set()
    for s in spots:
        li = int(labels[s.y, s.x])
        if li > 0:
            matched.add(li)
    fp = sum(1 for i in range(1, n) if i not in matched)
    base["components"] = n - 1
    base["false_positives"] = fp
    base["precision"] = (n - 1 - fp) / (n - 1) if n > 1 else 0.0
    return base
