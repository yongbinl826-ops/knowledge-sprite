import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const advisory = { code: 'textbook_operation_bundle', location: ['knowledge_points', 0, 'name'],
  severity: 'low', disposition: 'advisory', evidence: 'title_heuristic' };
function fixture() {
  return { version: 4, status: 'analyzed', analysis: { analysis_format: 'concept_list_v1',
    scope: '', technical_plan: '', assumptions: [], knowledge_points: [
      { id: 'k1', name: '图形绘制与显示刷新', description: '说明帧的绘制顺序和显示更新。', selection: 'learn' },
      { id: 'k2', name: '事件循环', description: '循环处理输入事件。', selection: 'learn' },
    ] }, analysis_advisories: [structuredClone(advisory)] };
}

test('saved naming feedback never renders a notice or changes ordinary confirmation controls', async () => {
  const { createServer } = await import('vite');
  const { createElement } = await import('react');
  const { renderToStaticMarkup } = await import('react-dom/server');
  const vite = await createServer({ configFile: false, root: fileURLToPath(new URL('..', import.meta.url)),
    server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' });
  const previousDocument = globalThis.document;
  globalThis.document = { documentElement: { dataset: {} } };
  try {
    const { ProjectConfirmation } = await vite.ssrLoadModule('/src/components/ProjectLearning.tsx');
    const version = fixture(), original = structuredClone(version);
    const props = { projectId: 'advisory-offline-test', version, current: true, busy: false,
      inputDirty: false, onSelectedChange() {}, onSave() {}, onConfirm() {}, capabilities: null };
    const render = extra => renderToStaticMarkup(createElement(ProjectConfirmation, { ...props, ...extra }));
    const cleanMarkup = render({ version: { ...version, analysis_advisories: undefined } });
    for (const stored of [undefined, null, {}, [], [null], [advisory], [advisory, advisory],
      [{ ...advisory, disposition: 'blocking', severity: 'high' }],
      [{ ...advisory, location: ['knowledge_points', 0, 'description'] }]]) {
      const markup = render({ version: { ...version, analysis_advisories: stored } });
      assert.equal(markup, cleanMarkup);
      assert.doesNotMatch(markup, /名称建议核对|simple-point-name-notice|simple-name-review|aria-describedby/);
      assert.match(markup, /<button class="primary-button">查找视频<\/button>/);
      assert.match(markup, /value="图形绘制与显示刷新"/);
    }

    const draft = structuredClone(version.analysis);
    draft.knowledge_points[0].name = '帧缓冲';
    const edited = render({ deviceMode: true, deviceDraft: draft });
    assert.doesNotMatch(edited, /名称建议核对|simple-point-name-notice|simple-name-review|aria-describedby/);
    assert.match(edited, /value="帧缓冲"/);
    assert.match(edited, /<button class="primary-button">查找视频<\/button>/);

    const historical = render({ current: false });
    assert.doesNotMatch(historical, /名称建议核对|simple-point-name-notice|simple-name-review|aria-describedby/);
    assert.doesNotMatch(historical, /class="primary-button"/);
    assert.match(historical, /value="图形绘制与显示刷新"/);
    assert.deepEqual(version, original);
  } finally {
    globalThis.document = previousDocument;
    await vite.close();
  }
});
