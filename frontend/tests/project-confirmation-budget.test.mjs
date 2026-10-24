import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

test('project confirmation accepts every selected point within the advertised helpful-video budget', async () => {
  const { createServer } = await import('vite');
  const { createElement } = await import('react');
  const { renderToStaticMarkup } = await import('react-dom/server');
  const vite = await createServer({ configFile: false, root: fileURLToPath(new URL('..', import.meta.url)),
    server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' });
  const previousDocument = globalThis.document;
  globalThis.document = { documentElement: { dataset: {} } };
  try {
    const { ProjectConfirmation } = await vite.ssrLoadModule('/src/components/ProjectLearning.tsx');
    function render(count, policy, batchSize = 30, analysisLimit = 30) {
      const version = { version: 1, analysis: { analysis_format: 'concept_list_v1', knowledge_points:
        Array.from({ length: count }, (_, i) => ({ id: `k${i}`, name: `概念${i}`, description: '', selection: 'learn' })) } };
      return renderToStaticMarkup(createElement(ProjectConfirmation, {
        projectId: 'budget-test', version, current: true, busy: false, inputDirty: false, onSelectedChange() {},
        capabilities: { limits: { max_knowledge_points: 5 }, project_analysis: { max_knowledge_points: analysisLimit },
          project_search: { recommendation_policy: policy, batch_size: batchSize, max_batches: 1 } },
      }));
    }
    for (const count of [6, 10, 15, 24, 25, 30]) {
      const markup = render(count, 'helpful-video-v1');
      assert.doesNotMatch(markup, /选择数量超过/);
      assert.match(markup, /<button class="primary-button">查找视频<\/button>/);
    }
    for (const markup of [render(31, 'helpful-video-v1'), render(11, 'helpful-video-v1', 10),
      render(25, 'helpful-video-v1', 30, 24), render(31, 'helpful-video-v1', null, null),
      render(6, 'related-reference-v1'), render(6, undefined), render(6, 'unknown-policy')]) {
      assert.match(markup, /选择数量超过/);
      assert.match(markup, /<button class="primary-button" disabled="">查找视频<\/button>/);
    }
    assert.doesNotMatch(render(5, 'related-reference-v1'), /选择数量超过/);
    assert.doesNotMatch(render(30, 'helpful-video-v1', null, null), /选择数量超过/);
    assert.match(render(30, 'helpful-video-v1', null, null), /<button class="primary-button">查找视频<\/button>/);
  } finally {
    globalThis.document = previousDocument;
    await vite.close();
  }
});
