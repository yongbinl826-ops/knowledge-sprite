# Android 移动界面验收记录（2026-10-21）

**状态：本轮范围内的 Android 模拟器 UI 复验通过，保留已知非阻断日志问题。** 当前源码快照已完成隔离构建、实际 APK 安装、三页布局、键盘输入、来源筛选、320 dp 窄屏和离线进程重启验证。最终只读源码核对时间为 **2026-10-21 11:39:36（北京时间）**；结论针对该时点匹配的测试 APK，不覆盖之后的源码变化。

## 版本与证据边界

- 首个测试 APK：`knowledge-sprite-qa.apk`，SHA-256 为 `6006939e51f042f1ded090ff52d4bad905eba324cdde985daf2f8d8b0a5c1a17`，4,190,497 字节。
- APK 内移动资产构建时间：2026-10-21 10:34:55（北京时间）；打包产物预检时间：10:47:47。
- 当时 55 个源码文件哈希、7 个打包资产清单及哈希全部匹配。完整源码收据保存在 [tested-apk-source-receipt.json](../../evidence/android-ui-20261021/results/tested-apk-source-receipt.json)。
- 后续恢复记录明确指出 `src/relatedRecommendations.ts` 已相对首个测试 APK 发生变更，因此保留首轮历史证据，另行隔离重建并完成下节复验，没有将旧 APK 结果直接替代新版本验收。
- 测试 APK 的 API 为 `http://127.0.0.1:18027`，仅连接本轮本地 QA 服务，`releaseEligible=false`。11:11 的恢复记录载明工作树移动构建 API 已恢复为 `http://127.0.0.1:8017`；这是恢复时点的记录，不替代当前工作树核验。见 [restored-build-state.json](../../evidence/android-ui-20261021/results/restored-build-state.json)。
- 本轮 QA 没有修改产品源代码。测试辅助内容包括合成数据服务、ADB 操作脚本、截图及验收文档；不交付发布签名或发布 APK。

## 恢复后的隔离复验（最终）

用户要求继续后，执行方在 `C:\Users\xiaoer\AppData\Local\Temp\android-qa-20261021\resume-1122\frontend` 保存源码快照并独立构建，没有写入演示目录的页面资产或 API 配置。[source-snapshot.json](../../evidence/android-ui-20261021/resume-1122/results/source-snapshot.json) 记录快照时间与文件哈希。

