# 품질 기준 — 실사 / 미화 두 등급

다른 에이전트가 이 문서만 읽고 동일하게 판정할 수 있도록 쓴다. 판정이 갈리는
지점은 전부 수치로 못박았고, **수치로 못 잡는 항목은 그렇다고 명시**했다.

두 등급은 서로 다른 상품이다. 섞으면 둘 다 실패한다.

| | **실사 증명사진** | **미화 증명사진** |
|---|---|---|
| 한 줄 | 잘 찍힌 사진관 사진 | 잘 찍히고 잘 손본 사진관 사진 |
| 파는 것 | "본인 그대로, 제대로" | "본인이 맞되, 가장 좋은 날의 본인" |
| 고객 기대 | 실물과 대조해도 같음 | 예쁘지만 아는 사람이 바로 알아봄 |
| 실패 모드 | 밋밋함 | **"이거 나 아닌데"** |
| 용도 | 이력서·공공 제출·사내 | 링크드인·프로필·SNS |

---

## 0. 두 등급을 가르는 단 하나의 원칙

> **미화는 피부·조명·정돈을 바꾼다. 골격·비율은 어느 등급에서도 안 바꾼다.**

실제 사진관이 하는 일이 정확히 이것이다. 사진관은 턱을 깎지 않는다 — 잘 비추고,
잡티를 지우고, 머리를 정돈한다. 미화 등급이 허용하는 것도 딱 거기까지다.

골격을 건드리는 순간 그것은 미화가 아니라 **다른 사람**이고, 고객이 환불을
요구하는 지점이다. 유사도 점수가 높게 나와도 마찬가지다 — §5 참조.

---

## 1. 공통 — 두 등급 모두 반드시

### 1-1. 하드 게이트 (하나라도 실패하면 노출 금지)

| 검사 | 기준 | 신뢰도 |
|---|---|---|
| 얼굴 1인 검출 | 정확히 1명 | 높음 |
| 규격 머리 길이 | 두개골 최상부~턱 32~36mm (여권), 30~34mm (일반) | 높음 |
| 머리카락 여백 | 프레임 상단까지 ≥ 1.5mm | 높음 |
| 눈 대칭 | 코 중심선 기준 좌우 편차 < 0.45 × 양안거리 | 높음 |
| 스튜디오다움 | `studio ≥ 0.45` (배경 균일도 + 조명 균일도) | 높음 |
| 피부 색조 이동 | `sqrt(Δa*² + Δb*²) ≤ 9.0` | 높음 |
| **골격 비율** | §5 의 inviolable 항목 전부 허용치 이내 | **중간 — 한계 있음** |

### 1-2. 절대 금지 (등급 무관)

- 턱·볼 깎기, 얼굴 갸름하게 만들기
- 눈 크기 변경
- 코 높이거나 좁히기
- 헤어라인 이동, 머리숱 추가
- 나이대 변경 (주름을 전부 지우는 것 포함)
- 피부 인종적 톤(a\*, b\*) 이동
- 키·목 길이 늘이기

### 1-3. 배경·조명 기준 (실측 근거)

레퍼런스 서비스 실측값이 목표치다:

- 배경: 좌우 가장자리 L\* **252~254**, 표준편차 **1 미만**, a\*/b\* 편차 **+0.0/+1.0**
  → 사실상 평탄한 순백 무채색. **방사형 그라데이션을 과하게 주면 오히려 합성 티가 난다**
- 조명: 얼굴 좌우 밝기 차 **L\* 5 이하**, 양쪽 눈에 캐치라이트
- 구도: 눈높이 프레임 상단에서 **46%**, 얼굴 중심 **50.0%**, roll **±0.5° 이내**

---

## 2. 실사 증명사진 — 기준

### 2-1. 수치

| 지표 | 게이트 | 목표 | 근거 |
|---|---|---|---|
| 본인 유사도 (SFace cos) | ≥ 0.55 | **≥ 0.68** | 레퍼런스 0.646~0.674를 넘어야 경쟁력 |
| 리터칭 아이덴티티 비용 Δcos | ≤ 0.03 | ≤ 0.02 | 손댈수록 본인에서 멀어진다 |
| 고주파(질감) 보존 | ≥ 0.95× 원본 | ≥ 1.0× | 레퍼런스는 3.70 → **4.66으로 증가** |
| 잡티 제거 면적 | ≤ 피부의 1.0% | ≤ 0.6% | 여드름만. 점·주근깨 보존 |
| 피부 색조 이동 | ≤ 6.0 | ≤ 4.0 | 레퍼런스 실측 4.1~4.5 |
| 실루엣 taper 변화 | ≤ 3.0% | ≈ 0% | 골격 불변 |

### 2-2. 허용

일시적인 것, 촬영 조건에서 온 것만 정리한다.

