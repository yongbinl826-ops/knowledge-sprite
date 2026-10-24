import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { helpfulVideoCovers, helpfulVideoRecommendations, hasHelpfulVideoPolicy } from '../src/helpfulVideoRecommendations.ts';

const stamp = '2026-10-23T09:00:10.000Z';
function entry(id, changes = {}, origin = 'search') {
  return { resource: { resource_id: id, title: `Pygame 教程 ${id}`, url: `https://www.bilibili.com/video/${id}`,
    canonical_url: `https://www.bilibili.com/video/${id}`, platform: 'bilibili', thumbnail_url: null,
    language: 'zh', requires_payment: null, fetch_status: 'not_fetched', video_evidence_status: 'search_discovered', playback_verified: false,
    ...changes }, origin, added_at: stamp, elapsed_seconds: 10, score: 0.8 };
}
function group(entries) {
  return { knowledge_point_id: 'search-k1', text: '键盘控制', items: [], total_matches: 0,
    recommendation_policy: 'helpful-video-v1', section_limit: 5, video_recommendations: entries };
}

test('helpful policy admits unvisited search, AI and technology videos without catalog or playback proof', () => {
  const result = group(['search', 'ai', 'technology'].map(origin => entry(origin, {}, origin)));
  const before = structuredClone(result);
  assert.equal(helpfulVideoRecommendations(result).length, 3);
  assert.equal(helpfulVideoCovers([{ pointId: 'k1', result }]).size, 3);
  assert.deepEqual(result, before);
  for (const video of helpfulVideoCovers([{ pointId: 'k1', result }]).values()) {
    assert.equal(video.label, undefined);
    assert.equal(video.notice, undefined);
    assert.deepEqual(video.knowledgePointIds, ['k1']);
  }
});

test('all related videos remain visible above the historical five-item section limit', () => {
  const result = group(Array.from({ length: 19 }, (_, index) => entry(`video-${index}`)));
  assert.equal(helpfulVideoCovers([{ pointId: 'k1', result }]).size, 19);
});

test('deduped all view retains each point association and either point can reuse the same video', () => {
  const original = entry('shared'), duplicate = entry('duplicate', { url: original.resource.url + '/?utm_source=sharing' });
  const groups = [{ pointId: 'k1', result: group([original, duplicate]) },
    { pointId: 'k2', result: group([{ ...original, added_at: '2026-10-23T09:00:12Z' }]) }];
  const all = [...helpfulVideoCovers(groups).values()];
  assert.equal(all.length, 1);
  assert.deepEqual(all[0].knowledgePointIds, ['k1', 'k2']);
  assert.equal(all[0].recommendedAt, stamp);
  for (const single of groups) assert.equal(helpfulVideoCovers([single]).size, 1);
});

test('late cover on a duplicate point fills one ranked card without changing titles, chapters or filters', () => {
  const first = { ...entry('BV1234567890'), score: 0.9, matched_chapters: [chapter('c1', '键盘事件', 1)] };
  const later = { ...entry('alias', { title: '较低排序的课程别名', url: first.resource.url + '/?p=2' }),
    score: 0.7, added_at: '2026-10-23T09:00:12Z', matched_chapters: [chapter('c2', '碰撞检测', 2)] };
  const groups = [{ pointId: 'k1', result: group([first]) }, { pointId: 'k2', result: group([later]) }];
  const before = [...helpfulVideoCovers(groups, 'bilibili').values()][0];
  assert.equal(before.image, undefined);
  const updated = structuredClone(groups);
  updated[1].result.video_recommendations[0].resource.thumbnail_url = 'http://i2.hdslb.com/bfs/archive/native.jpg';
  const preserved = structuredClone(updated);
  const covers = [...helpfulVideoCovers(updated, 'bilibili').values()];
  assert.equal(covers.length, 1);
  assert.equal(covers[0].image, 'https://i2.hdslb.com/bfs/archive/native.jpg');
  assert.deepEqual({ ...covers[0], image: undefined }, before);
  assert.equal(helpfulVideoCovers(updated, 'icourse163').size, 0);
  assert.deepEqual([...helpfulVideoCovers([updated[0]]).values()][0].chapters.map(row => row.chapter_id), ['c1']);
  assert.deepEqual([...helpfulVideoCovers([updated[1]]).values()][0].chapters.map(row => row.chapter_id), ['c2']);
  assert.deepEqual(updated, preserved);
});