- 与推荐展示／页面证据相关的现有测试 **11 项通过，0 失败**：[recommendations-tests.tap](../../evidence/android-ui-20261021/resume-1122/logs/recommendations-tests.tap)。
- 新一轮移动配置检查 **6 项通过，0 失败**，补齐了独立输出：[mobile-config-tests.tap](../../evidence/android-ui-20261021/resume-1122/logs/mobile-config-tests.tap)。
- 隔离 `:app:assembleDebug` 成功，127 个任务全部执行；[构建日志](../../evidence/android-ui-20261021/resume-1122/logs/gradle-build.log) 与首个 APK 的日志分别归档。
- 新测试 APK 的 SHA-256 为 `18e3fbb7fc4075459e37e81a4f33a1ca81e394f27b9460fafcf757f9a95f4f53`。其 26 项静态检查通过，55 个源码文件与 7 个打包资产精确匹配隔离收据；只读比较实时工作树源码、lock 与 Capacitor 源配置，检查时点差异为 0。见 [新 APK 预检](../../evidence/android-ui-20261021/resume-1122/results/apk-preflight.json) 与 [新源码收据](../../evidence/android-ui-20261021/resume-1122/results/tested-apk-source-receipt.json)。
- 新 APK 的构建 API 仍为本地合成 QA 地址 18027，不能作为发布包。复验使用本机已保存的合成结果，没有重启 fixture 服务。**7 个原生来源／知识点筛选组合全部通过**，见 [新筛选结果](../../evidence/android-ui-20261021/resume-1122/results/native-filter-results.json)；三页切换见 [current-layout-results.json](../../evidence/android-ui-20261021/resume-1122/results/current-layout-results.json)。
- 320 dp 三页、表单底部主按钮和键盘输入复验通过：[current-input-narrow-results.json](../../evidence/android-ui-20261021/resume-1122/results/current-input-narrow-results.json)。独立看图复核确认大幅宣传标题隐藏、无明显横向裁切或控件重叠、表单底部主按钮完整；知识点页底部操作不在该截图视口内，不扩展为全页视觉保证。见 [current-visual-review.json](../../evidence/android-ui-20261021/resume-1122/results/current-visual-review.json)。
- 离线进程重启复验通过：PID **1727 → 5697**，项目及 **5 张卡片**恢复，fixture 新 HTTP 请求 **0**，crash buffer 为空；见 [新重启结果](../../evidence/android-ui-20261021/resume-1122/results/native-restart-results.json)。
- 新 APK 安装启动后，模拟器出现 Android `System UI isn't responding` 系统对话框，遮挡首次复验；执行方确认应用 PID 1727 仍存在、当次 crash buffer 为空，从新 UI XML 定位 `Wait` 按钮后已恢复，三页切换成功。ActivityManager 同时记录 `com.android.phone`、`com.google.android.gms.persistent`、`com.google.android.as`、`com.google.android.inputmethod.latin` 的启动 ANR；尚无本应用 ANR 证据，不能将上述事件归因于本应用，也不能据此认定应用完全无异常。
- 新 APK 的首轮筛选复验被 `uiautomator null root` 中断，没有产生筛选断言失败；随后重新 dump 取得正常来源菜单。临时 QA helper 增加最多 2 次只读 dump 重试并保留失败 raw 输出，筛选重跑已完成。另一次 320 dp 取证因 QA 脚本缺少 swipe helper 参数报错，修正脚本后重跑通过；该报错不是产品断言失败。
- 重新进入输入框后，键盘截图经独立看图复核为真实弹出，`dumpsys` 的 `mInputShown=true`；输入 `Q` 后 UI XML 出现 `Android UI QAQ`，删除 `Q` 后恢复原值。[键盘截图](../../evidence/android-ui-20261021/resume-1122/screens/keyboard-recheck.png)、[输入后截图](../../evidence/android-ui-20261021/resume-1122/screens/keyboard-entered.png)、[恢复值 XML](../../evidence/android-ui-20261021/resume-1122/screens/keyboard-restored.xml) 已归档。

收尾于 11:39:36 再次只读核对：55 个源码文件、package-lock、Capacitor 源配置均与新 APK 收据匹配，7 个包内资产也匹配，差异为 0。[final-workspace-comparison.json](../../evidence/android-ui-20261021/resume-1122/results/final-workspace-comparison.json) 保存精确时点。此结论不能覆盖随后发生的工作树变更。

## 测试环境与数据

| 项目 | 本轮环境 |
| --- | --- |
| 应用 | `dev.knowledgeguide.sprite`，启动 Activity 为 `.MainActivity` |
| Android | 真实启动的 Android 模拟器，Android 15 / API 35，Pixel 7 |
| 标准屏幕 | 1080 × 2400，420 dpi（约 411 dp 宽） |
| 窄屏复核 | 840 × 1680，420 dpi，即 320 dp 宽 |
| WebView | 124.0.6367.219 |
| 编译目标 | compile SDK 36、target SDK 36、min SDK 24 |
| 工具 | 完整 JDK 21、Gradle 8.14.3、AGP 8.13.0、Android SDK 工具 |
| 测试项目 | `Android UI QA`，知识点“表单输入”“会话状态管理” |

所有课程数据均为 **QA 合成数据**，标题明确带 `[QA合成]`。课程 URL 使用 `example.invalid`，未点击外部链接。没有调用真实模型、真实课程检索、个人业务数据库或真实播放；合成的页面证据字段只用于通过组件正常的展示资格校验，不代表已抓取或核实真实课程。缩略图缺省，验证的是产品自带占位封面。

## 已完成的首个 APK 验收

