'use strict';
/* 순수 함수 단위 테스트 — 네트워크/브라우저 없이 실행: node test-units.js */

const assert = require('assert');
const { normalizeUrl, upscaleUrl, fileNameFor, parseProductIds, extFromType } = require('./scrape.js');

let pass = 0;
function t(name, fn) {
  try { fn(); pass++; console.log(`  ok  ${name}`); }
  catch (e) { console.error(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

console.log('upscaleUrl');
t('썸네일 크기 세그먼트를 교체하고 ex 접미사를 보존한다', () => {
  assert.strictEqual(
    upscaleUrl('https://thumbnail7.coupangcdn.com/thumbnails/remote/230x230ex/image/vendor_inventory/a/1.jpg', 1000),
    'https://thumbnail7.coupangcdn.com/thumbnails/remote/1000x1000ex/image/vendor_inventory/a/1.jpg');
});
t('q 접미사도 보존한다', () => {
  assert.strictEqual(
    upscaleUrl('https://thumbnail9.coupangcdn.com/thumbnails/remote/492x492q90/image/x.jpg', 1200),
    'https://thumbnail9.coupangcdn.com/thumbnails/remote/1200x1200q90/image/x.jpg');
});
t('접미사가 없어도 동작한다', () => {
  assert.strictEqual(
    upscaleUrl('https://thumbnail1.coupangcdn.com/thumbnails/remote/212x212/image/x.jpg', 800),
    'https://thumbnail1.coupangcdn.com/thumbnails/remote/800x800/image/x.jpg');
});
t('크기 세그먼트가 없는 원본 URL은 건드리지 않는다', () => {
  const u = 'https://image7.coupangcdn.com/image/vendor_inventory/2023/01/01/abc.jpg';
  assert.strictEqual(upscaleUrl(u, 1000), u);
});
t('날짜 경로(2023/01/01)를 크기로 오인하지 않는다', () => {
  const u = 'https://image6.coupangcdn.com/image/retail/2024/05/12/9/img.jpg';
  assert.strictEqual(upscaleUrl(u, 1000), u);
});
t('파일명 속 100x200 은 교체 대상이 아니다', () => {
  const u = 'https://image6.coupangcdn.com/image/product_100x200.jpg';
  assert.strictEqual(upscaleUrl(u, 1000), u);
});
t('coupangcdn 이 아닌 호스트는 건드리지 않는다', () => {
  const u = 'https://example.com/thumbnails/remote/230x230ex/image/x.jpg';
  assert.strictEqual(upscaleUrl(u, 1000), u);
});
t('size 가 0 이면(--no-upscale) 원본을 그대로 돌려준다', () => {
  const u = 'https://thumbnail7.coupangcdn.com/thumbnails/remote/230x230ex/image/x.jpg';
  assert.strictEqual(upscaleUrl(u, 0), u);
});

console.log('normalizeUrl');
t('프로토콜 상대 URL 을 https 로 채운다', () => {
  assert.strictEqual(normalizeUrl('//thumbnail7.coupangcdn.com/a.jpg'), 'https://thumbnail7.coupangcdn.com/a.jpg');
});
t('http 스킴을 https 로 강제 승격하지 않는다', () => {
  assert.strictEqual(normalizeUrl('http://cdn.example.com/a.jpg'), 'http://cdn.example.com/a.jpg');
});
t('data:/blob:/about: 은 제외한다', () => {
  assert.strictEqual(normalizeUrl('data:image/png;base64,AAAA'), null);
  assert.strictEqual(normalizeUrl('blob:https://x/y'), null);
  assert.strictEqual(normalizeUrl('about:blank'), null);
});
t('빈 값과 상대 경로는 null 이다', () => {
  assert.strictEqual(normalizeUrl(''), null);
  assert.strictEqual(normalizeUrl(null), null);
  assert.strictEqual(normalizeUrl('/img/a.jpg'), null);
});

console.log('parseProductIds');
t('productId / itemId / vendorItemId 를 뽑는다', () => {
  const ids = parseProductIds('https://www.coupang.com/vp/products/1234567890?itemId=99&vendorItemId=88&q=x');
  assert.strictEqual(ids.productId, '1234567890');
  assert.strictEqual(ids.itemId, '99');
  assert.strictEqual(ids.vendorItemId, '88');
});
t('상품 URL 이 아니면 productId 가 없다', () => {
  assert.strictEqual(parseProductIds('https://link.coupang.com/a/ABC').productId, undefined);
});
t('깨진 URL 에도 throw 하지 않는다', () => {
  assert.deepStrictEqual(parseProductIds('not a url'), {});
});

console.log('fileNameFor / extFromType');
t('인덱스를 3자리로 채우고 확장자를 유지한다', () => {
  assert.strictEqual(fileNameFor('https://x.com/path/photo.jpg', 'image/jpeg', 7), '007_photo.jpg');
});
t('확장자가 없으면 content-type 으로 채운다', () => {
  assert.strictEqual(fileNameFor('https://x.com/path/photo', 'image/webp', 1), '001_photo.webp');
});
t('content-type 도 없으면 .jpg 로 떨어진다', () => {
  assert.strictEqual(fileNameFor('https://x.com/path/photo', '', 1), '001_photo.jpg');
});
t('파일명에서 위험한 문자를 제거한다', () => {
  const n = fileNameFor('https://x.com/a/..%2F..%2Fetc%2Fpasswd', 'image/png', 2);
  assert.ok(!n.includes('/'), n);
  assert.ok(n.startsWith('002_'), n);
});
t('extFromType 은 파라미터가 붙은 content-type 도 처리한다', () => {
  assert.strictEqual(extFromType('image/png; charset=binary'), '.png');
  assert.strictEqual(extFromType('video/mp4'), '.mp4');
  assert.strictEqual(extFromType('text/html'), null);
});

console.log(`\n${pass}개 통과${process.exitCode ? ' (실패 있음)' : ''}`);
