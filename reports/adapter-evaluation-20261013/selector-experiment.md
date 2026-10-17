# Selector 离线实测与采用决定

本文件是 `tool-research.md` 初始只读研究之后获得授权的独立实验记录，保留原研究中“未安装/未运行”的时间事实，不覆盖为过去已完成。实际执行时间见下方及原始 JSON。

实验开始：2026-10-13T10:57:42.887036+00:00；完成：2026-10-13T10:57:43.777973+00:00。Python 3.13.5 / Windows，独立系统临时 venv。

结论：**本轮继续使用 BeautifulSoup，加模块化语义适配；不增加 Scrapling 生产依赖。** 在四份固定 HTML 的等价 selector/attribute 对照里，Scrapling 没有新增字段，虽然微基准更快。该结论只适用于解析层，不是采集框架、网络成功率或课程覆盖率比较。

| 文档角色 | BS4 中位毫秒 | Scrapling 中位毫秒 | BS4 / Scrapling | 输出 |
| --- | ---: | ---: | ---: | --- |
| course_home | 14.2513 | 1.9762 | 7.21 | 相同 |
| video_catalog | 18.2331 | 2.9315 | 6.22 | 相同 |
| video_chapter | 15.4306 | 2.2615 | 6.82 | 相同 |
| video_collection | 37.7936 | 5.1945 | 7.28 | 相同 |

每个解析器每份文档一次非计时预热，随后 7 次计时；奇偶轮交替执行顺序。计时包括创建 DOM、相同 CSS 查询、属性/文本提取与同一标准库 playlist JSON 解码；不包含导入、磁盘读取或 SHA 校验。每次输出哈希稳定，四份全部等价，新增非空字段 0。7 次全部原始时延及输出哈希保存在 `selector-comparison.json`，没有隐藏失败运行或只取最快值。

输入严格取 `sample-manifest.json` 的四项，逐项 SHA-256 与字节数核验；未增添课程页面。它们来自 2 个站点，但只有 1 个 SICP 课程家族，不能把 20/21 个章节算成 41 门课程或多领域泛化。

两组均提取到相同 meta 标题/简介、MIT 课程教师、视频页章描述、MIT 20 条目录标题及 href、Archive 21 条 playlist 标题和实际 JSON 属性。此处是原始 selector 结果等价，并非把所有命中视为业务字段正确：例如 `.course-info-instructor` 包含桌面/移动重复 DOM（6 项，对应 3 个名字），Archive 全局 `title` 也包含 SVG 图标标题（17 项）。对应产品字段仍需来源语义选择、去重和证据绑定，不能依靠更换解析器自动纠正。

`Selector(adaptive=False, huge_tree=False)`；只导入 parser，不导入 Scrapling fetcher、browser 或本应用模块。比较进程安装 Python audit hook 拒绝 socket/DNS/子进程事件；记录为 0 次。HTML 中的链接、图片、脚本仅作为数据，不执行、不跟随。本实验不是 OS 级网络沙箱，也不是第三方传输安全证明。

依赖均从显式官方 `https://pypi.org/simple` 解析，`selector-requirements.lock` 固定全部 9 个版本及哈希，安装使用 `--require-hashes`。原始 Scrapling wheel 的 hash 与研究阶段 PyPI 官方记录相同。`selector-installed-versions.txt` 记录实际版本；实验仅修改临时 venv 与本报告目录，没有向项目 pyproject/uv.lock 或生产 `.venv` 安装包。

复现（PowerShell，在项目根目录）：

```powershell
$evalDir = Join-Path ([System.IO.Path]::GetTempPath()) ('knowledge-sprite-selector-eval-' + [guid]::NewGuid().ToString('N'))
uv venv --no-config --python 3.13 $evalDir
$evalPython = Join-Path $evalDir 'Scripts/python.exe'
uv pip install --no-config --python $evalPython --default-index https://pypi.org/simple --require-hashes -r reports/adapter-evaluation-20261013/selector-requirements.lock
& $evalPython reports/adapter-evaluation-20261013/compare_selectors.py
```

脚本输出会写同名比较结果；如需留存本次历史，应先把报告目录复制到新的复现目录再运行，保持 manifest 的项目根路径解析一致。每次产生的耗时会因机器负载不同而变化，输出等价/来源哈希才是此对照的主要检验项。

Crawlee 未安装、未运行、未接入生产；其自定义 HTTP 接口与安全传输复审结论仍停留在研究层。当前实测只把 Scrapling 纯解析组件的 Windows/Python 3.13 运行与固定输入等价性由 unknown 更新为已测，不延伸到所有依赖平台、全部 HTML 或联网路径。
