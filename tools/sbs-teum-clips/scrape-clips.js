#!/usr/bin/env node
'use strict';

/*
 * SBS '틈만나면,' 클립 목록 수집기 (로컬 실행 전용)
 *
 * 클립 목록 페이지의 "더보기"를 끝까지 눌러 전 회차 클립 제목을 모으고,
 * 제목에서 게임 이름 후보를 뽑아 정리한다.
 *
 * 링크 수집은 CSS 클래스에 의존하지 않는다. 프로그램 경로(/enter/teum/)를 가리키는
 * a 태그를 전부 훑기 때문에 SBS가 마크업을 바꿔도 잘 버틴다.
 *
 * 게임 이름 추출은 '보조 수단'이다. 확정 목록이 아니라 후보 + 근거 제목을 함께 내놓아
 * 사람이 눈으로 확인할 수 있게 한다.
 */

const fs = require('fs');
const path = require('path');

function loadPlaywright() {
  try {
    return require('playwright').chromium;
  } catch (err) {
    console.error('[!] playwright를 찾을 수 없습니다. 이 디렉터리에서 먼저 실행하세요:');
    console.error('    npm install && npx playwright install chromium');
    process.exit(1);
  }
}

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';

const DEFAULT_URL = 'https://programs.sbs.co.kr/enter/teum/clips/82063';

const HELP = `
SBS '틈만나면,' 클립 목록 수집기

사용법:
  node scrape-clips.js [옵션]

옵션:
  --url <url>        클립 목록 페이지 (기본: ${DEFAULT_URL})
  --filter <str>     이 문자열을 포함한 링크만 수집 (기본: /enter/teum/)
  --out <dir>        저장 위치 (기본: ./output)
  --max-pages <n>    "더보기" 클릭 최대 횟수 (기본: 300)
  --channel <name>   설치된 실제 브라우저 사용 (chrome, msedge)
  --executable <p>   브라우저 실행 파일 직접 지정
  --headless         창 없이 실행 (기본은 창 표시)
  --timeout <ms>     페이지 이동 타임아웃 (기본: 60000)
  --from <file>      크롤링을 건너뛰고 기존 clips.json 으로 게임 목록만 다시 뽑음
  -h, --help         이 도움말

예시:
  node scrape-clips.js --channel chrome
  node scrape-clips.js --from output/clips.json
`;

function parseArgs(argv) {
  const opts = {
    url: DEFAULT_URL,
    filter: '/enter/teum/',
    out: path.resolve(__dirname, 'output'),
    maxPages: 300,
    channel: null,
    executable: null,
    headless: false,
    timeout: 60000,
    from: null,
    help: false,
  };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    const next = () => argv[++i];
    switch (a) {
      case '--url': opts.url = next(); break;
      case '--filter': opts.filter = next(); break;
      case '--out': opts.out = path.resolve(next()); break;
      case '--max-pages': opts.maxPages = parseInt(next(), 10) || 0; break;
      case '--channel': opts.channel = next(); break;
      case '--executable': opts.executable = next(); break;
      case '--headless': opts.headless = true; break;
      case '--headed': opts.headless = false; break;
      case '--timeout': opts.timeout = parseInt(next(), 10) || 60000; break;
      case '--from': opts.from = path.resolve(next()); break;
      case '-h': case '--help': opts.help = true; break;
      default:
        console.error(`알 수 없는 옵션: ${a}`);
        process.exit(1);
    }
  }
  return opts;
}

/* ---------- 게임 이름 추출 ---------- */

// 제목에 게임 이름이 따옴표로 묶여 나오는 경우가 많다: '병 위의 탁구공 맞히기'
const QUOTE_PAIRS = [['\u2018', '\u2019'], ['\u201C', '\u201D'], ["'", "'"], ['"', '"'], ['\u300C', '\u300D']];

