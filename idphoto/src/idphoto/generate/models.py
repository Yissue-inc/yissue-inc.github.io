"""이미지 생성 모델 로스터.

단가는 2026-09 공개 정보 기준 **추정**이다. 실제 청구는 출력 토큰 기준이므로,
파일럿을 돌리면 응답의 usageMetadata 로 실측치가 나온다 — 그 값을 쓴다.

모델을 여러 개 두는 이유: 증명사진은 '얼마나 본인 같은가'가 전부인데, 그건
모델마다 크게 다르고 프롬프트로 다 메울 수 없다. 같은 입력을 여러 모델에
돌려 우리 QA 지표로 줄 세우는 것이 가장 빠른 선택 방법이다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str
    usd_per_image: float
    note: str
    deprecated: str | None = None


MODELS: dict[str, ModelSpec] = {
    "gemini-3-pro-image": ModelSpec(
        "gemini-3-pro-image", "gemini", 0.134,
        "프롬프트 준수·피사체 일관성 최상위. 유사도가 가장 중요한 티어용"),
    "gemini-3.1-flash-image": ModelSpec(
        "gemini-3.1-flash-image", "gemini", 0.067,
        "속도·비용 균형. 대중 상품 기본값 후보"),
    "gemini-3.1-flash-lite-image": ModelSpec(
        "gemini-3.1-flash-lite-image", "gemini", 0.045,
        "512px. 무료 체험·프리뷰용"),
    "gemini-2.5-flash-image": ModelSpec(
        "gemini-2.5-flash-image", "gemini", 0.039,
        "구세대", deprecated="2026-10-02 종료 — 신규 사용 금지"),
}

#: 비교 테스트 기본 조합. 가격대가 다른 세 개를 묶어 유사도 차이가 값을
#: 정당화하는지 본다.
DEFAULT_ROSTER = ["gemini-3-pro-image", "gemini-3.1-flash-image",
                  "gemini-3.1-flash-lite-image"]


def resolve(names: list[str] | None) -> list[ModelSpec]:
    specs = []
    for n in (names or DEFAULT_ROSTER):
        spec = MODELS.get(n)
        if spec is None:
            raise KeyError(f"모르는 모델 {n!r}; 가능: {', '.join(MODELS)}")
        if spec.deprecated:
            raise ValueError(f"{n}: {spec.deprecated}")
        specs.append(spec)
    return specs
