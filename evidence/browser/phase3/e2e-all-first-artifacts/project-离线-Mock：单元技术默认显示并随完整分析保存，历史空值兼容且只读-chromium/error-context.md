# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: project.spec.ts >> 离线 Mock：单元技术默认显示并随完整分析保存，历史空值兼容且只读
- Location: tests\project.spec.ts:233:1

# Error details

```
Error: expect(received).toEqual(expected) // deep equality

- Expected  - 0
+ Received  + 3

@@ -27,10 +27,11 @@
            "f2",
          ],
          "id": "kp1",
          "learning_goal": "能够在本地工具中应用",
          "learning_order": 1,
+         "learning_skills": Array [],
          "name": "pandas 读取 Excel",
          "necessity": "required",
          "prerequisite_ids": Array [],
          "selection": "learn",
          "technology": "Python 3 / pandas（本地 Excel）",
@@ -42,10 +43,11 @@
            "f1",
          ],
          "id": "kp2",
          "learning_goal": "能够在本地工具中应用",
          "learning_order": 2,
+         "learning_skills": Array [],
          "name": "pandas 计算均值",
          "necessity": "required",
          "prerequisite_ids": Array [
            "kp1",
          ],
@@ -58,10 +60,11 @@
            "f2",
          ],
          "id": "kp3",
          "learning_goal": "能够在本地工具中应用",
          "learning_order": 3,
+         "learning_skills": Array [],
          "name": "Matplotlib 柱状图绘制",
          "necessity": "required",
          "prerequisite_ids": Array [
            "kp1",
          ],
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
        - generic [ref=e15]: "02"
        - text: 选择知识点
      - button "03 推荐视频" [disabled] [ref=e16]:
        - generic [ref=e18]: "03"
        - text: 推荐视频
    - button "我的项目" [ref=e19] [cursor=pointer]: 我的项目 ↗
  - main [ref=e20]:
    - complementary [ref=e21]:
      - paragraph [ref=e22]: 02 / LEARNING SCOPE
      - heading "选择此刻， 想学的知识。" [level=1] [ref=e23]: 选择此刻，想学的知识。
      - paragraph [ref=e24]: 围绕 Mock：Excel 成绩分析工具，选择适合你的学习单元。
      - button "查看或修改项目描述" [ref=e26] [cursor=pointer]: 查看或修改项目描述 ↗
      - paragraph [ref=e27]:
        - text: 已选择
        - strong [ref=e28]: "3"
        - text: 个学习单元
        - generic [ref=e29]: 建议按先修顺序学习，可自由调整。
      - generic [aria-hidden] [ref=e30]: "02"
    - generic [ref=e31]:
      - status [ref=e32]: 修改已保存为新版本，需要重新确认。
      - paragraph [ref=e33]: Mock：Excel 成绩分析工具 · v2 · 待确认
      - region [ref=e34]:
        - generic [ref=e35]:
          - generic [ref=e36]:
            - heading "确认知识点 · v2" [level=2] [ref=e37]: 你的项目，需要这些知识
            - paragraph [ref=e38]: 按先修顺序排列；展开学习单元，了解目标与实践任务。
          - generic [ref=e39]: 等待确认
        - group [ref=e40]:
          - generic "分析建议与默认假设" [ref=e41] [cursor=pointer]:
            - text: 分析建议与默认假设
            - generic [aria-hidden] [ref=e42]: ＋
        - group "学习单元排列方式" [ref=e43]:
          - button "按学习顺序" [pressed] [ref=e44] [cursor=pointer]
          - button "按项目任务" [ref=e45] [cursor=pointer]
        - region "学习顺序" [ref=e46]:
          - article [ref=e47]:
            - generic [aria-hidden] [ref=e48]: "01"
            - generic [ref=e49]:
              - generic [ref=e50]: 知识点名称：pandas 读取 Excel
              - textbox "知识点名称：pandas 读取 Excel" [ref=e51]:
                - /placeholder: 填写具体、适合检索的知识点
                - text: pandas 读取 Excel
              - generic [ref=e52]: 必需
              - button "删除知识点：pandas 读取 Excel" [ref=e53] [cursor=pointer]: 删除
            - group "pandas 读取 Excel的学习选择" [ref=e54]:
              - generic [ref=e55]:
                - checkbox "想学习" [checked] [ref=e56]
                - text: 想学习
            - paragraph [ref=e57]: 用于 读取与统计、图表与导出
            - paragraph [ref=e58]: 离线 Mock 知识点说明
            - paragraph [ref=e59]: 能够在本地工具中应用
            - paragraph [ref=e60]:
              - strong [ref=e61]: 先学技能：
              - text: 此版本尚未单独整理，可展开后补充。
            - group [ref=e62]:
              - generic "学习目标与前置关系 · 建议顺序 1 · 共享于 2 个功能" [ref=e63] [cursor=pointer]
              - option "必需" [selected]
              - option "拓展"
          - article [ref=e64]:
            - generic [aria-hidden] [ref=e65]: "02"
            - generic [ref=e66]:
              - generic [ref=e67]: 知识点名称：pandas 计算均值
              - textbox "知识点名称：pandas 计算均值" [ref=e68]:
                - /placeholder: 填写具体、适合检索的知识点
                - text: pandas 计算均值
              - generic [ref=e69]: 必需
              - button "删除知识点：pandas 计算均值" [ref=e70] [cursor=pointer]: 删除
            - group "pandas 计算均值的学习选择" [ref=e71]:
              - generic [ref=e72]:
                - checkbox "想学习" [checked] [ref=e73]
                - text: 想学习
            - paragraph [ref=e74]: 用于 读取与统计
            - paragraph [ref=e75]: 离线 Mock 知识点说明
            - paragraph [ref=e76]: 能够在本地工具中应用
            - paragraph [ref=e77]:
              - strong [ref=e78]: 先学技能：
              - text: 此版本尚未单独整理，可展开后补充。
            - group [ref=e79]:
              - generic "学习目标与前置关系 · 建议顺序 2" [ref=e80] [cursor=pointer]
              - option "必需" [selected]
              - option "拓展"
          - article [ref=e81]:
            - generic [aria-hidden] [ref=e82]: "03"
            - generic [ref=e83]:
              - generic [ref=e84]: 知识点名称：Matplotlib 柱状图绘制
              - textbox "知识点名称：Matplotlib 柱状图绘制" [ref=e85]:
                - /placeholder: 填写具体、适合检索的知识点
                - text: Matplotlib 柱状图绘制
              - generic [ref=e86]: 必需
              - button "删除知识点：Matplotlib 柱状图绘制" [ref=e87] [cursor=pointer]: 删除
            - group "Matplotlib 柱状图绘制的学习选择" [ref=e88]:
              - generic [ref=e89]:
                - checkbox "想学习" [checked] [ref=e90]
                - text: 想学习
            - paragraph [ref=e91]: 用于 图表与导出
            - paragraph [ref=e92]: 离线 Mock 知识点说明
            - paragraph [ref=e93]: 能够在本地工具中应用
            - paragraph [ref=e94]:
              - strong [ref=e95]: 先学技能：
              - text: 此版本尚未单独整理，可展开后补充。
            - group [ref=e96]:
              - generic "学习目标与前置关系 · 建议顺序 3" [ref=e97] [cursor=pointer]
              - option "必需" [selected]
              - option "拓展"
          - paragraph [ref=e98]: 需要新增单元或查看功能覆盖？切换到“按项目任务”。
        - paragraph [ref=e99]: 已勾选 3 项 · 未勾选 0 项 · 最多每批 5 项，预计 1 批
        - generic [ref=e100]:
          - button "保存修改，稍后确认" [disabled] [ref=e101]
          - button "查找推荐视频" [ref=e102] [cursor=pointer]
        - paragraph [ref=e103]: 分析模型：mock-test-only · 提示词：test-v1 · 2026/10/17 16:00:00
  - contentinfo [ref=e104]:
    - generic [ref=e105]: 让学习，发生在项目里。
    - generic [ref=e106]: 需求在本机服务保存 · 分析使用已配置的模型
```

