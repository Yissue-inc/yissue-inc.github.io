# 쿠팡 상품 에셋 스크래퍼

쿠팡 파트너스 딥링크(`link.coupang.com/a/...`) 또는 상품 URL을 넣으면
실제 브라우저로 페이지를 열어 **상품 메타데이터 + 이미지/영상 에셋**을 로컬에 저장합니다.

> **이 스크립트는 본인 PC에서 실행하세요.** Claude Code 웹 세션은 아웃바운드 정책상
> `link.coupang.com`을 포함한 일반 웹에 접근할 수 없어 여기서는 실행되지 않습니다.

## 설치

```bash
cd tools/coupang-scraper
npm install
npx playwright install chromium
```

## 사용법

```bash
# 파트너스 딥링크 그대로 사용 가능
node scrape.js "https://link.coupang.com/a/XXXXXX"

# 설치된 실제 크롬을 쓰면 차단을 통과할 확률이 가장 높다
node scrape.js "https://link.coupang.com/a/XXXXXX" --channel chrome

# 저장 위치와 업스케일 지정
node scrape.js "https://www.coupang.com/vp/products/1234567890" --out ./내상품 --upscale 1200
```

전체 옵션은 `node scrape.js --help`로 확인하세요.

| 옵션 | 설명 |
|---|---|
| `--out <dir>` | 저장 위치 (기본: `./output/<productId>`) |
| `--profile <dir>` | 브라우저 프로필. 쿠키가 유지돼 재실행 시 차단이 줄어듦 |
| `--channel <name>` | 설치된 실제 브라우저 사용 (`chrome`, `msedge`) — **차단 회피에 가장 효과적** |
| `--executable <path>` | 브라우저 실행 파일 직접 지정 |
| `--headless` | 창 없이 실행. 기본은 창 표시 (쿠팡은 headless 차단이 잦음) |
| `--upscale <px>` | CDN 썸네일 크기 세그먼트를 교체해 고해상도로 받음 (기본 1000, `--no-upscale`로 해제) |
| `--max-scroll <n>` | 상세 이미지 지연 로딩용 최대 스크롤 횟수 (기본 60) |
| `--min-bytes <n>` | 이 크기 미만 응답은 추적 픽셀로 보고 제외 (기본 1024) |
| `--no-download` | 목록/메타데이터만 저장하고 파일은 받지 않음 |
| `--no-screenshot` | 전체 페이지 스크린샷 생략 |

## 결과물

```
output/1234567890/
├── product.json     상품 메타데이터 + 전체 에셋 매니페스트
├── page.html        렌더링 완료된 DOM 스냅샷
├── page.png         전체 페이지 스크린샷
├── gallery/         상단 상품 이미지 (001_, 002_ ... 순서 보존)
├── detail/          상세 설명 이미지
└── other/           네트워크에서만 잡힌 나머지 에셋
```

`product.json`에는 상품명·가격·평점·리뷰수·브랜드·옵션과 함께
원본 JSON-LD, 리다이렉트 체인, `productId`/`itemId`/`vendorItemId`,
에셋별 원본 URL·저장 경로·바이트 수가 들어갑니다.

## 동작 방식

에셋 수집은 **두 경로의 합집합**이라 한쪽이 실패해도 누락되지 않습니다.

1. **네트워크 캡처** — 페이지가 실제로 내려받은 `image/*`, `video/*` 응답을 그대로 기록.
   CSS 클래스가 바뀌어도 영향을 받지 않습니다.
2. **DOM 추출** — `src`, `data-src`, `srcset`, 인라인 `background-image`까지 훑어
   아직 로드되지 않은 lazy 속성도 확보합니다.

메타데이터는 **JSON-LD(`application/ld+json`) → `og:` 메타태그 → CSS 선택자** 순으로 폴백합니다.
쿠팡 마크업은 수시로 바뀌므로 선택자 의존도를 의도적으로 낮췄습니다.

지연 로딩된 상세 이미지는 `"상세정보 더보기"` 계열 버튼을 먼저 클릭한 뒤
페이지 높이가 더 이상 늘지 않을 때까지 스크롤해서 전부 펼칩니다.

## 차단됐을 때

쿠팡은 봇 탐지가 강합니다. 실패하면 순서대로 시도하세요.

1. `--channel chrome` — 번들 크로미움 대신 실제 크롬 사용
2. headed 모드 유지(기본값). `--headless`는 차단률이 높습니다
3. 창이 뜬 상태에서 직접 캡차를 통과 — 차단 화면이 감지되면 스크립트가 멈추고
   Enter 입력을 기다립니다. 통과 후 Enter를 누르면 이어서 진행합니다
4. `--profile`을 유지해 쿠키를 재사용하면 재실행 시 통과율이 올라갑니다

상품명 추출에 실패하면 스크립트가 경고를 띄웁니다. 이때는 `page.png`를 먼저 열어
실제로 무엇이 렌더링됐는지 확인하세요.

## 테스트

```bash
node test-units.js
```

URL 정규화·해상도 업스케일·파일명 생성·상품 ID 파싱 등 순수 함수를
네트워크 없이 검증합니다.

## 알아둘 점

쿠팡 이용약관은 자동화된 크롤링을 제한하고 있고, 상품 상세 이미지의 저작권은
판매자/제조사에 있습니다. 파트너스 활동용으로 상품 정보가 필요하다면
**쿠팡 파트너스 오픈 API**가 정식 경로이며, 상품명·가격·이미지 URL·추적 링크를
약관 안에서 받을 수 있습니다. 이 스크립트는 개인적인 자료 수집·검토 용도로만 사용하고,
받은 이미지를 재배포할 때는 저작권을 별도로 확인하세요.
