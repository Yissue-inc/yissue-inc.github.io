#!/usr/bin/env node
'use strict';

/*
 * 쿠팡 상품 페이지 에셋 스크래퍼 (로컬 실행 전용)
 *
 * 파트너스 딥링크(link.coupang.com/a/...) 또는 상품 URL을 받아
 * 실제 브라우저로 페이지를 열고, 지연 로딩된 상세 이미지까지 모두 펼친 뒤
 * 상품 메타데이터와 이미지/영상 에셋을 로컬 폴더에 저장한다.
 *
 * 에셋 수집은 두 경로를 합집합으로 사용한다.
 *   1) 네트워크 캡처 - 페이지가 실제로 내려받은 image/video 응답 (CSS 클래스 변경에 영향 없음)
 *   2) DOM 추출     - src / data-src / srcset / background-image (아직 로드되지 않은 lazy 속성까지)
 *
 * 메타데이터는 JSON-LD(application/ld+json) → og: 메타태그 → CSS 선택자 순으로 폴백한다.
 * 쿠팡 마크업은 수시로 바뀌므로 선택자 의존도를 최대한 낮춘 구조다.
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

// playwright는 --help 등 브라우저가 필요 없는 경로에서도 스크립트가 뜨도록 지연 로딩한다.
function loadPlaywright() {
  try {
    return require('playwright').chromium;
  } catch (err) {
    console.error('[!] playwright를 찾을 수 없습니다. 이 디렉터리에서 다음을 먼저 실행하세요:');
    console.error('    npm install && npx playwright install chromium');
    process.exit(1);
  }
}

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';

const HELP = `
쿠팡 상품 에셋 스크래퍼

사용법:
  node scrape.js <쿠팡 URL> [옵션]

옵션:
  --out <dir>        저장 위치 (기본: ./output/<productId 또는 타임스탬프>)
  --profile <dir>    브라우저 프로필 디렉터리. 쿠키가 유지되어 재실행 시 차단이 줄어든다 (기본: ./.profile)
  --channel <name>   설치된 실제 브라우저 사용 (예: chrome, msedge). 봇 탐지 회피에 가장 효과적
  --executable <p>   브라우저 실행 파일 경로를 직접 지정 (--channel 대신 쓰는 수동 지정용)
  --headless         창 없이 실행 (기본은 창 표시 — 쿠팡은 headless 차단이 잦음)
  --upscale <px>     CDN 썸네일 크기 세그먼트를 해당 픽셀로 교체 (기본: 1000, 끄려면 --no-upscale)
  --max-scroll <n>   상세 이미지 지연 로딩용 최대 스크롤 횟수 (기본: 60)
  --min-bytes <n>    이 크기 미만 응답은 추적 픽셀로 보고 제외 (기본: 1024)
  --timeout <ms>     페이지 이동 타임아웃 (기본: 60000)
  --no-download      메타데이터/목록만 저장하고 파일은 받지 않음
  --no-screenshot    전체 페이지 스크린샷 생략
  -h, --help         이 도움말

예시:
  node scrape.js "https://link.coupang.com/a/XXXXXX" --channel chrome
  node scrape.js "https://www.coupang.com/vp/products/1234567890" --out ./내상품 --upscale 1200
`;

function parseArgs(argv) {
  const opts = {
    url: null,
    out: null,
    profile: path.resolve(__dirname, '.profile'),
    channel: null,
    executable: null,
    headless: false,
    upscale: 1000,
    maxScroll: 60,
    minBytes: 1024,
    timeout: 60000,
    download: true,
    screenshot: true,
    help: false,
  };
  const rest = [];
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    const next = () => argv[++i];
    switch (a) {
      case '--url': opts.url = next(); break;
      case '--out': opts.out = path.resolve(next()); break;
      case '--profile': opts.profile = path.resolve(next()); break;
      case '--channel': opts.channel = next(); break;
      case '--executable': opts.executable = next(); break;
      case '--headless': opts.headless = true; break;
      case '--headed': opts.headless = false; break;
      case '--upscale': opts.upscale = parseInt(next(), 10) || 0; break;
      case '--no-upscale': opts.upscale = 0; break;
      case '--max-scroll': opts.maxScroll = parseInt(next(), 10) || 0; break;
      case '--min-bytes': opts.minBytes = parseInt(next(), 10) || 0; break;
      case '--timeout': opts.timeout = parseInt(next(), 10) || 60000; break;
      case '--no-download': opts.download = false; break;
      case '--no-screenshot': opts.screenshot = false; break;
      case '-h': case '--help': opts.help = true; break;
      default:
        if (a.startsWith('-')) {
          console.error(`알 수 없는 옵션: ${a}`);
          process.exit(1);
        }
        rest.push(a);
    }
  }
  if (!opts.url && rest.length) opts.url = rest[0];
  return opts;
}

/* ---------- URL 유틸 ---------- */

