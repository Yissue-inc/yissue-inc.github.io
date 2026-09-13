# idphoto — AI 증명사진 파이프라인 MVP

셀카 몇 장에서 증명사진을 만드는 파이프라인. **상용 가능한 라이선스 컴포넌트만** 사용한다
(라이선스 감사 결과는 [`docs/fact-check.md`](docs/fact-check.md), [`models/LICENSES.md`](models/LICENSES.md)).

## 빠른 시작

```bash
pip install -r requirements.txt
./scripts/fetch_models.sh                   # Apache-2.0 모델 3종 (~43MB)

export PYTHONPATH=src
python -m idphoto gate  photo1.jpg photo2.jpg photo3.jpg
python -m idphoto run   photo*.jpg --spec id_kr --n 12 --out out/order
python -m idphoto check out/order/*.jpg     # AI 생성 표시 확인
```

Gemini 로 실제 생성하려면:

```bash
export GEMINI_API_KEY=...
python -m idphoto run photo*.jpg --provider gemini --model gemini-3.1-flash-image
```

## 파이프라인

| 단계 | 모듈 | 하는 일 |
|---|---|---|
| S0 | `gating.py` | 입력 품질 게이팅 → 한국어 코칭 메시지 |
| S1 | `detect.py` | YuNet 검출 + MediaPipe 478점 랜드마크 + 머리 최상부 추정 |
| S2 | `identity.py` | SFace 임베딩, 이상치 제외 평균 |
| S3 | `generate/` | 생성 프로바이더 (mock · Gemini) |
| S6 | `background.py` | 매팅 + 스튜디오 배경 + 키라이트 근사 |
| S7 | `retouch.py` | 주파수 분리 리터칭, 닷지&번, 그레이딩, 그레인 |
| S8 | `framing.py` | 규격 크롭 + 사후 검증 |
| S9 | `qa.py` | 하드 게이트 → 가중 스코어 → MMR 다양성 선발 |
| — | `provenance.py` | AI 생성 표시 메타데이터 |

품질 임계값은 전부 [`config.py`](src/idphoto/config.py) 한 곳에 있고, 각 값에 실측 근거를 적어 두었다.

## 설계상 중요한 결정

**InsightFace를 쓰지 않는다.** 코드는 MIT지만 `buffalo_l`을 포함한 **모든 사전학습 모델이
비상업 연구용**이다. 검출은 YuNet, 인식은 SFace(둘 다 OpenCV Zoo, Apache-2.0)로 대체했다.

**머리 최상부를 두 개 들고 있다.** 외교부 규정의 머리 길이는 "정수리(**머리카락을 제외한**
머리 최상부)부터 턱까지"다. 프레임에 머리가 들어가는지는 머리카락 최상부로, 규정상 머리
길이는 두개골 최상부로 판단한다. 실측에서 두 값은 크게 갈린다.

**고주파를 보존한다.** 리터칭은 주파수 분리로 저주파(피부톤·음영)만 고르고 모공·솜털·잔주름은
그대로 둔다. 여기를 뭉개면 즉시 'AI 티'가 난다. 보정 강도 0은 진짜로 아무것도 하지 않는다.

**유사도를 계속 측정한다.** 후처리 전후 `Δcos`를 재서 0.05를 넘으면 강도를 낮춘다.
현재 최대 강도에서 -0.032로 여유가 있다.

## 알려진 한계

- **매팅이 거칠다.** GrabCut 폴백은 머리카락 경계를 제대로 못 뽑는다. 프로덕션은
  BiRefNet(MIT)으로 교체할 것.
- **리라이팅이 물리 기반이 아니다.** `key_light`는 밝기 기울기 근사다. IC-Light(Apache-2.0)로 교체할 것.
- **mock 프로바이더는 의상을 바꾸지 못한다.** 배경·조명만 합성한다. 하류 단계 검증용이다.
- **mock 경로가 느리다** (GrabCut 때문에 장당 ~15초). Gemini 경로에는 해당 없다.
- **SFace 임계값이 미검증이다.** 실사용 클레임률로 재보정 필요.

## 법적 주의

여권·주민등록증 등 신분증에는 쓸 수 없다. 외교부 규정은 배경을 합성·편집한 사진의 제출을
명시적으로 금지한다. `passport_kr` 규격은 **미리보기 전용**이며 `accepts_ai=False`로 표시돼 있다.

AI기본법(2026-01-22 시행)상 메타데이터 표시만으로는 부족하고 **안내 문구를 1회 이상 별도
제공**해야 한다. 자세한 요구사항은 [`docs/fact-check.md`](docs/fact-check.md) §3.
