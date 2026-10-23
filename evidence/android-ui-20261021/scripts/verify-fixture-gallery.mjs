import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { createServer } from 'file:///D:/项目制知识引导小精灵/frontend/node_modules/vite/dist/node/index.js';
import react from 'file:///D:/项目制知识引导小精灵/frontend/node_modules/@vitejs/plugin-react/dist/index.js';
import { relatedRecommendations, recommendationUrlKey } from 'file:///D:/项目制知识引导小精灵/frontend/src/relatedRecommendations.ts';
import { hasVerifiedReferencePage, isVerifiedVideoPage } from 'file:///D:/项目制知识引导小精灵/frontend/src/verifiedVideoPage.ts';
import { externalUrl } from 'file:///D:/项目制知识引导小精灵/frontend/src/safeUrls.ts';
import { hasProjectScopeMismatch } from 'file:///D:/项目制知识引导小精灵/frontend/src/projectTypes.ts';

const root = 'D:/项目制知识引导小精灵/frontend';
const dir = 'C:/Users/xiaoer/AppData/Local/Temp/android-qa-20261021';
const require = createRequire(`${root}/package.json`);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const fixture = JSON.parse(readFileSync(`${dir}/fixture-example-search.json`, 'utf8'));
const results = [];
for (const topic of ['all', 'K1', 'K2']) {
  const expected = topic === 'all' ? [5, 3, 2, 0] : topic === 'K1' ? [3, 2, 1, 0] : [2, 1, 1, 0];
  for (const [index, platform] of ['all', 'bilibili', 'icourse163', 'xuetangx'].entries()) {
    const cards = new Map();
    for (const point of fixture.points.filter(p => (topic === 'all' || p.project_knowledge_point_id === topic) && !hasProjectScopeMismatch(p))) {
      for (const entry of relatedRecommendations(point.result, platform)) {
        if (!hasVerifiedReferencePage(entry) || !isVerifiedVideoPage(entry.resource)) continue;
        if (platform !== 'all' && entry.resource.platform !== platform) continue;
        if (!externalUrl(entry.href)) continue;
        cards.set(recommendationUrlKey(entry.resource) || entry.href, entry.resource.resource_id);
      }
    }
    assert.equal(cards.size, expected[index]);
    results.push({ topic, platform, cards: cards.size, expected: expected[index] });
  }
}

// Render the actual, unmodified React gallery via Vite's SSR transformer.
// Middleware mode does not listen on an HTTP port, and no external requests run.
globalThis.document = { documentElement: { dataset: {} } };
const vite = await createServer({ root, configFile: false, appType: 'custom', plugins: [react()],
  server: { middlewareMode: true, watch: null }, logLevel: 'error' });
try {
  const { ProjectVideoGallery } = await vite.ssrLoadModule('/src/components/ProjectVideoGallery.tsx');
  for (const [topic, expected] of [['all', 5], ['K1', 3], ['K2', 2]]) {
    const html = renderToStaticMarkup(React.createElement(ProjectVideoGallery, {
      version: fixture.version, points: fixture.points, topic, pipeline: fixture.pipeline,
      capabilities: { teaching_match_enabled: false, limits: { max_results_per_point: 5 }, platforms: [] },
    }));
    const cards = (html.match(/class="video-cover-card/g) || []).length;
    assert.equal(cards, expected, `Actual ProjectVideoGallery SSR ${topic}`);
    assert(!html.includes('video-gallery-empty'));
    writeFileSync(`${dir}/fixture-gallery-${topic}.html`, html);
    results.push({ actual_component_ssr: true, topic, cards, expected });
  }
} finally {
  await vite.close();
}
writeFileSync(`${dir}/fixture-gallery-validation.json`, JSON.stringify({ synthetic: true, external_requests: 0, checks: results }, null, 2));
console.log(JSON.stringify({ passed: results.length, checks: results }, null, 2));