function normalizeUrl(raw) {
  if (!raw) return null;
  const u = String(raw).trim();
  if (!u || u.startsWith('data:') || u.startsWith('blob:') || u.startsWith('about:')) return null;
  if (u.startsWith('//')) return 'https:' + u;
  // 스킴은 그대로 둔다. http를 https로 강제 승격하면 http로만 서빙되는 에셋을 통째로 놓친다.
  if (/^https?:\/\//i.test(u)) return u;
  return null;
}

// //thumbnail7.coupangcdn.com/thumbnails/remote/230x230ex/image/...
//   -> //thumbnail7.coupangcdn.com/thumbnails/remote/1000x1000ex/image/...
function upscaleUrl(u, size) {
  if (!size || !/coupangcdn\.com/i.test(u)) return u;
  return u.replace(
    /\/(\d{2,4})x(\d{2,4})(ex|q\d{1,3})?\//,
    (match, w, h, suffix) => `/${size}x${size}${suffix || ''}/`
  );
}

function extFromType(ct) {
  if (!ct) return null;
  const t = ct.split(';')[0].trim().toLowerCase();
  const map = {
    'image/jpeg': '.jpg', 'image/jpg': '.jpg', 'image/png': '.png',
    'image/gif': '.gif', 'image/webp': '.webp', 'image/avif': '.avif',
    'image/svg+xml': '.svg', 'image/bmp': '.bmp',
    'video/mp4': '.mp4', 'video/webm': '.webm', 'video/quicktime': '.mov',
  };
  return map[t] || null;
}

function fileNameFor(u, contentType, index) {
  let base = 'asset';
  try {
    base = path.basename(new URL(u).pathname) || 'asset';
  } catch (_) { /* keep default */ }
  base = base.replace(/[^A-Za-z0-9._-]/g, '_').slice(-80);
  if (!path.extname(base)) base += extFromType(contentType) || '.jpg';
  return `${String(index).padStart(3, '0')}_${base}`;
}

function parseProductIds(u) {
  const ids = {};
  try {
    const url = new URL(u);
    const m = /\/vp\/products\/(\d+)/.exec(url.pathname);
    if (m) ids.productId = m[1];
    for (const k of ['itemId', 'vendorItemId', 'sourceType', 'searchId']) {
      const v = url.searchParams.get(k);
      if (v) ids[k] = v;
    }
  } catch (_) { /* ignore */ }
  return ids;
}

/* ---------- 페이지 조작 ---------- */

async function autoScroll(page, maxSteps) {
  let stagnant = 0;
  let lastHeight = 0;
  for (let i = 0; i < maxSteps; i++) {
    const { height, bottom } = await page.evaluate(() => ({
      height: document.body.scrollHeight,
      bottom: window.scrollY + window.innerHeight,
    }));
    if (height === lastHeight && bottom >= height - 100) {
      if (++stagnant >= 3) break;
    } else {
      stagnant = 0;
    }
    lastHeight = height;
    await page.mouse.wheel(0, 1400);
    await page.waitForTimeout(350);
  }
  // 위로 한 번 돌아가 상단 갤러리의 lazy 이미지도 확실히 로드시킨다
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(600);
}

async function expandDetail(page) {
  const candidates = [
    'button:has-text("상세정보 더보기")',
    'button:has-text("상품정보 더보기")',
    'a:has-text("상세정보 펼쳐보기")',
    'button:has-text("펼쳐보기")',
    '.prod-detail-more',
    '[class*="detail-more"] button',
  ];
  for (const sel of candidates) {
    try {
      const el = page.locator(sel).first();
      if (await el.isVisible({ timeout: 800 })) {
        await el.click({ timeout: 3000 });
        await page.waitForTimeout(900);
        console.log(`    · "더보기" 확장: ${sel}`);
      }
    } catch (_) { /* 없으면 무시 */ }
  }
}

async function extractMetadata(page) {
  return page.evaluate(() => {
    const clean = (s) => (s ? String(s).replace(/\s+/g, ' ').trim() : null);
    const q = (sel) => { const el = document.querySelector(sel); return el ? clean(el.textContent) : null; };
    const firstOf = (sels) => { for (const s of sels) { const t = q(s); if (t) return t; } return null; };
    const metaOf = (name) => {
      const el = document.querySelector(`meta[property="${name}"], meta[name="${name}"]`);
      return el ? clean(el.getAttribute('content')) : null;
    };
    const absOf = (name) => {
      const v = metaOf(name);
      if (!v) return null;
      try { return new URL(v, location.href).href; } catch (_) { return v; }
    };

    // 1) JSON-LD Product (가장 안정적)
    let ld = null;
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const parsed = JSON.parse(s.textContent);
        const nodes = Array.isArray(parsed) ? parsed : (parsed['@graph'] || [parsed]);
        for (const n of nodes) {
          if (!n || !n['@type']) continue;
          const t = Array.isArray(n['@type']) ? n['@type'] : [n['@type']];
          if (t.includes('Product')) { ld = n; break; }
        }
      } catch (_) { /* 깨진 LD는 건너뜀 */ }
      if (ld) break;
    }

    const offers = ld && ld.offers
      ? (Array.isArray(ld.offers) ? ld.offers[0] : ld.offers)
      : null;

    const options = Array.from(
      document.querySelectorAll('.prod-option__item, [class*="option-item"]')
    ).map((el) => clean(el.textContent)).filter(Boolean).slice(0, 50);

    return {
      title:
        (ld && clean(ld.name)) ||
        metaOf('og:title') ||
        firstOf(['h1.prod-buy-header__title', 'h2.prod-buy-header__title', 'h1', '[class*="prod-buy-header__title"]']) ||
        clean(document.title),
      price:
        (offers && (offers.price || offers.lowPrice)) ||
        firstOf(['.prod-price .total-price strong', '.total-price > strong', 'span.total-price', '[class*="price-value"]']),
      currency: (offers && offers.priceCurrency) || 'KRW',
      originPrice: firstOf(['.prod-origin-price .origin-price', '[class*="origin-price"]']),
      rating: (ld && ld.aggregateRating && ld.aggregateRating.ratingValue) ||
        firstOf(['.rds-rating-score', '[class*="rating-star-num"]']),
      reviewCount: (ld && ld.aggregateRating && ld.aggregateRating.reviewCount) ||
        firstOf(['[class*="review-count"]', '#prod-review-nav-link .count']),
      brand: (ld && ld.brand && (ld.brand.name || ld.brand)) || null,
      seller: firstOf(['.prod-sale-vendor-name', '[class*="vendor-name"]']),
      description: (ld && clean(ld.description)) || metaOf('og:description'),
      ogImage: absOf('og:image'),
      options,
      jsonLd: ld || null,
    };
  });
}

