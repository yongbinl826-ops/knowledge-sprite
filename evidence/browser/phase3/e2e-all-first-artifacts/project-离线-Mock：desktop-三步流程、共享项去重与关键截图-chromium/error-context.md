# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: project.spec.ts >> 离线 Mock：desktop 三步流程、共享项去重与关键截图
- Location: tests\project.spec.ts:470:3

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('heading', { name: '项目课程结果 · v1' })
Expected: visible
Timeout: 7000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('heading', { name: '项目课程结果 · v1' }) with timeout 7000ms
  - waiting for getByRole('heading', { name: '项目课程结果 · v1' })

```

```yaml
- link "跳转到主要内容":
  - /url: "#stage-title"
- banner:
  - text: 项目制知识引导小精灵
  - navigation "项目学习流程":
    - button "01 项目描述"
    - button "02 选择知识点"
    - button "03 推荐视频"
  - button "我的项目"
- main:
  - complementary:
    - paragraph: 03 / CURATED LEARNING
    - heading "让知识， 走进你的项目。" [level=1]
    - paragraph: Excel 成绩分析工具 从相关的视频与章节开始。
    - button "← 调整知识点"
    - navigation "已选知识点":
      - paragraph: 已选知识点
      - button "全部" [pressed]
      - button "pandas 读取 Excel"
      - button "pandas 计算均值"
      - button "Matplotlib 柱状图绘制"
  - status: 已确认，按勾选的知识点分批查找推荐视频。
  - paragraph: Excel 成绩分析工具 · v2 · 检索完成
  - region "项目课程结果 · v2":
    - heading "项目课程结果 · v2" [level=2]: 推荐视频
    - paragraph: 从一个学习单元开始，将学到的内容用在项目里。
    - text: 检索完成
    - group: 查看检索进度与预算
    - heading "读取与统计" [level=3]
    - heading "pandas 读取 Excel" [level=4]
    - text: 检索完成 · 1 条推荐
    - complementary "pandas 读取 Excel的学习路线":
      - heading "从学会技能，到完成项目" [level=5]
      - status: 教学范围待核对
      - paragraph:
        - strong: 必要先修
        - text: 无额外先修，可从这里开始
      - region "先学这些技能":
        - heading "先学这些技能" [level=6]
        - paragraph: 学习可迁移的方法；教程不必使用同款项目。
        - paragraph: 此版本尚未区分可迁移技能。原项目要求保留在下方明细中，可返回知识点页补充。
      - region "带回项目练习":
        - heading "带回项目练习" [level=6]
        - text: 待自己实践
        - paragraph: 把技能用于自己的项目。课程匹配不会自动完成这些要求。
        - strong: 项目子任务
        - paragraph: 离线 Mock 知识点说明
        - strong: 试做后这样检查
        - paragraph: 能够在本地工具中应用
      - strong: 下一步
      - paragraph: 已有相关材料，但技能教学范围仍待核对；可先查看简介、目录，再决定是否需要调整或重新检索。
      - paragraph: 课程依据只说明当前可见材料的教学范围，不代表已经学会，也不代表项目练习完成。
      - group: 原项目要求来源核对 旧口径明细
    - region "待核实线索":
      - paragraph: 待核实 · 供参考
      - article:
        - link "前往原平台学习：离线 Mock 课程 kp1":
          - /url: https://example.org/mock-course
          - text: 来源未提供封面
        - text: 其他网站 待核实
        - heading "离线 Mock 课程 kp1" [level=4]:
          - link "离线 Mock 课程 kp1":
            - /url: https://example.org/mock-course
        - paragraph: 离线测试匹配
        - paragraph: 内容相关性待确认，可前往原平台查看。
        - link "去原平台学习 ：离线 Mock 课程 kp1（在新窗口打开）":
          - /url: https://example.org/mock-course
    - heading "pandas 计算均值" [level=4]
    - text: 检索完成 · 1 条推荐
    - complementary "pandas 计算均值的学习路线":
      - heading "从学会技能，到完成项目" [level=5]
      - status: 教学范围待核对
      - paragraph:
        - strong: 必要先修
        - text: pandas 读取 Excel
      - region "先学这些技能":
        - heading "先学这些技能" [level=6]
        - paragraph: 学习可迁移的方法；教程不必使用同款项目。
        - paragraph: 此版本尚未区分可迁移技能。原项目要求保留在下方明细中，可返回知识点页补充。
      - region "带回项目练习":
        - heading "带回项目练习" [level=6]
        - text: 待自己实践
        - paragraph: 把技能用于自己的项目。课程匹配不会自动完成这些要求。
        - strong: 项目子任务
        - paragraph: 离线 Mock 知识点说明
        - strong: 试做后这样检查
        - paragraph: 能够在本地工具中应用
      - strong: 下一步
      - paragraph: 已有相关材料，但技能教学范围仍待核对；可先查看简介、目录，再决定是否需要调整或重新检索。
      - paragraph: 课程依据只说明当前可见材料的教学范围，不代表已经学会，也不代表项目练习完成。
      - group: 原项目要求来源核对 旧口径明细
    - region "待核实线索":
      - paragraph: 待核实 · 供参考
      - article:
        - link "前往原平台学习：离线 Mock 课程 kp2":
          - /url: https://example.org/mock-course
          - text: 来源未提供封面
        - text: 其他网站 待核实
        - heading "离线 Mock 课程 kp2" [level=4]:
          - link "离线 Mock 课程 kp2":
            - /url: https://example.org/mock-course
        - paragraph: 离线测试匹配
        - paragraph: 内容相关性待确认，可前往原平台查看。
        - link "去原平台学习 ：离线 Mock 课程 kp2（在新窗口打开）":
          - /url: https://example.org/mock-course
    - heading "图表与导出" [level=3]
    - heading "Matplotlib 柱状图绘制" [level=4]
    - text: 检索完成 · 1 条推荐
    - complementary "Matplotlib 柱状图绘制的学习路线":
      - heading "从学会技能，到完成项目" [level=5]
      - status: 教学范围待核对
      - paragraph:
        - strong: 必要先修
        - text: pandas 读取 Excel
      - region "先学这些技能":
        - heading "先学这些技能" [level=6]
        - paragraph: 学习可迁移的方法；教程不必使用同款项目。
        - paragraph: 此版本尚未区分可迁移技能。原项目要求保留在下方明细中，可返回知识点页补充。
      - region "带回项目练习":
        - heading "带回项目练习" [level=6]
        - text: 待自己实践
        - paragraph: 把技能用于自己的项目。课程匹配不会自动完成这些要求。
        - strong: 项目子任务
        - paragraph: 离线 Mock 知识点说明
        - strong: 试做后这样检查
        - paragraph: 能够在本地工具中应用
      - strong: 下一步
      - paragraph: 已有相关材料，但技能教学范围仍待核对；可先查看简介、目录，再决定是否需要调整或重新检索。
      - paragraph: 课程依据只说明当前可见材料的教学范围，不代表已经学会，也不代表项目练习完成。
      - group: 原项目要求来源核对 旧口径明细
    - region "待核实线索":
      - paragraph: 待核实 · 供参考
      - article:
        - link "前往原平台学习：离线 Mock 课程 kp3":
          - /url: https://example.org/mock-course
          - text: 来源未提供封面
        - text: 其他网站 待核实
        - heading "离线 Mock 课程 kp3" [level=4]:
          - link "离线 Mock 课程 kp3":
            - /url: https://example.org/mock-course
        - paragraph: 离线测试匹配
        - paragraph: 内容相关性待确认，可前往原平台查看。
        - link "去原平台学习 ：离线 Mock 课程 kp3（在新窗口打开）":
          - /url: https://example.org/mock-course
    - paragraph: 章节信息来自实际检索证据。课程可能需要登录、选课或付费，以原平台为准。
    - button "重新检索这些知识点"
    - paragraph: 重新检索会创建新版本，上次结果保留；受相同预算与限流约束。
