# 키 접근 — 이 저장소의 준수 사항

정본은 `Yissue_Brain` 의 `Hermes/agents/_drafts/ai_api_key_access_protocol.md`
(2026-09-12, CK 검토 전 draft). 여기는 이 파이프라인이 그 프로토콜을 어떻게
지키는지만 적는다.

## 규칙

1. **키 파일을 직접 읽지 않는다.** `src/idphoto/keys.py` 가 `ai_keys.require()`
   한 곳으로만 받는다. 키는 `os.environ` 을 거쳐 provider 로 가고, 우리 코드를
   통과하지 않는다.
2. **키를 못 찾으면 멈춘다.** 환경별 해결 방법을 출력하고 종료코드 2로 끝난다.
   채팅으로 키를 요청하지 않는다.
3. **금액은 파일럿으로 잰다.** `--est-usd` 에 추측값을 넣지 않는다. `--n 1` 로
   파일럿을 돌리면 요약에 `usage` 와 `est_usd_next_run` 이 나온다.
4. **운영 키를 쓰지 않는다.** `ai_keys.py` 가 `anthropic-prod`·`openai-winpub` 을
   거부한다. 우리 쪽에서 우회하지 않는다.

## 환경별

| 환경 | 키 출처 |
|---|---|
| CK 로컬 맥 | `ai_keys.py` → `Hermes/.secrets/*.env` |
| VPS 컨테이너 | `ai_keys.py` → `/app/.secrets/*.env` |
| **클라우드 에이전트 (이 세션)** | ① API credential(권장) ② 환경변수 ③ 로컬 핸드오프 |

### 클라우드 환경에 붙이는 두 방법

| | API credential | 환경변수 |
|---|---|---|
| 키가 샌드박스에 들어오나 | **아니오** — 프록시가 VM 밖에서 헤더를 붙인다 | 예 — `os.environ` 에 그대로 |
| 에이전트가 키를 볼 수 있나 | **볼 수 없다** | 볼 수 있다 |
| 실행 중인 세션에 적용 | 프록시가 요청 시점에 붙이므로 적용됨 | **안 됨** — 세션 시작 시 1회 복사. 새 세션 필요 |
| 환경 사용자 전원에게 노출 | 값 열람 불가 | "누구나 값을 읽을 수 있음"(공식 문서) |
| 요금제 | Pro·Max 만 (Team·Enterprise 미지원) | 전 요금제 |

**API credential 을 권장한다.** 키 유출 경로가 원천적으로 없다.

Gemini 등록값:
- Allowed websites: `generativelanguage.googleapis.com`
- Custom headers: Name `x-goog-api-key`, **Prefix 비움**, Value = 키

`GeminiProvider(auth="proxy")` 가 이 경로를 쓴다. 키를 쿼리스트링(`?key=`)이 아니라
헤더로 보내도록 바꿨다 — URL 은 로그에 남지만 헤더는 남지 않는다.

검증(2026-09-13): credential 없이 호출하면
`403 PERMISSION_DENIED — Method doesn't allow unregistered callers` 가 온다.
요청이 구글까지 정상 도달한다는 뜻이고, credential 만 붙으면 200 이 된다.

이 세션 환경: `Default` (`env_01YVKtuJRdGZcKd4BkW7rCCe`, anthropic_cloud).

## 이 프로젝트에서 저지른 실수 (재발 방지)

- **코드를 읽고 키 위치를 추측했다.** `geo_measure.py` 가 `geo_measure.env` 를
  읽는 것을 보고 "Gemini 키가 거기 있다"고 단정했다. 실제로는 `gemini.env` 에
  있고, `geo_measure.env` 의 perplexity 칸은 빈값이다. → `ai_keys.py status` 로
  확인한다.
- **채팅으로 키를 요청했다.** 프로토콜 §5 금지 사항이다.
- **README 에 `export KEY=$(grep ... | cut -d= -f2)` 를 적었다.** 프로토콜 §3-3 의
  금지 예시와 동일하다. 제거했다.

## 주의: Gemini 키는 공유 자원

`gemini` 별칭은 **VPS GEO 측정과 같은 키**다(프로토콜 §1). 한도를 나눠 쓰므로
대량 생성은 GEO 주간 측정에 영향을 준다. 12장 규모 테스트는 작지만, 본격
배치 전에는 키 분리를 검토할 것 (프로토콜 §7 미결 항목).
