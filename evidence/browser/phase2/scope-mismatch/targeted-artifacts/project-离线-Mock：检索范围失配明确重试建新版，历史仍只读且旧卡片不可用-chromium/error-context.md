# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: project.spec.ts >> 离线 Mock：检索范围失配明确重试建新版，历史仍只读且旧卡片不可用
- Location: tests\project.spec.ts:620:1

# Error details

```
Error: expect(locator).not.toContainText(expected) failed

Locator: locator('.project-result-point')
Expected substring: not "本次没有找到"
Error: strict mode violation: locator('.project-result-point') resolved to 3 elements:
    1) <section class="result-group project-result-point">…</section> aka getByText('pandas 读取 Excel检索范围需重试 · 0 条推荐旧检索技术与本单元不一致，结果已隐藏；请重新检索。需要检索的学习范围：pandas 读取')
    2) <section class="result-group project-result-point">…</section> aka getByText('pandas 计算均值检索范围需重试 · 0 条推荐旧检索技术与本单元不一致，结果已隐藏；请重新检索。需要检索的学习范围：pandas')
    3) <section class="result-group project-result-point">…</section> aka getByText('Matplotlib 柱状图绘制检索范围需重试 · 0 条推荐旧检索技术与本单元不一致，结果已隐藏；请重新检索。需要检索的学习范围：Matplotlib')

Call log:
  - Expect "not toContainText" locator('.project-result-point') with timeout 7000ms
  - waiting for locator('.project-result-point')

```

# Page snapshot

```yaml
- generic [ref=e2]:
  - link "跳转到主要内容" [ref=e3] [cursor=pointer]:
    - /url: "#stage-title"
  - banner [ref=e4]:
    - generic [ref=e5]: 项目制知识引导小精灵
    - navigation "项目学习流程" [ref=e9]:
      - button "01 项目描述" [ref=e10] [cursor=pointer]:
        - generic [aria-hidden] [ref=e11]: ✓
        - generic [ref=e12]: "01"
        - text: 项目描述
      - button "02 选择知识点" [ref=e13] [cursor=pointer]:
        - generic [aria-hidden] [ref=e14]: ✓
        - generic [ref=e15]: "02"
        - text: 选择知识点
      - button "03 推荐视频" [ref=e16] [cursor=pointer]:
        - generic [ref=e18]: "03"
        - text: 推荐视频
    - button "我的项目" [ref=e19] [cursor=pointer]: 我的项目 ↗
  - main [ref=e20]:
    - complementary [ref=e21]:
      - paragraph [ref=e22]: 03 / CURATED LEARNING
      - heading "让知识， 走进你的项目。" [active] [level=1] [ref=e23]: 让知识，走进你的项目。
      - paragraph [ref=e24]: Mock：Excel 成绩分析工具从相关的视频与章节开始。
      - button "← 调整知识点" [ref=e26] [cursor=pointer]
      - navigation "已选知识点" [ref=e27]:
        - paragraph [ref=e28]: 已选知识点
        - button "全部" [pressed] [ref=e29] [cursor=pointer]
        - button "pandas 读取 Excel" [ref=e30] [cursor=pointer]
        - button "pandas 计算均值" [ref=e31] [cursor=pointer]
        - button "Matplotlib 柱状图绘制" [ref=e32] [cursor=pointer]
      - generic [aria-hidden] [ref=e33]: "03"
    - generic [ref=e34]:
      - paragraph [ref=e35]: Mock：Excel 成绩分析工具 · v1 · 部分完成
      - region [ref=e36]:
        - generic [ref=e37]:
          - generic [ref=e38]:
            - heading "项目课程结果 · v1" [level=2] [ref=e39]: 推荐视频
            - paragraph [ref=e40]: 从一个学习单元开始，将学到的内容用在项目里。
          - generic [ref=e41]: 部分完成
        - group [ref=e42]:
          - generic "查看检索进度与预算" [ref=e43] [cursor=pointer]
        - generic [ref=e44]:
          - heading "读取与统计" [level=3] [ref=e45]
          - generic [ref=e46]:
            - generic [ref=e47]:
              - heading "pandas 读取 Excel" [level=4] [ref=e48]
              - generic [ref=e49]: 检索范围需重试 · 0 条推荐
            - status "检索范围需重试" [ref=e50]:
              - paragraph [ref=e51]: 旧检索技术与本单元不一致，结果已隐藏；请重新检索。
              - paragraph [ref=e52]: 需要检索的学习范围：pandas 读取 Excel
              - paragraph [ref=e53]: 请使用下方「重新检索这些知识点」创建新版本，按当前学习范围重新查找。
          - generic [ref=e54]:
            - generic [ref=e55]:
              - heading "pandas 计算均值" [level=4] [ref=e56]
              - generic [ref=e57]: 检索范围需重试 · 0 条推荐
            - status "检索范围需重试" [ref=e58]:
              - paragraph [ref=e59]: 旧检索技术与本单元不一致，结果已隐藏；请重新检索。
              - paragraph [ref=e60]: 需要检索的学习范围：pandas 计算均值
              - paragraph [ref=e61]: 请使用下方「重新检索这些知识点」创建新版本，按当前学习范围重新查找。
        - generic [ref=e62]:
          - heading "图表与导出" [level=3] [ref=e63]
          - generic [ref=e64]:
            - generic [ref=e65]:
              - heading "Matplotlib 柱状图绘制" [level=4] [ref=e66]
              - generic [ref=e67]: 检索范围需重试 · 0 条推荐
            - status "检索范围需重试" [ref=e68]:
              - paragraph [ref=e69]: 旧检索技术与本单元不一致，结果已隐藏；请重新检索。
              - paragraph [ref=e70]: 需要检索的学习范围：Matplotlib 柱状图绘制
              - paragraph [ref=e71]: 请使用下方「重新检索这些知识点」创建新版本，按当前学习范围重新查找。
        - generic [ref=e72]:
          - paragraph [ref=e73]: 章节信息来自实际检索证据。课程可能需要登录、选课或付费，以原平台为准。
          - button "重新检索这些知识点" [ref=e74] [cursor=pointer]: 重新检索这些知识点 ↗
          - paragraph [ref=e75]: 重新检索会创建新版本，上次结果保留；受相同预算与限流约束。
  - contentinfo [ref=e76]:
    - generic [ref=e77]: 让学习，发生在项目里。
    - generic [ref=e78]: 需求在本机服务保存 · 分析使用已配置的模型
```

