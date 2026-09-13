# 팩트체크 결과 — 계획서 v1.0 정정

조사일 2026-09-13 · 1차 출처(원본 LICENSE 파일, 정부 고시, 공식 문서) 우선

---

## 요약: v1.0에서 틀렸거나 빠진 것

| # | 항목 | v1.0 서술 | 확인된 사실 | 영향 |
|---|---|---|---|---|
| 1 | InsightFace 라이선스 | "inswapper만 비상업, buffalo_l은 모델별 확인" | **auto-download 포함 모든 사전학습 모델이 비상업 연구용** | **치명** — ArcFace 임베딩이 QA 게이트의 핵심 부품인데 상용 불가였음 |
| 2 | CodeFormer | "리포별 확인" | **S-Lab License 1.0 — "non-commercial purpose" 명문** | 높음 — 복원 단계 전면 교체 |
| 3 | 머리 길이 측정 | "정수리(머리카락 포함)~턱" | **외교부: "정수리(머리카락을 제외한 머리 최상부)부터 턱까지"** | 높음 — 구현 버그였음, 수정 완료 |
| 4 | Gemini 2.5 Flash Image | 원가표의 저가 옵션 | **2026-10-02 종료 예정** | 중 — 신규 사용 금지 |
| 5 | AI기본법 표시 | "메타데이터만으로 되는지 법률 자문 필요" | **기계 판독 표시를 쓰면 "AI 생성" 사실을 안내 문구·음성 등으로 1회 이상 별도 제공해야 함** | 높음 — 메타데이터만으로는 불충분 |
| 6 | 여권 사진 배경 | "AI 사진 수리 안 됨" (일반론) | **"배경을 지우거나 흰색 배경에 인물을 임의로 합성한 사진은 제출 불가" 명문** | 중 — 근거가 더 강해짐 |

---

## 1. 라이선스 감사 (원본 LICENSE 직접 확인)

| 컴포넌트 | 라이선스 | 상용 | 확인 방법 |
|---|---|---|---|
| **OpenCV Zoo YuNet** | Apache-2.0 | ✅ | `opencv_zoo/LICENSE` |
| **OpenCV Zoo SFace** | Apache-2.0 | ✅ | `models/face_recognition_sface/README.md` |
| **MediaPipe** | Apache-2.0 | ✅ | 배포 패키지 |
| **BiRefNet** | MIT | ✅ | `ZhengPeng7/BiRefNet/LICENSE` |
| **IC-Light** | Apache-2.0 | ✅ | `lllyasviel/IC-Light/LICENSE` |
| **GFPGAN** | Apache-2.0 (제3자 컴포넌트 별도) | ✅ 단서부 | `TencentARC/GFPGAN/LICENSE` — "except for the third-party components listed below" 확인 필요 |
| **Qwen-Image-Edit** | Apache-2.0 | ✅ | |
| **CodeFormer** | S-Lab License 1.0 | ❌ | `sczhou/CodeFormer/LICENSE` — "Redistribution and use for **non-commercial purpose**" |
| **InsightFace 사전학습 전체** | non-commercial research only | ❌ | upstream README §License |
| **BRIA RMBG-2.0** | BRIA 상용 유료 | ❌ (유료 계약 시 ✅) | |

### InsightFace 원문 (핵심)

> The code of InsightFace is released under the MIT License. There is no limitation for both academic and commercial usage.
> The training data containing the annotation (and the models trained with these data) are available for **non-commercial research purposes only**.
> Both manual-downloading models from our github repo and auto-downloading models with our python-library follow the above license policy (which is for non-commercial research purposes only).

**`pip install insightface` 후 자동 다운로드되는 `buffalo_l`이 여기 포함된다.** 코드가 MIT라는 사실이 모델 사용을 허가하지 않는다. 이 서비스의 QA 게이트가 ArcFace 유사도에 의존하므로, 이걸 놓쳤으면 상용화 직전에 막혔다.

**대체 결과**: 검출 YuNet + 인식 SFace + 랜드마크 MediaPipe — 전부 Apache-2.0. 현 구현은 InsightFace 의존이 0이다.

---

## 2. 한국 증명사진 규격 (외교부 여권안내)

- 크기 **35 × 45 mm**
- 머리 길이 **정수리(머리카락을 제외한 머리 최상부)부터 턱까지 32~36 mm**
- 6개월 이내 촬영한 천연색 상반신 정면 **탈모**(모자 미착용) 사진
- 배경: 균일한 흰색, 잉크 자국·테두리 없음
- 온라인 신청 파일: **413 × 531 px 권장** — 35×45mm @300dpi 계산값과 일치
- **"사진 편집 프로그램(예: 포토샵 등)을 사용하여 배경을 지우거나 흰색 배경에 인물을 임의로 합성한 사진은 제출 불가"**
- 외교부가 **온라인 여권 사진 검증** 메뉴를 무료 제공 — 우리 규격 리포트 기능의 레퍼런스이자 경쟁 기준

### 구현에 반영한 것

