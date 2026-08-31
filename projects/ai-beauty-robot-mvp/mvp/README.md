# MVP 스캐폴드 — 하드웨어 없이 먼저 돌려보기

협동로봇 리드타임은 보통 **4~8주**입니다. 팔이 오기를 기다리는 동안 앱 전체를 완성하기 위한
최소 구현입니다. **설치할 것 없습니다 (표준 라이브러리만 사용).**

```bash
cd projects/ai-beauty-robot-mvp

python -m mvp.demo                    # 단일 세션 90초 여정을 콘솔에서 확인
python -m mvp.demo --realtime         # 로봇 동작에 실제 지연을 넣어 체감 속도 확인
python -m mvp.demo --policy rule      # 룰 기반 정책으로 실행

python -m mvp.simulate --sessions 800 # 밴딧이 정말 똑똑해지는지 검증
```

## 파일 지도

| 파일 | 역할 | 언제 손대나 |
|---|---|---|
| `store.py` | **SQLite 로그 스키마.** 이 프로젝트에서 가장 중요한 파일 | **Day 1** — 팀이 스키마에 합의할 것 |
| `catalog.py` · `data/products.json` | 제품 20종 + 클러스터 | Week 8 — 실제 취급 제품으로 교체 |
| `skin.py` | 측정 어댑터 (Mock / 로컬휴리스틱 / 벤더API) | Week 7~8 |
| `recommender.py` | 룰(S0) + LinUCB 밴딧(S1) | Week 8~10 |
| `counselor.py` | LLM 상담 + **규제 금지어 필터** | Week 9 |
| `robot.py` | 로봇 드라이버 (`MockArm` / myCobot / xArm / Dobot) | Week 3~5 |
| `session.py` | 세션 상태머신 + 보상 산출 | Week 11~12 |
| `simulate.py` | 학습 루프 검증 | 상시 |
| `linalg.py` | numpy 없는 소형 역행렬 | numpy 도입 시 교체 |
| `data/slots.json.example` | 티칭 좌표 형식 | Week 4 |

## 실행 결과 예시

`python -m mvp.simulate --sessions 600` — 동일한 고객 스트림을 두 정책에 통과시킨 결과입니다.
시뮬레이터에는 **룰이 모르는 선호 4가지**를 숨겨두었고, 밴딧이 그걸 찾아내는지를 봅니다.
(수치는 시드에 따라 달라집니다.)

```
        구간        룰 기반(S0)      밴딧(S1)        차이
      1-100           56.0%        55.0%     -1.0p     ← 초반엔 룰 prior 를 그대로 따름
    301-400           50.0%        53.0%     +3.0p ▲▲
    501-600           45.0%        56.5%    +11.5p ▲▲▲▲▲▲▲

  클러스터    이름            룰     밴딧     변화
  C1        진정/수분       147     191      +44 ↑   ← 누구에게나 안전한 선택임을 발견
  C5        각질/결         164      45     -119 ↓   ← 즉석 수락률이 낮음을 발견하고 버림
  C6        자외선차단        12     147     +135 ↑   ← 젊은 층 선호를 발견
```

룰 기반은 `texture` 지표만 보고 각질 제품(C5)을 계속 추천하지만, 밴딧은 **"측정값은 높은데
사람들이 안 집어간다"** 는 사실을 200세션 즈음부터 학습해 추천을 3분의 1로 줄입니다.
이것이 PLAN.md 6장에서 말하는 학습 루프의 실제 동작입니다.

## 이 스캐폴드가 의도적으로 지키는 규칙

1. **로봇은 슬롯 번호만 안다.** `robot.py` 에 비즈니스 로직이 들어오면 로봇 교체가 불가능해집니다.
2. **외부 의존은 전부 어댑터 뒤에.** 측정 벤더·LLM 벤더 교체가 반나절 작업이어야 합니다.
3. **개인 식별 컬럼이 스키마에 아예 없다.** 없으면 유출도 없습니다.
4. **금지어 필터는 LLM 출력 뒤에 한 번 더.** 프롬프트만 믿으면 언젠가 새어 나옵니다.
5. **밴딧의 arm 은 SKU 가 아니라 클러스터.** SKU 단위면 매장 데이터 속도로 영원히 학습 안 됩니다.
6. **전달 순서를 랜덤화하고 로깅한다.** 안 하면 "1번 슬롯이 최고"라고 학습합니다.

## 다음에 채울 것 (TODO)

- [ ] `skin.LocalHeuristicAnalyzer.analyze()` — 촬영 부스 완성 후 (Week 7~8)
- [ ] `skin.ApiSkinAnalyzer.analyze()` — 벤더 계약 후
- [ ] `counselor.ClaudeCounselor.script()` — 구조화 출력 + 제품 ID 화이트리스트 검증 (Week 9)
- [ ] `robot.MyCobotArm` / `XArmArm` 의 `move_l` · `set_gripper` · `gripped` (Week 4~5)
- [ ] `data/slots.json` — 티칭 좌표 20슬롯 (Week 4)
- [ ] 키오스크 UI 6화면 (Week 11)
- [ ] 야간 배치: SQLite → Postgres 동기화 + 주 1회 정책 재학습·배포
