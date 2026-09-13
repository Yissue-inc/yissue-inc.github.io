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
| S7 | `retouch.py` · `blemish.py` · `regions.py` | 프로 리터칭 13단계 (아래) |
| S8 | `framing.py` | 규격 크롭 + 사후 검증 |
| S9 | `qa.py` | 하드 게이트 → 가중 스코어 → MMR 다양성 선발 |
| — | `provenance.py` | AI 생성 표시 메타데이터 |

### S7 리터칭 — 사진관 워크플로 순서 그대로

색보정 → **잡티 힐링** → 홍조 → 주파수 분리 → 다크서클 → 팔자주름 → T존/턱선 윤곽 →
국소대비 → 공막/홍채 → 치아 → 선택적 디테일 샤프닝 → 그레이딩 → 출력 샤프닝 → 그레인.

전역 스무딩을 쓰지 않는 것이 핵심이다. 잡티를 개별로 지우기 때문에 주파수 분리를
약하게 걸어도 되고, 그래야 모공·솜털·잔주름이 살아남는다.

품질 임계값은 전부 [`config.py`](src/idphoto/config.py) 한 곳에 있고, 각 값에 실측 근거를 적어 두었다.

## 설계상 중요한 결정

**InsightFace를 쓰지 않는다.** 코드는 MIT지만 `buffalo_l`을 포함한 **모든 사전학습 모델이
비상업 연구용**이다. 검출은 YuNet, 인식은 SFace(둘 다 OpenCV Zoo, Apache-2.0)로 대체했다.

**머리 최상부를 두 개 들고 있다.** 외교부 규정의 머리 길이는 "정수리(**머리카락을 제외한**
머리 최상부)부터 턱까지"다. 프레임에 머리가 들어가는지는 머리카락 최상부로, 규정상 머리
길이는 두개골 최상부로 판단한다. 실측에서 두 값은 크게 갈린다.

**고주파를 보존한다.** 리터칭은 주파수 분리로 저주파(피부톤·음영)만 고르고 모공·솜털·잔주름은
그대로 둔다. 여기를 뭉개면 즉시 'AI 티'가 난다. 보정 강도 0은 진짜로 아무것도 하지 않는다.

**아이덴티티 예산을 자동으로 지킨다.** `apply_within_budget` 이 리터칭 후 `Δcos` 를
재고, 0.05 예산을 넘으면 전체 강도를 70% → 45% → 25% 로 물러선다. 리터처가 마지막에
"아직 이 사람으로 보이나"를 확인하는 것과 같은 일이다. 실측 단계별 비용은
[`docs/retouch-calibration.md`](docs/retouch-calibration.md).

**점을 지우지 않는다.** 잡티 검출기가 여드름(어둡고 **붉다**)과 점(어둡고 **붉지 않다**)을
구분해 후자는 보존한다. 점은 본인을 식별하는 특징이다.

**제거 면적에 상한이 있다.** 검출기는 완벽하지 않으므로 총 제거 면적을 피부의 1.5%로
묶고, 확신이 큰 후보부터 채운다. 기질이 나빠도 피해가 무한정 커지지 않는다.

**라이선스는 스위치다.** `Config.licensing` 이 `"research"`(품질 상한 탐색 — 뭐든 씀)와
`"commercial"`(정리된 것만) 을 가른다. `license_audit()` 이 출시 전 구매·교체 목록을
자동으로 뽑는다.

## 알려진 한계

- **매팅이 거칠다.** GrabCut 폴백은 머리카락 경계를 제대로 못 뽑는다. 프로덕션은
  BiRefNet(MIT)으로 교체할 것.
- **리라이팅이 물리 기반이 아니다.** `key_light`는 밝기 기울기 근사다. IC-Light(Apache-2.0)로 교체할 것.
- **mock 프로바이더는 의상을 바꾸지 못한다.** 배경·조명만 합성한다. 하류 단계 검증용이다.
- **mock 경로가 느리다** (GrabCut 때문에 장당 ~15초). Gemini 경로에는 해당 없다.
- **SFace 임계값이 미검증이다.** 실사용 클레임률로 재보정 필요.
- **잡티 검출 재현율이 낮다.** 합성 평가에서 재현율 0.42 / 정밀도 0.53 (필름 그레인이
  심한 적대적 기질 기준). 실사진으로 재보정이 필요하다 — 자세한 수치는
  [`docs/retouch-calibration.md`](docs/retouch-calibration.md).

## 법적 주의

여권·주민등록증 등 신분증에는 쓸 수 없다. 외교부 규정은 배경을 합성·편집한 사진의 제출을
명시적으로 금지한다. `passport_kr` 규격은 **미리보기 전용**이며 `accepts_ai=False`로 표시돼 있다.

AI기본법(2026-01-22 시행)상 메타데이터 표시만으로는 부족하고 **안내 문구를 1회 이상 별도
제공**해야 한다. 자세한 요구사항은 [`docs/fact-check.md`](docs/fact-check.md) §3.
