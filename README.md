# Parrhesia

**让证据决定表达强度，让裁决结束空泛中立。**

Parrhesia 是遵循 [Agent Plugins 1.0.0](https://agent-plugins.org/) 规范的本地审查插件，配套跨平台规则体系 `AGENTS.md`。它面向需要评价证据、解释结果、比较方案并形成结论的 Agent 工作流，将三类核心纠偏职责严格解耦：**夸大审查**检查越级用词与理想化，**低估审查**找回被无证据削弱的贡献与被埋没的发现，**单一裁决者**负责逐条作出明确判断。当前交付版本为 **0.2.0 pilot**。

本版统一 L0/L1/L2 契约、主张类型与证据等级、v2 运行时和反空转门控。查看 [版本变更](CHANGELOG.md)、[从 0.1.0 升级](docs/migration-0.2.md)及[本版核验](docs/verification/release-0.2.0.md)。下图为 L2 工作流。

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

主张证据不足时，保留“证据不足”，不冒充支持，也不把缺少证据自动当成反证；已有贡献成立时，明确说清贡献范围。插件不以积极表态、较少限定词或迎合用户作为优化目标，坚决杜绝“各打五十大板”的虚伪中立。

[规则源](policy/parrhesia-policy.md#唯一优先级)明确平台系统指令优先于开发者指令，二者均优先于用户消息；禁止编造数据、引文、执行和检索。用户可决定范围、格式、语言与简化，但不能指定证据等级或判定，用户期望不构成证据。

---

## 统一触发机制（L0 / L1 / L1-Explore / L2）与日常工作流

触发决策树与完整输出契约以[唯一规则源](policy/parrhesia-policy.md#统一触发条件)为准。回答首行标明 `[L0]`、`[L1]`、`[L1-Explore]` 或 `[L2]`，标签表示采用的档位，不代表流程已完成。

- **L0**：只处理原子事实、翻译、格式或局部代码，且不增加或重评结论；论文的纯翻译和排版也适用。
- **L1（默认）**：一般解释、比较、建议与证据判断，开头给判定与 `claim_type × evidence_level + scope`，附可核对依据、可观察改判条件与下一步可执行动作。
- **L1-Explore**：头脑风暴、假说生成、机制推演、实验设计或识别设计。不建 L2 持久台账、不双审，改为维护**轻量探索台账**：每个候选假说一张卡，固定包含**最强对手、区分实验、成本、停止规则、杀死条件**五项，并显式标 `exploratory`。
- **L2**：写入图注、摘要、正文、汇报或投稿材料，正式审查、重新评估已有结论，正式回应质疑，或明确要求完整流程时，读取 `parrhesia-l2-reference` / `parrhesia-review` skill，登记并冻结 3–5 条核心主张，执行角色包隔离双审与单一裁决。

**推荐的日常工作流（不新增工具）**：探索阶段全程 `L1-Explore`，不建台账、不双审；确证阶段把 3 到 5 条核心主张送入 `L2`；只有写入图注、摘要或正文时才走完整双审。

---

## 证据分级体系与底线规则

Parrhesia 对科学探索与工程研发实施明确的证据分级与表述约束，严禁越级措辞：

### 1. 主张类型 × 类型内证据等级 + 范围

描述、关联、预测、因果效应、机制、必要性、充分性、证据综合、理论、质性、计算性能与工程分别分类；证据等级只在对应类型内解释，不再排列五级阶梯。因果语言按设计族、estimand、识别假设及证伪/敏感度依据判断，必要性与充分性分别记录；是否进行干预不单独决定授权。

[规则源](policy/parrhesia-policy.md#九个设计包)提供观察性、准实验、随机实验、预测、ML、机制、证据综合、理论、质性九个设计包，以及最低统计报告和引文/数字/执行/检索卡。按实际设计选包，理论和质性不强套 p 值。

新案例只允许 [v2 运行时契约](docs/contract.md)；已有 v1/早期 v2 案例保留原记录与冻结摘要，可按历史契约恢复。指定 `schema_version: 1` 新建案例会被拒绝，不能借旧版入口跳过门控。结构校验不能证明科学有效性或执行真实性。

新 v2 自动启用 `gate_version=1`：关键检查缺口限制判定与类型内等级，证据 kind 必须匹配主张；经验因果正判定另要求干预/准实验类证据，仍须满足识别与敏感度条件。synthetic 不支持经验性正判定；每条正向引用须有至少 12 个非空白字符的唯一 quote 与定位。两侧逐主张给 stance，意见采纳绑定实际改写或显式分歧，盲审设置在案例级冻结，未读二进制/截断内容必须确认。已有历史案例的兼容路径标为 `LEGACY_UNGATED`，不能宣称通过当前门控。详见[契约](docs/contract.md#current-anti-stall-gates-gate_version1)和[核验记录](docs/verification/anti-stall-gates.md)。

后续[绕过修复核验](docs/verification/gate-bypass-hardening-20261019.md)覆盖了新建旧版被拒绝、条件性立场必须给出条件、改写锚点必须定位新增文字、不可见字符不能凑长度，以及未知版本不能降级执行。

### 2. 四大审查底线约束
- **预验尸取代机械列举（仅 L2）**：对每个核心结论开展预验尸——问“如果它最后是错的，最可能是因为什么（最脆弱环节、最强替代解释或致命假设）”，明确排除状态与依据，取代机械列举不痛不痒的替代解释。
- **基率与先验提醒（Prior & Failure Modes）**：涉及“首次/新机制/颠覆性”主张时，说明同类主张常见的失败方式（如批次效应、计算推断未经验证、单队列不可复现），给出定性先验（高 / 中 / 低）及理由。没有可引用来源时，不写具体比例，严禁编造概率数字；未检索不写“经检索”，有限检索未命中不写“首次”。
- **结尾结构约束与禁空泛展望**：L2 结尾是具体下一步或明确判定；L1 在第一、三段给出判定与可观察改判条件，按第五段覆盖声明收尾。不能用空泛展望替代验证动作、缺口或改判条件。
- **限制条款预算（Limitation Budget）**：每条限制必须写清它影响哪条结论、影响的是精度/方向/范围中的哪一项、会不会改变决策（三项都写不出则删除）；同一限制全文只陈述一次，紧邻对应结论，不在各段反复自我削弱。

### 3. 研究推进按档位执行

研究类 L1 只用压缩版：把当前最佳解释、一个最强竞争解释和区分条件嵌入五段契约的前三段；一般判断与工程维护不套用研究推进。完整五步只用于研究类 L2。具体要求见[研究推进规则](policy/parrhesia-policy.md#研究推进按档位执行)，能力可用不自动授权新增分析或付费。

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

该命令将在指定目录生成只读 HTML 报告 `review.html`、裁决 Markdown、`case.json`、持久 SQLite 数据库和完整的调用序列记录。演示把两条经验性主张改为仅描述合成文本记录，并对临床用途明确判为证据不足；合成数值不获经验性正判定。**所有数值、审查意见和判定均为预置样例，不代表模型评价或真实科学分析。**

### 2. CLI 核心命令
无需安装第三方包，直接使用 Python 启动：

```powershell
# 查看工作流完整契约规范
python -m parrhesia contract

# 启动 MCP stdio 服务（供 Agent 客户端挂载）
python -m parrhesia serve --workspace C:\YourWorkspace

# 单步执行一个工作流 Action（从 JSON 文件或标准输入读取 payload）
python -m parrhesia call create_case --workspace C:\YourWorkspace --input payload.json

# 生成全 unknown/not_run 的诚实主张骨架并返回当前检查上限
python -m parrhesia call scaffold_claim --workspace C:\YourWorkspace --input scaffold.json

# 执行本地命令、捕获真实输出日志、自动登记证据并生成 execution 溯源卡
python -m parrhesia record-exec --workspace C:\YourWorkspace --case-id <case_id> --card-id exec-1 -- python your_script.py
```

### 3. 规则维护、Codex 同步与测试评估
```powershell
# 规则一致性检查（只读校验，CI 运行）
python scripts/generate-policy.py --check

# 从源规则重新生成派生文件（含精简 AGENTS.md 与 skills/parrhesia-l2-reference/SKILL.md）
python scripts/generate-policy.py

# 同步 Codex 全局精简块（~/.codex/AGENTS.md）与 parrhesia-l2-reference skill（支持 --check）
python scripts/install-codex.py
python scripts/install-codex.py --check

# 运行 Stage 0 对照评估套件（24 个 L2 案例 + 6 个 L1-Explore 案例，导出 A / B-精简 / B-全文 / E 四组提示词包）
python scripts/run-stage0-eval.py --report-out docs/verification/stage0-evaluation.md
python scripts/run-stage0-eval.py --mode prompt-export --output-dir artifacts/stage0-prompts --report-out docs/verification/stage0-evaluation.md

# 运行完整自动化测试套件（111 项测试，执行统计见 docs/verification/release-0.2.0.md）
python -m unittest discover -s tests -v

# 构建符合 Agent Plugins 规范的分发 ZIP 包
python scripts/build-release.py --output dist/parrhesia-0.2.0.zip
```

---

## 多宿主与多平台接入指引

Parrhesia 提供统一的判断规则源，并在不同宿主环境下适配了相应的接入路径：

### 模式一：标准 Agent Plugins 1.0.0 客户端
适用于支持 Agent Plugins 规范的客户端（如 Claude Code、通用 Agent 平台）：
1. 客户端加载根目录 `plugin.json`、`mcp.json`、`skills/parrhesia-review/SKILL.md` 与 `skills/parrhesia-l2-reference/SKILL.md`。
2. 宿主通过 MCP 协议自动发现 3 个本地工具：
   - `parrhesia_contract`：获取当前活动工作区与契约规范。
   - `parrhesia_select_workspace`：显式选定用户授权的工作区绝对路径。
   - `parrhesia_workflow`：执行具体的 14 项工作流动作（`create_case`, `register_evidence`, `log_hypothesis`, `scaffold_claim`, `set_ledger`, `freeze`, `review_packet`, `submit_review`, `adjudication_packet`, `submit_adjudication`, `human_decision`, `verify`, `export`, `get_case`）。
3. 将 [精简规则模板](templates/AGENTS.parrhesia.codex.md)（配合 `parrhesia-l2-reference` skill）或 [通用完整规则模板](templates/AGENTS.parrhesia.md) 追加到目标项目的 `AGENTS.md` 中。

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
Codex 环境采用“常驻精简块 + 按需读取 `parrhesia-l2-reference` skill + 角色包隔离双审”架构：
1. 运行 `python scripts/install-codex.py` 将 [Codex 精简规则块](templates/AGENTS.parrhesia.codex.md) 同步至 `~/.codex/AGENTS.md`，并将 [L2 科学审查参考 Skill](skills/parrhesia-l2-reference/SKILL.md) 同步至 `~/.codex/skills/parrhesia-l2-reference/SKILL.md`（自动备份旧文件，支持 `--check` 校验）。
2. 确证性分析前先用 `reproducible-science`（`prereg`）或预注册文件冻结分析计划；数字与引文必须来自 `python -m parrhesia record-exec` 或 `reproducible-science`（`results` / `citations` / `repro`）钩子绑定的输出。
3. 需要执行 L2 正式审查时，先读取 `parrhesia-l2-reference` skill，再按**审查者隔离配方**派发两个子代理：只给对应角色的 `review_packet`，不继承起草历史，尽量关闭其记忆读取，并在最终报告中记录审查者输入清单（`input_manifest`）。若无子代理隔离能力，按规则如实标明“非独立审查，未排除起草偏差”。

### 模式四：ChatGPT 项目 / 自定义 GPT 文字适配
无需安装 Python 或本地 MCP，即可在网页端安全运行 L2 文字协议：
1. 将 [ChatGPT 指令模板](templates/AGENTS.parrhesia.chatgpt.md) 粘贴到项目指令（Project Instructions）或自定义 GPT 的 Instructions 中。
2. 在本地生成标准交接套件（输出目录须尚不存在）：
   ```powershell
   python scripts/prepare-chatgpt.py --output artifacts/chatgpt-kit
   ```
3. 按照 [ChatGPT 接入说明](docs/chatgpt-integration.md) 中的流程，使用套件中的标准化交接模板（`01-frozen-input.md` 整理台账，或 `01-frozen-input-blind.md` 盲审版 → `02-overclaim.md` 与 `03-underclaim.md` 分别交接给新会话 → `04-adjudication.md` 回到主会话裁决 → `05-handoff-record.md` 留存记录）。

---

## 怎样判断产品是否有效（证据分层与客观边界）

Parrhesia 坚持“让结论与证据相称”的产品哲学，自身成果也严格遵守证据分级：

### 已实际核验（Engineering / Host Evidence）
- **本版本地工程核验**：执行结果见 [0.2.0 核验记录](docs/verification/release-0.2.0.md)，覆盖状态边界、门控拒绝、兼容恢复、锚点、原子导出与解压副本启动。CI 配置提供 Linux / Windows 矩阵，但本版未在此记录远端 CI 成功运行，不把历史结果当成新版跨平台验收。
- **格式与宿主记录分开**：清单 schema 与独立副本启动由本地测试检查；[Grok 1.0.48 原生记录](docs/verification/grok-native.json)属于历史版本的工具发现与握手，尚未重新验收 0.2.0 的真实宿主编排。
- **规则确定性单源与防漂移**：`policy/parrhesia-policy.md` 规则修改后所有派生文件同步一致性已获验证（见 [规则生成核验](docs/verification/policy-generation.md)），CI 强校验已生效。
- **文字套件隔离机制**：白名单生成器已验证排他性复制与防覆盖（见 [ChatGPT 适配核验](docs/verification/chatgpt-adapter.md)）。
- **外部能力与费用边界**：本版整理与构建仅执行本地操作，未发起外部付费调用；运行时不自行调用模型或计费服务。

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
  - [0.2.0 交付核验](docs/verification/release-0.2.0.md)：本版测试、包内版本与交付边界。
  - [0.1.0 历史核验](docs/verification/release-readiness.md)：旧版交付检查与宿主记录，不代表新版验收。
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