// 게임 이름에 자주 등장하는 사물
// '공', '구멍' 같은 지나치게 일반적인 낱말은 넣지 않는다.
// ('선공개'가 '공'에, 유재석 별명 '게임 구멍'이 '구멍'에 걸려 오탐이 난다)
const GAME_NOUNS = ['공기', '딱지', '탁구공', '제기', '팽이', '풍선', '컵', '젠가', '다트', '블록',
  '카드', '고리', '피크', '동전', '주사위', '볼링', '화살', '접시', '빨대', '종이컵', '페트병',
  '윷', '구슬', '병뚜껑', '젓가락', '신발', '모자', '공깃돌', '농구공', '축구공', '야구공'];

// 게임 이름을 끝맺는 동작
const ACTION_SUFFIX = ['맞히기', '맞추기', '넘기기', '판치기', '쌓기', '불기', '던지기', '넣기',
  '뒤집기', '세우기', '빼기', '옮기기', '튕기기', '통과하기', '탈출', '올리기', '붙이기', '피하기',
  '터트리기', '굴리기', '잡기', '건너기', '띄우기'];

// 어절 끝이 이러면 게임 이름이 아니라 서술어/부사다: '깔끔하게', '유지하며', '필승법으로'
const CONNECTIVE = /(하게|하며|하고|해서|하는|하자|면서|으로|에서|에게|부터|까지|만에|보다|없이|있게|같이|이며|이고|되며|한|던)$/;

// 그 자체로는 게임 이름이 될 수 없는 진행 용어
const STOP_TOKENS = new Set(['미션', '게임', '틈', '단계', '도전', '성공', '실패', '멤버들',
  '세리머니', '첫', '두', '세', '네', '번째', '모두', '다시', '오늘', '기회', '연속', '한']);

// 프로그램명 접두사('틈만나면, : ')를 떼어내 잡음을 줄인다
function stripPrefix(title) {
  const i = title.indexOf(' : ');
  return i === -1 ? title : title.slice(i + 3);
}

// 게임 이름이 되려면 사물이 들어가거나 동작으로 끝나야 한다.
// 이 관문이 '미션', '틈 미션', '게임 구멍' 같은 진행 용어/별명을 걸러낸다.
function qualifies(phrase) {
  const tokens = phrase.split(/\s+/).filter(Boolean);
  if (!tokens.length) return false;
  if (tokens.some((t) => CONNECTIVE.test(t))) return false;
  if (tokens.every((t) => STOP_TOKENS.has(t) || /^\d+개?$/.test(t))) return false;

  const hasNoun = GAME_NOUNS.some((n) => phrase.includes(n));
  const hasAction = ACTION_SUFFIX.some((sfx) => phrase.endsWith(sfx));
  const nominalized = /[가-힣]{2,}기$/.test(phrase); // 'OO기'로 끝나는 동명사
  return hasNoun || hasAction || nominalized;
}

// 후보 앞뒤에 붙은 진행 용어를 떼어낸다: '멤버들 딱지 2개 넘기기' -> '딱지 2개 넘기기'
function trimStopTokens(phrase) {
  const tokens = phrase.split(/\s+/).filter(Boolean);
  while (tokens.length && STOP_TOKENS.has(tokens[0])) tokens.shift();
  while (tokens.length && STOP_TOKENS.has(tokens[tokens.length - 1])) tokens.pop();
  return tokens.join(' ') || phrase;
}

function scoreCandidate(text) {
  const t = text.trim();
  if (!t || t.length < 2 || t.length > 30) return -99;
  if (!qualifies(t)) return -99;

  let score = 0;
  if (ACTION_SUFFIX.some((sfx) => t.endsWith(sfx))) score += 4;
  else if (/[가-힣]{2,}기$/.test(t)) score += 2;
  if (GAME_NOUNS.some((n) => t.includes(n))) score += 3;

  const words = t.split(/\s+/).length;
  if (words >= 2 && words <= 4) score += 1; // 게임 이름은 보통 2~4어절

  if (/[.…!?~]$/.test(t)) score -= 4;       // 대사체
  if (t.includes('\u00D7')) score -= 4;      // 출연자 나열
  if (/\d+단계/.test(t)) score -= 2;
  return score;
}