`FaceGeometry`가 두 지점을 따로 들고 있다.

- `crown` — 머리카락 최상부. 균일 배경에서 매트로 뽑는다. **프레임에 머리가 들어가는지** 판단용.
- `skull_top` — 머리카락 제외 머리 최상부. 랜드마크에서 두개골 비율로 외삽한다. **규정상 머리 길이** 측정용.

`PhotoSpec.head_measure`가 `"skull"`(여권·증명·반명함) / `"hair"`(프로필)을 선언하고, `frame_to_spec`이 그에 맞는 기준점으로 스케일을 잡는다.

실측에서 두 값은 크게 갈린다 — 생성물 샘플에서 **44.9% 차이**(모자 착용 케이스). 한 값으로 뭉뚱그렸다면 머리숱 많은 사용자의 사진이 규정보다 작게 잡혀 반려됐을 것이다.

---

## 3. AI기본법 표시 의무 (2026-01-22 시행)

「인공지능 발전과 신뢰 기반 조성 등에 관한 기본법」및 시행령.

- 인공지능사업자는 생성형 AI 산출물에 대해 **생성형 AI에 의해 생성되었다는 사실을 표시**해야 한다.
- 표시는 **사람 또는 기계가 판독할 수 있는 형식** 모두 인정 — 비가시적 워터마크가 허용된다.
- **단서(중요)**: 기계 판독 방식으로 표시하는 경우, "생성형 AI에 의하여 생성되었다"는 사실을 **안내 문구·음성 등으로 1회 이상 별도 제공**해야 한다.
- 실물과 구분이 어려운 가상 콘텐츠는 사람이 명확히 인식 가능한 방식으로 표시.
- 위반 시 시정명령 및 **최대 3,000만 원 과태료**.
- 수범자는 **인공지능사업자**다. 생성 도구를 쓰는 최종 이용자는 수범자가 아니다 — 서비스를 제공하는 우리가 의무 주체다.

### 구현에 반영한 것

`provenance.py`가 EXIF/XMP에 IPTC `DigitalSourceType = trainedAlgorithmicMedia`와 한/영 고지문을 심는다. **그러나 이것만으로는 요건을 충족하지 못한다** — 안내 문구 제공이 세트여야 한다. 따라서 제품 요구사항:

1. 생성 **전** 화면에 "본 결과물은 AI로 생성됩니다" 명시적 고지 + 동의 (1회 이상 제공 요건)
2. 다운로드 화면에 동일 고지 재노출
3. 모든 산출물에 메타데이터 삽입 (구현 완료)
4. 주문별 생성 모델·버전·시각 감사 로그 (`disclosure_record`에 포함)

가시 워터마크는 무료 체험·프리뷰에만 적용한다(`watermark_preview`). 유료 증명사진에 가시 워터마크를 넣으면 상품 가치가 사라지므로, 위 1·2·3 조합의 적법성 확인이 **법률 자문의 1순위 질문**이다.

---

## 4. 생성 모델 단가·수명 (2026-09 기준, 계약 전 재확인 필요)

| 모델 | 장당 단가 | 비고 |
|---|---|---|
| `gemini-3-pro-image` | 약 $0.134 (1K~2K), $0.24 (4K) | 프롬프트 준수·일관성 최상위 |
| `gemini-3.1-flash-image` | 약 $0.067 (1024) | 속도·비용 우위. **신규 기본값** |
| `gemini-3.1-flash-lite-image` | 약 $0.045 (512) | |
| `gemini-2.5-flash-image` | $0.039 / 배치 $0.0195 | **2026-10-02 종료 예정 — 사용 금지** |
| Batch API | 표준가 50% | 비동기 배치 구조와 잘 맞는다 |

계획서 v1.0의 원가표는 `gemini-3-pro-image` 기준 $2.68/주문(40장)이었다. `gemini-3.1-flash-image`로 바꾸면 **$2.68 → $1.34**, 배치 API를 쓰면 **$0.67**까지 내려간다. 자체호스팅 전환 손익분기가 v1.0 추정(일 7건)보다 뒤로 밀린다 — 재계산 필요.

---

## 5. 아직 검증되지 않은 것

- **인핸즈의 실제 파이프라인 구성** — 외부 관측 기반 추론이며 확인된 사실이 아니다. (enhanz.io가 이 세션의 egress 정책에 막혀 직접 조사 불가)
- **`gemini-3.1-flash-image`의 얼굴 유사도 실측** — API 키 확보 후 120 케이스로 측정해야 한다.
- **SFace 유사도 임계값** — OpenCV 레퍼런스는 동일인 판정 0.363을 제시한다. 현재 게이트는 0.42로 잡았으나 근거는 "보수적으로"일 뿐, 실사용 클레임률로 재보정해야 한다.
- **GFPGAN 제3자 컴포넌트** — Apache-2.0 본문 외 "third-party components" 목록의 라이선스.
- **AI기본법 표시 요건의 증명사진 적용** — 법률 자문 전 미확정.
