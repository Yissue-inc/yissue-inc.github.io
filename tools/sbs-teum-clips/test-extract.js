'use strict';
/*
 * 게임 이름 추출 회귀 테스트 — 네트워크/브라우저 없이 실행: node test-extract.js
 * real-titles.json 은 SBS 공식 클립의 실제 제목이다 (검색으로 수집).
 */

const assert = require('assert');
const { buildGameList, stageOf, toCsv, extractQuoted, extractBeforeOutcome } = require('./scrape-clips.js');
const titles = require('./real-titles.json');

const clips = titles.map((t, i) => ({ title: t, url: `https://programs.sbs.co.kr/enter/teum/clip/82063/OC${i}` }));
const { games, otherQuoted } = buildGameList(clips);
const names = games.map((g) => g.name);

let pass = 0;
function t(name, fn) {
  try { fn(); pass++; console.log(`  ok  ${name}`); }
  catch (e) { console.error(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

console.log('실제 제목에서 게임 이름을 찾아낸다');
for (const expected of ['병 위의 탁구공 맞히기', '기타 피크 판치기', '딱지 2개 넘기기', '협동 공기']) {
  t(`'${expected}' 를 찾는다`, () => {
    assert.ok(names.includes(expected), `찾지 못함. 실제 결과: ${JSON.stringify(names)}`);
  });
}

console.log('진행 용어와 별명은 게임으로 잡지 않는다');
for (const junk of ['미션', '게임', '틈 미션', '게임 구멍', '첫 번째 미션', '손전략', '도전']) {
  t(`'${junk}' 는 제외한다`, () => {
    assert.ok(!names.includes(junk), `게임 목록에 섞임: ${JSON.stringify(names)}`);
  });
}

console.log('잡음 억제');
t('결과에 따옴표/대괄호 조각이 남지 않는다', () => {
  const dirty = names.filter((n) => /['"‘’“”\[\]]/.test(n));
  assert.deepStrictEqual(dirty, [], `조각 섞임: ${JSON.stringify(dirty)}`);
});
t('부분 문자열은 더 긴 이름에 흡수된다 (공기 -> 협동 공기)', () => {
  assert.ok(!names.includes('공기'), '단독 "공기" 가 남았다');
  assert.ok(names.includes('협동 공기'));
});
t('한 클립에서 같은 게임을 중복 집계하지 않는다', () => {
  const g = games.find((x) => x.name === '딱지 2개 넘기기');
  assert.strictEqual(g.count, 1, `count=${g.count} (근거 클립은 1건뿐)`);
  assert.strictEqual(g.examples.length, 1);
});
t('게임 후보 수가 과도하게 늘지 않는다', () => {
  assert.ok(games.length <= 8, `후보 ${games.length}건 — 잡음이 늘었을 수 있다: ${JSON.stringify(names)}`);
});

console.log('보조 출력');
t('걸러진 따옴표 문구는 원문 그대로 남는다', () => {
  const raw = otherQuoted.map((o) => o.name);
  assert.ok(raw.includes('게임 구멍'), `원문 보존 실패: ${JSON.stringify(raw)}`);
});
t('따옴표 추출은 프로그램명 접두사를 무시한다', () => {
  const q = extractQuoted("틈만나면, : 유재석, '병 위의 탁구공 맞히기' 게임 3단계 성공★");
  assert.ok(q.includes('병 위의 탁구공 맞히기'), JSON.stringify(q));
});
t('n-gram 추출은 성공 앞 구간만 본다', () => {
  const out = extractBeforeOutcome('틈만나면, : 멤버들, 딱지 2개 넘기기 한 번에 성공★');
  assert.ok(out.includes('딱지 2개 넘기기'), JSON.stringify(out));
});

console.log('부가 파싱');
t('단계를 뽑는다', () => {
  assert.strictEqual(stageOf('3단계 성공★'), 3);
  assert.strictEqual(stageOf('2 단계 미션'), 2);
  assert.strictEqual(stageOf('단계 없음'), null);
});
t('CSV 는 따옴표와 쉼표를 이스케이프한다', () => {
  const csv = toCsv([{ date: '2026-01-01', stage: 1, title: '유재석, "테스트" 성공', url: 'http://x' }]);
  assert.ok(csv.includes('"유재석, ""테스트"" 성공"'), csv);
});

console.log(`\n${pass}개 통과${process.exitCode ? ' (실패 있음)' : ''}`);
console.log(`추출된 게임: ${JSON.stringify(names, null, 0)}`);
