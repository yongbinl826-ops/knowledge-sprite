# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: project.spec.ts >> 离线 Mock：单元技术默认显示并随完整分析保存，历史空值兼容且只读
- Location: tests\project.spec.ts:218:1

# Error details

```
Error: expect(received).toBeLessThanOrEqual(expected)

Expected: <= 129
Received:    238
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
            - group [ref=e60]:
              - generic "学习目标与前置关系 · 建议顺序 1 · 共享于 2 个功能" [active] [ref=e61] [cursor=pointer]
              - generic [ref=e62]:
                - paragraph [ref=e63]:
                  - strong [ref=e64]: 为什么学：
                  - text: 完成所关联的功能
                - paragraph [ref=e65]:
                  - strong [ref=e66]: 学会后能做：
                  - text: 能够在本地工具中应用
                - paragraph [ref=e67]:
                  - strong [ref=e68]: 必要先修：
                  - text: 无额外先修，可从这里开始
                - paragraph [ref=e69]:
                  - strong [ref=e70]: 同时用于：
                  - text: 读取与统计、图表与导出
              - generic [ref=e71]:
                - generic [ref=e72]: 本单元使用的工具或技术
                - textbox "本单元使用的工具或技术" [ref=e73]:
                  - /placeholder: 例如 pygame、pandas、Arduino
                  - text: Python 3 / pandas（本地 Excel）
                - paragraph [ref=e74]: 用于寻找同一种技术的教程；通用概念可以留空。
              - generic [ref=e75]:
                - generic [ref=e76]: 学习到什么程度
                - textbox "学习到什么程度" [ref=e77]: 能够在本地工具中应用
              - generic [ref=e78]:
                - generic [ref=e79]:
                  - generic [ref=e80]: 建议学习顺序
                  - spinbutton "建议学习顺序" [ref=e81]: "1"
                - generic [ref=e82]:
                  - generic [ref=e83]: 学习属性
                  - combobox "学习属性" [ref=e84]:
                    - option "必需" [selected]
                    - option "拓展"
              - group "前置知识点（可调整，顺序需早于当前知识点）" [ref=e85]:
                - generic [ref=e87]:
                  - checkbox "pandas 计算均值" [ref=e88]
                  - text: pandas 计算均值
                - generic [ref=e89]:
                  - checkbox "Matplotlib 柱状图绘制" [ref=e90]
                  - text: Matplotlib 柱状图绘制
              - group "用于哪些功能" [ref=e91]:
                - generic [ref=e93]:
                  - checkbox "读取与统计" [checked] [ref=e94]
                  - text: 读取与统计
                - generic [ref=e95]:
                  - checkbox "图表与导出" [checked] [ref=e96]
                  - text: 图表与导出
          - article [ref=e97]:
            - generic [aria-hidden] [ref=e98]: "02"
            - generic [ref=e99]:
              - generic [ref=e100]: 知识点名称：pandas 计算均值
              - textbox "知识点名称：pandas 计算均值" [ref=e101]:
                - /placeholder: 填写具体、适合检索的知识点
                - text: pandas 计算均值
              - generic [ref=e102]: 必需
              - button "删除知识点：pandas 计算均值" [ref=e103] [cursor=pointer]: 删除
            - group "pandas 计算均值的学习选择" [ref=e104]:
              - generic [ref=e105]:
                - checkbox "想学习" [checked] [ref=e106]
                - text: 想学习
            - paragraph [ref=e107]: 用于 读取与统计
            - paragraph [ref=e108]: 离线 Mock 知识点说明
            - paragraph [ref=e109]: 能够在本地工具中应用
            - group [ref=e110]:
              - generic "学习目标与前置关系 · 建议顺序 2" [ref=e111] [cursor=pointer]
              - option "必需" [selected]
              - option "拓展"
          - article [ref=e112]:
            - generic [aria-hidden] [ref=e113]: "03"
            - generic [ref=e114]:
              - generic [ref=e115]: 知识点名称：Matplotlib 柱状图绘制
              - textbox "知识点名称：Matplotlib 柱状图绘制" [ref=e116]:
                - /placeholder: 填写具体、适合检索的知识点
                - text: Matplotlib 柱状图绘制
              - generic [ref=e117]: 必需
              - button "删除知识点：Matplotlib 柱状图绘制" [ref=e118] [cursor=pointer]: 删除
            - group "Matplotlib 柱状图绘制的学习选择" [ref=e119]:
              - generic [ref=e120]:
                - checkbox "想学习" [checked] [ref=e121]
                - text: 想学习
            - paragraph [ref=e122]: 用于 图表与导出
            - paragraph [ref=e123]: 离线 Mock 知识点说明
            - paragraph [ref=e124]: 能够在本地工具中应用
            - group [ref=e125]:
              - generic "学习目标与前置关系 · 建议顺序 3" [ref=e126] [cursor=pointer]
              - option "必需" [selected]
              - option "拓展"
          - paragraph [ref=e127]: 需要新增单元或查看功能覆盖？切换到“按项目任务”。
        - paragraph [ref=e128]: 已勾选 3 项 · 未勾选 0 项 · 最多每批 5 项，预计 1 批
        - generic [ref=e129]:
          - button "保存修改，稍后确认" [disabled] [ref=e130]
          - button "查找推荐视频" [ref=e131] [cursor=pointer]
        - paragraph [ref=e132]: 分析模型：mock-test-only · 提示词：test-v1 · 2026/10/17 16:00:00
  - contentinfo [ref=e133]:
    - generic [ref=e134]: 让学习，发生在项目里。
    - generic [ref=e135]: 需求在本机服务保存 · 分析使用已配置的模型
```