test('an unsafe or empty leading thumbnail cannot hide a later safe same-course image', () => {
  for (const thumbnail_url of [null, '', 'javascript:alert(1)', 'http://unknown.example.org/cover.jpg']) {
    const leading = entry('BV1234567890', { thumbnail_url });
    const observed = entry('alias', { url: leading.resource.url, thumbnail_url: 'https://images.example.org/native.jpg' });
    const covers = [...helpfulVideoCovers([{ pointId: 'k1', result: group([leading]) },
      { pointId: 'k2', result: group([observed]) }]).values()];
    assert.equal(covers.length, 1);
    assert.equal(covers[0].image, observed.resource.thumbnail_url);
    assert.equal(covers[0].title, leading.resource.title);
  }
});

test('explicit paid and unsafe links are excluded; unknown price and unavailable page are allowed', () => {
  const unsafe = ['javascript:alert(1)', 'http://127.0.0.1/private', 'https://user:password@example.com/video', 'https://x.local/video'];
  const result = group([entry('unknown'), entry('free', { requires_payment: false }), entry('paid', { requires_payment: true }),
    ...unsafe.map((url, index) => entry(`unsafe-${index}`, { url }))]);
  assert.deepEqual(helpfulVideoRecommendations(result).map(row => row.resource.resource_id), ['unknown', 'free']);
});

test('source filtering and Chinese-first ordering retain English with one card per video', () => {
  const result = group([entry('en', { title: 'Pygame tutorial', language: 'en' }),
    entry('zh', { title: '游戏实战', platform: 'icourse163' }),
    entry('part-1', { url: 'https://www.bilibili.com/video/BV1234567890/?p=1' }),
    entry('part-2', { url: 'https://www.bilibili.com/video/BV1234567890/?p=2' })]);
  const videos = [...helpfulVideoCovers([{ pointId: 'k1', result }]).values()];
  assert.equal(videos.length, 3);
  assert.equal(videos.at(-1).id, 'en');
  assert.equal(helpfulVideoCovers([{ pointId: 'k1', result }], 'icourse163').size, 1);
});

function chapter(id, title, index, url = `https://www.bilibili.com/video/BV1234567890?p=${index}`) {
  return { chapter_id: id, title, index, url, source_url: 'https://www.bilibili.com/video/BV1234567890',
    source_kind: 'html.bilibili.initial_state', observed_at: stamp };
}

test('chapters arrive after cards and stay scoped to the selected knowledge points', () => {
  const course = entry('BV1234567890');
  const first = chapter('c1', '键盘事件', 1), second = chapter('c2', '碰撞检测', 2);
  const empty = helpfulVideoCovers([{ pointId: 'k1', result: group([course]) }]);
  assert.deepEqual([...empty.values()][0].chapters, []);
  const groups = [
    { pointId: 'k1', result: group([{ ...course, matched_chapters: [first] }]) },
    { pointId: 'k2', result: group([{ ...course, matched_chapters: [first, second] }]) },
  ];
  const before = structuredClone(groups);
  const all = [...helpfulVideoCovers(groups).values()];
  assert.equal(all.length, 1);
  assert.equal(all[0].recommendedAt, stamp);
  assert.equal(all[0].title, course.resource.title);
  assert.deepEqual(all[0].chapters.map(value => value.title), ['键盘事件', '碰撞检测']);
  assert.deepEqual([...helpfulVideoCovers([groups[0]]).values()][0].chapters.map(value => value.title), ['键盘事件']);
  assert.equal([...helpfulVideoCovers([groups[1]]).values()][0].chapters.length, 2);
  assert.deepEqual(groups, before);
});

test('a catalog entry repeating the video title does not duplicate its heading', () => {
  const course = { ...entry('BV1234567890', { title: 'Python 中的变量与赋值' }), matched_chapters: [
    chapter('same', 'Python中的变量与赋值', 1), chapter('specific', '变量命名规则', 2),
  ] };
  const video = [...helpfulVideoCovers([{ pointId: 'k1', result: group([course]) }]).values()][0];
  assert.equal(video.title, course.resource.title);
  assert.deepEqual(video.chapters.map(value => value.title), ['变量命名规则']);
  assert.equal(course.matched_chapters.length, 2);
});

