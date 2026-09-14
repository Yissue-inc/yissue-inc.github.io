"""컨택트 시트 — 많은 후보를 한 장으로 보고 고르기 위한 도구.

사진이 수십 장이면 한 장씩 보는 것은 현실적이지 않다. 전부를 격자로 붙이고
각 칸에 순위·유사도·판정을 새겨 두면, 한 장만 보고도 어느 것이 쓸 만한지
가려낼 수 있다.

라벨은 ASCII 로만 새긴다. OpenCV 기본 폰트는 한글을 렌더링하지 못하고,
기계마다 한글 폰트 경로가 달라 깨질 위험이 있다. 한국어 설명은 표준출력의
표로 내보낸다 — 이미지에는 숫자와 판정만 있으면 충분하다.
"""
from __future__ import annotations

import cv2
import numpy as np

#: 판정별 테두리 색 (BGR)
BORDER = {
    "pass": (90, 170, 80),        # 초록 — 통과
    "near": (60, 165, 220),       # 주황 — 게이트는 통과하나 목표 미달
    "fail": (70, 70, 200),        # 빨강 — 탈락
}


def _fit(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """비율을 유지하며 (w, h) 칸에 넣는다. 남는 곳은 흰색."""
    ih, iw = img.shape[:2]
    s = min(w / iw, h / ih)
    r = cv2.resize(img, (max(1, int(iw * s)), max(1, int(ih * s))),
                   interpolation=cv2.INTER_AREA)
    canvas = np.full((h, w, 3), 246, np.uint8)
    y, x = (h - r.shape[0]) // 2, (w - r.shape[1]) // 2
    canvas[y:y + r.shape[0], x:x + r.shape[1]] = r
    return canvas


def _label(tile: np.ndarray, lines: list[str], verdict: str) -> np.ndarray:
    """칸 아래에 라벨 띠를 붙이고 판정 색으로 테두리를 두른다."""
    h, w = tile.shape[:2]
    pad = max(28, int(h * 0.075)) * len(lines)
    out = np.full((h + pad, w, 3), 252, np.uint8)
    out[:h] = tile

    scale = max(0.38, w / 620.0)
    y = h + int(pad / len(lines) * 0.68)
    for line in lines:
        cv2.putText(out, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
                    (30, 30, 30), max(1, int(scale * 1.6)), cv2.LINE_AA)
        y += int(pad / len(lines))

    color = BORDER.get(verdict, BORDER["fail"])
    cv2.rectangle(out, (0, 0), (w - 1, out.shape[0] - 1), color,
                  max(2, int(w / 150)))
    return out


def contact_sheet(entries: list[dict], cols: int = 6,
                  tile_w: int = 260) -> np.ndarray:
    """entries: [{image, rank, id_cos, verdict, note}] → 격자 한 장."""
    if not entries:
        return np.full((80, 320, 3), 246, np.uint8)

    tile_h = int(tile_w * 4.5 / 3.5)      # 증명사진 비율
    tiles = []
    for e in entries:
        lines = [f"#{e['rank']:02d}  cos {e['id_cos']:.3f}  {e['verdict'].upper()}"]
        if e.get("note"):
            lines.append(e["note"][:34])
        tiles.append(_label(_fit(e["image"], tile_w, tile_h), lines, e["verdict"]))

    th = max(t.shape[0] for t in tiles)
    tiles = [np.vstack([t, np.full((th - t.shape[0], t.shape[1], 3), 252, np.uint8)])
             if t.shape[0] < th else t for t in tiles]

    gap = 10
    rows = []
    for i in range(0, len(tiles), cols):
        row = tiles[i:i + cols]
        while len(row) < cols:
            row.append(np.full_like(tiles[0], 252))
        strip = row[0]
        for t in row[1:]:
            strip = np.hstack([strip, np.full((th, gap, 3), 252, np.uint8), t])
        rows.append(strip)

    sheet = rows[0]
    for r in rows[1:]:
        sheet = np.vstack([sheet, np.full((gap, sheet.shape[1], 3), 252, np.uint8), r])
    return cv2.copyMakeBorder(sheet, 14, 14, 14, 14, cv2.BORDER_CONSTANT,
                              value=(252, 252, 252))


def strip(entries: list[dict], tile_w: int = 420) -> np.ndarray:
    """상위 후보만 크게 가로로 붙인다."""
    return contact_sheet(entries, cols=max(1, len(entries)), tile_w=tile_w)
