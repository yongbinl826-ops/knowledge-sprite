# Android 原生工程与可验证边界

本工程使用 Capacitor Android 原生容器和原生插件，不是只交付一个响应式网址。应用标识为 `dev.knowledgeguide.sprite`，名称为“项目制学习引导小精灵”。页面资产放在包内；`server.url`、任意 `allowNavigation` 和远程整页加载均未开启。当前 Windows 环境没有可用 JDK/SDK，未生成 APK/AAB、未安装到手机，也未编译 iOS。

## 依赖与原生工具

官方 npm registry 查询和 package-lock 均精确锁定：core/android/cli **8.5.3**，preferences **8.0.1**，browser **8.0.5**，app **8.1.2**。公开 tarball 地址与 integrity 保存在本轮验证材料及锁文件，Gradle wrapper 的官方 SHA256 写入 wrapper 配置。没有执行 npm 安装脚本，没有下载 Gradle 发行包、Android SDK 或接受新许可。

Capacitor v8 的 Node 要求为22+；本次实际 Node24.14.0/npm11.9.0。官方 Android 流程需要 Android Studio/SDK；生成模板和已安装 Android 插件声明 minSdk24、compile/targetSdk36、Java21、AGP8.13.0、Gradle8.14.3。环境路径核实与编译原文见 [工具链检查](validation/mobile-concepts-20261020/native-toolchain-preflight.json)、[离线编译记录](validation/mobile-concepts-20261020/android-unsigned-build-attempt.log)。PATH 没有 java/javac/adb/emulator/gradle，既有 JAVA_HOME/Android SDK 路径均不存在；离线编译在 Gradle 启动前以失效 JAVA_HOME 退出1。未修改这些全局设置。[Capacitor Android](https://capacitorjs.com/docs/android)、[环境要求](https://capacitorjs.com/docs/getting-started/environment-setup)。

## 构建与同步

在 `frontend` 目录使用现有 Node：

```powershell
npm ci --ignore-scripts --no-audit --no-fund
npm run mobile:test
npm run build:mobile:debug -- --api-base http://127.0.0.1:8017
npm run mobile:check
```

`build:mobile:debug` 编译到 **dist-mobile** 并执行 `cap sync android`。默认 `npm run build` 仍是旧网页的 `dist`，不得用移动包覆盖现有网页。移动脚本不加载 `.env`，Vite 自动公开环境变量前缀被关闭，仅显式编译 `VITE_DEVICE_MODE=true`、API 基址和 `VITE_MOBILE_DEBUG_LOOPBACK`。后者在debug为true、release为false，独立于Vite production构建始终为false的DEV标记。构建凭据扫描报告规则名和路径，不回显命中内容；这是有限模式检查，不是万能密钥检测。

最终设备前端已合并并重新构建、同步为本机8017调试资产。父课程语境修复后的实际ASGI回归使用相同前端/原生源码的独立8937测试基址和合成供应商；测试端口已关闭，本地应用使用8017。两种构建的API基址、源码及资产SHA分别有收据，不能把测试基址构建当作发布包。`dist-mobile`、Android public assets、cap config/plugin JSON、Cordova桥接模块是生成物；资产与源码一致并不表示 Java 已编译或手机已安装。同步调试构建时应使用本脚本或明确 `MOBILE_BUILD_KIND=debug`，不要裸跑 `cap sync` 覆盖已验证的调试配置。

开发 HTTP 例外仅允许 localhost、127.0.0.1、::1，Android debug 专用 network-security-config 以外仍默认拒绝明文；debug 资产仅用于调试，禁止作为 release。手机的127.0.0.1指手机本身；未来使用 Android USB 调试时可显式建立 adb reverse 到开发服务，本次未执行。没有全局 cleartext、LAN/IP wildcard、用户CA信任或任意导航豁免。

## 发布门槛

```powershell
# 仅在已有明确的真实部署HTTPS域名后，替换此处变量。
$env:VITE_API_BASE_URL = '<用户给定的HTTPS API origin>'
npm run build:mobile
npm run mobile:check
```

当前没有提供部署域名，因此运行 `build:mobile` 会以固定代码 `mobile_api_base_required` 退出2，且不会开始新的资产编译。发布基址必须是 HTTPS 公共域名 origin，拒绝 credentials、路径、query、fragment、localhost/IP和占位域名。构建验证语法与配置，不声称已验证服务器可达、TLS或后端授权。

准备完成后可在已配置 Java21/SDK36 的机器上打开 `frontend/android`。`mobile-release-gate.gradle` 会在 release 构建前核对 release receipt、API origin、native config、lock/config SHA、src全量清单及vite/index/tsconfig源文件SHA、每个包内资产SHA和确切资产清单（包括sync生成的Cordova桥接stub），禁止额外旧文件，拒绝陈旧或debug/远程WebView资产。debug/release 均设置 `signingConfig null`，避免自动生成持久 debug/release keystore。因此即使将来完成编译，产物也仍是 unsigned，**编译、签名、安装、商店发布是不同状态**；签名和安装需要后续用户控制，本次没有创建任何签名材料或商店账户。

## 本机记录与系统行为

Preferences 的Android实现虽使用SharedPreferences，但8.0.1的set调用apply()，立即完成Promise不能证明POST之前已落盘。因此关键记录改由本地`DurableDeviceStore`插件处理，使用独立私有SharedPreferences命名空间`KnowledgeSpriteDevice`。仅暴露get/set：key限`knowledge-sprite.device.`前缀、最长256字符且无控制符；值限UTF-8 10MiB。get返回value为null或string；set在Bridge现有worker上调用commit()，只有返回true才resolve `{committed:true}`；false/异常固定拒绝且不回显数据。前端必须等待成功，失败不得fallback或继续POST。未混用官方Preferences.apply，也不读旧CapStorage。MainActivity在super.onCreate之前注册插件，避免v8.5.3创建Bridge后注册失效；没有额外线程池或executor。

这是轻量KV而非加密数据库；卸载清除数据。不保存供应商API密钥，也不提供账号、云同步或导入导出。commit返回语义来自Android API；本轮没有可用JDK/设备，不能把源审和JS mock说成真实断电/进程kill持久化通过。[Preferences](https://capacitorjs.com/docs/apis/preferences)、[Android commit](https://developer.android.com/reference/android/content/SharedPreferences.Editor#commit())。

Manifest 设置 `allowBackup=false`。旧版 `fullBackupContent` 和 Android12+ `dataExtractionRules` 排除 root/file/database/sharedpref/external 及对应 device 域；cloud-backup、device-transfer、cross-platform-transfer 均排除全部这些域，避免把 Preferences/WebView记录或待恢复能力信息经OS云备份或迁移转出。Android不同版本/OEM仍需真机复核，静态XML不等于系统执行结果。[Android Auto Backup](https://developer.android.com/identity/data/autobackup)。

Browser 插件使用 Android 浏览器支持的 Custom Tabs；网页跳转前仍需 frontend 的 HTTPS/source URL 校验，不给 WebView 添加导航白名单。App 插件供返回键、resume/后台恢复使用，frontend 负责其业务逻辑；本工程没有宣称原生按钮/持久化/后台恢复已在设备上验证。[Browser](https://capacitorjs.com/docs/apis/browser)、[App](https://capacitorjs.com/docs/apis/app)。

WebView 的本地origin为 `https://localhost`，后端必须明确允许这个来源并按设备模式执行真实的访问隔离/能力校验；Origin和设备自报头本身不是认证。原生包内不放供应商密钥，不远程加载整份前端。

## 原生图标与启动页

默认Capacitor模板图标/启动位图已替换为原创手写书本vector，使用墨黑、暖白和蓝点。API24普通图标与API26+ adaptive图标、启动主题均引用这一标识；没有使用外部图片或模型。静态XML可解析，但未将其声称为Android设备实际启动观感。

## 本轮证据与剩余阻碍

- 已通过：6组离线配置/实际Vite production flag编译/陈旧源码与额外chunk测试（含多个边界断言）、TS/Vite移动构建、3个官方插件的sync注册清单、本地durable插件注册/commit源合同与 `cap sync android`、XML/SDK/asset SHA/有限密钥模式检查。
- 已证明拒绝：缺发布HTTPS域名时退出2；原生离线编译因失效JAVA_HOME退出1。
- 未验证：Gradle实际编译/manifest合并、真机安装、原生DurableDeviceStore commit失败/跨重启/kill恢复/卸载、返回键/安全区/外部浏览器/断网恢复、OEM备份行为。它们需要可用JDK/SDK、设备与明确部署服务条件。
- 交付源码、锁文件、本地 Web 的dist与独立调试dist-mobile及已同步原生资产；不交付 node_modules、cache、.gradle、build、local.properties、keystore、APK/AAB。移动资产为debug，不能当作release。开发者也可从锁文件重新恢复依赖、构建和同步。

Windows未生成iOS项目或声称完成iOS编译；若目标包含iOS，需另行在macOS/Xcode环境建立并验收，Preferences也需对应Apple隐私清单。