const esc = (c) => c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// 따옴표/대괄호로 묶인 구간을 지운다. 인용구는 extractQuoted 가 따로 처리하므로,
// n-gram 단계에서는 지워야 "미션' 딱지 2개 넘기기" 같은 조각이 안 생긴다.
function stripQuotedSpans(text) {
  let out = text;
  for (const [open, close] of QUOTE_PAIRS) {
    out = out.replace(new RegExp(`${esc(open)}[^${esc(close)}]{0,60}${esc(close)}`, 'g'), ' ');
  }
  return out.replace(/\[[^\]]{0,40}\]/g, ' ');
}

function extractQuoted(title) {
  const body = stripPrefix(title);
  const found = [];
  for (const [open, close] of QUOTE_PAIRS) {
    const re = new RegExp(`${esc(open)}([^${esc(close)}]{2,40})${esc(close)}`, 'g');
    let m;
    while ((m = re.exec(body)) !== null) found.push(m[1].trim());
  }
  return found;
}

// 따옴표가 없는 제목 대비: '... 딱지 2개 넘기기 한 번에 성공' 처럼
// 성공/실패 앞 최대 6어절 안의 모든 n-gram(1~4어절)을 후보로 던지고 점수로 거른다.
function extractBeforeOutcome(title) {
  const body = stripQuotedSpans(stripPrefix(title));
  const out = [];
  const re = /(성공|실패)/g;
  let m;
  while ((m = re.exec(body)) !== null) {
    const tokens = body.slice(0, m.index).split(/[\s,\u3001]+/).filter(Boolean).slice(-6);
    for (let start = 0; start < tokens.length; start++) {
      for (let len = 1; len <= 4 && start + len <= tokens.length; len++) {
        out.push(tokens.slice(start, start + len).join(' '));
      }
    }
  }
  return out;
}