# Test source

```ts
  528 |   await expect(checkbox).not.toBeChecked();
  529 |   await expect(page.getByRole('button', { name: '查找推荐视频', exact: true })).toBeDisabled();
  530 |   await page.getByRole('checkbox', { name: /我了解未勾选/ }).focus();
  531 |   await page.keyboard.press('Space');
  532 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).focus();
  533 |   await page.keyboard.press('Enter');
  534 |   await assertStep(page, 3);
  535 |   await expect(page.locator('#stage-title')).toBeFocused();
  536 |   expect(mock.calls.selected).toEqual(['kp2', 'kp3']);
  537 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  538 | });
  539 | 
  540 | test('离线 Mock：默认按先修学习顺序排列，切换项目任务仍单列并保留选择', async ({ page }) => {
  541 |   const mock = await mockProject(page, { initial: true });
  542 |   const current = mock.versions.get(1)!.analysis!;
  543 |   current.knowledge_points = [current.knowledge_points[2], current.knowledge_points[0], current.knowledge_points[1]];
  544 |   current.knowledge_points.find(point => point.id === 'kp1')!.function_ids = ['f2', 'f1'];
  545 |   await enterProject(page, true);
  546 |   await expect(page.getByRole('button', { name: '按学习顺序', exact: true })).toHaveAttribute('aria-pressed', 'true');
  547 |   expect(await page.locator('.project-point').evaluateAll(points => points.map(point => point.getAttribute('data-point-id')))).toEqual(['kp1', 'kp2', 'kp3']);
  548 |   await firstPoint(page, 'kp3').getByRole('checkbox', { name: '想学习', exact: true }).uncheck();
  549 |   await expect(page.locator('.selection-count')).toContainText('2');
  550 |   await page.getByRole('button', { name: '按项目任务', exact: true }).click();
  551 |   await expect(page.getByRole('button', { name: '按项目任务', exact: true })).toHaveAttribute('aria-pressed', 'true');
  552 |   expect(await page.locator('.project-point').evaluateAll(points => points.map(point => point.getAttribute('data-point-id')))).toEqual(['kp2', 'kp1', 'kp3']);
  553 |   await expect(page.locator('.project-point[data-point-id="kp1"]')).toHaveCount(1);
  554 |   await expect(firstPoint(page, 'kp3').getByRole('checkbox', { name: '想学习', exact: true })).not.toBeChecked();
  555 |   await page.getByRole('button', { name: '按学习顺序', exact: true }).click();
  556 |   expect(await page.locator('.project-point').evaluateAll(points => points.map(point => point.getAttribute('data-point-id')))).toEqual(['kp1', 'kp2', 'kp3']);
  557 |   expect(mock.calls.edit).toHaveLength(0); expect(mock.calls.search).toHaveLength(0);
  558 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  559 | });
  560 | 
  561 | test('离线 Mock：输入草稿与学习单元草稿刷新恢复，不隐式创建项目或新版本', async ({ page }) => {
  562 |   const mock = await mockProject(page);
  563 |   await enterProject(page);
  564 |   await fillBrief(page);
  565 |   await page.locator('.project-description .search-options > summary').click();
  566 |   await page.getByLabel('我的学习起点').selectOption('intermediate');
  567 |   await page.getByLabel('我已经会什么（选填）').fill('已学循环和函数，第一次做图形游戏');
  568 |   await page.reload();
  569 |   await expect(page.getByLabel('项目名称', { exact: true })).toHaveValue('Excel 成绩分析工具');
  570 |   await expect(page.getByLabel('功能需求', { exact: true })).toHaveValue(/读取本地 Excel/);
  571 |   await page.locator('.project-description .search-options > summary').click();
  572 |   await expect(page.getByLabel('我的学习起点')).toHaveValue('intermediate');
  573 |   await expect(page.getByLabel('我已经会什么（选填）')).toHaveValue('已学循环和函数，第一次做图形游戏');
  574 |   expect(mock.calls.create).toHaveLength(0); expect(mock.calls.analyze).toBe(0);
  575 |   await page.getByRole('button', { name: '分析项目' }).click();
  576 |   await firstPoint(page, 'kp2').locator('.point-title-line input').fill('保留的单元名称草稿');
  577 |   await firstPoint(page, 'kp3').getByRole('checkbox', { name: '想学习', exact: true }).uncheck();
  578 |   await page.reload();
  579 |   await expect(firstPoint(page, 'kp2').locator('.point-title-line input')).toHaveValue('保留的单元名称草稿');
  580 |   await expect(firstPoint(page, 'kp3').getByRole('checkbox', { name: '想学习', exact: true })).not.toBeChecked();
  581 |   expect(mock.calls.edit).toHaveLength(0); expect(mock.calls.confirm).toHaveLength(0); expect(mock.calls.search).toHaveLength(0);
  582 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  583 | });
  584 | 
  585 | test('离线 Mock：分析失败保留输入，修改后重试复用已保存项目', async ({ page }) => {
  586 |   const mock = await mockProject(page, { failAnalyzeOnce: true });
  587 |   await enterProject(page);
  588 |   await fillBrief(page);
  589 |   await page.getByRole('button', { name: '分析项目' }).click();
  590 |   await expect(page.getByRole('alert')).toContainText('模型暂时不可用');
  591 |   await expect(page.getByLabel('项目名称', { exact: true })).toHaveValue('Excel 成绩分析工具');
  592 |   await captureResponsiveState(page, 'analysis-error');
  593 |   await page.getByLabel('功能需求', { exact: true }).fill('方向键控制挡板，记录得分，结束后能够重新开始。');
  594 |   await page.getByRole('button', { name: '分析项目' }).click();
  595 |   await expect(page.getByRole('heading', { name: '确认知识点 · v1' })).toBeVisible();
  596 |   await expect(page.getByRole('alert')).toHaveCount(0);
  597 |   expect(mock.calls.create).toHaveLength(1); expect(mock.calls.analyze).toBe(2);
  598 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  599 | });
  600 | 
  601 | test('离线 Mock：无结果重试创建并确认新版本，旧结果可回看且不重复同版检索', async ({ page }) => {
  602 |   const mock = await mockProject(page, { initial: true, noResults: true });
  603 |   await enterProject(page, true);
  604 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
  605 |   await expect(page.getByText('本次没有找到可展示的相关课程。', { exact: true })).toHaveCount(3);
  606 |   await captureResponsiveState(page, 'no-results');
  607 |   await page.getByRole('button', { name: '重新检索这些知识点' }).click();
  608 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v2' })).toBeVisible();
  609 |   expect(mock.calls.edit).toHaveLength(1);
  610 |   expect(mock.calls.search).toEqual([1, 2]);
  611 |   expect(mock.calls.confirm.map(call => call.version)).toEqual([1, 2]);
  612 |   expect(mock.versions.get(1)!.status).toBe('completed');
  613 |   await page.getByRole('button', { name: '我的项目' }).click();
  614 |   await page.getByLabel('查看版本', { exact: true }).selectOption('1');
  615 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v1' })).toBeVisible();
  616 |   await expect(page.getByText('本次没有找到可展示的相关课程。', { exact: true })).toHaveCount(3);
  617 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  618 | });
  619 | 
  620 | test('离线 Mock：检索范围失配明确重试建新版，历史仍只读且旧卡片不可用',async({page})=>{
  621 |   const mock=await mockProject(page,{initial:true,scopeMismatch:true});
  622 |   const old=mock.versions.get(1)!;old.status='partial';old.confirmation={version:1,confirmed_at:time};
  623 |   old.batches=[{batch_id:'old-scope-batch',status:'completed',project_knowledge_point_ids:['kp1','kp2','kp3'],job_id:'old-scope-job'}];
  624 |   await enterProject(page,true);
  625 |   await expect(page.getByRole('heading',{name:'项目课程结果 · v1'})).toBeVisible();
  626 |   await expect(page.locator('.scope-mismatch-notice')).toHaveCount(3);
  627 |   await expect(page.locator('.resource-card,.unit-coverage,.skeleton-card,.search-progress')).toHaveCount(0);
> 628 |   await expect(page.locator('.project-result-point')).not.toContainText('本次没有找到');
      |                                                           ^ Error: expect(locator).not.toContainText(expected) failed
  629 |   await expect(page.locator('.scope-mismatch-notice').first()).toContainText('创建新版本');
  630 |   await page.getByRole('button',{name:'重新检索这些知识点'}).click();
  631 |   await expect(page.getByRole('heading',{name:'项目课程结果 · v2'})).toBeVisible();
  632 |   await expect(page.locator('.scope-mismatch-notice')).toHaveCount(0);
  633 |   expect(mock.calls.edit).toHaveLength(1);expect(mock.calls.search).toEqual([2]);
  634 |   expect(mock.calls.confirm.map(call=>call.version)).toEqual([2]);
  635 |   expect(old.batches[0].job_id).toBe('old-scope-job');expect(old.status).toBe('partial');
  636 |   await page.getByRole('button',{name:'我的项目'}).click();
  637 |   await page.getByLabel('查看版本',{exact:true}).selectOption('1');
  638 |   await expect(page.getByRole('heading',{name:'项目课程结果 · v1'})).toBeVisible();
  639 |   await expect(page.locator('.scope-mismatch-notice').first()).toContainText('当前为历史结果');
  640 |   await expect(page.getByRole('button',{name:'重新检索这些知识点'})).toHaveCount(0);
  641 |   await expect(page.locator('.resource-card,.unit-coverage')).toHaveCount(0);
  642 |   expect(mock.calls.edit).toHaveLength(1);expect(mock.calls.search).toEqual([2]);
  643 |   expect(mock.calls.runtime).toEqual([]);expect(mock.calls.console).toEqual([]);expect(mock.calls.unexpected).toEqual([]);
  644 | });
  645 | 
  646 | test('离线 Mock：无结果的平台搜索固定HTTPS来源并编码原单元词，明确区别推荐视频', async ({ page }) => {
  647 |   const mock = await mockProject(page, { initial: true, noResults: true });
  648 |   const current = mock.versions.get(1)!;
  649 |   current.status = 'completed'; current.confirmation = { version: 1, confirmed_at: time };
  650 |   current.batches = [{ batch_id: 'empty-batch', status: 'completed', project_knowledge_point_ids: ['kp1', 'kp2', 'kp3'], job_id: 'empty-job' }];
  651 |   const keyword = 'pandas C++ & 空值? <script>alert(1)</script> #主题';
  652 |   current.analysis!.knowledge_points[0].name = keyword;
  653 |   await enterProject(page, true);
  654 |   const links = page.locator('.platform-search-fallback');
  655 |   await expect(links).toHaveCount(3);
  656 |   const target = new URL((await links.first().getAttribute('href'))!);
  657 |   expect(target.protocol).toBe('https:'); expect(target.hostname).toBe('search.bilibili.com'); expect(target.pathname).toBe('/all');
  658 |   expect([...target.searchParams.keys()]).toEqual(['keyword']);
  659 |   expect(target.searchParams.get('keyword')).toBe(keyword);
  660 |   expect(target.hash).toBe(''); expect(target.username).toBe(''); expect(target.password).toBe('');
  661 |   await expect(links.first()).toHaveAttribute('target', '_blank');
  662 |   await expect(links.first()).toHaveAttribute('rel', 'noopener noreferrer');
  663 |   await expect(links.first()).toHaveAccessibleName(/平台搜索入口，非已推荐视频/);
  664 |   await expect(page.locator('.resource-card, .project-results script')).toHaveCount(0);
  665 |   // A student who did not choose this platform should not receive that fallback.
  666 |   current.input.preferred_platforms = ['icourse163'];
  667 |   await page.reload();
  668 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v1' })).toBeVisible();
  669 |   await expect(page.locator('.platform-search-fallback')).toHaveCount(0);
  670 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  671 | });
  672 | 
  673 | test('离线 Mock：分析加载可刷新恢复，减少动态偏好停用所有动画与过渡', async ({ page }) => {
  674 |   const mock = await mockProject(page, { analysisPending: true });
  675 |   await page.emulateMedia({ reducedMotion: 'reduce' });
  676 |   await enterProject(page);
  677 |   await fillBrief(page);
  678 |   await page.getByRole('button', { name: '分析项目' }).click();
  679 |   await expect(page.getByText('正在梳理项目知识点', { exact: true })).toBeVisible();
  680 |   await expect(page.getByRole('button', { name: '正在梳理知识点…' })).toBeDisabled();
  681 |   await page.reload();
  682 |   await expect(page.getByText('正在梳理项目知识点', { exact: true })).toBeVisible();
  683 |   await expect(page.getByLabel('功能需求', { exact: true })).toHaveValue(/读取本地 Excel/);
  684 |   const motions = await page.locator('.breathing-dots i,.stage-content,.primary-button').evaluateAll(elements => elements.map(element => {
  685 |     const style = getComputedStyle(element); return { animation: style.animationName, transition: style.transitionDuration };
  686 |   }));
  687 |   expect(motions.every(motion => motion.animation === 'none' && motion.transition.split(',').every(value => parseFloat(value) === 0))).toBe(true);
  688 |   await captureResponsiveState(page, 'loading-reduced-motion');
  689 |   await mkdir(screenshotRoot, { recursive: true });
  690 |   await writeFile(resolve(screenshotRoot, '../motion-observations.json'), JSON.stringify({ fixture: 'offline mocked analysis loading', reducedMotion: 'reduce', computedStyles: motions }, null, 2));
  691 |   expect(mock.calls.create).toHaveLength(1); expect(mock.calls.analyze).toBe(1);
  692 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  693 | });
  694 | 
```