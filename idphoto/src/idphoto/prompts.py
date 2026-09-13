"""S3 — 프롬프트 프리셋과 빌더.

증명사진 프롬프트의 핵심은 "잘 만들어라"가 아니라 **"바꾸지 말 것"을
명시**하는 것이다. 이미지 생성 모델은 기본적으로 얼굴을 '예쁘게' 만들려는
편향이 강하고(얼굴 축소·눈 확대·주름 제거·피부톤 밝히기), 이것이 AI 증명사진
이탈의 최대 원인이다. PRESERVE 블록은 선택이 아니라 필수다.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product

WARDROBE = {
    "suit_black":   "a black notch-lapel suit jacket over a crisp white dress shirt",
    "suit_navy":    "a navy single-breasted suit jacket over a white dress shirt",
    "suit_charcoal": "a charcoal grey suit jacket over a light blue dress shirt",
    "shirt_white":  "a crisp white dress shirt, no jacket, collar neatly pressed",
    "knit_navy":    "a fine-gauge navy crew-neck knit over a white collared shirt",
}

BACKDROP_PROMPT = {
    "white":      "seamless pure white studio paper with a gentle radial falloff",
    "light_gray": "seamless light grey studio paper with a gentle radial falloff",
    "soft_blue":  "seamless pale blue-grey studio paper with a gentle radial falloff",
    "warm_gray":  "seamless warm grey studio paper with a gentle radial falloff",
}

LIGHTING = {
    "studio_3pt": ("three-point studio lighting: a 45-degree key softbox, a 1:2 "
                   "fill ratio, a subtle hair light, and a soft rectangular "
                   "catchlight visible in both eyes"),
    "soft_flat":  ("large frontal softbox with near-shadowless even illumination "
                   "and a soft catchlight in both eyes"),
}

#: 절대 바꾸면 안 되는 것. 모든 프롬프트에 그대로 들어간다.
PRESERVE = (
    "Keep the exact facial identity of the person in the reference photographs: "
    "eye shape and spacing, eyelid crease, nose bridge and tip, philtrum, lip "
    "shape, jawline, cheekbone structure, skin tone, moles, freckles, wrinkles, "
    "and apparent age. "
    "Do NOT slim or reshape the face. Do NOT enlarge the eyes. Do NOT remove "
    "wrinkles, moles or skin texture. Do NOT lighten the skin tone. Do NOT change "
    "the hairline. Preserve the shape of any eyeglasses exactly."
)

NEGATIVE = (
    "beauty filter, skin smoothing, plastic or airbrushed skin, anime or "
    "illustration style, oversaturated colour, asymmetric or mismatched eyes, "
    "warped eyeglass frames, extra fingers, visible text or watermark, "
    "wide-angle facial distortion"
)

FRAMING = (
    "Reframe as a formal ID photograph: head and shoulders, subject facing the "
    "camera straight on, gaze directly into the lens, shoulders square and level, "
    "neutral closed-lip expression, head vertically centred with even space on "
    "both sides."
)

LENS = ("Shot on an 85mm portrait lens at f/5.6, natural facial proportions, "
        "no wide-angle distortion.")


# ---------------------------------------------------------------------------
# 프롬프트 변형
#
# 레퍼런스 서비스 출력을 실측해 얻은 목표치(docs/reference-calibration.md):
#   유사도 0.646~0.674 · 배경 L* 252~254 거의 평탄 · a*/b* 편차 +0.0/+1.0
#   고주파 3.70 → 4.66 (질감이 오히려 증가) · 피부 Δa* +0.0 (붉은기 유지)
#   눈높이 프레임 상단 46.3% · 얼굴 중심 x 50.0% · roll -0.24°
#
# 이 수치들을 프롬프트로 직접 지시할 수 있는 형태로 옮긴 변형을 두고,
# 어느 쪽이 유사도를 더 지키는지 실측으로 고른다. 프롬프트는 추측으로
# 고르는 것이 아니라 재서 고른다.
# ---------------------------------------------------------------------------

#: 질감 보존 지시. 레퍼런스가 고주파를 오히려 늘렸다는 실측에 근거한다 —
#: 매끄러운 피부를 요구하면 이 서비스의 핵심 품질이 사라진다.
TEXTURE = (
    "Render real photographic skin: visible pores, fine vellus hair, natural "
    "texture variation. This is a photograph, not an illustration or a render."
)

#: 레퍼런스 실측을 그대로 옮긴 구도·배경 지시
MEASURED_FRAMING = (
    "Frame so the eye line sits about 46% down from the top edge and the face "
    "is horizontally centred. Keep the head perfectly upright."
)
MEASURED_BACKDROP = (
    "Background: flat neutral white, evenly lit, with almost no gradient and no "
    "colour cast at all."
)

#: 미화 금지를 한 번 더 못박는 블록. 모델의 기본 편향이 가장 강하게 나타나는
#: 항목들을 개별로 나열한다.
NO_BEAUTIFY = (
    "Do not beautify. Specifically: do not slim the jaw or cheeks, do not "
    "enlarge or reshape the eyes, do not raise the nose bridge, do not smooth "
    "away wrinkles or pores, do not whiten the skin, do not remove moles or "
    "freckles, do not change the hairline or add hair."
)


@dataclass(frozen=True)
class Preset:
    key: str
    wardrobe: str
    backdrop: str
    lighting: str = "studio_3pt"

    def as_dict(self) -> dict:
        """QA 의 MMR 다양성 선발이 쓰는 조합 키."""
        return {"wardrobe": self.wardrobe, "backdrop": self.backdrop,
                "lighting": self.lighting}


def _base(preset: Preset) -> list[tuple[str, str]]:
    return [
        ("PRESERVE — highest priority", PRESERVE),
        ("REFRAME", FRAMING),
        ("WARDROBE", WARDROBE[preset.wardrobe]),
        ("LIGHT", LIGHTING[preset.lighting]),
        ("BACKGROUND", BACKDROP_PROMPT[preset.backdrop]),
        ("LENS", LENS),
        ("AVOID", NEGATIVE),
    ]


def _v_baseline(preset: Preset) -> list[tuple[str, str]]:
    """현행. 다른 변형의 대조군이다."""
    return _base(preset)


def _v_lock(preset: Preset) -> list[tuple[str, str]]:
    """미화 금지를 항목별로 못박고 질감을 명시적으로 요구한다."""
    blocks = _base(preset)
    blocks.insert(1, ("DO NOT BEAUTIFY", NO_BEAUTIFY))
    blocks.insert(2, ("TEXTURE", TEXTURE))
    return blocks


def _v_measured(preset: Preset) -> list[tuple[str, str]]:
    """레퍼런스 실측치를 구도·배경 지시로 직접 옮긴 변형."""
    blocks = _v_lock(preset)
    return [(k, MEASURED_FRAMING if k == "REFRAME"
             else MEASURED_BACKDROP if k == "BACKGROUND" else v)
            for k, v in blocks]


VARIANTS = {
    "baseline": _v_baseline,
    "lock": _v_lock,
    "measured": _v_measured,
}

DEFAULT_VARIANT = "lock"


def build(preset: Preset, variant: str = DEFAULT_VARIANT) -> str:
    try:
        blocks = VARIANTS[variant](preset)
    except KeyError:
        raise KeyError(f"모르는 프롬프트 변형 {variant!r}; "
                       f"가능: {', '.join(VARIANTS)}") from None
    return "\n\n".join(f"[{k}]\n{v}" for k, v in blocks)


def grid(wardrobes: list[str] | None = None, backdrops: list[str] | None = None,
         lightings: list[str] | None = None) -> list[Preset]:
    """의상×배경×조명 조합. 상위 N장이 전부 똑같아 보이는 것을 막는다."""
    w = wardrobes or ["suit_black", "suit_navy", "shirt_white"]
    b = backdrops or ["white", "light_gray", "soft_blue"]
    li = lightings or ["studio_3pt"]
    return [Preset(f"{a}|{c}|{d}", a, c, d) for a, c, d in product(w, b, li)]
