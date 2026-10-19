# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: search.spec.ts >> 移动端无横向溢出，表单可用
- Location: tests\search.spec.ts:161:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('heading', { name: '想学的知识，去哪里学？' })
Expected: visible
Timeout: 7000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('heading', { name: '想学的知识，去哪里学？' }) with timeout 7000ms
  - waiting for getByRole('heading', { name: '想学的知识，去哪里学？' })

```

```yaml
- link "跳转到知识点输入":
  - /url: "#knowledge"
- banner:
  - text: 项目制知识引导小精灵
  - button "从项目开始"
- main:
  - paragraph: DIRECT / LEARNING
  - heading "想学的知识， 从这里开始。" [level=1]
  - paragraph: 输入具体知识点，找到相关视频与有证据的学习章节。
  - complementary:
    - heading "学习需求" [level=2]
    - text: 知识点 0 / 5
    - textbox "知识点":
      - /placeholder: 每行一个知识点，最多 5 个
    - text: 每行输入一个知识点，重复行会自动合并。 学生基础
    - combobox "学生基础":
      - option "初学者" [selected]
      - option "有一定基础"
      - option "进阶学习"
      - option "不限"
    - text: 学习语言
    - combobox "学习语言":
      - option "中文" [selected]
      - option "英语"
      - option "不限"
    - group: 更多筛选
    - button "开始查找"
  - region "推荐课程":
    - heading "推荐课程" [level=2]
    - paragraph: 找到对应章节，去原平台学习
    - strong: 搜索服务暂不可用
    - paragraph: 请先在服务端接入 SearXNG，或启用已配置的 Tavily。
    - heading "想学什么？" [level=3]
    - paragraph: 输入知识点，找到课程和对应章节
  - group: 来源与访问说明 ＋