# Test source

```ts
  144 | });
  145 | 
  146 | test('离线 Mock：全部取消勾选只保存选择，不创建空检索', async ({ page }) => {
  147 |   const mock = await mockProject(page, { initial: true });
  148 |   await enterProject(page, true);
  149 |   for (const id of ['kp1', 'kp2', 'kp3']) await firstPoint(page, id).getByLabel('想学习', { exact: true }).uncheck();
  150 |   await page.getByRole('button', { name: '保存选择', exact: true }).click();
  151 |   await expect(page.getByText('已保存选择；没有勾选知识点，未创建检索任务。')).toBeVisible();
  152 |   expect(mock.calls.confirm).toHaveLength(1); expect(mock.calls.search).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  153 | });
  154 | 
  155 | test('离线 Mock：旧版掌握仅在草稿转换，明确保存才建新版且历史不变', async ({ page }) => {
  156 |   const mock = await mockProject(page, { initial: true });
  157 |   mock.versions.get(1)!.analysis!.knowledge_points[0].selection = 'mastered';
  158 |   await enterProject(page, true);
  159 |   await expect(firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true })).not.toBeChecked();
  160 |   await expect(page.locator('.point-choices input[type="radio"]')).toHaveCount(0);
  161 |   await expect(page.getByText('已经掌握', { exact: true })).toHaveCount(0);
  162 |   await expect(page.getByText('暂时跳过', { exact: true })).toHaveCount(0);
  163 |   expect(mock.versions.get(1)!.analysis!.knowledge_points[0].selection).toBe('mastered');
  164 |   expect(mock.calls.edit).toHaveLength(0);
  165 |   await expect(page.getByRole('region', { name: '前置知识冲突' })).toBeVisible();
  166 |   await expect(page.getByRole('button', { name: '查找推荐视频', exact: true })).toBeDisabled();
  167 |   await page.getByRole('button', { name: '保存修改，稍后确认', exact: true }).click();
  168 |   await expect(page.getByRole('heading', { name: '确认知识点 · v2' })).toBeVisible();
  169 |   expect(mock.calls.edit[0].knowledge_points[0].selection).toBe('skip');
  170 |   expect(mock.calls.edit[0].knowledge_points.every(point => ['learn', 'skip'].includes(point.selection))).toBe(true);
  171 |   await firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true }).check();
  172 |   await expect(page.locator('.project-point[data-point-id="kp1"]')).toHaveCount(1);
  173 |   await expect(firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true })).toBeChecked();
  174 |   await page.getByRole('button', { name: '保存修改，稍后确认', exact: true }).click();
  175 |   await expect(page.getByRole('heading', { name: '确认知识点 · v3' })).toBeVisible();
  176 |   expect(mock.calls.edit[1].knowledge_points[0].selection).toBe('learn');
  177 |   await page.getByRole('button', { name: '我的项目' }).click();
  178 |   await page.getByLabel('查看版本', { exact: true }).selectOption('1');
  179 |   await expect(firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true })).not.toBeChecked();
  180 |   await expect(firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true })).toBeDisabled();
  181 |   expect(mock.versions.get(1)!.analysis!.knowledge_points[0].selection).toBe('mastered');
  182 |   expect(mock.calls.edit).toHaveLength(2);
  183 |   expect(mock.calls.search).toEqual([]); expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  184 | });
  185 | 
  186 | test('离线 Mock：增删改与方案编辑生成新版本，删除前置需先处理引用', async ({ page }) => {
  187 |   const mock = await mockProject(page, { initial: true });
  188 |   await enterProject(page, true);
  189 |   await firstPoint(page, 'kp1').getByRole('button', { name: /删除知识点/ }).click();
  190 |   await expect(page.getByRole('alert')).toContainText('仍依赖这个知识点');
  191 |   await firstPoint(page, 'kp2').getByRole('button', { name: /删除知识点/ }).click();
  192 |   await expect(page.locator('[data-point-id="kp2"]')).toHaveCount(0);
  193 |   await page.getByRole('button', { name: '按项目任务', exact: true }).click();
  194 |   await page.getByRole('button', { name: '＋ 为“读取与统计”添加知识点', exact: true }).click();
  195 |   await page.getByLabel('知识点名称：新增知识点', { exact: true }).fill('pandas 处理空值');
  196 |   await page.locator('.analysis-suggestions > summary').click();
  197 |   await page.getByLabel('建议技术方案（可修改的假设）').fill('使用 Python 和 pandas，暂不绘图。');
  198 |   await page.getByRole('button', { name: '保存修改，稍后确认' }).click();
  199 |   await expect(page.getByRole('heading', { name: '确认知识点 · v2' })).toBeVisible();
  200 |   expect(mock.calls.edit[0].knowledge_points.map(point => point.name)).toContain('pandas 处理空值');
  201 |   expect(mock.calls.edit[0].knowledge_points.map(point => point.id)).not.toContain('kp2');
  202 |   expect(mock.calls.edit[0].technical_plan).toBe('使用 Python 和 pandas，暂不绘图。');
  203 |   expect(mock.calls.confirm).toEqual([]); expect(mock.calls.search).toEqual([]);
  204 | });
  205 | 
  206 | test('离线 Mock：保存编辑后确认失败仍恢复新版本，重试不重复编辑', async ({ page }) => {
  207 |   const mock = await mockProject(page, { initial: true, failConfirmOnce: true });
  208 |   await enterProject(page, true);
  209 |   await firstPoint(page, 'kp2').locator('.point-title-line input').fill('pandas 均值与缺失值');
  210 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
  211 |   await expect(page.getByRole('alert')).toContainText('修改已保存');
  212 |   await expect(page.getByRole('heading', { name: '确认知识点 · v2' })).toBeVisible();
  213 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
  214 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v2' })).toBeVisible();
  215 |   expect(mock.calls.edit).toHaveLength(1); expect(mock.calls.confirm.map(call => call.version)).toEqual([2, 2]);
  216 | });
  217 | 
  218 | test('离线 Mock：单元技术默认显示并随完整分析保存，历史空值兼容且只读', async ({ page }, testInfo) => {
  219 |   const mock = await mockProject(page, { initial: true });
  220 |   const initial = mock.versions.get(1)!.analysis!;
  221 |   initial.knowledge_points[0].technology = 'pandas';
  222 |   const original = structuredClone(initial);
  223 |   const changedTechnology = 'Python 3 / pandas（本地 Excel）';
  224 |   await enterProject(page, true);
  225 |   await firstPoint(page, 'kp1').locator('summary').click();
  226 |   const technology = firstPoint(page, 'kp1').getByLabel('本单元使用的工具或技术', { exact: true });
  227 |   await expect(technology).toBeVisible();
  228 |   await expect(technology).toHaveValue('pandas');
  229 |   await expect(technology).toHaveAttribute('maxlength', '80');
  230 |   await expect(technology).toBeEditable();
  231 |   // A legacy unit can omit the optional field without a render or draft mutation.
  232 |   await firstPoint(page, 'kp2').locator('summary').click();
  233 |   await expect(firstPoint(page, 'kp2').getByLabel('本单元使用的工具或技术', { exact: true })).toHaveValue('');
  234 |   await technology.fill(changedTechnology);
  235 |   await page.getByRole('button', { name: '保存修改，稍后确认', exact: true }).click();
  236 |   await expect(page.getByRole('heading', { name: '确认知识点 · v2' })).toBeVisible();
  237 |   expect(mock.calls.edit).toEqual([{ ...original, knowledge_points: original.knowledge_points.map(point => point.id === 'kp1' ? { ...point, technology: changedTechnology } : point) }]);
  238 |   await firstPoint(page, 'kp1').locator('summary').click();
  239 |   const savedTechnology = firstPoint(page, 'kp1').getByLabel('本单元使用的工具或技术', { exact: true });
  240 |   await expect(savedTechnology).toHaveValue(changedTechnology);
  241 |   await savedTechnology.scrollIntoViewIfNeeded();
  242 |   await page.screenshot({ path: testInfo.outputPath('unit-technology-saved.png'), fullPage: false, animations: 'disabled' });
  243 |   const technologyLayout = await savedTechnology.evaluate(element => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth }));
> 244 |   expect(technologyLayout.scrollWidth).toBeLessThanOrEqual(technologyLayout.clientWidth + 1);
      |                                        ^ Error: expect(received).toBeLessThanOrEqual(expected)
  245 |   await page.getByRole('button', { name: '我的项目' }).click();
  246 |   await page.getByLabel('查看版本', { exact: true }).selectOption('1');
  247 |   await expect(page.getByRole('heading', { name: '确认知识点 · v1' })).toBeVisible();
  248 |   await firstPoint(page, 'kp1').locator('summary').click();
  249 |   await expect(firstPoint(page, 'kp1').getByLabel('本单元使用的工具或技术', { exact: true })).toHaveValue('pandas');
  250 |   await expect(firstPoint(page, 'kp1').getByLabel('本单元使用的工具或技术', { exact: true })).toBeDisabled();
  251 |   await firstPoint(page, 'kp2').locator('summary').click();
  252 |   const historicalEmpty = firstPoint(page, 'kp2').getByLabel('本单元使用的工具或技术', { exact: true });
  253 |   await expect(historicalEmpty).toHaveValue('');
  254 |   await expect(historicalEmpty).toBeDisabled();
  255 |   expect(mock.versions.get(1)!.analysis!.knowledge_points[0].technology).toBe('pandas');
  256 |   expect(mock.versions.get(1)!.analysis!.knowledge_points[1].technology).toBeUndefined();
  257 |   expect(mock.calls.edit).toHaveLength(1); expect(mock.calls.confirm).toHaveLength(0); expect(mock.calls.search).toHaveLength(0);
  258 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.console).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  259 |   await writeFile(resolve(process.cwd(), '../evidence/browser/unit-technology-browser-observations.json'), JSON.stringify({ kind: 'isolated browser transport fixture, not live model evidence', defaultTechnology: 'pandas', submittedTechnology: mock.calls.edit[0].knowledge_points[0].technology,
  260 |     entireAnalysisPreserved: true, inputMaxLength: 80, technologyLayout, historicalDefaultUnchanged: true, historicalMissingTechnology: '', historicalFieldsDisabled: true, mutationRequests: mock.calls.edit.length }, null, 2));
  261 | });
  262 | 
  263 | test('离线 Mock：预算超限保留全部知识点，需求修改后阻止旧分析确认', async ({ page }) => {
  264 |   const mock = await mockProject(page, { initial: true, count: 7, maxBatches: 1 });
  265 |   await enterProject(page, true);
  266 |   await expect(page.getByText(/超过项目 1 批上限/)).toBeVisible();
  267 |   await expect(page.getByRole('button', { name: '查找推荐视频', exact: true })).toBeDisabled();
  268 |   expect(new Set(await page.locator('[data-point-id]').evaluateAll(elements => elements.map(element => element.getAttribute('data-point-id')))).size).toBe(7);
  269 |   await page.getByRole('button', { name: '查看或修改项目描述' }).click();
  270 |   await page.getByLabel('功能需求', { exact: true }).fill('功能需求有实质变化，需要重新分析。');
  271 |   await page.getByRole('navigation', { name: '项目学习流程' }).getByRole('button', { name: /选择知识点/ }).click();
  272 |   await expect(page.getByText(/需求已有未保存修改/)).toBeVisible();
  273 |   await expect(page.getByRole('button', { name: '查找推荐视频', exact: true })).toBeDisabled();
  274 |   expect(mock.calls.search).toEqual([]);
  275 | });
  276 | 
  277 | test('离线 Mock：模型未配置仍保存原始输入，保留直接搜索入口', async ({ page }) => {
  278 |   const mock = await mockProject(page, { unconfigured: true });
  279 |   await enterProject(page);
  280 |   await expect(page.getByText(/项目分析不可用/)).toBeVisible();
  281 |   await page.getByLabel('项目名称', { exact: true }).fill('不能丢失的需求');
  282 |   await page.getByLabel('功能需求', { exact: true }).fill('读取表格并导出统计图');
  283 |   await page.getByRole('button', { name: '保存项目并检查分析配置' }).click();
  284 |   await expect(page.getByRole('alert')).toContainText('未配置可用模型');
  285 |   await expect(page.getByLabel('功能需求', { exact: true })).toHaveValue('读取表格并导出统计图');
  286 |   expect(mock.calls.create[0].requirements).toBe('读取表格并导出统计图');
  287 |   expect(mock.calls.search).toEqual([]);
  288 |   await page.getByRole('button', { name: '直接搜索知识点', exact: true }).click();
  289 |   await expect(page.getByLabel('知识点', { exact: true })).toBeVisible();
  290 | });
  291 | 
  292 | test('离线 Mock：历史结果保留版本，新版本不混入旧课程；手机布局无溢出', async ({ page }, testInfo) => {
  293 |   const mock = await mockProject(page, { initial: true });
  294 |   await enterProject(page, true);
  295 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
  296 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  297 |   await page.getByRole('button', { name: '← 调整知识点', exact: true }).click();
  298 |   await firstPoint(page, 'kp2').locator('.point-title-line input').fill('新版本统计方法');
  299 |   await page.getByRole('button', { name: '保存修改，稍后确认' }).click();
  300 |   await expect(page.getByRole('heading', { name: '确认知识点 · v2' })).toBeVisible();
  301 |   await expect(page.locator('.resource-card')).toHaveCount(0);
  302 |   await page.getByRole('button', { name: '我的项目' }).click();
  303 |   await page.getByLabel('查看版本', { exact: true }).selectOption('1');
  304 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v1' })).toBeVisible();
  305 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  306 |   await expect(page.getByRole('button', { name: '查找推荐视频', exact: true })).toHaveCount(0);
  307 |   const historyRetry = page.getByRole('button', { name: '重新检索这些知识点' });
  308 |   expect(await historyRetry.count() === 0 || await historyRetry.isDisabled()).toBe(true);
  309 |   await page.setViewportSize({ width: 390, height: 844 });
  310 |   await page.screenshot({ path: testInfo.outputPath('project-mobile-history.png'), fullPage: true });
  311 |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  312 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  313 | });
  314 | 
  315 | test('离线 Mock：部分完成仅有文字资源时显示明确空态，不假示仍在检索', async ({ page }, testInfo) => {
  316 |   const mock = await mockProject(page, { initial: true });
  317 |   const current = mock.versions.get(1)!;
  318 |   current.status = 'partial'; current.confirmation = { version: 1, confirmed_at: time };
  319 |   current.batches = [{ batch_id: 'partial-batch', status: 'partial', project_knowledge_point_ids: ['kp1', 'kp2', 'kp3'], job_id: 'partial-job' }];
  320 |   await page.route('**/api/projects/mock-project/results*', route => {
  321 |     const snapshot = mock.view();
  322 |     snapshot.points = snapshot.points!.map(point => ({ ...point, status: 'partial', result: {
  323 |       knowledge_point_id: point.project_knowledge_point_id, text: point.name, total_matches: 0, items: [],
  324 |       partial_items: [{ ...resource(point.project_knowledge_point_id), resource: { ...resource(point.project_knowledge_point_id).resource, resource_type: 'article' } }],
  325 |     } }));
  326 |     return route.fulfill({ json: snapshot });
  327 |   });
  328 |   await enterProject(page, true);
  329 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v1' })).toBeVisible();
  330 |   await expect(page.getByText('本次检索部分完成，未找到可展示的课程。', { exact: true })).toHaveCount(3);
  331 |   await expect(page.getByText('正在读取或查找课程…', { exact: true })).toHaveCount(0);
  332 |   await expect(page.locator('.resource-card')).toHaveCount(0);
  333 |   await page.locator('.project-results').scrollIntoViewIfNeeded();
  334 |   await page.screenshot({ path: testInfo.outputPath('partial-terminal-empty.png'), fullPage: false });
  335 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  336 | });
  337 | 
  338 | test('离线 Mock：平台筛选无匹配区别于本次无结果，切回全部恢复课程', async ({ page }) => {
  339 |   const mock = await mockProject(page, { initial: true });
  340 |   const current = mock.versions.get(1)!;
  341 |   current.status = 'completed'; current.confirmation = { version: 1, confirmed_at: time };
  342 |   current.batches = [{ batch_id: 'completed-batch', status: 'completed', project_knowledge_point_ids: ['kp1', 'kp2', 'kp3'], job_id: 'completed-job' }];
  343 |   await page.route('**/api/projects/mock-project/results*', route => {
  344 |     const snapshot = mock.view();
```