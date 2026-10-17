# B站与 MOOC：条款、robots 与应用停采原因核查

审查日期：**2026-10-17**。只用 web 工具各读取现有官方条款和 robots 两个 URL，共 4 个 URL、无重试。没有请求课程详情、平台 API 或媒体，没有浏览器操作、生产代码/数据库写入或历史报告修改。

## 核查结果

| 项目 | B站 | 中国大学 MOOC |
|---|---|---|
| 当前代码记录 | `explicit_permission_required`，审查日 2026-10-13 | `unreviewed_permission_scope`，审查日 2026-10-13 |
| 当前配置下离线策略判断 | `site_policy_blocked` | `policy_unreviewed` |
| 本次官方条款读取 | 仅标题，正文 0 行；未重新取得条款正文 | 正文可读，显示生效/更新日 2021-07-16 |
| 本次 robots 读取 | 可读，仅列两条禁止路径 | 工具返回不可访问，未提供 HTTP 状态 |
| 本次课程页 HTTP/浏览器/目录 | 均未核验，由主任务另行记录 | 均未核验，由主任务另行记录 |

当前实际常量名为 `PLATFORM_POLICY_REVIEWS`，判断在 `Fetcher._site_policy`。`allowed_restricted_hosts=[]`，两个平台均会在应用发出详情请求前停止。这个状态**不是本次课程页被服务器拒绝的证据**。离线策略调用没有联网。

## B站

2026-10-13 的历史官方域检索审查记录将 [用户使用协议](https://www.bilibili.com/blackboard/protocal/licence.html) 第 **5.6(3)** 条归纳为：自动取得平台服务、内容或数据须事先取得明确书面许可；记录中的版本日期为 **2025-04-30**，项目没有该许可记录。此次 web 直开只有协议标题和 0 行正文，故**不能声称今天重新核验了该条正文或版本日期**。当前停采依据是保留的历史条款审查与应用策略，并非今天观察到的 403、验证码或登录墙。历史来源：`reports/catalog-probe-policy-review-20261013.json`。

本次 [robots.txt](https://www.bilibili.com/robots.txt) 的可读规则为：

```text
User-agent: *
Disallow: /medialist/detail/
Disallow: /index.html
```

这份规则没有禁止所有 `/video/` 路径；它也不能替代条款许可。工具未暴露原始 HTTP 状态，不能据此填写本次 HTTP 200。

## 中国大学 MOOC

本次读取的 [官方用户服务协议](https://www.icourse163.org/topics/mooc_privacy_service/) 正文显示 **2021-07-16** 生效并更新。第 **3.1** 条描述可“浏览课程信息”，观看、学习课程需登录；第 **5.2.7** 条对第三方插件、工具或服务接入平台和相关系统提出“未经书面许可”的限制；第 **8.6** 条约束内容与课程资料的知识产权和复用。上述归纳仅用于解释现有产品策略：公开介绍可供用户浏览，与本应用自动聚合的许可范围是两个问题，后者仍未解决。

`policy_unreviewed` 应表述为**本应用暂未确认自动采集许可范围**，不能表述为整站永久禁止访问或本次抓取已经遭拒。

本次 [robots.txt](https://www.icourse163.org/robots.txt) 只得到 web 工具的不可访问提示，没有原站 HTTP 状态或规则正文。2026-10-13 的直接请求曾记录 **404**，但该历史状态不能冒充今天的状态；404 本身也不是课程页拒绝访问的证明。

## 证据边界

web 工具报告 B站条款/robots 的抓取标签为 `today`，MOOC 协议为 `yesterday`；它提供检索/读取文本而非原始 HTTP 日志。因此本次 4 个 URL 读取不等于 4 次独立核验的原站 HTTP 200。未观察到明确 403 或 CAPTCHA，亦不据此声称普通浏览器一定可访问。课程页、目录和播放情况须引用主任务的独立实际观察。

结构化记录、历史来源哈希、当前代码哈希与逐项 `unknown/null` 边界见 [policy-audit.json](policy-audit.json)。未更新任何平台策略或放宽名单。