```

# Test source

```ts
  65  |   const mooc: ResourceItem = { ...item, resource: { ...item.resource, resource_id: 'fixture-mooc', title: '测试：第六名 MOOC 课程', url: 'https://www.icourse163.org/course/TEST-123456', platform: 'icourse163', resource_type: 'course' } };
  66  |   const topFive = Array.from({ length: 5 }, (_, i) => ({ ...item, resource: { ...item.resource, resource_id: `fixture-${i}` } }));
  67  |   await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], total_matches: 6, items: topFive, platform_items: { bilibili: topFive, icourse163: [mooc] } }] });
  68  |   await page.goto('/?job=test-job');
  69  |   await expect(page.locator('.resource-card')).toHaveCount(5);
  70  |   await expect(page.getByRole('heading', { name: '测试：第六名 MOOC 课程', exact: true })).toHaveCount(0);
  71  |   await page.getByLabel('来源平台').selectOption('icourse163');
  72  |   await expect(page.locator('.resource-card')).toHaveCount(1);
  73  |   await expect(page.getByRole('heading', { name: '测试：第六名 MOOC 课程', exact: true })).toBeVisible();
  74  |   await page.getByLabel('来源平台').selectOption('all');
  75  |   await expect(page.locator('.resource-card')).toHaveCount(5);
  76  | });
  77  | 
  78  | test('未配置状态、必填和知识点预算校验；无假结果', async ({ page }, testInfo) => {
  79  |   const consoleErrors: string[] = [];
  80  |   page.on('pageerror', error => consoleErrors.push(error.message));
  81  |   await setup(page, { ...caps, search: { ...caps.search, status: 'unconfigured', message: '请先在服务端接入 SearXNG，或启用已配置的 Tavily。' } });
  82  |   await page.goto('/?mode=manual');
  83  |   await expect(page).toHaveTitle('项目制知识引导小精灵 · 课程与视频发现');
  84  |   await expect(page.getByText('搜索服务暂不可用')).toBeVisible();
  85  |   await expect(page.locator('.resource-card')).toHaveCount(0);
  86  |   await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  87  |   await page.screenshot({ path: testInfo.outputPath('desktop-empty.png'), fullPage: true });
  88  |   await page.getByRole('button', { name: '开始查找' }).click();
  89  |   await expect(page.getByRole('alert')).toHaveText('请至少输入一个知识点。');
  90  |   await page.getByLabel('知识点', { exact: true }).fill('一\n二\n三\n四\n五\n六');
  91  |   await page.getByRole('button', { name: '开始查找' }).click();
  92  |   await expect(page.getByRole('alert')).toHaveText('最多输入 5 个知识点，请分批查找。');
  93  |   expect(consoleErrors).toEqual([]);
  94  | });
  95  | 
  96  | test('多知识点提交、分组筛选、简洁占位封面与安全原平台外链', async ({ page }, testInfo) => {
  97  |   await setup(page);
  98  |   let submitted: unknown;
  99  |   await page.route('**/api/search-jobs', async route => { submitted = route.request().postDataJSON(); await route.fulfill({ status: 202, json: { job_id: 'test-job' } }); });
  100 |   let pollCount = 0;
  101 |   await page.route('**/api/search-jobs/test-job', route => {
  102 |     pollCount += 1;
  103 |     return route.fulfill({ json: pollCount === 1 ? { ...baseJob, status: 'running', phase: 'searching', progress: { ...baseJob.progress, queries_completed: 1 } } : baseJob });
  104 |   });
  105 |   await page.goto('/?mode=manual');
  106 |   await page.getByLabel('知识点', { exact: true }).fill('非预设知识点：空间哈希\n边界条件\n边界条件');
  107 |   await page.getByText('更多筛选', { exact: true }).click();
  108 |   await page.getByLabel('技术版本').fill('WebGL 2');
  109 |   await page.getByLabel('项目背景').fill('地图可视化');
  110 |   await page.getByRole('button', { name: '开始查找' }).click();
  111 |   await expect(page.getByText('正在查找', { exact: true })).toBeVisible();
  112 |   await expect(page.locator('.search-progress')).toContainText('1/4');
  113 |   await expect(page.getByText('检索完成', { exact: true })).toBeVisible();
  114 |   expect(submitted).toMatchObject({ knowledge_points: ['非预设知识点：空间哈希', '边界条件'], technical_version: 'WebGL 2', project_context: '地图可视化' });
  115 |   await expect(page.locator('.result-group')).toHaveCount(2);
  116 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  117 |   await expect(page.locator('.resource-card img')).toHaveCount(0);
  118 |   await expect(page.locator('.cover-placeholder')).toHaveCount(3);
  119 |   await expect(page.locator('.course-cover').first()).toHaveAttribute('href', 'https://www.bilibili.com/video/BV_TEST_ONLY?p=2');
  120 |   await expect(page.locator('.course-cover').first()).toHaveAttribute('rel', 'noopener noreferrer');
  121 |   await expect(page.locator('.course-cover').first()).toHaveAttribute('target', '_blank');
  122 |   await expect(page.locator('.resource-card').first()).toContainText('内容相关性待确认，可前往原平台查看。');
  123 |   await expect(page.locator('.resource-card h4').first()).toContainText('<img src=x onerror=alert(1)>');
  124 |   await expect(page.locator('.chapter-list, .evidence-details, video, iframe')).toHaveCount(0);
  125 |   await page.getByLabel('来源平台').selectOption('other');
  126 |   await expect(page.locator('.resource-card')).toHaveCount(1);
  127 |   await expect(page.getByText('当前平台下暂无课程，可切换到全部平台。')).toBeVisible();
  128 |   await page.getByLabel('来源平台').selectOption('all');
  129 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  130 |   await page.screenshot({ path: testInfo.outputPath('desktop-fixture-results.png'), fullPage: true });
  131 | });
  132 | 
  133 | test('正常无结果区别于服务失败', async ({ page }) => {
  134 |   await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], total_matches: 0, items: [] }] });
  135 |   await page.goto('/?job=test-job');
  136 |   await expect(page.getByText('本次没有找到相关课程，试试调整知识点。')).toBeVisible();
  137 |   await expect(page.getByText('本次搜索未能完成，请稍后重试。')).toHaveCount(0);
  138 | });
  139 | 
  140 | test('全部服务失败不会降级为预设课程', async ({ page }) => {
  141 |   await setup(page, caps, { ...baseJob, status: 'failed', errors: [{ code: 'configuration_error', message: '搜索服务未配置' }] }, { ...results, status: 'failed', groups: [{ ...results.groups[0], total_matches: 0, items: [] }], search_attempts: [] });
  142 |   await page.goto('/?job=test-job');
  143 |   await expect(page.getByText('本次搜索未能完成，请稍后重试。')).toBeVisible();
  144 |   await expect(page.getByText('本次没有找到相关课程，试试调整知识点。')).toHaveCount(0);
  145 |   await expect(page.locator('.resource-card')).toHaveCount(0);
  146 |   await page.getByText('本次查找说明').click();
  147 |   await expect(page.locator('.task-records')).toContainText('搜索服务未配置');
  148 | });
  149 | 
  150 | test('部分失败保留结果、任务中断如实显示', async ({ page }) => {
  151 |   await setup(page, caps, { ...baseJob, status: 'partial', warnings: ['详情预算已达到限制'], errors: [{ code: 'search_unavailable', message: '一个搜索请求失败' }] }, { ...results, status: 'partial' });
  152 |   await page.goto('/?job=test-job');
  153 |   await expect(page.getByText('已找到以下课程，部分来源尚未完成核验。')).toBeVisible();
  154 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  155 |   await page.route('**/api/search-jobs/test-job', route => route.fulfill({ json: { ...baseJob, status: 'interrupted' } }));
  156 |   await page.reload();
  157 |   await expect(page.getByText('查找已中断，可重新提交；已找到的课程仍可查看。')).toBeVisible();
  158 |   await expect(page.getByRole('button', { name: '开始查找' })).toBeEnabled();
  159 | });
  160 | 
  161 | test('移动端无横向溢出，表单可用', async ({ page }, testInfo) => {
  162 |   await page.setViewportSize({ width: 390, height: 844 });
  163 |   await setup(page, { ...caps, search: { ...caps.search, status: 'unconfigured', message: '请先在服务端接入 SearXNG，或启用已配置的 Tavily。' } });
  164 |   await page.goto('/?mode=manual');
> 165 |   await expect(page.getByRole('heading', { name: '想学的知识，去哪里学？' })).toBeVisible();
      |                                                                    ^ Error: expect(locator).toBeVisible() failed
  166 |   await page.getByLabel('知识点', { exact: true }).fill('任意新知识点');
  167 |   await page.getByLabel('学习语言').selectOption('en');
  168 |   await expect(page.getByLabel('学习语言')).toHaveValue('en');
  169 |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  170 |   await page.screenshot({ path: testInfo.outputPath('mobile-empty.png'), fullPage: true });
  171 | });
  172 | 
  173 | test('请求出错明确显示错误', async ({ page }) => {
  174 |   await setup(page);
  175 |   await page.route('**/api/search-jobs', route => route.fulfill({ status: 503, json: { detail: '当前搜索服务不可用' } }));
  176 |   await page.goto('/?mode=manual');
  177 |   await page.getByLabel('知识点', { exact: true }).fill('任意新知识点');
  178 |   await page.getByRole('button', { name: '开始查找' }).click();
  179 |   await expect(page.getByRole('alert')).toContainText('当前搜索服务不可用');
  180 |   await expect(page.locator('.resource-card')).toHaveCount(0);
  181 |   await expect(page.getByRole('button', { name: '开始查找' })).toBeEnabled();
  182 | });
  183 | 
  184 | test('封面按来源图片展示，加载失败回退；点击入口保留原平台地址', async ({ page }) => {
  185 |   const coverUrl = 'https://images.example.org/isolated-cover.png';
  186 |   const brokenUrl = 'https://images.example.org/isolated-missing.png';
  187 |   const picture: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, title: '隔离封面图片 fixture', thumbnail_url: coverUrl } };
  188 |   const broken: ResourceItem = { ...picture, resource: { ...picture.resource, resource_id: 'broken-cover', title: '加载失败封面 fixture', thumbnail_url: brokenUrl } };
  189 |   const unsafe: ResourceItem = { ...picture, resource: { ...picture.resource, resource_id: 'unsafe-cover', title: '非法链接 fixture', url: 'javascript:alert(1)', thumbnail_url: 'javascript:alert(1)' } };
  190 |   await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], items: [picture, broken, unsafe] }] });
  191 |   // Images are isolated fixture responses, never external network reads.
  192 |   await page.route(coverUrl, route => route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=', 'base64') }));
  193 |   await page.route(brokenUrl, route => route.fulfill({ status: 404, body: 'fixture image unavailable' }));
  194 |   await page.goto('/?job=test-job');
  195 |   const cards = page.locator('.resource-card');
  196 |   await expect(cards.nth(0).locator('.course-cover img')).toHaveAttribute('src', coverUrl);
  197 |   await expect.poll(() => cards.nth(0).locator('.course-cover img').evaluate(image => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0)).toBe(true);
  198 |   await expect(cards.nth(0).locator('.course-cover img')).toHaveAttribute('referrerpolicy', 'no-referrer');
  199 |   await expect(cards.nth(0).locator('.course-cover')).toHaveAttribute('href', picture.resource.url);
  200 |   await cards.nth(1).scrollIntoViewIfNeeded();
  201 |   await expect(cards.nth(1).locator('.cover-placeholder')).toBeVisible();
  202 |   await expect(cards.nth(1).locator('.course-cover img')).toHaveCount(0);
  203 |   await expect(cards.nth(2).locator('.cover-placeholder')).toBeVisible();
  204 |   await expect(cards.nth(2).locator('a')).toHaveCount(0);
  205 |   await expect(page.locator('.chapter-list, .evidence-details, video, iframe')).toHaveCount(0);
  206 | });
  207 | 
  208 | test('目录仅用于最多两条知识点匹配章节，标题转义且不展示播放器或完整目录', async ({ page }, testInfo) => {
  209 |   const chapters: Chapter[] = [
  210 |     { title: '第一章：坐标转换', url: 'https://www.bilibili.com/video/BV_TEST_ONLY?p=35', evidence_id: 'c1', start_seconds: 65, duration_seconds: 2743 },
  211 |     { title: '坐标转换 <img src=x onerror=alert(1)>', url: null, evidence_id: 'c2' },
  212 |     { title: '坐标转换扩展章节', url: null, evidence_id: 'c3' },
  213 |     { title: '坐标转换非法直链', url: 'javascript:alert(1)', evidence_id: 'c4' },
  214 |     { title: '无关：矩阵乘法', url: null, evidence_id: 'c5' },
  215 |     { title: '坐标转换无逐行来源', url: null },
  216 |   ];
  217 |   const catalogItem: ResourceItem = { ...otherItem,
  218 |     resource: { ...otherItem.resource, title: '隔离课程 fixture', resource_type: 'course', metadata_evidence_level: 'catalog', chapters },
  219 |     match: { ...otherItem.match, topic_evidence_status: 'supported', supporting_evidence_ids: ['c1'] },
  220 |     evidence: chapters.slice(0, 5).map(chapterEvidence) };
  221 |   await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], text: '坐标转换', items: [catalogItem] }] });
  222 |   await page.goto('/?job=test-job');
  223 |   await expect(page.locator('.learning-location li')).toHaveText(['第一章：坐标转换', '坐标转换 <img src=x onerror=alert(1)>']);
  224 |   const chapterLink = page.locator('.learning-location a');
  225 |   await expect(chapterLink).toHaveCount(1);
  226 |   await expect(chapterLink).toHaveText('第一章：坐标转换');
  227 |   await expect(chapterLink).toHaveAttribute('href', 'https://www.bilibili.com/video/BV_TEST_ONLY?p=35');
  228 |   await expect(chapterLink).toHaveAttribute('target', '_blank');
  229 |   await expect(chapterLink).toHaveAttribute('rel', 'noopener noreferrer');
  230 |   await expect(page.locator('.learning-location li').nth(1).locator('a')).toHaveCount(0);
  231 |   await expect(page.locator('.learning-location img, a[href^="javascript:"]')).toHaveCount(0);
  232 |   await expect(page.locator('.resource-card')).not.toContainText('坐标转换扩展章节');
  233 |   await expect(page.locator('.resource-card')).not.toContainText('矩阵乘法');
  234 |   await expect(page.locator('.chapter-list, .evidence-details, video, iframe')).toHaveCount(0);
  235 |   await expect(page.locator('.course-cover')).toHaveAttribute('href', catalogItem.resource.url);
  236 |   await expect(page.locator('.resource-card h4 a')).toHaveAttribute('href', catalogItem.resource.url);
  237 |   await expect(page.locator('.course-cover')).toHaveAttribute('target', '_blank');
  238 |   await expect(page.locator('.course-cover')).toHaveAttribute('rel', 'noopener noreferrer');
  239 |   await page.screenshot({ path: testInfo.outputPath('matched-chapters-desktop.png'), fullPage: true });
  240 |   await page.setViewportSize({ width: 390, height: 844 });
  241 |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  242 |   await page.screenshot({ path: testInfo.outputPath('matched-chapters-mobile.png'), fullPage: true });
  243 | });
  244 | 
  245 | test('同课程在不同知识点分组只能展示当前组匹配章节', async ({ page }) => {
  246 |   const chapters: Chapter[] = [{ title: 'Python列表', evidence_id: 'list' }, { title: 'Python字典', evidence_id: 'dict' }];
  247 |   const course: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, title: 'Python基础', resource_type: 'course', chapters },
  248 |     match: { ...otherItem.match, topic_evidence_status: 'supported', supporting_evidence_ids: ['list', 'dict'] }, evidence: chapters.map(chapterEvidence) };
  249 |   await setup(page, caps, baseJob, { ...results, groups: [
  250 |     { ...results.groups[0], text: 'Python 列表', items: [course] },
  251 |     { ...results.groups[1], text: 'Python 字典', items: [{ ...course, match: { ...course.match, knowledge_point_id: 'kp2' } }] },
  252 |   ] });
  253 |   await page.goto('/?job=test-job');
  254 |   await expect(page.locator('.result-group').nth(0).locator('.learning-location li')).toHaveText(['Python列表']);
  255 |   await expect(page.locator('.result-group').nth(1).locator('.learning-location li')).toHaveText(['Python字典']);
  256 | });
  257 | 
  258 | test('目录逐行身份和数值校验拒绝交叉引用、篡改与非法时长', async ({ page }) => {
  259 |   const chapters: Chapter[] = [
  260 |     { title: '坐标转换有效未知字段章节', evidence_id: 'strict-0', url: null, start_seconds: null, end_seconds: null, duration_seconds: null },
  261 |     { title: '坐标转换有效零起点章节', evidence_id: 'strict-1', start_seconds: 0, end_seconds: 0, duration_seconds: 1 },
  262 |   ];
  263 |   const records = chapters.map(chapterEvidence);
  264 |   // Missing and explicit null are equivalent unknowns in either direction.
  265 |   records[0].text = JSON.stringify({ title: chapters[0].title });
```