- 여드름·뾰루지 (붉고 작은 것)
- 홍조 — **완화만**, 혈색은 남긴다 (레퍼런스 Δa\* +0.0)
- 유분 반사
- 옷 먼지·구겨짐, 칼라 정돈
- 잔머리 (머리카락 자체는 안 건드림)
- 조명·배경 교체, 정면 구도 보정

### 2-3. 금지

§1-2 전부 + 다음:

- 주름·팔자주름 **제거** (그림자 완화는 다크서클만 최대 30%)
- 점·주근깨·흉터 제거
- 다크서클 완전 제거
- 치아 화이트닝 20% 초과
- 피부 스무딩으로 모공이 안 보이게 되는 것

### 2-4. 판정 문구

> "실물과 나란히 놓고 봐도 같은 사람이고, 사진관에서 잘 찍은 날의 사진처럼 보인다."

애매하면 **덜 손댄 쪽**을 고른다.

---

## 3. 미화 증명사진 — 기준

### 3-1. 수치

| 지표 | 게이트 | 목표 | 실사 대비 |
|---|---|---|---|
| 본인 유사도 (SFace cos) | ≥ 0.50 | **≥ 0.62** | 완화 |
| 리터칭 아이덴티티 비용 Δcos | ≤ 0.06 | ≤ 0.045 | 완화 |
| 고주파(질감) 보존 | ≥ 0.80× 원본 | ≥ 0.90× | 완화 — 단 **0.80 미만은 플라스틱** |
| 잡티 제거 면적 | ≤ 피부의 3.0% | ≤ 2.0% | 완화 |
| 피부 색조 이동 | ≤ 9.0 | ≤ 6.0 | 완화 |
| **실루엣 taper 변화** | **≤ 3.0%** | **≈ 0%** | **동일 — 완화 없음** |
| **골격 inviolable 비율** | **허용치 이내** | — | **동일 — 완화 없음** |

**마지막 두 줄이 이 등급의 정의다.** 나머지는 전부 완화하되 골격은 고정이다.

### 3-2. 추가로 허용 (실사에서 금지였던 것)

- 잔주름 **완화** (제거 아님 — 깊은 주름은 남긴다)
- 다크서클 최대 **60%** 완화
- 팔자주름 그림자 완화
- 피부톤 균일화 강화 (밝기 표준편차 감소 — 레퍼런스도 46.7 → 27.0)
- 치아 화이트닝 최대 40%
- 홍채 또렷함 강화, 속눈썹 라인 정돈
- 입체감 강화 (T존 하이라이트 · 턱선 음영) — **명암으로만, 형태 변경 금지**
- 자세 보정 (목·어깨 수평), 의상 핏 정돈
- 머리 정돈 강화 (스타일 변경 아님)

### 3-3. 여전히 금지

§1-2 전부. **하나도 완화되지 않는다.** 특히:

- 턱 깎기 — 미화 요청의 가장 흔한 형태이자 가장 확실한 환불 사유
- 눈 키우기
- 코 성형
- 점 제거 — 본인이 자기 얼굴에서 찾는 표식이다
- 나이 지우기 — 50대가 30대로 보이면 본인이 아니다

### 3-4. 판정 문구

> "아는 사람이 한눈에 알아보고, 본인은 '오늘 잘 나왔네'라고 생각한다."

애매하면 **골격 쪽을 의심한다**. 예뻐 보이는데 뭔가 낯설면 십중팔구 형태가 바뀐 것이다.

---

## 4. 프롬프트

`python3 -m idphoto prompt --variant <이름>` 으로 출력한다.

### 4-1. 실사 등급 — PRESERVE 블록

```
[PRESERVE — highest priority]
Keep the exact facial identity of the person in the reference photographs:
eye shape and spacing, eyelid crease, nose bridge and tip, philtrum, lip
shape, jawline, cheekbone structure, skin tone, moles, freckles, wrinkles,
and apparent age.
Do NOT slim or reshape the face. Do NOT enlarge the eyes. Do NOT remove
wrinkles, moles or skin texture. Do NOT lighten the skin tone. Do NOT
change the hairline. Preserve the shape of any eyeglasses exactly.

[DO NOT BEAUTIFY]
Do not beautify. Specifically: do not slim the jaw or cheeks, do not
enlarge or reshape the eyes, do not raise the nose bridge, do not smooth
away wrinkles or pores, do not whiten the skin, do not remove moles or
freckles, do not change the hairline or add hair.

[TEXTURE]
Render real photographic skin: visible pores, fine vellus hair, natural
texture variation. This is a photograph, not an illustration or a render.
```

### 4-2. 미화 등급 — PRESERVE 블록

**금지 목록이 짧아지지 않는다는 점에 주의.** 허용 목록만 추가된다.