| 检查 | 结果及证据 |
| --- | --- |
| 设备存储／任务／上下文自动检查 | 34 项通过，0 失败；[TAP](../../evidence/android-ui-20261021/logs/device-unit-tests.tap)、[命令记录](../../evidence/android-ui-20261021/results/device-unit-tests-run.json) |
| 移动配置自动检查 | 首轮执行方确认 6 项通过；后续隔离复验重新运行并归档 6 项通过的输出，见上节，不与首轮 34 项 TAP 混为一份记录 |
| `mobile:check` | 通过；归档的是 API 恢复后的静态检查记录，[mobile-check-restored.log](../../evidence/android-ui-20261021/logs/mobile-check-restored.log)，该脚本本身不执行原生代码 |
| 原生编译 | `:app:assembleDebug` 成功，127 个任务（120 执行、7 个已更新），[gradle-build.log](../../evidence/android-ui-20261021/logs/gradle-build.log) |
| APK 预检 | 26 项通过；应用 ID、SDK 级别、资产收据及网络配置从实际 APK 读取，[apk-preflight.json](../../evidence/android-ui-20261021/results/apk-preflight.json) |
| 三页移动布局 | 大幅宣传标题、英文页编号、背景大数字不显示；保留实际操作区、三步导航、知识点与来源选择 |
| 320 dp 窄屏 | 三页截图未见横向裁切；项目表单主按钮经正常向下滚动可达；这不表示长表单所有控件同时处于首屏 |
| 输入与知识点选择 | 可输入并切换知识点勾选；软键盘真实显示另由隔离复验的独立截图补证 |
| 来源／知识点组合 | 7 个原生界面组合通过，详见下表及 [native-filter-results.json](../../evidence/android-ui-20261021/results/native-filter-results.json) |
| 离线进程重启 | 移除本轮 API 的 ADB 反向转发后 force-stop 并重新启动，PID 6162 → 6303；项目与 5 张课程卡恢复，QA 服务新请求数 0，[native-restart-results.json](../../evidence/android-ui-20261021/results/native-restart-results.json) |
| Android 返回键 | 结果页 → 知识点页 → 项目描述页；输入保留，有 `native-back-stage-2/1` 截图和 XML |
| 崩溃检查 | 此次检查的 crash buffer 为空；不是对所有设备、所有生命周期或所有错误日志的完整保证 |

APK 内 `server.url`、`allowNavigation` 均未设置；本地 WebView origin 为 `https://localhost`；`webContentsDebuggingEnabled=false`。调试网络配置仅对 `localhost`、`127.0.0.1`、`::1` 放行明文，其余默认拒绝。调试 APK 的 Android `debuggable=true`，不能把这个属性与 WebView 调试配置混为一谈。

### 原生来源筛选结果

| 知识点 | 来源 | 实际卡片数 | 结果 |
| --- | --- | ---: | --- |
| 全部 | 全部 | 5 | 通过 |
| 全部 | B站 | 3 | 通过 |
| 全部 | MOOC | 2 | 通过 |
| 表单输入 | MOOC | 1 | 通过，切换知识点后保留来源选择 |
| 表单输入 | 学堂在线 | 0 | 通过，显示“该来源暂无视频，可切换其他来源。” |
| 表单输入 | 全部 | 3 | 通过 |
| 会话状态管理 | 全部 | 2 | 通过 |

计数来自 Android UI XML 中的课程标题节点，而非凭截图估算。ADB 点击先取最新 UI tree，按精确文本、类名等定位并从节点 bounds 计算中心；未使用截图猜坐标。

### 关键截图

以下为首个 APK 的真实模拟器截图，不是设计图。新 APK 的最终截图另列其后，避免混用版本。

| 页面或行为 | 截图 |
| --- | --- |
| 320 dp 项目描述 | [narrow-stage-1.png](../../evidence/android-ui-20261021/screens/narrow-stage-1.png) |
| 320 dp 表单底部操作 | [narrow-stage-1-bottom.png](../../evidence/android-ui-20261021/screens/narrow-stage-1-bottom.png) |
| 320 dp 知识点选择 | [narrow-stage-2.png](../../evidence/android-ui-20261021/screens/narrow-stage-2.png) |
| 320 dp 视频列表与筛选 | [narrow-stage-3.png](../../evidence/android-ui-20261021/screens/narrow-stage-3.png) |
| 原生来源菜单 | [source-menu.png](../../evidence/android-ui-20261021/screens/source-menu.png) |
| MOOC 结果 | [stage-3-mooc.png](../../evidence/android-ui-20261021/screens/stage-3-mooc.png) |
| 来源无结果 | [stage-3-empty.png](../../evidence/android-ui-20261021/screens/stage-3-empty.png) |
| 离线重启恢复 | [offline-restart.png](../../evidence/android-ui-20261021/screens/offline-restart.png) |