function buildGameList(clips) {
  const bucket = new Map();
  const otherQuoted = new Map();

  const add = (rawName, source, clip) => {
    const key = trimStopTokens(String(rawName).trim());
    if (!key) return;
    const score = scoreCandidate(key);
    if (score < 2) {
      // 게임 이름 관문은 못 넘었지만 따옴표로 강조된 문구는 따로 남겨 사람이 보게 한다
      const raw = String(rawName).trim(); // 참고용이므로 원문 그대로 보존한다
      if (source === 'quoted' && raw.length >= 2 && raw.length <= 30) {
        if (!otherQuoted.has(raw)) otherQuoted.set(raw, { name: raw, count: 0, examples: [] });
        const o = otherQuoted.get(raw);
        o.count++;
        if (o.examples.length < 2) o.examples.push({ title: clip.title, url: clip.url });
      }
      return;
    }
    if (!bucket.has(key)) bucket.set(key, { name: key, score, source, count: 0, examples: [] });
    const b = bucket.get(key);
    b.count++;
    if (b.examples.length < 3) b.examples.push({ title: clip.title, url: clip.url });
    if (source === 'quoted') b.source = 'quoted'; // 따옴표 근거가 더 강하다
  };

  // 한 클립에서 여러 n-gram이 같은 이름으로 정규화될 수 있다
  // ('멤버들 딱지 2개 넘기기', '딱지 2개 넘기기 한' -> '딱지 2개 넘기기').
  // 클립 단위로 중복을 걷어내야 count 가 '이 게임이 등장한 클립 수'를 뜻하게 된다.
  for (const clip of clips) {
    const seenKeys = new Set();
    const feed = (names, source) => {
      for (const n of names) {
        const key = trimStopTokens(String(n).trim());
        if (!key || seenKeys.has(key)) continue;
        seenKeys.add(key);
        add(n, source, clip);
      }
    };
    feed(extractQuoted(clip.title), 'quoted');
    feed(extractBeforeOutcome(clip.title), 'outcome');
  }

  // 더 긴 후보에 통째로 포함되고 점수도 낮으면 부분 문자열은 버린다
  // ('공기' -> '협동 공기' 에 흡수)
  let games = [...bucket.values()];
  games = games.filter((g) =>
    !games.some((other) => other !== g && other.name.includes(g.name) && other.score >= g.score)
  );

  games.sort((a, b) => b.score - a.score || b.count - a.count || a.name.localeCompare(b.name));
  const extras = [...otherQuoted.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  return { games, otherQuoted: extras };
}

function stageOf(title) {
  const m = /([123])\s*단계/.exec(title);
  return m ? Number(m[1]) : null;
}

/* ---------- 출력 ---------- */

function toCsv(clips) {
  const esc = (v) => `"${String(v == null ? '' : v).replace(/"/g, '""')}"`;
  const rows = [['date', 'stage', 'title', 'url'].join(',')];
  for (const c of clips) rows.push([esc(c.date), esc(c.stage), esc(c.title), esc(c.url)].join(','));
  return rows.join('\n') + '\n';
}

function toMarkdown(result, clips) {
  const { games, otherQuoted } = result;
  const lines = [];
  lines.push('# 틈만나면, 게임 이름 정리', '');
  lines.push(`- 수집 클립: **${clips.length}건**`);
  lines.push(`- 게임 후보: **${games.length}건**`);
  lines.push(`- 생성 시각: ${new Date().toISOString()}`, '');
  lines.push('> 클립 제목에서 자동 추출한 결과입니다. 근거 제목을 함께 실었으니 눈으로 확인하세요.', '');

  const strong = games.filter((g) => g.source === 'quoted');
  const weak = games.filter((g) => g.source !== 'quoted');

  const section = (heading, list, note) => {
    if (!list.length) return;
    lines.push(`## ${heading}`, '');
    if (note) lines.push(note, '');
    lines.push('| 게임 | 등장 | 근거 클립 |');
    lines.push('|---|---|---|');
    for (const g of list) {
      const ex = g.examples
        .map((e) => `[${e.title.replace(/\|/g, '\\|')}](${e.url})`)
        .join('<br>');
      lines.push(`| **${g.name}** | ${g.count} | ${ex} |`);
    }
    lines.push('');
  };

  section('따옴표로 명시된 게임 이름', strong, '제목에 게임 이름이 그대로 인용된 것들로, 가장 확실합니다.');
  section('문맥에서 추정한 게임 이름', weak, '성공/실패 앞 문구에서 뽑았습니다. 대체로 맞지만 확인을 권합니다.');

  if (otherQuoted.length) {
    lines.push('## 그 밖의 따옴표 문구', '');
    lines.push('게임 이름 조건(사물 또는 동작 포함)은 못 넘었지만 제목에서 강조된 문구입니다.');
    lines.push('별명·대사가 대부분이나, 놓친 게임 이름이 섞여 있을 수 있어 남깁니다.', '');
    for (const o of otherQuoted.slice(0, 60)) {
      lines.push(`- ${o.name} (${o.count}회) — [예시](${o.examples[0].url})`);
    }
    lines.push('');
  }

  return lines.join('\n');
}

/* ---------- 크롤링 ---------- */

async function harvest(page, filter, seen) {
  const items = await page.evaluate((f) => {
    const out = [];
    for (const a of document.querySelectorAll('a[href]')) {
      const href = a.href;
      if (!href || href.indexOf(f) === -1) continue;
      if (!/\/(clip|vod)\//.test(href)) continue;

      let title = (a.getAttribute('title') || '').trim();
      if (!title) {
        const img = a.querySelector('img[alt]');
        if (img) title = (img.getAttribute('alt') || '').trim();
      }
      if (!title) title = (a.innerText || '').replace(/\s+/g, ' ').trim();
      if (!title || title.length < 4) continue;

      let date = null;
      const box = a.closest('li, article, .item, div');
      if (box) {
        const m = /(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})/.exec(box.innerText || '');
        if (m) date = `${m[1]}-${String(m[2]).padStart(2, '0')}-${String(m[3]).padStart(2, '0')}`;
      }
      out.push({ url: href.split('#')[0], title, date });
    }
    return out;
  }, filter);

  let added = 0;
  for (const it of items) {
    if (!seen.has(it.url)) { seen.set(it.url, it); added++; }
  }
  return added;
}

async function clickMore(page) {
  const selectors = [
    'button:has-text("더보기")',
    'a:has-text("더보기")',
    '.btn_more', '.more_btn', '[class*="more"] button', '[class*="more"] a',
  ];
  for (const sel of selectors) {
    try {
      const el = page.locator(sel).first();
      if (await el.isVisible({ timeout: 500 })) {
        await el.click({ timeout: 3000 });
        return true;
      }
    } catch (_) { /* 다음 후보 */ }
  }
  return false;
}

async function crawl(opts) {
  const chromium = loadPlaywright();
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

  const browser = await chromium.launch(launchOpts);
  const ctx = await browser.newContext(launchOpts);
  const page = await ctx.newPage();

  console.log(`[1/3] 클립 목록 열기: ${opts.url}`);
  await page.goto(opts.url, { waitUntil: 'domcontentloaded', timeout: opts.timeout });
  await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});

  const seen = new Map();
  await harvest(page, opts.filter, seen);
  console.log(`    · 첫 화면에서 ${seen.size}건`);

  console.log('[2/3] "더보기" 끝까지 펼치기');
  let stagnant = 0;
  for (let i = 0; i < opts.maxPages; i++) {
    const before = seen.size;
    const clicked = await clickMore(page);
    if (!clicked) {
      // 더보기 버튼이 없으면 무한 스크롤로 간주
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    }
    await page.waitForTimeout(1200);
    await harvest(page, opts.filter, seen);

    if (seen.size === before) {
      if (++stagnant >= 3) { console.log(`    · 더 이상 늘지 않아 종료 (${i + 1}회 시도)`); break; }
    } else {
      stagnant = 0;
      process.stdout.write(`\r    · ${seen.size}건 수집...`);
    }
  }
  process.stdout.write('\n');

  await browser.close();
  return [...seen.values()];
}