```
[IDENTITY — inviolable]
This must remain unmistakably the same person. Keep the bone structure
exactly: face width at the cheekbones and at the jaw, jaw taper, chin
shape, eye size and spacing, eyelid crease, nose length and width, the
proportions between features, and the apparent age bracket. Keep moles,
freckles and any distinctive marks. Keep the natural skin undertone.

Do NOT slim the jaw or cheeks. Do NOT enlarge or reshape the eyes. Do NOT
raise or narrow the nose. Do NOT change the hairline or add hair. Do NOT
make the person look younger than they are. Do NOT lighten the skin tone.
These hold even though this is a flattering portrait.

[FLATTER — what you may improve]
Treat this as a skilled studio photographer and retoucher would: clear
temporary blemishes and redness, even out skin tone, soften — not erase —
fine lines and under-eye shadow, tidy stray hair, brighten the eyes
slightly, tidy the clothing fit and collar, and light the face so it looks
its best. Add dimension with light and shadow only, never by changing shape.

[TEXTURE]
Keep real photographic skin: pores and fine texture must remain visible.
Flattering, not airbrushed. This is a photograph, not an illustration.
```

### 4-3. 두 등급 공통 (구도·조명·배경)

```
[REFRAME]
Frame so the eye line sits about 46% down from the top edge and the face
is horizontally centred. Keep the head perfectly upright.

[LIGHT]
Three-point studio lighting: a 45-degree key softbox, a 1:2 fill ratio, a
subtle hair light, and a soft rectangular catchlight visible in both eyes.

[BACKGROUND]
Flat neutral white, evenly lit, with almost no gradient and no colour cast.

[LENS]
Shot on an 85mm portrait lens at f/5.6, natural facial proportions, no
wide-angle distortion.

[AVOID]
beauty filter, skin smoothing, plastic or airbrushed skin, anime or
illustration style, oversaturated colour, asymmetric or mismatched eyes,
warped eyeglass frames, extra fingers, visible text or watermark,
wide-angle facial distortion
```

---

## 5. ⚠️ 자동 검사의 한계 — 반드시 읽을 것

**유사도 점수는 성형을 잡지 못한다.** 실측:

| 변형 | SFace 유사도 | 랜드마크 taper 변화 | 실루엣 taper 변화 |
|---|---|---|---|
| 턱 6% 깎기 | 0.972 | −0.4% | −1.7% |
| 턱 12% 깎기 | 0.957 | −1.8% | −3.8% |
| 턱 20% 깎기 | **0.937** | −3.0% | **−6.8%** |
| 눈 30% 키우기 | 0.762 | −14.5% (잡힘) | — |

**턱을 20% 깎아도 유사도가 0.937입니다.** 어떤 유사도 게이트도 이걸 통과시킵니다.

그래서:
1. **실루엣 taper** 가 주 지표다 (랜드마크보다 2.3배 민감). 단 **미세한 깎기(6~12%)는
   이것으로도 확실히 잡히지 않는다.**
2. 랜드마크 비율은 눈 크기 변경 같은, 실루엣이 못 보는 것을 담당한다.
3. **6~12% 수준의 미세한 얼굴 깎기는 현재 자동으로 못 잡는다.** 이 구간은
   **사람이 봐야 한다.** 아래 방법을 쓴다:
   - 원본과 결과를 **같은 눈 위치·같은 양안거리로 정렬**해 겹쳐 본다
   - 턱선과 볼 라인만 본다. 얼굴 전체 인상은 조명 때문에 판단을 흐린다
   - 애매하면 탈락시킨다. 미화 등급에서도 마찬가지다

랜드마크가 약한 이유: MediaPipe 는 얼굴 모델을 피팅하므로 이런 왜곡에 **스스로
강건하다** — 잡으려는 대상에 둔감하도록 설계돼 있다. 원시 윤곽 폭은 20% 깎기에서
2.3% 밖에 안 움직였다.

---

## 6. 다른 에이전트를 위한 판정 절차

```
1. python3 -m idphoto catalog "<후보>/*.jpg" --refs "<원본>/*.jpg" --out out/판정
2. contact_sheet.png 로 전체를 훑는다 — 테두리 색으로 1차 분류
3. 하드 게이트 탈락분은 그대로 버린다 (§1-1)
4. 통과분에서 등급 기준(§2 또는 §3)의 목표치를 넘는 것만 남긴다
5. 남은 것을 원본과 정렬해 겹쳐 보고 턱선·볼 라인을 확인한다 (§5)
6. 애매하면 탈락
```

**고를 때 순서**: 골격 유지 → 스튜디오다움 → 유사도 → 질감 → 심미.
심미가 마지막인 이유는, 앞의 넷이 무너진 사진은 예뻐도 팔 수 없기 때문이다.