新 APK 的最终截图：[项目描述](../../evidence/android-ui-20261021/resume-1122/screens/narrow-stage-1.png)、[表单底部按钮](../../evidence/android-ui-20261021/resume-1122/screens/narrow-stage-1-bottom.png)、[知识点选择](../../evidence/android-ui-20261021/resume-1122/screens/narrow-stage-2.png)、[视频与来源筛选](../../evidence/android-ui-20261021/resume-1122/screens/narrow-stage-3.png)、[恢复标准尺寸后的列表](../../evidence/android-ui-20261021/resume-1122/screens/current-standard-final.png)、[离线重启](../../evidence/android-ui-20261021/resume-1122/screens/offline-restart.png)。每张均保留同名 UI XML。

## 已知日志问题与未覆盖项

启动日志存在 `Error injecting safe area CSS: TypeError: Cannot read properties of null (reading 'style')`。执行方定位到 Capacitor 的 `SystemBars.java` 启动注入，读取 `document.documentElement.style` 时文档元素暂为空。本轮截图未见相关布局受影响，作为**非阻断的启动日志问题**保留；未修改依赖，也不宣称零 JavaScript 错误。

| 进程 | 安全区域 CSS consoleError | Chromium 缓存错误 | `Seed missing signature` |
| --- | ---: | ---: | ---: |
| 首轮 PID 6162 | 1 | 0 | 1 |
| 首轮重启 PID 6303 | 0 | 0 | 1 |
| 新 APK PID 1727 | 3 | 4 | 1 |
| 新 APK 重启 PID 5697 | 1 | 0 | 1 |

四份应用日志中 `FATAL EXCEPTION` 行数均为 0，采集的 crash buffer 为空；这与存在上述 consoleError 并不矛盾。系统界面卡住和系统进程启动 ANR 的根因仍为 `unknown`，尚未诊断；捕获的 ActivityManager 摘要未包含本应用 ANR。见 [脱敏日志摘要](../../evidence/android-ui-20261021/resume-1122/results/sanitized-log-summary.json) 与 [环境 ANR 摘要](../../evidence/android-ui-20261021/resume-1122/logs/environment-anr-summary.log)。不将系统包 ANR 归因于产品，原始 console 值日志不进入归档。

离线恢复只证明本轮测试应用在一次 force-stop／进程重启后能读取已保存项目和结果；不证明断电、存储写满、损坏恢复、卸载恢复、所有 OEM 备份策略或长期持久性。没有验收发布构建、真实手机、iOS、其他 WebView 版本、真实课程封面、外部浏览器跳转、课程播放、真实网络服务或性能基准。

## 复现说明

以下命令是复现指引；本次归档过程没有执行设备、服务、构建或页面资产配置操作。应使用独立 QA 目录和隔离的前端副本，避免修改正在使用的产品包。归档脚本是本轮现场快照，其中筛选／重启脚本使用 `emulator-5556` 和脚本目录下的 SDK；回放时需按实际目录和设备序列号调整。

1. 在隔离前端副本准备依赖，并使用显式 QA 地址构建移动资产；配置完整 JDK 21 / SDK 36，再执行 Gradle。

   ```powershell
   # 在隔离 frontend 副本内执行
   npm run build:mobile:debug -- --api-base http://127.0.0.1:18027
   npm run mobile:test
   npm run mobile:check
   node --experimental-transform-types --test --test-reporter=tap tests/device-storage.test.mjs tests/device-tasks.test.mjs tests/device-reviewed-context.test.mjs
   Set-Location android
   .\gradlew.bat :app:assembleDebug --console=plain
   ```

   `mobile:check` 在编译前执行；它会拒绝 Android 工程目录中已有的 APK／签名材料。工程默认输出未签名 APK，安装前使用临时 QA 签名；不改产品签名配置，不复制已有发布密钥。

