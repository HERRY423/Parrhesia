# 统一规则生成核验

日期：2026-10-16（America/Los_Angeles）。本次为规则维护与工程验证，没有执行科学分析或模型双审。

## 实现范围

唯一编辑源为 `policy/parrhesia-policy.md`，生成仓库 AGENTS.md、通用/Codex/ChatGPT 三个模板、SKILL 和六个 ChatGPT 交接模板（含 `01-frozen-input-blind.md` 盲审版）。

生成器现已支持按平台组合模块：规则源拆分为 `core`（所有平台共用）、`l2_protocol`（文字版协议）、`plugin_tools`（本地工具与人工介入约束）和 `agentmuxer`（外部能力与额度边界）四块。每个目标文件声明自己包含哪几块：
- **ChatGPT 版**：声明并组合 `core + l2_protocol`（纯文字协议，排除了本地 MCP 工具和 AgentMuxer 规则）；
- **Codex / Grok / 仓库 / Skill**：声明并组合 `core + l2_protocol + plugin_tools + agentmuxer`。

`python scripts/generate-policy.py` 更新生成结果，`--check` 只读检查。分发构建与 ChatGPT 套件生成命令先做一致性检查；分发 ZIP 包含规则源和生成器，可在解压后独立检查。GitHub 工作流 `.github/workflows/policy.yml` 配置了检查命令与覆盖 Linux 和 Windows 双平台的完整测试套件，远程执行状态须另查具体 run，不能以本地结果代替。

## 实际本地结果

完整测试执行 66 项：本地 65 通过，1 跳过（已有的 Windows 符号链接权限检查；Linux CI 全通）。`python scripts/generate-policy.py --check` 通过。

一致性测试与断言覆盖：
1. **模块级逐字一致**：`core`、`l2_protocol`、`plugin_tools`、`agentmuxer` 在所有声明包含它的目标入口中均逐字完全相同，在未声明它的入口中均严格不存在；
2. **纯文字隔离断言**：显式断言 ChatGPT 模板中绝对不出现 `search_offerings` 与 `parrhesia_contract`；
3. **入口清单与已提交内容**：检查 11 项产物与白名单匹配；
4. **触发条件联动漂移**：修改 `core` 触发条件后，所有主入口同时失效并能重新生成；
5. **异常与恶意源阻断**：重复模块区块、未知声明模块、损坏标记在写入前均失败且不产生副作用；
6. **分发打包强守门**：分发打包在规则漂移时拒绝创建 ZIP；
7. **报告标签与规则对齐**：显式断言 `report.py` 标签与规则用词一致（“条件性支持”对齐，排除“部分支持”）；
8. **研究推进规范在位**：当前断言检查所有主入口均包含研究类 L1 压缩版与仅研究类 L2 的完整版，并排除旧的“非 L0 全量执行”要求。

这些结果证明本次检查范围内的模块化组合与漂移检测行为，不证明规则文本不存在所有语义冲突，也不证明真实宿主遵守规则。既有安装、外部项目和已生成的旧套件未自动修改，使用者需要显式更新或重新复制。

## 2026-10-17 触发与 L1 契约更新

规则源新增触发决策树与回答首行档位标签；L0 收窄为原子事实、翻译、格式、局部代码且不新增或重评结论。L1 固定五段，包含带证据定位的一句话理由、可观察改判条件、点名原句的双向自查和覆盖七项的底线声明。研究类 L1 使用压缩版，完整版仅用于研究类 L2；生成的独立审查与裁决提示词也要求首行 `[L2]`。

本轮实际运行 `python scripts/generate-policy.py --check` 通过，`python -m unittest discover -s tests -p test_policy.py -v` 共 8 项全部通过，`git diff --check` 通过。测试首次在沙箱默认临时目录遇到权限错误，改用工作区内临时目录后通过。未重跑上文所述完整 66 项测试，未执行宿主行为验收或模型效果评价；文本分档行为仍需真实宿主案例检验。
