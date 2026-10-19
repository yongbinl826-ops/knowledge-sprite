# 新技能支持分支独立复核

本轮只读源码与离线合成元数据；0 HTTP、0 模型、0 DB 写入。

- P3-V1（medium，reproduced; reported to root and backend owner）：Expression substring and unordered numeric literal checks accept end < starter for end < start and 5/25 for 25/5. 位置 `teaching_match.py::_valid_quote`；证据 `evidence/phase3-audit/semantic-independent-boundary-probe.json`。
- P3-V2（medium，reproduced; reported to root and backend owner）：Standalone Prerequisites/Next lesson heading without colon does not govern following skill quote. 位置 `teaching_match.py::_valid_quote`；证据 `evidence/phase3-audit/semantic-independent-boundary-probe.json`。
- P3-V3（medium，reproduced; reported to root and backend owner）：Title support survives same-resource own description that explicitly excludes the very skill or marks it prerequisite/future. The literal fallback reproduces it without any model error. 位置 `teaching_match.py::_validate_pair_decision and literal_decision`；证据 `evidence/phase3-audit/semantic-independent-read-binding-probe.json`。
- P3-V4（medium，code policy concern; no retained production example with flag true observed）：requires_login=True always removes even fetched, identity-bound video teaching metadata from the learning-skills branch. This can suppress a legitimate platform destination rather than exposing its access requirement. 位置 `teaching_match.py::_prepare_pair`；证据 `stage guard and test_teaching_match.py unconfirmed-source parametrization`。

8 类缓存/上下文变更均拒绝旧判定；GET 路径不调用模型，媒体绑定、只读缓存完整键、两次调用上限和外层 deadline 未发现同类高/中风险。
这不是语义模型真实准确率验收。需 owner 修复后定向复核，不能把静态检查当产品新检索通过。
