# 门控绕过修复核验

日期：2026-10-19（America/Los_Angeles）。这是同一开发上下文内的本地工程复核，不是独立科学审查或原生宿主验收。

## 发现与修复

| 原有路径 | 当前行为 | 回归定位 |
|---|---|---|
| create_case 指定 schema_version=1 可新建未门控案例 | 新建只允许 v2；v1 请求返回 legacy_creation_disabled，事务不留下案例；已有历史案例仍按原契约恢复 | test_gate_bypasses.test_new_legacy_case_cannot_disable_current_gates；test_server.test_legacy_creation_rejected_over_mcp_without_poisoning_next_request |
| review 的 partially_supported 没有要求 condition | 强制填写实际条件；UNKNOWN/空白/纯不可见字符不能充当条件；final decision 与 partial disposition 同步排除占位条件 | test_gate_bypasses.test_conditional_stance_needs_a_real_condition；test_conditional_decision_and_adoption_reject_placeholder_conditions |
| 部分采纳用原句已有片段作锚点，另加无关文字即可声称 incorporated | 改写锚点须在 proposed_text 与 revised_text 中均唯一，且原句中没有该片段，定位真正改变的文字；无法落实时记录 disagreement | test_gate_bypasses.test_preexisting_anchor_is_not_incorporation；test_repeated_revision_anchor_is_not_unique |
| 不可见字符可凑足 quote 最短长度 | 长度计算不计控制/格式、组合附加符、私用码点和空白；字面匹配仍保留原文，不隐式正规化证据 | test_gate_bypasses.test_invisible_quote_cannot_satisfy_minimum_length |
| 不支持的已存 gate_version 被解释为旧版；布尔值与整数相等也可混淆版本 | 读入时显式校验 schema/gate 的整型值及组合；不支持版本返回 unsupported_contract_version，不降级处理 | test_gate_bypasses.test_unknown_contract_versions_never_fall_back_to_legacy |

修复前先运行六个回归探针，确认上述接受路径未被拒绝，再修改实现；未知版本探针的断言上下文错误也一并修正。随后增加最终条件、MCP 拒绝后的恢复检查。旧版生命周期测试现在从测试专用数据库夹具恢复历史记录，不再通过生产入口新建 v1，以免为了兼容测试保留绕过通道。

## 实际验证

`python -m unittest discover -s tests -v`：**103 项，102 通过，1 跳过，无失败**，耗时 10.375 秒。跳过项是当前 Windows 账户不能创建符号链接，不计作通过。

覆盖新拒绝路径、合法条件/改写正路径、拒绝后状态不变、历史 v1/v2 恢复、冻结摘要、完整演示、报告、真实 MCP 子进程、分发解压启动和生成文件一致性。完整测试使用工作区临时目录，原子导出所需的硬链接测试在获准的本地沙箱外执行。

`python scripts/generate-policy.py --check` 与 `git diff --check` 均通过。规则、模板、README 和运行时契约同步说明新建 v1 已停止支持。

## 边界

“新片段”与“唯一匹配”只验证文本变化，不能证明修改在语义上解决了意见；实际条件与理由仍需审阅。旧记录及已经导出的文件没有被改写或自动重新认证。没有执行真实科学分析、外部模型效果评价或宿主模型独立性验收。
