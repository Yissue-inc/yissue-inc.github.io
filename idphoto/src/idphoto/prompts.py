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


def build(preset: Preset) -> str:
    return "\n\n".join([
        "[PRESERVE — highest priority]\n" + PRESERVE,
        "[REFRAME]\n" + FRAMING,
        "[WARDROBE]\n" + WARDROBE[preset.wardrobe],
        "[LIGHT]\n" + LIGHTING[preset.lighting],
        "[BACKGROUND]\n" + BACKDROP_PROMPT[preset.backdrop],
        "[LENS]\n" + LENS,
        "[AVOID]\n" + NEGATIVE,
    ])


def grid(wardrobes: list[str] | None = None, backdrops: list[str] | None = None,
         lightings: list[str] | None = None) -> list[Preset]:
    """의상×배경×조명 조합. 상위 N장이 전부 똑같아 보이는 것을 막는다."""
    w = wardrobes or ["suit_black", "suit_navy", "shirt_white"]
    b = backdrops or ["white", "light_gray", "soft_blue"]
    li = lightings or ["studio_3pt"]
    return [Preset(f"{a}|{c}|{d}", a, c, d) for a, c, d in product(w, b, li)]