test('text-only chapters remain readable, unsafe chapter links never become anchors', () => {
  const course = { ...entry('BV1234567890'), matched_chapters: [chapter('c1', '循环结构', 1, null),
    chapter('c2', '条件表达式', 2, 'javascript:alert(1)')] };
  const video = [...helpfulVideoCovers([{ pointId: 'k1', result: group([course]) }]).values()][0];
  assert.equal(video.chapters.length, 2);
  assert.equal(video.chapters[0].href, undefined);
  assert.equal(video.chapters[1].href, undefined);
});

test('legacy, absent and unknown policies cannot enable the helpful path', () => {
  for (const policy of ['related-reference-v1', undefined, 'future-policy']) {
    const result = { ...group([entry('v')]), recommendation_policy: policy };
    assert.equal(hasHelpfulVideoPolicy(result), false);
    assert.equal(helpfulVideoCovers([{ pointId: 'k1', result }]).size, 0);
  }
});

test('equivalent Bilibili hosts and MOOC course routes dedupe without merging terms', () => {
  const rows = [entry('b1', { url: 'https://bilibili.com/video/BV1234567890?p=1' }),
    entry('b2', { url: 'https://www.bilibili.com/video/BV1234567890/?p=2' }),
    ...['https://icourse163.org/course/BIT-1001873001', 'https://www.icourse163.org/course/0809BIT021E-1001873001',
      'https://www.icourse163.org/course/detail.htm?cid=1001873001',
      'https://www.icourse163.org/course/BIT-1001873001?tid=1001'].map((url, i) => entry(`m${i}`, { url, platform: 'icourse163' }))];
  const covers = [...helpfulVideoCovers([{ pointId: 'k1', result: group(rows) }]).values()];
  assert.equal(covers.length, 3);
  assert.equal(covers[0].href, rows[0].resource.url);
});

test('actual gallery markup contains timing associations and no fallback or verification labels', async () => {
  const { createServer } = await import('vite');
  const { createElement } = await import('react');
  const { renderToStaticMarkup } = await import('react-dom/server');
  const vite = await createServer({ configFile: false, root: fileURLToPath(new URL('..', import.meta.url)),
    server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' });
  const previousDocument = globalThis.document;
  globalThis.document = { documentElement: { dataset: {} } };
  try {
    const { ProjectVideoGallery } = await vite.ssrLoadModule('/src/components/ProjectVideoGallery.tsx');
    const recommendations = Array.from({ length: 7 }, (_, index) => entry(`v${index}`, {}, ['search', 'ai', 'technology'][index % 3]));
    const points = ['k1', 'k2'].map(id => ({ project_knowledge_point_id: id, status: 'completed', result: group(recommendations.map((row, index) => index === 0 ? { ...row, matched_chapters: [chapter('shared', '共享章节', 1), chapter(id, id === 'k1' ? '键盘事件' : '碰撞检测', 2)] } : row)) }));
    const version = { status: 'completed', analysis: { knowledge_points: ['k1', 'k2'].map(id => ({ id, selection: 'learn' })) } };
    const markup = renderToStaticMarkup(createElement(ProjectVideoGallery, { version, points, capabilities: null, topic: 'all' }));
    assert.equal((markup.match(/data-resource-id=/g) || []).length, 7);
    assert.equal((markup.match(/data-knowledge-point-ids="k1 k2"/g) || []).length, 7);
    assert.equal((markup.match(/data-recommended-at="2026-10-23T09:00:10.000Z"/g) || []).length, 7);
    assert.doesNotMatch(markup, /video-reference-label|基础参考|相关参考|精确讲授|页面未核验|AI/);
    assert.match(markup, /rel="noopener noreferrer"/);
    assert.equal((markup.match(/data-chapter-id="shared"/g) || []).length, 1);
    assert.match(markup, /｜<a[^>]+>键盘事件<\/a>/);
    assert.match(markup, /｜<a[^>]+>碰撞检测<\/a>/);
    const single = renderToStaticMarkup(createElement(ProjectVideoGallery, { version, points, capabilities: null, topic: 'k2' }));
    assert.equal((single.match(/data-resource-id=/g) || []).length, 7);
    assert.equal((single.match(/data-knowledge-point-ids="k2"/g) || []).length, 7);
    assert.doesNotMatch(single, /键盘事件/);
    assert.match(single, /碰撞检测/);
  } finally {
    globalThis.document = previousDocument;
    await vite.close();
  }
});
