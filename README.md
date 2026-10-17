# Parrhesia

**让证据决定表达强度，让裁决结束空泛中立。**

Parrhesia 是遵循 [Agent Plugins 1.0.0](https://agent-plugins.org/) 规范的本地审查插件，配套跨平台规则体系 `AGENTS.md`。它面向需要评价证据、解释结果、比较方案并形成结论的 Agent 工作流，将三类核心纠偏职责严格解耦：**夸大审查**检查越级用词与理想化，**低估审查**找回被无证据削弱的贡献与被埋没的发现，**单一裁决者**负责逐条作出明确判断。当前交付版本为 **0.1.0 pilot**。

```text
初稿 (Draft) + 结构化台账 (Ledger) + 原始证据 (Evidence Snapshots)
                         ↓ 登记并冻结 (Freeze)
       ┌─────────────────┴─────────────────┐
       ↓ 干净上下文 1                      ↓ 干净上下文 2
  夸大审查包 (Overclaim Packet)        低估审查包 (Underclaim Packet)
       └─────────────────┬─────────────────┘
                         ↓ 双审齐备
                   单一裁决 (Adjudication)
                         ↓
             来源哈希与原文锚点核对 (Verification)
                         ↓
               原子导出只读报告 (Report & SQLite)
```

主张证据不足时，明确判定为“不支持”或“证据不足”；已有贡献成立时，明确说清贡献范围。插件不以积极表态、较少限定词或迎合用户作为优化目标，坚决杜绝“各打五十大板”的虚伪中立。

---

## 统一触发机制（L0 / L1 / L2）

为了平衡执行效率与审查严格度，Parrhesia 采用统一的三层触发阶梯：

- **L0 不启动**：日常翻译、格式修改、简单事实回答、局部代码修正；探索阶段的假设生成、随手记录、单次计算或查数。按任务本身直接完成，不启动额外机制。
- **L1 仅用规则（默认）**：需要形成判断但不需要持久台账或双审对比。用“支持 / 条件性支持 / 不支持 / 证据不足”自查并写明改判条件；不建台账、不开子代理。交付前做轻量双向自查（回答两个问题，每问最多一句）：
  - **夸大**：有没有哪句话的强度超过了证据？
  - **低估**：有没有哪个已经被支持的发现，被限制语盖住或埋到了结尾？
  - *注：仅提到 Parrhesia 不自动升级为 L2。*
- **L2 完整流程**：用户要求将发现写入图注、摘要、正文、汇报或投稿材料；要求正式审查、重新评估已有结论或升级为核心论点；已有结论被质疑，需要正式回应。只审 3–5 条核心主张，不审全文。登记结构化台账、冻结同一版本、派发两份独立角色包、主代理逐条裁决并导出报告。

---

## 证据分级体系与底线规则

Parrhesia 对科学探索与工程研发实施明确的证据分级与表述约束，严禁越级措辞：

### 1. 科学级别与工程级别
- **科学级别**：描述性观察 (`descriptive`) → 相关 (`association`) → 可预测 (`predictive`) → 机制线索 (`mechanistic`) → 因果或必要充分性 (`causal`)。用词严格与级别相称（如仅有相关证据用“与…相关”，有预测证据用“可预测”，提示机制用“提示…可能参与”，唯有干预证据才允许用“导致/调控”）。
- **工程级别**：测试通过 (`test_passed`) → 宿主验收 (`host_accepted`) → 用户效果 (`user_impact`)。
  - **严禁跃迁**：严禁将单元测试通过跃迁为宿主环境已验收；严禁将宿主握手连通或样例运行跃迁为用户实际业务生效或模型收益证明。

### 2. 四大审查底线约束
- **预验尸取代机械列举**：对每个核心结论开展预验尸——问“如果它最后是错的，最可能是因为什么（最脆弱环节、最强替代解释或致命假设）”，明确排除状态与依据，取代机械列举不痛不痒的替代解释。
- **基率提醒（Base-rate Alert）**：涉及“新机制”“首次”或颠覆性主张时，先说明该类说法在领域历史上成立的先验基率；未检索不写“经检索”，有限检索未命中不写“首次”。
- **禁用空泛套话**：禁用“具有重要意义”、“有待进一步研究”、“可能存在一定影响”等无信息增量的防御性套话，必须替换为具体成立范围、缺口或改判条件。
- **限制条款预算（Limitation Budget）**：每条限制必须写清它影响哪条结论、影响的是精度/方向/范围中的哪一项、会不会改变决策（三项都写不出则删除）；同一限制全文只陈述一次，紧邻对应结论，不在各段反复自我削弱。

---

## 已实现能力

- **持久可恢复的案例状态机**：基于 SQLite3 保存初稿、结论台账、原始证据快照、假说登记、双向审查意见、裁决与事件历史。状态机推进单向不可逆（`draft -> frozen -> reviewed -> adjudicated -> export_pending -> exported`），支持断点恢复；冻结后严禁静默改稿。
- **相同输入、分开的审查包**：冻结时原子生成两包；不带另一侧意见、作者会话 ID 或期望判定字段。由宿主负责创建干净独立的上下文。
- **完整裁决约束**：每条结论必须给出判定（`supported` / `partially_supported` / `unsupported` / `insufficient_evidence`）、理由、范围、置信理由与改判条件；每条意见必须绑定结论并作出采纳、部分采纳或驳回。两位审查者不是投票者，不折中、不平均。
- **有界审查与注意力保护**：每侧最多 3 条会改变判断的实质问题（允许零条）。超过 3 条时返回 `needs_split` 并阻塞裁决，强制缩小范围另建后续 case，杜绝截断隐藏关键问题。
- **来源与原文锚点核对**：保存源文件 bytes 与 SHA-256 哈希，核对可选的原文引用锚点子串；严密区分内容不匹配、缺失与未验证。内容不匹配直接阻止导出。
- **人类介入审计留痕**：支持 `pause` / `challenge` / `defer` / `accept`；显式记录调用方转录的人类决定、范围与理由。`pause` 阻止后续写入，`challenge` / `defer` 阻止最终导出，后续显式 `accept` 方可解除。
- **单源规则生成与强一致性防漂移**：以 `policy/parrhesia-policy.md` 为唯一真实源（SSOT），确定性生成仓库 `AGENTS.md`、通用/Codex/ChatGPT 模板、Skill 文件与交接文件；内置 `--check` 守门与 GitHub Actions CI 检查。
- **零额外依赖的本地运行时**：仅依赖 Python 3.11+ 标准库。不自动联网、不擅自调用外部模型、不执行用户提交的代码。

---

## 快速上手与 CLI 工具

### 1. 运行离线端到端演示
在插件目录内运行（输出目录必须尚不存在）：

```powershell
python -m parrhesia demo --output .\artifacts\my-demo
```

该命令将在指定目录生成只读 HTML 报告 `review.html`、裁决 Markdown、`case.json`、持久 SQLite 数据库和完整的调用序列记录。演示包含三个人工构造的合成样例（因果降级、承认直接比较差异、明确证据不足）。**所有数值、审查意见和判定均为预置样例，不代表模型评价或真实科学分析。**

### 2. CLI 核心命令
无需安装第三方包，直接使用 Python 启动：

```powershell
# 查看工作流完整契约规范
python -m parrhesia contract

# 启动 MCP stdio 服务（供 Agent 客户端挂载）
python -m parrhesia serve --workspace C:\YourWorkspace

# 单步执行一个工作流 Action（从 JSON 文件或标准输入读取 payload）
python -m parrhesia call create_case --workspace C:\YourWorkspace --input payload.json
```

### 3. 规则维护与测试
```powershell
# 规则一致性检查（只读校验，CI 运行）
python scripts/generate-policy.py --check

# 从源规则重新生成派生文件
python scripts/generate-policy.py

# 运行完整自动化测试套件（62 项测试）
python -m unittest discover -s tests -v

# 构建符合 Agent Plugins 规范的分发 ZIP 包
python scripts/build-release.py --output dist/parrhesia-0.1.0.zip
```

---

## 多宿主与多平台接入指引

Parrhesia 提供统一的判断规则源，并在不同宿主环境下适配了相应的接入路径：

### 模式一：标准 Agent Plugins 1.0.0 客户端
适用于支持 Agent Plugins 规范的客户端（如 Claude Code、通用 Agent 平台）：
1. 客户端加载根目录 `plugin.json`、`mcp.json` 与 `skills/parrhesia-review/SKILL.md`。
2. 宿主通过 MCP 协议自动发现 3 个本地工具：
   - `parrhesia_contract`：获取当前活动工作区与契约规范。
   - `parrhesia_select_workspace`：显式选定用户授权的工作区绝对路径。
   - `parrhesia_workflow`：执行具体的 13 项工作流动作（`create_case`, `register_evidence`, `set_ledger`, `freeze`, `review_packet`, `submit_review`, `adjudication_packet`, `submit_adjudication`, `verify`, `export` 等）。
3. 将 [通用规则模板](templates/AGENTS.parrhesia.md) 追加到目标项目的 `AGENTS.md` 中。

### 模式二：Grok Build 项目适配
针对 Grok Build CLI 环境（`grok 1.0.48+`），适配器将运行时、项目技能和 MCP 配置自动安全安装到指定项目：

```powershell
# 运行安装脚本（自动备份已有文件，合并 .mcp.json 与 AGENTS.md 规则块）
python scripts/install-grok.py --project C:\YourProject
# 或使用 PowerShell 脚本
& .\scripts\install-grok.ps1 -Project C:\YourProject

# 在目标项目中验证 MCP 工具发现与健康状态
grok --cwd C:\YourProject inspect
grok --cwd C:\YourProject mcp doctor parrhesia --json
```
*详细说明、备份还原与未信任目录安全对照见 [Grok 接入说明](docs/grok-integration.md)。*

### 模式三：Codex CLI / Agent 项目接入
Codex 环境可通过规则块与子代理完成独立双审与裁决：
1. 将 [Codex 规则模板](templates/AGENTS.parrhesia.codex.md) 追加到项目的 `AGENTS.md`，保留原有内容。
2. 需要执行 L2 正式审查时，由主代理将同一冻结资料派发给两个不继承起草历史的新子代理（或独立新会话），分别承担夸大审查与低估审查角色。
3. 审查结果返回主代理，由主代理完成统一裁决并导出。若无子代理隔离能力，按规则如实标明“非独立审查，未排除起草偏差”。

### 模式四：ChatGPT 项目 / 自定义 GPT 文字适配
无需安装 Python 或本地 MCP，即可在网页端安全运行 L2 文字协议：
1. 将 [ChatGPT 指令模板](templates/AGENTS.parrhesia.chatgpt.md) 粘贴到项目指令（Project Instructions）或自定义 GPT 的 Instructions 中。
2. 在本地生成标准交接套件（输出目录须尚不存在）：
   ```powershell
   python scripts/prepare-chatgpt.py --output artifacts/chatgpt-kit
   ```
3. 按照 [ChatGPT 接入说明](docs/chatgpt-integration.md) 中的流程，使用套件中的 5 个标准化交接模板（`01-frozen-input.md` 整理台账 → `02-overclaim.md` 与 `03-underclaim.md` 分别交接给新会话 → `04-adjudication.md` 回到主会话裁决 → `05-handoff-record.md` 留存记录）。

---

## 怎样判断产品是否有效（证据分层与客观边界）

Parrhesia 坚持“让结论与证据相称”的产品哲学，自身成果也严格遵守证据分级：

### 已实际核验（Engineering / Host Evidence）
- **本地工程契约已验证**：最近一次执行 62 项自动化单元与集成测试，61 项通过，1 项因 Windows 账户无法创建符号链接而跳过；检查范围包括状态边界、并发、持久恢复、路径越界拒绝、原文锚点核对与硬链接原子导出。
- **多宿主连接与格式合规**：根清单通过 Agent Plugins 1.0.0 官方 JSON Schema 校验；Grok 1.0.48 实测完成 3 个工具发现与握手（见 [Grok 原生记录](docs/verification/grok-native.json)）；脱离源码的 ZIP 解压副本与安装副本可独立启动并读取契约。
- **规则确定性单源与防漂移**：`policy/parrhesia-policy.md` 规则修改后所有派生文件同步一致性已获验证（见 [规则生成核验](docs/verification/policy-generation.md)），CI 强校验已生效。
- **文字套件隔离机制**：白名单生成器已验证排他性复制与防覆盖（见 [ChatGPT 适配核验](docs/verification/chatgpt-adapter.md)）。
- **外部能力与费用边界**：本轮 AgentMuxer 仅用于免费能力发现（支出 $0.00），未调用任何外部付费接口，代码中不包含任何模型私有凭据或计费平台接口。

### 尚未建立的证据（What is NOT Measured）
- **真实模型行为改善幅度尚未测量**：尚未在大规模真实任务或盲评集上测量 Grok / ChatGPT 的过度防御、理想化和空泛中立是否统计学显著减少。
- **内核不保证科学真实性**：来源哈希一致仅证明本地文件字节未被篡改，不证明数据来自真实实验、代码切实运行或引文真正支持主张。
- **上下文隔离程度依赖宿主**：内核保证了生成的两包字段严格分离；但若宿主在同一对话中连续扮演角色，或跨会话共享了全局知识库，起草偏差仍然存在，此时系统强制标为“隔离未验证”或“非独立审查”。

下一阶段的严格对照评估方法详见 [对照评价方案](docs/evaluation-plan.md)。

---

## 文档索引

- **架构与设计**
  - [产品设计说明](docs/product-design.md)：产品承诺、三种偏倚分离逻辑、生命周期与边界。
  - [接口契约规范](docs/contract.md)：13 个 Action 的输入 Payload、返回结构与状态机约束。
  - [对照评价方案](docs/evaluation-plan.md)：保留集构建、对照实验设计与盲评指标体系。
- **宿主集成指南**
  - [Grok 项目适配指南](docs/grok-integration.md)：Grok Build CLI 安装、信任配置与 MCP 诊断。
  - [ChatGPT 项目适配指南](docs/chatgpt-integration.md)：ChatGPT 项目/自定义 GPT 文字协议与交接操作。
- **核验与证据记录**
  - [交付核验报告](docs/verification/release-readiness.md)：0.1.0 交付检查、独立审阅修复与未建立证据。
  - [规则生成核验报告](docs/verification/policy-generation.md)：单源生成一致性与防漂移测试报告。
  - [ChatGPT 适配核验报告](docs/verification/chatgpt-adapter.md)：文字套件白名单与隔离性核验。
  - [Grok 原生诊断结果](docs/verification/grok-native.json)：Grok 1.0.48 本地握手与工具枚举数据。
- **规则源与模板**
  - [唯一规则源](policy/parrhesia-policy.md)：所有派生文件的源定义。
  - [完整仓库 AGENTS.md](AGENTS.md) / [通用追加模板](templates/AGENTS.parrhesia.md) / [Codex 模板](templates/AGENTS.parrhesia.codex.md) / [ChatGPT 模板](templates/AGENTS.parrhesia.chatgpt.md)。

---

## 许可证与代码仓库

- 许可协议：[Apache-2.0 License](LICENSE)
- 代码仓库：[HERRY423/Parrhesia](https://github.com/HERRY423/Parrhesia)
