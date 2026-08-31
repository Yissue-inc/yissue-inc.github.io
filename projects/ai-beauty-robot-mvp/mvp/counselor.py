"""상담 멘트 생성 (LLM 어댑터) + 규제 금지어 필터.

⚠️ LLM 만 믿지 마세요. 시스템 프롬프트에 금지어를 넣어도 새어 나옵니다.
   **출력 후 필터를 한 번 더 통과**시키고, 걸리면 안전한 템플릿 문장으로 대체합니다.
   화장품법·의료기기법상 '진단/치료/효능 단정' 표현은 회사 리스크입니다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 의료기기 오인 / 효능 단정 표현
BANNED_PATTERNS = [
    r"진단", r"치료", r"질환", r"질병", r"병변", r"처방", r"의학적",
    r"완치", r"낫습니다", r"낫게", r"제거됩니다", r"없어집니다", r"사라집니다",
    r"개선을?\s*보장", r"효과를?\s*보장", r"100\s*%", r"부작용\s*없",
    r"아토피", r"건선", r"피부염", r"주사(?:비)?피부",
]
_BANNED_RE = re.compile("|".join(BANNED_PATTERNS))

SAFE_FALLBACK = (
    "측정 결과를 바탕으로 지금 신경 쓰이실 만한 항목을 정리해드렸어요. "
    "가벼운 제품부터 손등에 발라보시고 느낌을 알려주세요."
)


def sanitize(text: str) -> tuple[str, list[str]]:
    """금지어가 하나라도 있으면 통째로 안전 문장으로 대체하고, 무엇이 걸렸는지 반환."""
    hits = sorted(set(_BANNED_RE.findall(text)))
    return (SAFE_FALLBACK, hits) if hits else (text, [])


@dataclass
class Script:
    greeting: str
    concerns_line: str
    usage_tip: str
    blocked_terms: list[str]


class Counselor:
    name = "base"
    def script(self, measurement, profile, recs) -> Script: raise NotImplementedError


class TemplateCounselor(Counselor):
    """LLM 없이도 데모가 되는 템플릿 상담사. 네트워크 폴백으로도 씁니다."""

    name = "template"
    LABELS = {"dryness": "건조함", "redness": "붉은기", "oiliness": "유분",
              "pore": "모공", "texture": "결", "wrinkle": "잔주름",
              "pigmentation": "색소", "dark_circle": "눈가 어두움",
              "acne": "트러블", "tone": "톤 균일도"}

    def script(self, measurement, profile, recs) -> Script:
        top = [self.LABELS.get(k, k) for k, _ in measurement.top_concerns(3)]
        text = (f"오늘 측정에서는 {', '.join(top)} 항목이 상대적으로 높게 나왔어요. "
                f"{profile.age_band} · {profile.skin_type} 피부 기준으로 두 가지를 골라봤습니다.")
        clean, hits = sanitize(text)
        return Script(
            greeting="안녕하세요, 피부 측정이 끝났어요.",
            concerns_line=clean,
            usage_tip="손등 안쪽에 소량 발라보시고, 따갑거나 붉어지면 바로 닦아내세요.",
            blocked_terms=hits,
        )


class ClaudeCounselor(Counselor):
    """Claude API 어댑터 (실제 연동 시 사용).

        pip install anthropic
        from anthropic import Anthropic
        client = Anthropic()
        msg = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=400,
            system=SYSTEM_PROMPT,              # 금지어 목록 + 출력 스키마 명시
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )

    구현 규칙 4가지:
      1. 출력을 JSON 스키마로 강제하고, 파싱 실패 시 TemplateCounselor 로 폴백
      2. 추천 제품 ID 는 반드시 화이트리스트 검증 (없는 제품을 지어내면 폐기 후 재시도)
      3. 응답을 스트리밍으로 받아 첫 문장을 0.5초 내 표시 — 그 사이 로봇 픽을 병렬 시작
      4. 최종 출력에 sanitize() 를 반드시 적용
    """

    name = "claude"

    def __init__(self, model: str = "claude-sonnet-5", fallback: Counselor | None = None):
        self.model = model
        self.fallback = fallback or TemplateCounselor()

    def script(self, measurement, profile, recs) -> Script:
        raise NotImplementedError("W9 과제. 지금은 TemplateCounselor 를 사용하세요.")