- contentinfo: 让学习，发生在项目里。 需求在本机服务保存 · 分析使用已配置的模型
```

# Test source

```ts
  399 |   await expect(page.getByRole('alert')).toHaveCount(0);
  400 |   const readsBeforeConfirm = reads;
  401 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
  402 |   await expect.poll(() => reads).toBeGreaterThan(readsBeforeConfirm);
  403 |   await expect(page.getByRole('alert')).toContainText('Mock：暂时超出项目预算，修改已保存。');
  404 |   expect(mock.calls.confirm).toHaveLength(1); expect(mock.calls.search).toHaveLength(0);
  405 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  406 | });
  407 | 
  408 | const screenshotRoot = resolve(process.cwd(), process.env.QA_EVIDENCE_ROOT || '../evidence/browser', 'screenshots');
  409 | const responsiveViewports = [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'tablet', width: 768, height: 1024 }, { name: 'mobile', width: 390, height: 844 }];
  410 | async function capture(page: Page, name: string) {
  411 |   await mkdir(screenshotRoot, { recursive: true });
  412 |   await page.screenshot({ path: resolve(screenshotRoot, name), fullPage: false, animations: 'disabled' });
  413 | }
  414 | async function assertNoOverflow(page: Page) {
  415 |   const measurement = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth,
  416 |     overflow: [...document.querySelectorAll('body *')].filter(element => {
  417 |       const bounds = element.getBoundingClientRect();
  418 |       return bounds.width > 0 && (bounds.left < -1 || bounds.right > innerWidth + 1) && getComputedStyle(element).position !== 'absolute';
  419 |     }).map(element => ({ tag: element.tagName, class: element.className })).slice(0, 8) }));
  420 |   expect(measurement.scroll, JSON.stringify(measurement)).toBeLessThanOrEqual(measurement.width);
  421 | }
  422 | async function captureResponsiveState(page: Page, state: string) {
  423 |   for (const viewport of responsiveViewports) {
  424 |     await page.setViewportSize({ width: viewport.width, height: viewport.height });
  425 |     await page.evaluate(() => window.scrollTo(0, 0));
  426 |     await assertNoOverflow(page);
  427 |     await capture(page, `mock-${viewport.name}-${state}.png`);
  428 |   }
  429 | }
  430 | async function fillBrief(page: Page) {
  431 |   await page.getByLabel('项目名称', { exact: true }).fill('Excel 成绩分析工具');
  432 |   await page.getByLabel('功能需求', { exact: true }).fill('读取本地 Excel 成绩表，统计均值，绘制柱状图并导出图表与统计表。');
  433 | }
  434 | async function assertKeyTextContrast(page: Page, viewport: string, state = 'entry') {
  435 |   const observations = await page.evaluate(() => {
  436 |     const channels = (value: string) => value.match(/[\d.]+/g)!.map(Number);
  437 |     const background = (element: Element): number[] => {
  438 |       const color = channels(getComputedStyle(element).backgroundColor);
  439 |       return color.length < 4 || color[3] > 0 ? color : element.parentElement ? background(element.parentElement) : [255, 255, 255];
  440 |     };
  441 |     const luminance = (rgb: number[]) => rgb.slice(0, 3).map(channel => {
  442 |       const value = channel / 255; return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
  443 |     }).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
  444 |     return ['h1', '.stage-description', '.project-description .field > label', '.default-assumption', '.primary-button', '.stage-navigation button:not(:disabled)'].flatMap(selector => [...document.querySelectorAll(selector)].filter(element => element.checkVisibility()).map(element => {
  445 |       const style = getComputedStyle(element);
  446 |       const foreground = channels(style.color); const backdrop = background(element);
  447 |       const first = luminance(foreground); const second = luminance(backdrop);
  448 |       const ratio = (Math.max(first, second) + .05) / (Math.min(first, second) + .05);
  449 |       const size = parseFloat(style.fontSize); const bold = parseInt(style.fontWeight) >= 700;
  450 |       return { selector, text: element.textContent?.trim(), foreground, background: backdrop, ratio, minimum: size >= 24 || (bold && size >= 18.66) ? 3 : 4.5 };
  451 |     }));
  452 |   });
  453 |   await mkdir(screenshotRoot, { recursive: true });
  454 |   await writeFile(resolve(screenshotRoot, `../contrast-${viewport}${state === 'entry' ? '' : `-${state}`}.json`), JSON.stringify({ kind: 'sampled key text contrast, not a full accessibility audit', viewport, state, observations }, null, 2));
  455 |   expect(observations.every(row => row.ratio >= row.minimum), JSON.stringify(observations)).toBe(true);
  456 | }
  457 | async function assertStep(page: Page, step: number) {
  458 |   await expect(page.locator('.stage-navigation [aria-current="step"]')).toHaveText(new RegExp(`0${step}`));
  459 |   await expect(page.locator('.stage-main')).toHaveClass(new RegExp(`stage-${step}`));
  460 |   await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  461 |   await expect(page.locator('h1')).toBeVisible();
  462 |   await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  463 |   const headingLines = await page.locator('h1').evaluate(heading => [...heading.childNodes]
  464 |     .filter(node => node.nodeType === Node.TEXT_NODE && node.textContent?.trim())
  465 |     .flatMap(node => { const range = document.createRange(); range.selectNodeContents(node); return [...range.getClientRects()]; }).length);
  466 |   expect(headingLines).toBe(2);
  467 | }
  468 | 
  469 | for (const viewport of responsiveViewports) {
  470 |   test(`离线 Mock：${viewport.name} 三步流程、共享项去重与关键截图`, async ({ page }) => {
  471 |     const mock = await mockProject(page);
  472 |     await page.setViewportSize({ width: viewport.width, height: viewport.height });
  473 |     await enterProject(page);
  474 |     await expect(page).toHaveTitle('项目制知识引导小精灵 · 课程与视频发现');
  475 |     await assertStep(page, 1);
  476 |     await expect(page.getByRole('navigation', { name: '项目学习流程' }).getByRole('button', { name: /选择知识点/ })).toBeDisabled();
  477 |     await expect(page.getByRole('navigation', { name: '项目学习流程' }).getByRole('button', { name: /推荐视频/ })).toBeDisabled();
  478 |     await expect(page.locator('.project-confirmation,.project-results')).toHaveCount(0);
  479 |     await fillBrief(page);
  480 |     await expect(page.getByText('需求保存在本机，并会发送至已配置的模型服务；所选知识点用于课程检索。请勿输入敏感信息。', { exact: true })).toBeVisible();
  481 |     await assertNoOverflow(page);
  482 |     await assertKeyTextContrast(page, viewport.name);
  483 |     await capture(page, `mock-${viewport.name}-01-input.png`);
  484 |     if (viewport.name === 'mobile') {
  485 |       await page.getByRole('button', { name: '分析项目' }).scrollIntoViewIfNeeded();
  486 |       await capture(page, 'mock-mobile-01-action.png');
  487 |     }
  488 |     await page.getByRole('button', { name: '分析项目' }).click();
  489 |     await expect(page.getByRole('heading', { name: '确认知识点 · v1' })).toBeVisible();
  490 |     await assertStep(page, 2);
  491 |     await assertKeyTextContrast(page, viewport.name, 'selection');
  492 |     await expect(page.locator('#project-name,.project-results')).toHaveCount(0);
  493 |     await expect(page.locator('.project-point')).toHaveCount(3);
  494 |     await expect(page.locator('.project-point[data-point-id="kp1"]')).toHaveCount(1);
  495 |     await expect(page.locator('.analysis-suggestions')).not.toHaveAttribute('open', '');
  496 |     await assertNoOverflow(page);
  497 |     await capture(page, `mock-${viewport.name}-02-selection.png`);
  498 |     await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
> 499 |     await expect(page.getByRole('heading', { name: '项目课程结果 · v1' })).toBeVisible();
      |                                                                      ^ Error: expect(locator).toBeVisible() failed
  500 |     await assertStep(page, 3);
  501 |     await assertKeyTextContrast(page, viewport.name, 'results');
  502 |     await expect(page.locator('.project-confirmation,#project-name')).toHaveCount(0);
  503 |     await expect(page.locator('.project-result-point')).toHaveCount(3);
  504 |     await expect(page.locator('.resource-card')).toHaveCount(3);
  505 |     await assertNoOverflow(page);
  506 |     await capture(page, `mock-${viewport.name}-03-results.png`);
  507 |     await page.getByRole('button', { name: 'pandas 计算均值', exact: true }).click();
  508 |     await expect(page.locator('.project-result-point')).toHaveCount(1);
  509 |     await expect(page.locator('.resource-card')).toHaveCount(1);
  510 |     await page.getByRole('button', { name: '← 调整知识点', exact: true }).click();
  511 |     await assertStep(page, 2);
  512 |     await expect(page.locator('.project-results')).toHaveCount(0);
  513 |     expect(mock.calls.runtime).toEqual([]); expect(mock.calls.console).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  514 |   });
  515 | }
  516 | 
  517 | test('离线 Mock：键盘可跳过页头、填写需求、提交并将焦点移至新步骤标题', async ({ page }) => {
  518 |   const mock = await mockProject(page);
  519 |   await enterProject(page);
  520 |   await page.keyboard.press('Tab');
  521 |   await expect(page.getByRole('link', { name: '跳转到主要内容' })).toBeFocused();
  522 |   await capture(page, 'mock-desktop-keyboard-skip-link.png');
  523 |   await page.keyboard.press('Enter');
  524 |   await expect(page.locator('#stage-title')).toBeFocused();
  525 |   await page.keyboard.press('Tab');
  526 |   await expect(page.getByLabel('项目名称', { exact: true })).toBeFocused();
  527 |   await page.keyboard.type('Keyboard learning project');
  528 |   await page.keyboard.press('Tab');
  529 |   await expect(page.getByLabel('功能需求', { exact: true })).toBeFocused();
  530 |   await page.keyboard.type('Read a local dataset, summarize values and export a chart.');
  531 |   await page.keyboard.press('Tab');
  532 |   await expect(page.locator('summary').first()).toBeFocused();
  533 |   await page.keyboard.press('Tab');
  534 |   await expect(page.getByRole('button', { name: '分析项目' })).toBeFocused();
  535 |   await page.keyboard.press('Enter');
  536 |   await expect(page.getByRole('heading', { name: '确认知识点 · v1' })).toBeVisible();
  537 |   await expect(page.locator('#stage-title')).toBeFocused();
  538 |   const checkbox = firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true });
  539 |   await checkbox.focus();
  540 |   await page.keyboard.press('Space');
  541 |   await expect(checkbox).not.toBeChecked();
  542 |   await expect(page.getByRole('button', { name: '查找推荐视频', exact: true })).toBeDisabled();
  543 |   await page.getByRole('checkbox', { name: /我了解未勾选/ }).focus();
  544 |   await page.keyboard.press('Space');
  545 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).focus();
  546 |   await page.keyboard.press('Enter');
  547 |   await assertStep(page, 3);
  548 |   await expect(page.locator('#stage-title')).toBeFocused();
  549 |   expect(mock.calls.selected).toEqual(['kp2', 'kp3']);
  550 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  551 | });
  552 | 
  553 | test('离线 Mock：默认按先修学习顺序排列，切换项目任务仍单列并保留选择', async ({ page }) => {
  554 |   const mock = await mockProject(page, { initial: true });
  555 |   const current = mock.versions.get(1)!.analysis!;
  556 |   current.knowledge_points = [current.knowledge_points[2], current.knowledge_points[0], current.knowledge_points[1]];
  557 |   current.knowledge_points.find(point => point.id === 'kp1')!.function_ids = ['f2', 'f1'];
  558 |   await enterProject(page, true);
  559 |   await expect(page.getByRole('button', { name: '按学习顺序', exact: true })).toHaveAttribute('aria-pressed', 'true');
  560 |   expect(await page.locator('.project-point').evaluateAll(points => points.map(point => point.getAttribute('data-point-id')))).toEqual(['kp1', 'kp2', 'kp3']);
  561 |   await firstPoint(page, 'kp3').getByRole('checkbox', { name: '想学习', exact: true }).uncheck();
  562 |   await expect(page.locator('.selection-count')).toContainText('2');
  563 |   await page.getByRole('button', { name: '按项目任务', exact: true }).click();
  564 |   await expect(page.getByRole('button', { name: '按项目任务', exact: true })).toHaveAttribute('aria-pressed', 'true');
  565 |   expect(await page.locator('.project-point').evaluateAll(points => points.map(point => point.getAttribute('data-point-id')))).toEqual(['kp2', 'kp1', 'kp3']);
  566 |   await expect(page.locator('.project-point[data-point-id="kp1"]')).toHaveCount(1);
  567 |   await expect(firstPoint(page, 'kp3').getByRole('checkbox', { name: '想学习', exact: true })).not.toBeChecked();
  568 |   await page.getByRole('button', { name: '按学习顺序', exact: true }).click();
  569 |   expect(await page.locator('.project-point').evaluateAll(points => points.map(point => point.getAttribute('data-point-id')))).toEqual(['kp1', 'kp2', 'kp3']);
  570 |   expect(mock.calls.edit).toHaveLength(0); expect(mock.calls.search).toHaveLength(0);
  571 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  572 | });
  573 | 
  574 | test('离线 Mock：输入草稿与学习单元草稿刷新恢复，不隐式创建项目或新版本', async ({ page }) => {
  575 |   const mock = await mockProject(page);
  576 |   await enterProject(page);
  577 |   await fillBrief(page);
  578 |   await page.locator('.project-description .search-options > summary').click();
  579 |   await page.getByLabel('我的学习起点').selectOption('intermediate');
  580 |   await page.getByLabel('我已经会什么（选填）').fill('已学循环和函数，第一次做图形游戏');
  581 |   await page.reload();
  582 |   await expect(page.getByLabel('项目名称', { exact: true })).toHaveValue('Excel 成绩分析工具');
  583 |   await expect(page.getByLabel('功能需求', { exact: true })).toHaveValue(/读取本地 Excel/);
  584 |   await page.locator('.project-description .search-options > summary').click();
  585 |   await expect(page.getByLabel('我的学习起点')).toHaveValue('intermediate');
  586 |   await expect(page.getByLabel('我已经会什么（选填）')).toHaveValue('已学循环和函数，第一次做图形游戏');
  587 |   expect(mock.calls.create).toHaveLength(0); expect(mock.calls.analyze).toBe(0);
  588 |   await page.getByRole('button', { name: '分析项目' }).click();
  589 |   await firstPoint(page, 'kp2').locator('.point-title-line input').fill('保留的单元名称草稿');
  590 |   await firstPoint(page, 'kp3').getByRole('checkbox', { name: '想学习', exact: true }).uncheck();
  591 |   await page.reload();
  592 |   await expect(firstPoint(page, 'kp2').locator('.point-title-line input')).toHaveValue('保留的单元名称草稿');
  593 |   await expect(firstPoint(page, 'kp3').getByRole('checkbox', { name: '想学习', exact: true })).not.toBeChecked();
  594 |   expect(mock.calls.edit).toHaveLength(0); expect(mock.calls.confirm).toHaveLength(0); expect(mock.calls.search).toHaveLength(0);
  595 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  596 | });
  597 | 
  598 | test('离线 Mock：分析失败保留输入，修改后重试复用已保存项目', async ({ page }) => {
  599 |   const mock = await mockProject(page, { failAnalyzeOnce: true });
```