/* ---------- 메인 ---------- */

async function main() {
  const opts = parseArgs(process.argv);
  if (opts.help) { console.log(HELP); return; }

  let clips;
  if (opts.from) {
    console.log(`[1/3] 기존 파일에서 로드: ${opts.from}`);
    const raw = JSON.parse(fs.readFileSync(opts.from, 'utf8'));
    clips = Array.isArray(raw) ? raw : raw.clips;
    if (!Array.isArray(clips)) throw new Error('clips.json 형식이 올바르지 않습니다 (배열 또는 {clips:[]})');
    console.log(`    · ${clips.length}건`);
  } else {
    clips = await crawl(opts);
  }

  for (const c of clips) c.stage = stageOf(c.title);
  clips.sort((a, b) => (a.date || '').localeCompare(b.date || '') || a.title.localeCompare(b.title));

  console.log('[3/3] 게임 이름 추출 및 저장');
  const result = buildGameList(clips);

  fs.mkdirSync(opts.out, { recursive: true });
  fs.writeFileSync(path.join(opts.out, 'clips.json'),
    JSON.stringify({ scrapedAt: new Date().toISOString(), source: opts.from || opts.url, count: clips.length, clips }, null, 2), 'utf8');
  fs.writeFileSync(path.join(opts.out, 'clips.csv'), toCsv(clips), 'utf8');
  fs.writeFileSync(path.join(opts.out, 'games.md'), toMarkdown(result, clips), 'utf8');

  console.log('\n완료');
  console.log(`  클립      : ${clips.length}건`);
  console.log(`  게임 후보 : ${result.games.length}건 (따옴표 근거 ${result.games.filter((g) => g.source === 'quoted').length}건)`);
  console.log(`  저장 위치 : ${opts.out}`);
  console.log('    clips.json / clips.csv / games.md');
  if (clips.length === 0) {
    console.log('\n[!] 한 건도 수집되지 않았습니다. --filter 값이 실제 링크 경로와 맞는지 확인하세요.');
  }
}

module.exports = { extractQuoted, scoreCandidate, extractBeforeOutcome, buildGameList, stageOf, toCsv };

if (require.main === module) {
  main().catch((err) => {
    console.error(`\n[!] 오류: ${err && err.stack ? err.stack : err}`);
    process.exit(1);
  });
}
