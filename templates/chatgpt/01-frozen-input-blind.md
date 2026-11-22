<!-- Generated from policy/parrhesia-policy.md; DO NOT EDIT. Run: python scripts/generate-policy.py -->
# 冻结资料模板（盲审默认版：仅含主张与证据，不含初稿正文与起草押注）

这是 L2 文字协议的**默认盲审模板**（`blind=true`），供两侧共同使用。仅提供主张、证据与原始结果，**不含初稿正文与起草者押注/实验偏好**，避免叙事修辞先入为主。保存为新文件；`case_id` / `revision_id` 为人工标识，勿填未计算的哈希。完整字段见套件 `skills/parrhesia-l2-reference/SKILL.md`。

## 本轮信息

- case_id：待填（如 CHAT-001）
- revision_id：待填（如 R1）
- 审查模式：盲审默认（blind=true，仅含主张与证据，不含初稿正文与起草押注）
- 引用旧版本：无 / 待填
- 具体问题：待填
- 研究对象及适用条件：待填
- 主张 ID 清单：待填（L2 通常 3–5 条）
- 资料是否已冻结：否（核对完后由操作者记录）
- 资料读取限制：待填（如全文已提供 / 仅摘要 / 截断范围；未核实写 UNKNOWN）

## 证据清单

每项复制此段，附件须另行提供，不能只给审查者无法访问的本地路径。

- evidence_id：E-001
- 文件名 / 公开文献链接及定位（页码、表号、行号）：待填
- 来源类型：实际观察 / 提交者报告 / 合成样例（未确认写 UNKNOWN）
- 溯源层级：session_anchored（Code Interpreter 实测 stdout 或用户逐字原文/表格定位，无机械哈希核对）/ tool_bound / unanchored
- 支持本轮判断的原文、数值或表格：待填
- 已提供范围及缺失、截断部分：待填
- 实际计算的 SHA-256（可选，未计算留空或写未计算）：待填

## 结论台账

每条主张复制此段。不要把用户期待的判定写入资料；仅填写适用设计包与检查行，确实缺失的事实才记 `UNKNOWN`。

- ID：C-001
- 原命题：待填
- 范围（对象、条件、分析单位、数据范围）：待填
- 主张类型、类型内证据等级与范围：claim_type：待填；evidence_level：待填（按该类型枚举）；scope：待填
- 主张方向 claim_direction：benefit / harm / null（区分有益、有害或界定空效应；方向与是否有益分开）
- 终点角色 endpoint_role：primary / secondary / safety / exploratory（不因单个次要终点否定主贡献）
- 主张基础 claim_basis：empirical / synthetic / formal（据实选择；synthetic 不支持经验性正判定）
- 证据 ID 与定位：待填
- 适用设计包（仅填适用包及适用行，字段详见 `skills/parrhesia-l2-reference/SKILL.md`：observational / quasi_experimental / randomized / prediction / ml / mechanism / evidence_synthesis / theory / qualitative；每行写状态/理由/证据 ID）：待填
- causal_basis（仅因果/必要/充分/因果链机制填写：设计族、estimand、识别假设、证伪/敏感度；必要与充分分别记录）：不适用 / 待填
- statistical_report（定量主张按适用项填写：units_sample_size、estimand_scale、estimate_uncertainty、model_assumptions、missingness_exclusions、multiplicity_selection、comparisons_baselines、robustness_limits；缺失项记 UNKNOWN）：待填
- provenance_cards（按需填写，文字模式标 `session_anchored` 及无机械哈希核对）：citation（source/locator/claim_link/support_relation/read_extent）| number（value/unit_denominator/population_time/derivation/uncertainty/locator）| execution（command/inputs/exit_status/outputs/log_locator，含 Code Interpreter stdout）| search（database/query/searched_at/coverage/results/limitations）
- 效应量与不确定性（如点估计、95% CI 与 p 值；未报告写 UNKNOWN）：待填
- 来源：预设 / 探索性（未确认写 UNKNOWN）；依据：待填
- 对科学或工程问题的贡献：待填
- 预验尸（如果最后是错的最可能因为什么）：待填；排除状态及依据：待填
- 涉及“首次/新机制/颠覆性”的先验说明（同类主张常见失败方式、定性先验高/中/低及理由；无引用不写具体比例）：无 / 待填
- 引用旧 ID：无 / 待填

逐项按实证填通过 / 失败 / 不适用（确实缺失才填未知），不机械填满。

| 底线检查 | 状态（通过 / 失败 / 未知 / 不适用） | 依据或不适用理由 |
|---|---|---|
| 数据质控 | 待填 | 待填 |
| 样本和批次结构 | 待填 | 待填 |
| 分析单位与独立重复 | 待填 | 待填 |
| 方法前提 | 待填 | 待填 |
| 多重比较 | 待填 | 待填 |
| 训练测试泄漏 | 待填 | 待填 |
| 阴性对照或基线 | 待填 | 待填 |

## 发出前

核对两份副本的本轮信息、主张与证据一致；确认已移除起草对话、初稿正文、起草者押注、其他审查意见、期望结论、密钥及无关私密资料。不改写不利证据；资料缺失或截断须明示。
