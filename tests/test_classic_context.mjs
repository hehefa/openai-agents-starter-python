import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { guideCollection, guideParentOrigin, guideStorageKey, readableSourceUrl } from '../src/guideContext.ts';

assert.equal(guideCollection('?site=p4&collection=classic&lang=en'), 'classic');
for (const search of ['', '?site=p4', '?site=hefa&collection=classic', '?site=p4&collection=other']) {
  assert.equal(guideCollection(search), undefined);
  assert.equal(guideStorageKey(guideCollection(search)), 'works-guide-session-v1');
}
assert.notEqual(guideStorageKey(guideCollection('?site=p4&collection=classic')), guideStorageKey());

for (const host of ['hefa.p4theater.cn', 'p4theater.cn', 'p.p4theater.cn']) {
  assert.equal(readableSourceUrl(`https://${host}/knowledge/test/#source`), `https://${host}/knowledge/test/#source`);
  assert.equal(guideParentOrigin(`https://${host}/works`, 'guide.p4theater.cn'), `https://${host}`);
}
for (const value of ['https://p.p4theater.cn.evil.com/', 'https://p.p4theater.cn:8443/', 'https://user:secret@p.p4theater.cn/', 'http://p.p4theater.cn/', 'javascript:alert(1)']) {
  assert.equal(readableSourceUrl(value), undefined);
}
for (const referrer of ['https://p.p4theater.cn.evil.com/', 'http://p.p4theater.cn/', 'http://localhost:8842/']) {
  assert.equal(guideParentOrigin(referrer, 'guide.p4theater.cn'), undefined);
}
assert.equal(guideParentOrigin('http://localhost:8842/', 'localhost'), 'http://localhost:8842');
const config = JSON.parse(await readFile(new URL('../edgeone.json', import.meta.url)));
const policy = config.headers.flatMap(row => row.headers).find(row => row.key === 'Content-Security-Policy').value;
assert.equal(policy, "frame-ancestors 'self' https://hefa.p4theater.cn https://p4theater.cn https://p.p4theater.cn");
console.log('Classic guide context, exact source/parent origins, and frame policy checks passed.');
