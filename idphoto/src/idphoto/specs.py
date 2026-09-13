"""증명사진 규격 정의.

수치 출처는 docs/fact-check.md 참조. 규격은 발급처 고시가 1차 출처이며,
여기 값은 구현 기본값이다 — 실제 제출 전 반드시 발급처 규정을 확인할 것.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhotoSpec:
    key: str
    label: str
    width_mm: float
    height_mm: float
    head_min_mm: float          # 정수리(머리카락 포함) ~ 턱끝
    head_max_mm: float
    top_margin_mm: float        # 프레임 상단 ~ 정수리 목표 여백
    dpi: int
    background: str             # 배경 프리셋 키
    accepts_ai: bool            # AI 생성물 제출 허용 여부 (보수적 기본값)
    note: str
    head_measure: str = "skull"
    """머리 길이를 어디서 재는가.

    "skull" — 머리카락을 제외한 머리 최상부부터 턱까지. 외교부 여권 사진
              규정이 명시하는 기준이며, 국내 증명사진 관행도 이를 따른다.
    "hair"  — 머리카락 최상부부터 턱까지. 규정이 없는 프로필 사진에서
              시각적으로 자연스러운 크기를 잡을 때 쓴다.
    """

    @property
    def head_target_mm(self) -> float:
        return (self.head_min_mm + self.head_max_mm) / 2.0

    @property
    def px_per_mm(self) -> float:
        return self.dpi / 25.4

    @property
    def size_px(self) -> tuple[int, int]:
        return (round(self.width_mm * self.px_per_mm),
                round(self.height_mm * self.px_per_mm))

    def head_range_px(self) -> tuple[float, float]:
        return (self.head_min_mm * self.px_per_mm,
                self.head_max_mm * self.px_per_mm)


SPECS: dict[str, PhotoSpec] = {
    "passport_kr": PhotoSpec(
        key="passport_kr", label="여권사진 (대한민국)",
        width_mm=35, height_mm=45, head_min_mm=32, head_max_mm=36,
        top_margin_mm=3.0, dpi=300, background="white",
        accepts_ai=False,
        note="외교부 규정상 배경 합성·편집 사진은 제출 불가. 규격 미리보기 용도로만 제공한다.",
        head_measure="skull",
    ),
    "id_kr": PhotoSpec(
        key="id_kr", label="일반 증명사진 / 이력서",
        width_mm=35, height_mm=45, head_min_mm=30, head_max_mm=34,
        top_margin_mm=4.0, dpi=300, background="light_gray",
        accepts_ai=True,
        note="이력서·사내 프로필·일반 서류용. 공공기관 채용은 AI 사진 불가 공고가 있으므로 제출처 확인 필요.",
        head_measure="skull",
    ),
    "half_kr": PhotoSpec(
        key="half_kr", label="반명함 (3x4cm)",
        width_mm=30, height_mm=40, head_min_mm=25, head_max_mm=29,
        top_margin_mm=3.5, dpi=300, background="white",
        accepts_ai=True,
        note="학생증·사원증 등.",
        head_measure="skull",
    ),
    "profile_sq": PhotoSpec(
        key="profile_sq", label="프로필 정사각 (링크드인·사내)",
        width_mm=50, height_mm=50, head_min_mm=28, head_max_mm=34,
        top_margin_mm=7.0, dpi=300, background="soft_blue",
        accepts_ai=True,
        note="규제 제약이 가장 적고 마진이 좋은 세그먼트.",
        head_measure="hair",
    ),
}

DEFAULT_SPEC = "id_kr"


def get_spec(key: str) -> PhotoSpec:
    try:
        return SPECS[key]
    except KeyError:
        raise KeyError(f"unknown spec {key!r}; available: {', '.join(SPECS)}") from None