async function extractDomAssets(page) {
  return page.evaluate(() => {
    const out = [];
    const detailRoots = Array.from(document.querySelectorAll(
      '#productDetail, .product-detail, .prod-detail, [class*="product-detail"], .vendor-item, .subType-IMAGE'
    ));
    const groupFor = (el) => (detailRoots.some((r) => r.contains(el)) ? 'detail' : 'gallery');

    const push = (raw, el, kind) => {
      if (!raw) return;
      let href;
      try { href = new URL(String(raw).trim(), location.href).href; } catch (_) { return; }
      if (!/^https?:/i.test(href)) return;
      out.push({ url: href, group: groupFor(el), kind });
    };

    for (const img of document.querySelectorAll('img')) {
      for (const attr of ['src', 'data-src', 'data-original', 'data-img-src', 'data-lazy-src']) {
        push(img.getAttribute(attr), img, 'img');
      }
      const ss = img.getAttribute('srcset') || img.getAttribute('data-srcset');
      if (ss) for (const part of ss.split(',')) push(part.trim().split(/\s+/)[0], img, 'img');
    }
    for (const s of document.querySelectorAll('source')) {
      push(s.getAttribute('src'), s, 'source');
      const ss = s.getAttribute('srcset');
      if (ss) for (const part of ss.split(',')) push(part.trim().split(/\s+/)[0], s, 'source');
    }
    for (const v of document.querySelectorAll('video')) {
      push(v.getAttribute('src'), v, 'video');
      push(v.getAttribute('poster'), v, 'img');
    }
    for (const el of document.querySelectorAll('[style*="url("]')) {
      const m = /url\((['"]?)(.*?)\1\)/.exec(el.getAttribute('style') || '');
      if (m) push(m[2], el, 'background');
    }
    return out;
  });
}

/* ---------- 다운로드 ---------- */

async function downloadAsset(ctx, asset, destPath, upscale, referer) {
  const attempts = [];
  const upscaled = upscaleUrl(asset.url, upscale);
  if (upscaled !== asset.url) attempts.push(upscaled);
  attempts.push(asset.url);

  for (const candidate of attempts) {
    try {
      const res = await ctx.request.get(candidate, {
        timeout: 30000,
        headers: { referer, 'user-agent': UA },
      });
      if (!res.ok()) continue;
      const body = await res.body();
      if (!body || body.length === 0) continue;
      const ct = res.headers()['content-type'] || asset.contentType || '';
      const finalPath = path.extname(destPath)
        ? destPath
        : destPath + (extFromType(ct) || '.jpg');
      fs.writeFileSync(finalPath, body);
      return { file: path.basename(finalPath), bytes: body.length, fetchedFrom: candidate, contentType: ct };
    } catch (_) {
      // 다음 후보 URL로
    }
  }
  return null;
}

/* ---------- 메인 ---------- */

async function main() {
  const opts = parseArgs(process.argv);
  if (opts.help || !opts.url) {
    console.log(HELP);
    process.exit(opts.url ? 0 : 1);
  }
  if (!normalizeUrl(opts.url)) {
    console.error(`[!] 올바른 http(s) URL이 아닙니다: ${opts.url}`);
    process.exit(1);
  }

  const chromium = loadPlaywright();
  console.log(`[1/7] 브라우저 실행 (${opts.headless ? 'headless' : 'headed'}${opts.channel ? `, channel=${opts.channel}` : ''}${opts.executable ? `, exe=${opts.executable}` : ''})`);
  fs.mkdirSync(opts.profile, { recursive: true });

  const launchOpts = {
    headless: opts.headless,
    viewport: { width: 1440, height: 960 },
    userAgent: UA,
    locale: 'ko-KR',
    timezoneId: 'Asia/Seoul',
    args: ['--disable-blink-features=AutomationControlled', '--lang=ko-KR'],
  };
  if (opts.channel) launchOpts.channel = opts.channel;
  if (opts.executable) launchOpts.executablePath = opts.executable;

  const ctx = await chromium.launchPersistentContext(opts.profile, launchOpts);

  // 자동화 흔적 최소화
  await ctx.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR', 'ko', 'en-US'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
  });

  const page = ctx.pages()[0] || (await ctx.newPage());

  // 네트워크에서 실제로 내려온 미디어를 그대로 캡처 (선택자 변경에 영향받지 않음)
  const captured = new Map();
  page.on('response', (res) => {
    try {
      const ct = res.headers()['content-type'] || '';
      if (!/^(image|video)\//i.test(ct)) return;
      const len = parseInt(res.headers()['content-length'] || '0', 10);
      const u = normalizeUrl(res.url());
      if (!u) return;
      if (!captured.has(u)) captured.set(u, { contentType: ct, bytes: len });
    } catch (_) { /* ignore */ }
  });

  const redirects = [];
  page.on('framenavigated', (frame) => {
    if (frame === page.mainFrame()) redirects.push(frame.url());
  });

  console.log(`[2/7] 페이지 이동: ${opts.url}`);
  try {
    const resp = await page.goto(opts.url, { waitUntil: 'domcontentloaded', timeout: opts.timeout });
    // HTTP 3xx 리다이렉트는 framenavigated 로 잡히지 않으므로 요청 체인을 거슬러 올라간다
    if (resp) {
      const chain = [];
      for (let req = resp.request(); req; req = req.redirectedFrom()) chain.unshift(req.url());
      redirects.unshift(...chain);
    }
  } catch (err) {
    console.error(`[!] 페이지 이동 실패: ${err.message}`);
    await ctx.close();
    process.exit(1);
  }
  await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});

  const finalUrl = page.url();
  const ids = parseProductIds(finalUrl);
  console.log(`    · 최종 URL: ${finalUrl}`);
  if (ids.productId) console.log(`    · productId=${ids.productId}${ids.itemId ? ` itemId=${ids.itemId}` : ''}${ids.vendorItemId ? ` vendorItemId=${ids.vendorItemId}` : ''}`);

  // 차단/캡차 감지
  const bodyText = await page.evaluate(() => document.body ? document.body.innerText.slice(0, 400) : '');
  if (/Access Denied|잠시 후 다시|비정상적인 접근|captcha|자동입력 방지/i.test(bodyText)) {
    console.warn('[!] 봇 차단 화면으로 보입니다. 창에서 직접 인증을 통과시킨 뒤 Enter를 누르세요.');
    console.warn('    (--channel chrome 옵션과 headed 모드가 통과율이 가장 높습니다.)');
    await new Promise((resolve) => process.stdin.once('data', resolve));
    await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
  }

  console.log('[3/7] 상세 영역 펼치기 + 지연 로딩 스크롤');
  await expandDetail(page);
  await autoScroll(page, opts.maxScroll);
  await expandDetail(page);
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});

  console.log('[4/7] 메타데이터 추출');
  const meta = await extractMetadata(page);
  console.log(`    · 상품명: ${meta.title || '(추출 실패)'}`);
  console.log(`    · 가격: ${meta.price || '(추출 실패)'}`);

  console.log('[5/7] 에셋 목록 수집');
  const domAssets = await extractDomAssets(page);

  // DOM 정보(그룹)를 우선하고, 네트워크 캡처로 빠진 것을 보충한다
  const merged = new Map();
  for (const a of domAssets) {
    const u = normalizeUrl(a.url);
    if (!u) continue;
    if (!merged.has(u)) merged.set(u, { url: u, group: a.group, kind: a.kind, source: 'dom' });
  }
  for (const [u, info] of captured) {
    if (merged.has(u)) {
      merged.get(u).contentType = info.contentType;
      merged.get(u).source = 'dom+network';
      if (info.bytes) merged.get(u).bytes = info.bytes;
    } else {
      merged.set(u, {
        url: u,
        group: 'other',
        kind: /^video\//i.test(info.contentType) ? 'video' : 'img',
        contentType: info.contentType,
        bytes: info.bytes,
        source: 'network',
      });
    }
  }

  // 추적 픽셀/스프라이트 제거: 네트워크에서 확인된 크기가 기준치 미만이면 뺀다
  let assets = [...merged.values()].filter((a) => {
    if (a.source === 'network' && a.bytes && a.bytes < opts.minBytes) return false;
    if (/\.(svg)$/i.test(a.url) && a.group === 'other') return false;
    return true;
  });

  const order = { gallery: 0, detail: 1, other: 2 };
  assets.sort((a, b) => (order[a.group] - order[b.group]) || a.url.localeCompare(b.url));

  const counts = assets.reduce((acc, a) => { acc[a.group] = (acc[a.group] || 0) + 1; return acc; }, {});
  console.log(`    · 총 ${assets.length}개 (gallery ${counts.gallery || 0} / detail ${counts.detail || 0} / other ${counts.other || 0})`);

  const outDir = opts.out || path.resolve(__dirname, 'output', ids.productId || String(Date.now()));
  fs.mkdirSync(outDir, { recursive: true });
  console.log(`[6/7] 저장 위치: ${outDir}`);

  if (opts.screenshot) {
    await page.screenshot({ path: path.join(outDir, 'page.png'), fullPage: true }).catch((e) =>
      console.warn(`    · 스크린샷 실패: ${e.message}`)
    );
  }
  fs.writeFileSync(path.join(outDir, 'page.html'), await page.content(), 'utf8');

  let downloaded = 0;
  let failed = 0;
  if (opts.download) {
    console.log('[7/7] 에셋 다운로드');
    const perGroupIndex = {};
    for (const asset of assets) {
      fs.mkdirSync(path.join(outDir, asset.group), { recursive: true });
      perGroupIndex[asset.group] = (perGroupIndex[asset.group] || 0) + 1;
      const name = fileNameFor(asset.url, asset.contentType, perGroupIndex[asset.group]);
      const dest = path.join(outDir, asset.group, name);
      const result = await downloadAsset(ctx, asset, dest, opts.upscale, finalUrl);
      if (result) {
        Object.assign(asset, result, { path: `${asset.group}/${result.file}` });
        downloaded++;
        process.stdout.write(`\r    · ${downloaded}/${assets.length} 저장 중...`);
      } else {
        asset.error = 'download_failed';
        failed++;
      }
    }
    process.stdout.write('\n');
  } else {
    console.log('[7/7] --no-download 지정: 파일은 받지 않고 목록만 저장');
  }

  const manifest = {
    scrapedAt: new Date().toISOString(),
    inputUrl: opts.url,
    finalUrl,
    redirectChain: [...new Set(redirects)],
    ids,
    product: meta,
    stats: { total: assets.length, downloaded, failed, byGroup: counts },
    assets,
  };
  fs.writeFileSync(path.join(outDir, 'product.json'), JSON.stringify(manifest, null, 2), 'utf8');

  await ctx.close();

  console.log('\n완료');
  console.log(`  저장 위치 : ${outDir}`);
  console.log(`  메타데이터: product.json`);
  console.log(`  렌더 HTML : page.html${opts.screenshot ? ' / page.png' : ''}`);
  if (opts.download) console.log(`  에셋      : ${downloaded}개 성공, ${failed}개 실패`);
  if (!meta.title) {
    console.log('\n[!] 상품명 추출에 실패했습니다. 차단 페이지를 받았을 가능성이 높습니다.');
    console.log('    page.png를 열어 실제로 무엇이 렌더링됐는지 먼저 확인하세요.');
  }
}

module.exports = { normalizeUrl, upscaleUrl, fileNameFor, parseProductIds, extFromType };

// 다른 모듈에서 require할 때는 순수 함수만 노출하고 실행하지 않는다.
if (require.main === module) {
  main().catch((err) => {
    console.error(`\n[!] 오류: ${err && err.stack ? err.stack : err}`);
    process.exit(1);
  });
}