# Test source

```ts
  152 |   expect(mock.calls.search).toEqual([2]);
  153 |   await expect(page.locator('.platform-search-fallback')).toHaveCount(0);
  154 |   await captureResponsiveState(page, 'search-loading');
  155 |   await page.getByRole('button', { name: '取消项目检索' }).click();
  156 |   await page.locator('.search-diagnostics > summary').click();
  157 |   await expect(page.locator('.project-batches').getByText('已取消', { exact: true })).toBeVisible();
  158 |   expect(mock.calls.cancel).toBe(1); expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  159 | });
  160 | 
  161 | test('离线 Mock：全部取消勾选只保存选择，不创建空检索', async ({ page }) => {
  162 |   const mock = await mockProject(page, { initial: true });
  163 |   await enterProject(page, true);
  164 |   for (const id of ['kp1', 'kp2', 'kp3']) await firstPoint(page, id).getByLabel('想学习', { exact: true }).uncheck();
  165 |   await page.getByRole('button', { name: '保存选择', exact: true }).click();
  166 |   await expect(page.getByText('已保存选择；没有勾选知识点，未创建检索任务。')).toBeVisible();
  167 |   expect(mock.calls.confirm).toHaveLength(1); expect(mock.calls.search).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  168 | });
  169 | 
  170 | test('离线 Mock：旧版掌握仅在草稿转换，明确保存才建新版且历史不变', async ({ page }) => {
  171 |   const mock = await mockProject(page, { initial: true });
  172 |   mock.versions.get(1)!.analysis!.knowledge_points[0].selection = 'mastered';
  173 |   await enterProject(page, true);
  174 |   await expect(firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true })).not.toBeChecked();
  175 |   await expect(page.locator('.point-choices input[type="radio"]')).toHaveCount(0);
  176 |   await expect(page.getByText('已经掌握', { exact: true })).toHaveCount(0);
  177 |   await expect(page.getByText('暂时跳过', { exact: true })).toHaveCount(0);
  178 |   expect(mock.versions.get(1)!.analysis!.knowledge_points[0].selection).toBe('mastered');
  179 |   expect(mock.calls.edit).toHaveLength(0);
  180 |   await expect(page.getByRole('region', { name: '前置知识冲突' })).toBeVisible();
  181 |   await expect(page.getByRole('button', { name: '查找推荐视频', exact: true })).toBeDisabled();
  182 |   await page.getByRole('button', { name: '保存修改，稍后确认', exact: true }).click();
  183 |   await expect(page.getByRole('heading', { name: '确认知识点 · v2' })).toBeVisible();
  184 |   expect(mock.calls.edit[0].knowledge_points[0].selection).toBe('skip');
  185 |   expect(mock.calls.edit[0].knowledge_points.every(point => ['learn', 'skip'].includes(point.selection))).toBe(true);
  186 |   await firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true }).check();
  187 |   await expect(page.locator('.project-point[data-point-id="kp1"]')).toHaveCount(1);
  188 |   await expect(firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true })).toBeChecked();
  189 |   await page.getByRole('button', { name: '保存修改，稍后确认', exact: true }).click();
  190 |   await expect(page.getByRole('heading', { name: '确认知识点 · v3' })).toBeVisible();
  191 |   expect(mock.calls.edit[1].knowledge_points[0].selection).toBe('learn');
  192 |   await page.getByRole('button', { name: '我的项目' }).click();
  193 |   await page.getByLabel('查看版本', { exact: true }).selectOption('1');
  194 |   await expect(firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true })).not.toBeChecked();
  195 |   await expect(firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true })).toBeDisabled();
  196 |   expect(mock.versions.get(1)!.analysis!.knowledge_points[0].selection).toBe('mastered');
  197 |   expect(mock.calls.edit).toHaveLength(2);
  198 |   expect(mock.calls.search).toEqual([]); expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  199 | });
  200 | 
  201 | test('离线 Mock：增删改与方案编辑生成新版本，删除前置需先处理引用', async ({ page }) => {
  202 |   const mock = await mockProject(page, { initial: true });
  203 |   await enterProject(page, true);
  204 |   await firstPoint(page, 'kp1').getByRole('button', { name: /删除知识点/ }).click();
  205 |   await expect(page.getByRole('alert')).toContainText('仍依赖这个知识点');
  206 |   await firstPoint(page, 'kp2').getByRole('button', { name: /删除知识点/ }).click();
  207 |   await expect(page.locator('[data-point-id="kp2"]')).toHaveCount(0);
  208 |   await page.getByRole('button', { name: '按项目任务', exact: true }).click();
  209 |   await page.getByRole('button', { name: '＋ 为“读取与统计”添加知识点', exact: true }).click();
  210 |   await page.getByLabel('知识点名称：新增知识点', { exact: true }).fill('pandas 处理空值');
  211 |   await page.locator('.analysis-suggestions > summary').click();
  212 |   await page.getByLabel('建议技术方案（可修改的假设）').fill('使用 Python 和 pandas，暂不绘图。');
  213 |   await page.getByRole('button', { name: '保存修改，稍后确认' }).click();
  214 |   await expect(page.getByRole('heading', { name: '确认知识点 · v2' })).toBeVisible();
  215 |   expect(mock.calls.edit[0].knowledge_points.map(point => point.name)).toContain('pandas 处理空值');
  216 |   expect(mock.calls.edit[0].knowledge_points.map(point => point.id)).not.toContain('kp2');
  217 |   expect(mock.calls.edit[0].technical_plan).toBe('使用 Python 和 pandas，暂不绘图。');
  218 |   expect(mock.calls.confirm).toEqual([]); expect(mock.calls.search).toEqual([]);
  219 | });
  220 | 
  221 | test('离线 Mock：保存编辑后确认失败仍恢复新版本，重试不重复编辑', async ({ page }) => {
  222 |   const mock = await mockProject(page, { initial: true, failConfirmOnce: true });
  223 |   await enterProject(page, true);
  224 |   await firstPoint(page, 'kp2').locator('.point-title-line input').fill('pandas 均值与缺失值');
  225 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
  226 |   await expect(page.getByRole('alert')).toContainText('修改已保存');
  227 |   await expect(page.getByRole('heading', { name: '确认知识点 · v2' })).toBeVisible();
  228 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
  229 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v2' })).toBeVisible();
  230 |   expect(mock.calls.edit).toHaveLength(1); expect(mock.calls.confirm.map(call => call.version)).toEqual([2, 2]);
  231 | });
  232 | 
  233 | test('离线 Mock：单元技术默认显示并随完整分析保存，历史空值兼容且只读', async ({ page }, testInfo) => {
  234 |   const mock = await mockProject(page, { initial: true });
  235 |   const initial = mock.versions.get(1)!.analysis!;
  236 |   initial.knowledge_points[0].technology = 'pandas';
  237 |   const original = structuredClone(initial);
  238 |   const changedTechnology = 'Python 3 / pandas（本地 Excel）';
  239 |   await enterProject(page, true);
  240 |   await firstPoint(page, 'kp1').locator('summary').click();
  241 |   const technology = firstPoint(page, 'kp1').getByLabel('本单元使用的工具或技术', { exact: true });
  242 |   await expect(technology).toBeVisible();
  243 |   await expect(technology).toHaveValue('pandas');
  244 |   await expect(technology).toHaveAttribute('maxlength', '80');
  245 |   await expect(technology).toBeEditable();
  246 |   // A legacy unit can omit the optional field without a render or draft mutation.
  247 |   await firstPoint(page, 'kp2').locator('summary').click();
  248 |   await expect(firstPoint(page, 'kp2').getByLabel('本单元使用的工具或技术', { exact: true })).toHaveValue('');
  249 |   await technology.fill(changedTechnology);
  250 |   await page.getByRole('button', { name: '保存修改，稍后确认', exact: true }).click();
  251 |   await expect(page.getByRole('heading', { name: '确认知识点 · v2' })).toBeVisible();
> 252 |   expect(mock.calls.edit).toEqual([{ ...original, knowledge_points: original.knowledge_points.map(point => point.id === 'kp1' ? { ...point, technology: changedTechnology } : point) }]);
      |                           ^ Error: expect(received).toEqual(expected) // deep equality
  253 |   await firstPoint(page, 'kp1').locator('summary').click();
  254 |   const savedTechnology = firstPoint(page, 'kp1').getByLabel('本单元使用的工具或技术', { exact: true });
  255 |   await expect(savedTechnology).toHaveValue(changedTechnology);
  256 |   await savedTechnology.scrollIntoViewIfNeeded();
  257 |   await page.screenshot({ path: testInfo.outputPath('unit-technology-saved.png'), fullPage: false, animations: 'disabled' });
  258 |   const technologyLayout = await savedTechnology.evaluate(element => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth }));
  259 |   expect(technologyLayout.scrollWidth).toBeLessThanOrEqual(technologyLayout.clientWidth + 1);
  260 |   await page.getByRole('button', { name: '我的项目' }).click();
  261 |   await page.getByLabel('查看版本', { exact: true }).selectOption('1');
  262 |   await expect(page.getByRole('heading', { name: '确认知识点 · v1' })).toBeVisible();
  263 |   await firstPoint(page, 'kp1').locator('summary').click();
  264 |   await expect(firstPoint(page, 'kp1').getByLabel('本单元使用的工具或技术', { exact: true })).toHaveValue('pandas');
  265 |   await expect(firstPoint(page, 'kp1').getByLabel('本单元使用的工具或技术', { exact: true })).toBeDisabled();
  266 |   await firstPoint(page, 'kp2').locator('summary').click();
  267 |   const historicalEmpty = firstPoint(page, 'kp2').getByLabel('本单元使用的工具或技术', { exact: true });
  268 |   await expect(historicalEmpty).toHaveValue('');
  269 |   await expect(historicalEmpty).toBeDisabled();
  270 |   expect(mock.versions.get(1)!.analysis!.knowledge_points[0].technology).toBe('pandas');
  271 |   expect(mock.versions.get(1)!.analysis!.knowledge_points[1].technology).toBeUndefined();
  272 |   expect(mock.calls.edit).toHaveLength(1); expect(mock.calls.confirm).toHaveLength(0); expect(mock.calls.search).toHaveLength(0);
  273 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.console).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  274 |   await writeFile(resolve(process.cwd(), process.env.QA_EVIDENCE_ROOT || '../evidence/browser', 'unit-technology-browser-observations.json'), JSON.stringify({ kind: 'isolated browser transport fixture, not live model evidence', defaultTechnology: 'pandas', submittedTechnology: mock.calls.edit[0].knowledge_points[0].technology,
  275 |     entireAnalysisPreserved: true, inputMaxLength: 80, technologyLayout, historicalDefaultUnchanged: true, historicalMissingTechnology: '', historicalFieldsDisabled: true, mutationRequests: mock.calls.edit.length }, null, 2));
  276 | });
  277 | 
  278 | test('离线 Mock：预算超限保留全部知识点，需求修改后阻止旧分析确认', async ({ page }) => {
  279 |   const mock = await mockProject(page, { initial: true, count: 7, maxBatches: 1 });
  280 |   await enterProject(page, true);
  281 |   await expect(page.getByText(/超过项目 1 批上限/)).toBeVisible();
  282 |   await expect(page.getByRole('button', { name: '查找推荐视频', exact: true })).toBeDisabled();
  283 |   expect(new Set(await page.locator('[data-point-id]').evaluateAll(elements => elements.map(element => element.getAttribute('data-point-id')))).size).toBe(7);
  284 |   await page.getByRole('button', { name: '查看或修改项目描述' }).click();
  285 |   await page.getByLabel('功能需求', { exact: true }).fill('功能需求有实质变化，需要重新分析。');
  286 |   await page.getByRole('navigation', { name: '项目学习流程' }).getByRole('button', { name: /选择知识点/ }).click();
  287 |   await expect(page.getByText(/需求已有未保存修改/)).toBeVisible();
  288 |   await expect(page.getByRole('button', { name: '查找推荐视频', exact: true })).toBeDisabled();
  289 |   expect(mock.calls.search).toEqual([]);
  290 | });
  291 | 
  292 | test('离线 Mock：模型未配置仍保存原始输入，保留直接搜索入口', async ({ page }) => {
  293 |   const mock = await mockProject(page, { unconfigured: true });
  294 |   await enterProject(page);
  295 |   await expect(page.getByText(/项目分析不可用/)).toBeVisible();
  296 |   await page.getByLabel('项目名称', { exact: true }).fill('不能丢失的需求');
  297 |   await page.getByLabel('功能需求', { exact: true }).fill('读取表格并导出统计图');
  298 |   await page.getByRole('button', { name: '保存项目并检查分析配置' }).click();
  299 |   await expect(page.getByRole('alert')).toContainText('未配置可用模型');
  300 |   await expect(page.getByLabel('功能需求', { exact: true })).toHaveValue('读取表格并导出统计图');
  301 |   expect(mock.calls.create[0].requirements).toBe('读取表格并导出统计图');
  302 |   expect(mock.calls.search).toEqual([]);
  303 |   await page.getByRole('button', { name: '直接搜索知识点', exact: true }).click();
  304 |   await expect(page.getByLabel('知识点', { exact: true })).toBeVisible();
  305 | });
  306 | 
  307 | test('离线 Mock：历史结果保留版本，新版本不混入旧课程；手机布局无溢出', async ({ page }, testInfo) => {
  308 |   const mock = await mockProject(page, { initial: true });
  309 |   await enterProject(page, true);
  310 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
  311 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  312 |   await page.getByRole('button', { name: '← 调整知识点', exact: true }).click();
  313 |   await firstPoint(page, 'kp2').locator('.point-title-line input').fill('新版本统计方法');
  314 |   await page.getByRole('button', { name: '保存修改，稍后确认' }).click();
  315 |   await expect(page.getByRole('heading', { name: '确认知识点 · v2' })).toBeVisible();
  316 |   await expect(page.locator('.resource-card')).toHaveCount(0);
  317 |   await page.getByRole('button', { name: '我的项目' }).click();
  318 |   await page.getByLabel('查看版本', { exact: true }).selectOption('1');
  319 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v1' })).toBeVisible();
  320 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  321 |   await expect(page.getByRole('button', { name: '查找推荐视频', exact: true })).toHaveCount(0);
  322 |   const historyRetry = page.getByRole('button', { name: '重新检索这些知识点' });
  323 |   expect(await historyRetry.count() === 0 || await historyRetry.isDisabled()).toBe(true);
  324 |   await page.setViewportSize({ width: 390, height: 844 });
  325 |   await page.screenshot({ path: testInfo.outputPath('project-mobile-history.png'), fullPage: true });
  326 |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  327 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  328 | });
  329 | 
  330 | test('离线 Mock：部分完成仅有文字资源时显示明确空态，不假示仍在检索', async ({ page }, testInfo) => {
  331 |   const mock = await mockProject(page, { initial: true });
  332 |   const current = mock.versions.get(1)!;
  333 |   current.status = 'partial'; current.confirmation = { version: 1, confirmed_at: time };
  334 |   current.batches = [{ batch_id: 'partial-batch', status: 'partial', project_knowledge_point_ids: ['kp1', 'kp2', 'kp3'], job_id: 'partial-job' }];
  335 |   await page.route('**/api/projects/mock-project/results*', route => {
  336 |     const snapshot = mock.view();
  337 |     snapshot.points = snapshot.points!.map(point => ({ ...point, status: 'partial', result: {
  338 |       knowledge_point_id: point.project_knowledge_point_id, text: point.name, total_matches: 0, items: [],
  339 |       partial_items: [{ ...resource(point.project_knowledge_point_id), resource: { ...resource(point.project_knowledge_point_id).resource, resource_type: 'article' } }],
  340 |     } }));
  341 |     return route.fulfill({ json: snapshot });
  342 |   });
  343 |   await enterProject(page, true);
  344 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v1' })).toBeVisible();
  345 |   await expect(page.getByText('本次检索部分完成，未找到可展示的课程。', { exact: true })).toHaveCount(3);
  346 |   await expect(page.getByText('正在读取或查找课程…', { exact: true })).toHaveCount(0);
  347 |   await expect(page.locator('.resource-card')).toHaveCount(0);
  348 |   await page.locator('.project-results').scrollIntoViewIfNeeded();
  349 |   await page.screenshot({ path: testInfo.outputPath('partial-terminal-empty.png'), fullPage: false });
  350 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  351 | });
  352 | 
```