2. 将归档的 `scripts` 中 QA 文件复制到独立运行目录，运行本地合成数据服务；服务仅监听 127.0.0.1:18027。安装本轮签名的 QA APK 后反向转发该端口并启动应用。

   ```powershell
   $qaRoot = 'C:\Users\xiaoer\AppData\Local\Temp\android-qa-20261021'
   $adbPath = Join-Path $qaRoot 'sdk/platform-tools/adb.exe'
   $qaSerial = 'emulator-5556'
   # 服务需在单独的终端运行；这些命令会操作专用 QA 设备。
   python (Join-Path $qaRoot 'fixture_server.py')
   # 另一终端：
   & $adbPath -s $qaSerial install -r (Join-Path $qaRoot 'knowledge-sprite-qa.apk')
   & $adbPath -s $qaSerial reverse tcp:18027 tcp:18027
   & $adbPath -s $qaSerial shell am start -n dev.knowledgeguide.sprite/.MainActivity
   ```

3. 正常填写项目、确认知识点并进入视频页。合成课程标题均带 `[QA合成]`。使用 UI tree 驱动操作和取证；不点击 `example.invalid` 链接。

   ```powershell
   $helperPath = Join-Path $qaRoot 'adb_qa.py'
   python $helperPath --adb $adbPath --serial $qaSerial capture stage-1
   python $helperPath --adb $adbPath --serial $qaSerial summary
   python $helperPath --adb $adbPath --serial $qaSerial tap --text '视频来源'
   python $helperPath --adb $adbPath --serial $qaSerial tap --text 'MOOC' --class android.widget.CheckedTextView
   python $helperPath --adb $adbPath --serial $qaSerial capture stage-3-mooc
   ```

   helper 先等待可读取的 UI tree 再截图；PNG 使用 subprocess 二进制输出保存。`input` 仅支持明确的 ASCII 文本，非 ASCII 输入会报错，不静默替换。多节点匹配必须提供显式索引。

4. 筛选脚本从“全部知识点／全部来源”的视频页开始，依次验收表中 7 个组合。重启脚本会移除 QA 端口反向转发、force-stop 并重新启动专用 QA 应用，校验项目、课程及请求计数。不要用于存有个人数据的其他应用。

   ```powershell
   python (Join-Path $qaRoot 'native_filter_check.py')
   python (Join-Path $qaRoot 'native_restart_check.py')
   ```

## 证据归档与收尾

证据位于 [evidence/android-ui-20261021](../../evidence/android-ui-20261021)。原始归档含 18 组 PNG/XML、结果 JSON、测试 TAP、Gradle 日志及测试脚本；原始 50 文件的哈希在 [evidence-manifest.json](../../evidence/android-ui-20261021/evidence-manifest.json)。恢复工作时逐项复核这 50 个文件，均未变化。后续补充内容单独生成 manifest，不改写旧 APK 预检结果。

归档不包含 SDK、JDK、AVD、APK、keystore、原始 console 值日志、完整 ADB 命令日志、请求认证值或原生存储内容。测试脚本可能包含认证协议处理逻辑，但没有归档实际认证凭据。

新 APK 的最终结果、截图、独立视觉复核、脱敏日志、6 项配置测试、输入窄屏脚本及包含 dump 重试的 helper 均已归档。最终文件清单和哈希见 [evidence-manifest-final.json](../../evidence/android-ui-20261021/evidence-manifest-final.json)；较早的 `continued` manifest 是复验中间状态快照，保留作过程记录。

专用 QA 模拟器已通过 `emu kill` 正常关闭，后续范围内进程检查无残留；共享 ADB 服务保留。恢复复验没有重启 fixture，未调用、重启或改写 8001 服务及演示页面资产配置。见 [cleanup-results.json](../../evidence/android-ui-20261021/resume-1122/results/cleanup-results.json) 和 [emulator-shutdown.log](../../evidence/android-ui-20261021/resume-1122/logs/emulator-shutdown.log)。
