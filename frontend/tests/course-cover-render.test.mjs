import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

// Render the real component in memory. Image event/loading behavior is verified
// separately in the existing browser; these tests require no network or DOM.
let vite, CourseCover;
before(async () => {
  vite = await createServer({ configFile: false, root: fileURLToPath(new URL('..', import.meta.url)),
    server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' });
  ({ CourseCover } = await vite.ssrLoadModule('/src/components/ResourceCard.tsx'));
});
after(async () => { await vite?.close(); });
const render = props => renderToStaticMarkup(createElement(CourseCover, {
  title: 'Python 循环结构', href: 'https://www.bilibili.com/video/av50100', ...props,
}));

test('a pending cover keeps its image request mounted over the placeholder', () => {
  const markup = render({ image: 'https://i0.hdslb.com/bfs/archive/slow-cover.jpg', coverOnly: true });
  assert.match(markup, /class="cover-placeholder cover-code"/);
  assert.match(markup, /<img[^>]*src="https:\/\/i0\.hdslb\.com\/bfs\/archive\/slow-cover\.jpg"/);
  assert.match(markup, /<img[^>]*style="position:absolute;inset:0;opacity:0"/);
  assert.match(markup, /loading="lazy"/);
  assert.match(markup, /referrerPolicy="no-referrer"/i);
  assert.match(markup, /<a class="course-cover"/);
  assert.doesNotMatch(markup, /<span|封面暂不可用|来源未提供封面/);
});

test('missing and rejected cover URLs keep the existing placeholder without a request', () => {
  for (const image of [null, undefined, 'http://images.example.org/cover.jpg', 'https://127.0.0.1/cover.jpg']) {
    const markup = render({ image, coverOnly: true });
    assert.match(markup, /class="cover-placeholder cover-code"/);
    assert.doesNotMatch(markup, /<img/);
  }
});

test('a new supported image URL renders a fresh pending request without extra card text', () => {
  const missing = render({ image: null, coverOnly: true });
  const arrived = render({ image: 'http://i2.hdslb.com/bfs/archive/arrived.jpg', coverOnly: true });
  assert.doesNotMatch(missing, /<img/);
  assert.match(arrived, /src="https:\/\/i2\.hdslb\.com\/bfs\/archive\/arrived\.jpg"/);
  assert.match(arrived, /class="cover-placeholder cover-code"/);
  assert.match(arrived, /<img[^>]*alt=""/);
  assert.doesNotMatch(arrived, /<span/);
});
