# 로컬 인수인계 — 여기부터 이어서 하면 됩니다

클라우드 세션에서 만든 것을 로컬에서 이어받기 위한 문서. **이 파일 하나만 읽고
시작해도 됩니다.** 클라우드 세션을 텔레포트하지 않아도 되고, claude.ai 계정
로그인(`/login`)도 필요 없습니다 — API 키 인증 상태의 로컬 Claude Code 로 충분합니다.

## 지금 상태 한 줄

파이프라인은 **완성돼 있고 실제 사진으로 검증됐습니다.** 남은 것은 **생성 API 호출
한 번**뿐입니다. 클라우드 세션에서는 Gemini 키에 닿을 수 없어 그 한 걸음만 막혀 있었습니다.

## 로컬에서 첫 실행

```bash
cd idphoto
pip install -r requirements.txt
./scripts/fetch_models.sh
export PYTHONPATH=src

python3 -m idphoto doctor
```

`doctor` 가 모델 파일·의존성·생성 API 인증을 한 번에 점검합니다. 인증은 **무과금
엔드포인트**로 확인하므로 비용이 들지 않습니다.

## 파일럿 (다음 할 일)

키는 **`ai_keys.py` 로만** 받습니다. 파일을 직접 읽거나 `export` 하지 않습니다
(`docs/key-access.md` 참조 — 그렇게 하다 실제로 틀린 파일을 짚었습니다).

```bash
./scripts/pilot.sh <입력사진1> <입력사진2> <입력사진3>
```

또는 모델·프롬프트를 교차해 한 번에 비교:

```bash
python3 ~/…/Hermes/automation/ai_keys.py run gemini \
  --purpose "AI 증명사진 3x3 교차 파일럿" --est-usd 0.74 \
  --model gemini-3.1-flash-image \
  -- python3 -m idphoto run <사진들> --provider gemini \
     --models gemini-3-pro-image,gemini-3.1-flash-image,gemini-3.1-flash-lite-image \
     --variants baseline,lock,measured \
     --spec id_kr --n 9 --present 3 --out out/pilot
```

9장 = 3모델 × 3프롬프트 완전 교차. 공시가 기준 **$0.738** (프로토콜 §4 자동 구간 $1 이내).
끝나면 요약의 `usage` 와 `est_usd_next_run` 이 **실측 단가**입니다 — 다음 배치는 그 값으로.

## 합격선 (실측으로 확정된 값)

| 기준 | 값 | 출처 |
|---|---|---|
| OpenCV SFace 동일인 판정 | 0.363 | 레퍼런스 구현 |
| 같은 사람 다른 실사진 2장 (최악) | **0.547** | 자연 하한 |
| **인핸즈 출력 vs 참조 평균** | **0.646 ~ 0.674** | **넘어야 할 선** |
| 우리 하드 게이트 / 목표 | 0.50 / 0.65 | `config.py` |

인핸즈 출력 2장은 우리 QA 게이트를 종합점수 0.754 / 0.824 로 통과합니다.

## API 없이도 되는 것

프롬프트가 좋은지 보는 데는 생성 API 가 필요 없습니다.

```bash
python3 -m idphoto prompt --variant measured         # 웹 UI 에 붙여넣을 프롬프트
python3 -m idphoto measure 결과.jpg --refs 원본*.jpg  # 어디서 만들었든 같은 잣대로 채점
```

## 먼저 읽을 문서

| 문서 | 내용 |
|---|---|
| `README.md` | 파이프라인 구조, 설계 결정, 알려진 한계 |
| `docs/key-access.md` | 키 취급 규칙 + 여기서 저지른 실수 3가지 |
| `docs/reference-calibration.md` | 레퍼런스 실측으로 잡은 버그 3개와 확정 임계값 |
| `docs/fact-check.md` | 라이선스·규격·AI기본법 정정 사항 |
| `docs/retouch-calibration.md` | 리터칭 단계별 아이덴티티 비용 실측 |

## 주의

- **여권용으로 팔지 않습니다.** 외교부 규정이 배경 합성·편집 사진 제출을 명시적으로
  금지합니다. `passport_kr` 규격은 미리보기 전용(`accepts_ai=False`).
- **AI 생성 표시**는 메타데이터만으로 부족합니다. 안내 문구를 **1회 이상 별도 제공**해야
  합니다(AI기본법, 최대 3천만원 과태료). `docs/fact-check.md` §3.
- **`gemini` 별칭은 VPS GEO 측정과 한도를 공유**합니다. 반복 튜닝이 잦아지면 키를 분리할 것.
- 사용자 사진은 `samples/private/`(gitignore)에 둡니다. 공개 저장소이고 얼굴은 민감정보입니다.

## 아직 안 한 것

- 실제 생성 호출 (= 파일럿). 정장 변환 품질은 아직 육안 확인 전입니다.
- 잡티 검출 재현율이 낮습니다(합성 기준 0.42/정밀도 0.53). 실사진 재보정 필요.
- 매팅은 GrabCut 폴백이 거칩니다. 프로덕션은 BiRefNet(MIT)으로 교체할 것.
- 리라이팅이 물리 기반이 아닙니다. IC-Light(Apache-2.0)로 교체할 것.
