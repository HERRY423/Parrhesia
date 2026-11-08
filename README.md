# Parrhesia

**让证据决定表达强度，让裁决结束空泛中立。**

**语言 / Language**：简体中文 · **[English](README.en.md)**

Parrhesia 是遵循 [Agent Plugins 1.0.0](https://agent-plugins.org/) 规范的本地证据校准与双审裁决插件，配套单源生成的跨平台规则体系 `AGENTS.md`。当前版本为 **`0.2.0` pilot**（新案例采用 `schema_version=2` 与反空转机械门控 `gate_version=1`，保留历史记录兼容恢复）。

查看 [版本变更记录](CHANGELOG.md) · [从 0.1.0 升级指南](docs/migration-0.2.md) · [0.2.0 交付核验](docs/verification/release-0.2.0.md) · [Stage 0 对照评估报告](docs/verification/stage0-evaluation.md)

---

## 为什么需要 Parrhesia？

当同一个大模型在单次对话里同时承担“写初稿、挑毛病、找亮点、下结论”时，极易陷入三种系统性失真。Parrhesia 的核心设计是将这三项冲突职责在架构上**严格解耦**：

| 典型失真模式 | 日常 AI 协作中的可观察症状 | Parrhesia 的解耦机制 | 严禁使用的伪指标 |
| :--- | :--- | :--- | :--- |
| **1. 理想化与越级夸大**<br>*(Overclaim)* | 从相关性直接跳到“驱动/调控/导致”；把合成测试或单次跑通写成真实临床/生产收益；把局部条件成立外推为普遍规律 | **夸大审查者 (`overclaim`)**<br>只查越级用词、未排除混杂与推理跳步：*现有证据最高只能支撑到哪一级？* | “语气听起来是否谦虚谨慎” |
| **2. 过度防御与免责通胀**<br>*(Underclaim)* | 明明已有稳健的外部验证或实测改进，却用“样本量有限、缺乏多中心三期试验、仅供参考”把真实贡献抹平；每段末尾反复自我削弱 | **低估审查者 (`underclaim`)**<br>专找被无依据削弱的已证实贡献与无信息免责套话：*证据已经扎实支持了什么？* | “删掉了多少条免责声明” |
| **3. 空泛中立与和稀泥**<br>*(Hollow Neutrality)* | “一方面……另一方面……未来还需更多研究”，两边讨好却不做实质比较，把判断责任推回给用户 | **单一裁决者 (`adjudicator`)**<br>禁止投票或折中取平均；逐条裁决采纳/部分采纳/驳回，给出唯一判定与**可观察改判条件** | “结论是否鲜明或迎合用户” |

### 一眼看懂校准前后的区别

- ❌ **越级夸大反例**：“单细胞共表达与回归显著（$p=0.002$）证明转录因子 X 激活通路 Y 并导致耐药。”
- ❌ **过度免责反例**：“尽管独立外部队列（$N=120$）中模型区分度达 AUROC 0.84（95% CI 0.77–0.90），但鉴于样本量有限、潜在未知偏倚及缺乏多中心三期随机试验，目前无法得出确定结论，仅供参考。”
- ✅ **Parrhesia 校准写法**：
  > “在独立外部验证队列（$N=120$）中，该模型对 1 年复发表现出稳健的外部区分度（`prediction × externally_validated`，**支持**；AUROC 0.84，95% CI 0.77–0.90），支持其作为同分布人群风险分层的候选工具；临床决策净获益（`utility`）尚待前瞻性干预评估。若后续跨中心队列校准斜率偏离 $[0.8, 1.2]$，则将适用范围收窄至原中心同分布人群。”

**三条不可逾越的底线**（详见[唯一规则源](policy/parrhesia-policy.md#唯一优先级)）：
1. **权限与取舍顺序**：平台系统指令 > 平台开发者指令 > 用户消息；在此边界内，**数据保密与花费上限 > 证据真实 > 强度匹配 > 完整表达已支持的贡献 > 效率**。
2. **绝不伪造确定性，也不把缺证据当反证**：严禁编造数据、数字、引文、执行或检索。证据不足时明确判为 `insufficient_evidence`（这是正式结论而非逃避），既不包装成“支持”，也不把“尚无证据”当成“不支持”。
3. **用户期望不是证据**：用户可以决定任务范围、输出格式、语言和流程简化，但不能指定证据等级或判定结果。

---

## 安装与多平台接入指南

运行本地 MCP 服务与 CLI 需要 **Python 3.11+**（仅使用 Python 标准库，**零第三方依赖**，无需 `pip install` 任何外部包）。

### 方式一：Codex 插件市场安装（图形界面 / CLI）

#### 1. 图形界面“添加插件市场”（推荐）

在 Codex 桌面端的插件管理页面点击 **添加插件市场**（*从 GitHub 仓库、Git URL 或本地文件夹添加*），按弹窗字段填写：

| 弹窗字段 | 填写内容 | 说明 |
| :--- | :--- | :--- |
| **来源** | `HERRY423/Parrhesia`<br>*(或 `https://github.com/HERRY423/Parrhesia.git`)* | 若使用离线包或本地克隆，可直接选择包含 `.agents/plugins/marketplace.json` 的本地仓库根目录（如 `C:\Parrhesia`） |
| **Git 引用** | `main` | 使用主分支获取最新 `0.2.0` 更新；如需固定版本可填写对应 commit 或 tag |
| **稀疏路径** | **留空** | 插件清单直接位于仓库根目录，**请勿填写**输入框灰字占位符 `plugins/codex` |

点击右下角 **添加市场** 后，在插件市场列表中选择 **Parrhesia Marketplace** 并安装 **Parrhesia**。

#### 2. Codex CLI 命令行添加

```powershell
# 从 GitHub 添加插件市场并安装插件
codex plugin marketplace add HERRY423/Parrhesia --ref main
codex plugin add parrhesia@parrhesia-marketplace

# （可选）从本地克隆目录添加市场
codex plugin marketplace add C:\Parrhesia
```

#### 3. 同步 Codex 全局精简规则与 L2 科学参考技能

Codex 采用“**常驻精简规则块 + 按需加载 `parrhesia-l2-reference` 技能 + 角色包隔离双审**”架构，避免常驻 41 KB 全文规则挤占上下文：

```powershell
# 将精简规则块同步至 ~/.codex/AGENTS.md，并将 L2 参考技能同步至 ~/.codex/skills/parrhesia-l2-reference/SKILL.md
python scripts/install-codex.py

# 只读校验当前 Codex 配置是否与仓库唯一规则源保持同步
python scripts/install-codex.py --check
```

---

### 方式二：Claude Code 插件市场与通用 Agent Plugins 1.0.0 客户端

#### 1. Claude Code 命令行安装

```bash
claude plugin marketplace add HERRY423/Parrhesia
claude plugin install parrhesia@parrhesia-marketplace
```

#### 2. 标准 Agent Plugins 1.0.0 客户端挂载

支持 Agent Plugins 1.0.0 规范的宿主可直接加载根目录 `plugin.json`、`mcp.json` 与 `skills/`，通过 stdio MCP 自动发现 3 个本地工具：
- `parrhesia_contract`：读取当前活动工作区与完整运行时契约规范。
- `parrhesia_select_workspace`：显式切换至用户授权的已有工作区绝对路径。
- `parrhesia_workflow`：调度 14 项工作流动作（`create_case`、`register_evidence`、`log_hypothesis`、`scaffold_claim`、`set_ledger`、`freeze`、`review_packet`、`submit_review`、`adjudication_packet`、`submit_adjudication`、`human_decision`、`verify`、`export`、`get_case`）。

---

### 方式三：Grok Build CLI 项目级适配

针对 Grok Build CLI（`grok 1.0.48+`），提供幂等安装脚本，自动备份已有文件并安全合并项目 `.mcp.json` 与 `AGENTS.md` 规则块：

```powershell
# 安装到目标项目（或运行 & .\scripts\install-grok.ps1 -Project C:\YourProject）
python scripts/install-grok.py --project C:\YourProject

# 验证工具发现与 MCP 握手状态
grok --cwd C:\YourProject inspect
grok --cwd C:\YourProject mcp doctor parrhesia --json
```
*详见 [Grok 接入说明](docs/grok-integration.md)。*

---

### 方式四：ChatGPT 网页端 / 自定义 GPT 纯文字协议（零本地依赖）

无需本地运行 Python 或 MCP，即可在网页端通过多会话隔离运行 L2 双审协议：
1. 将 [ChatGPT 规则模板](templates/AGENTS.parrhesia.chatgpt.md) 粘贴至 ChatGPT Project Instructions 或 Custom GPT Instructions。
2. 生成标准交接模板套件（输出目录须尚不存在）：
   ```powershell
   python scripts/prepare-chatgpt.py --output artifacts/chatgpt-kit
   ```
3. 按 [ChatGPT 接入说明](docs/chatgpt-integration.md) 执行跨会话交接：`01-frozen-input.md`（或盲审版 `01-frozen-input-blind.md`）冻结台账 → 分别在两个新建独立会话中粘贴 `02-overclaim.md` 与 `03-underclaim.md` → 回到主会话用 `04-adjudication.md` 裁决 → 用 `05-handoff-record.md` 归档。

---

## 四档渐进工作流（L0 / L1 / L1-Explore / L2）

Parrhesia 不为简单任务制造流程负担，也不在关键结论上放水。每次回答首行标明当前采用的档位（进度消息不标）：

```text
收到任务请求
  │
  ├─► 仅涉及翻译 / 排版 / 单一可核对原子事实 / 局部代码修改 / 只返回数值不解释含义？
  │     └──► [L0] 直接完成任务，零额外结构
  │
  ├─► 处于头脑风暴 / 假说生成 / 机制推演 / 实验设计或统计识别设计阶段？
  │     └──► [L1-Explore] 轻量探索台账（不建 L2 持久台账、不开双审）
  │            维护 2–3 张候选假说卡（显式标 exploratory），每张卡固定五项：
  │            ① 最强对手 · ② 区分实验 · ③ 成本 · ④ 停止规则 · ⑤ 杀死条件
  │
  ├─► 日常解释 / 方案比较 / 证据判断 / 阶段性小结？
  │     └──► [L1] 默认判别契约
  │            ① 开头给判定与 claim_type × evidence_level + scope
  │            ② 可核对依据（研究类点名最强竞争解释）
  │            ③ 可观察改判条件 · ④ 下一步可执行动作 · ⑤ 底线检查例外报告
  │
  └─► 写入图注 / 摘要 / 正文 / 汇报 / 投稿材料，或正式审查核心论点、回应质疑？
        └──► [L2] 完整台账冻结 + 独立双审 + 单一裁决（每次仅审 3–5 条核心主张，不审全文）
```

> **推荐的日常科研与研发工作流**：
> 探索阶段全程使用 **`L1-Explore`** 快速收敛假说与证伪条件 → 确证阶段把 **3–5 条核心主张**送入 **`L2`** → 只有写入图注、摘要、正文或汇报材料时才执行完整双审。

### L2 完整生命周期与状态机

```text
初稿 (Draft) + 原始证据快照 (Evidence Snapshots) + 诚实骨架 (scaffold_claim) + 结论台账 (Ledger v2)
                                      │
                                      ▼  freeze（计算修订摘要，案例级锁定 blind=true）
                    ┌─────────────────┴─────────────────┐
                    ▼ 独立干净上下文 1                  ▼ 独立干净上下文 2
          夸大审查包 (Overclaim Packet)       低估审查包 (Underclaim Packet)
          [0–3 条实质问题 + 逐主张 stance]    [0–3 条实质问题 + 逐主张 stance]
                    └─────────────────┬─────────────────┘
                                      ▼  双审齐备（若任一侧 >3 条实质问题则 needs_split 阻塞）
                            单一裁决 (Adjudication)
              [逐主张最终判定 + 逐意见落实锚点 revised_text_quote 或显式分歧]
                                      │
                                      ▼  verify & export
                来源 SHA-256 哈希、原文唯一 quote 锚点与未读确认核对
                                      │
                                      ▼  原子硬链接写入
                   只读 HTML 报告 / Markdown 报告 / SQLite 审计留痕
```

---

## 核心机制：二维证据分级与八大反空转门控

### 1. 告别单一线性阶梯：`claim_type × evidence_level + scope`（Claim Schema v2）

传统五级阶梯（描述→相关→预测→机制→因果）隐含了“预测不如机制高级、重复多次相关就能升级成因果”的错误诱导。Parrhesia `0.2.0` 改为**12 类主张 × 类型内证据等级 + 适用范围**，并显式区分依据性质 `claim_basis`（`empirical` 经验观测 / `synthetic` 合成示例 / `formal` 形式证明）：

| 主张类型 (`claim_type`) | 类型内证据等级（`evidence_level`，均含最低级 `unassessed`） | 措辞与授权边界 |
| :--- | :--- | :--- |
| **描述** `description` | `recorded` · `measurement_checked` · `replicated` | 仅描述已观察对象，不外推总体或机制 |
| **关联** `association` | `unadjusted` · `adjusted` · `robust_association` | 写“与……相关”；协变量调整或稳健性不等于消除未测混杂 |
| **预测** `prediction` | `apparent` · `internally_validated` · `externally_validated` · `prospectively_evaluated` | 写明目标、时点与人群；外部区分度不自动等于临床效用或因果机制 |
| **因果效应** `causal_effect` | `unidentified` · `identified_under_assumptions` · `sensitivity_supported` | 仅针对指定 `estimand`、设计族与识别假设作因果表述 |
| **机制** `mechanism` | `compatible` · `component_tested` · `causal_chain_tested` | 共表达/富集仅算 `compatible` 线索；完整链条须排查替代通路 |
| **必要性** `necessity` | `bounded_test` · `counterfactual_supported` | 指定背景中移除 $X$ 后 $Y$ 是否仍可发生；**不等于充分性** |
| **充分性** `sufficiency` | `bounded_test` · `counterfactual_supported` | 指定背景中引入 $X$ 能否产生 $Y$；**不等于必要性** |
| **证据综合** `synthesis` | `mapped` · `critically_appraised` · `synthesized_with_uncertainty` | 继承原研究偏倚与依赖结构；合并分析不能凭空制造因果识别 |
| **理论** `theory` | `conjectured` · `proved_under_assumptions` · `independently_checked` | 强制 `claim_basis="formal"`；数值例子不代替证明，定理不直接等同经验事实 |
| **质性** `qualitative` | `situated_description` · `interpretation_audited` · `triangulated` | 保留情境与反例，不强套总体频率、$p$ 值或实验因果 |
| **计算性能** `computational` | `benchmark_measured` · `reproduced` · `externally_evaluated` | 交代数据集、基线、算力与随机种子；榜单表现不等于真实部署收益 |
| **工程** `engineering` | `test_passed` · `host_accepted` · `user_impact` | 单元测试通过不代替真实宿主验收，握手成功不等于用户实际收益 |

> **硬性规则**：
> - `unassessed`、`unidentified`、`conjectured` **严禁给予正向判定**（`supported` / `partially_supported`）。
> - **经验因果授权与观察性条件支持**：经验因果无条件正判定（`supported`）要求干预或准实验证据（`intervention` / `quasi_experiment`）。纯观察性证据（`observation`）若要获得 `causal_effect` 的**条件性支持（`partially_supported`）**，必须同时具备完整 `causal_basis`（明确 `estimand`、识别假设与证伪/敏感度分析均通过并绑定证据）、通过观察性设计包的核心检查（时间顺序、混杂控制、稳健性），并在 `condition` 中显式写明所依赖的不可检验假设。

### 2. 九大设计包、八项统计报告与四类溯源卡

在 L2 台账中，每条主张按实际研究设计挂载结构化记录（理论与质性研究不强套 $p$ 值，未执行的项如实保留 `unknown` 或 `not_run`）：
- **9 个设计包 (`design_packages`)**：`observational`（观察性）、`quasi_experimental`（准实验）、`randomized`（随机实验）、`prediction`（预测）、`ml`（机器学习）、`mechanism`（机制）、`evidence_synthesis`（证据综合）、`theory`（理论）、`qualitative`（质性）。
- **8 项最低统计报告 (`statistical_report`)**：分析单位与独立样本量 (`units_sample_size`)、目标量与尺度 (`estimand_scale`)、效应估计与不确定性区间 (`estimate_uncertainty`)、模型假设 (`model_assumptions`)、缺失与排除 (`missingness_exclusions`)、多重比较与选择过程 (`multiplicity_selection`)、对照与基线直接比较 (`comparisons_baselines`)、稳健性与外推限制 (`robustness_limits`)。
- **4 类溯源卡 (`provenance_cards`)**：`citation`（引文卡）、`number`（数字卡）、`execution`（执行卡）、`search`（检索卡）。
  - **硬绑定与预注册约束**：数字与引文必须来自 `python -m parrhesia record-exec` 或 `reproducible-science`（`results` / `citations` / `repro`）钩子绑定的真实输出；确证性分析前必须先用 `reproducible-science`（`prereg`）或预注册文件冻结分析计划，未事先冻结的一律标 `exploratory`。

### 3. 八大反空转与反橡皮图章机械门控（`gate_version=1`）

为防止模型“空手填 `pass`、理由写 `'ok'`、核心检查填 `not_applicable`、拿无关原文片段充当 `quote`、把观察性数据伪报成 `intervention`”或“双审零意见直接放行”，`0.2.0` 内核在提交时执行严格的确定性交叉核验（拒绝时不推进状态机）：

1. **全包覆盖与逐级递进检查上限 (`check_ceilings` & `FAMILY_TIER_CHECKS`)**：
   - **全部 9 个设计包必选覆盖**：不仅因果、机制、预测、计算与关联受必选检查约束，`theory`（如 `definitions_assumptions`、`proof`）、`qualitative`（如 `epistemic_position`、`sampling_context`、`analysis_audit`）与 `evidence_synthesis`（如 `protocol_search`、`eligibility_selection`、`bias_dependence`）的核心检查同样**严禁用 `not_applicable` 规避**。
   - **相邻证据等级机械区分**：同一 `claim_type` 内的相邻等级绑定严格递进的设计检查、固定检查与统计报告门槛（例如 `association` 中 `unadjusted < adjusted < robust_association` 逐级增加混杂控制与稳健性要求；`causal_effect` 中 `identified_under_assumptions` 要求识别假设通过，而 `sensitivity_supported` 额外强制 `falsification_sensitivity` 与设计包敏感度/稳健性检查通过；`theory`、`qualitative`、`synthesis` 各级亦逐级递进），模型无法靠主观换标签跨级晋升。
2. **证据绑定的实质性 `pass`、中英占位词拦截与裁决交叉引用 (`effective_status`、`is_placeholder` & `uncited_check_evidence`)**：设计包、统计报告与因果识别中任何填 `pass` 的检查项，必须同时具备**非空 `evidence_ids`** 与**实质性理由**（自动拦截 `"ok"`、`"pass"`、`"yes"`、`"done"`、`"TBD"`、`"TODO"`、`"see above"` 及中文 `"未知"`、`"无"`、`"待定"`、`"见上"`、`"同上"`、`"略"`、`"通过"`、`"合格"` 等敷衍占位词，该黑名单同时覆盖 `condition`、`location`、`estimand` 与 `disagreement`）；正向裁决必须显式引用支撑这些必选 `pass` 检查项的证据 ID（遗漏触发 `uncited_check_evidence`）。引文溯源卡冲突检测（`is_contradicting_relation`）不仅匹配 `unsupported`/`contradicts`/`不支持`，还识别 `"does not support"`、`"fails to support"`、`"contrary to"`、`"无法支持"`、`"不足以支持"`、`"与主张矛盾"`、`"证伪"` 等自然语言改写（并排除 `"does not contradict"` / `"不矛盾"` 等双重否定）。
3. **证据类型硬兼容与原文自相矛盾拦截 (`incompatible_evidence_kind` & `contradictory_evidence_kind`)**：正向判定引用的每条证据 `kind` 必须与目标 `claim_type × evidence_level` 兼容；若证据快照原文明确声明了与所报 `kind` 冲突的弱研究设计（如把写明“观察性队列 / 非随机”的原文登记为 `kind="intervention"`，或把“仅内部交叉验证”登记为 `kind="prediction_external"`），门控直接以 `contradictory_evidence_kind` 拒绝。
4. **合成证据隔离 (`synthetic_empirical_support`)**：任何 `kind` 或 `provenance` 为 `synthetic` 的证据，严禁支持 `empirical` 或 `formal` 的正向结论；合成正向演示仅限 `description × recorded` 或 `computational × benchmark_measured`。
5. **中英分权重的唯一原文锚点与主张相关性核验 (`unanchored_positive_evidence` & `unlinked_evidence_quote`)**：正向判定的每条引用需要包含至少 **12 个可见非空白单位（按信息密度区分语种：每个中日韩汉字计 2 单位，即至少 6 个汉字或 12 个 ASCII 字符）** 且在保存的完整原文中**唯一匹配**的 `quote` 与非占位符 `location`，同时该 `quote` 必须与主张文本、效应量/不确定性区间或已核对溯源卡共享定量数值、领域实词或定位锚点（截取文件页眉、版权声明等无关片段将触发 `unlinked_evidence_quote` 拒绝）。
6. **ANSI 终端日志清洗、超 128 KiB 文本自动窗口化与未读确认 (`text_content` & `unread_ack_required`)**：
   - `text_content()` 自动剥离 `record-exec` 常见的 ANSI 颜色/光标控制序列（`\x1b[...m` 等）与终端退格/换页控制符，确保带颜色的测试与实验日志可直接作为可读文本支持正向判定，同时继续拦截 PDF/ZIP/PNG/ELF 头与含 `\x00` 的二进制流。
   - 审查包内联文本上限为 **128 KiB**（控制单次上下文体积的工程预算）：对于超过 128 KiB 的可读 UTF-8 文本，若已登记唯一且与主张关联的 `quote`，引擎会自动以 `quote` 为中心切出 $\le 128\text{ KiB}$ 的可读上下文窗口（`excerpt_window.quote_anchored = true`），在 `unread_evidence_ids` 中显式确认截断状态后即可直接支持正向判定，无需用户手动切分文件；无锚点超长文件与二进制文件则禁止支持正向判定。
7. **逐主张立场全覆盖与单侧 3 条意见聚焦预算 (`incomplete_stances`)**：即使某侧审查者提出的修改意见 `findings` 为 0 条，也必须对每条冻结主张提交 `claim_stances`（评价原命题；`partially_supported` 必须附非占位符的真实条件）。单侧审查每次聚焦最重要的 **0–3 条**实质问题（超出时标记 `needs_split` 要求拆分主张，避免琐碎挑刺淹没核心缺陷）。
8. **实质性意见落实核验、分歧留痕与盲审冻结 (`finding_not_incorporated` & `case_level_blind`)**：标记 `incorporated` 不仅要求 `revised_text_quote`（$\ge 6$ 个汉字或 $\ge 12$ 个 ASCII 字符）在建议文与修订文中唯一出现且不区分大小写地不在原句中，还执行**实质落实核验**：禁止保留原句主体仅在末尾追加无关句子、禁止保留已被 `proposed_text` 删改的受批夸大词项，且 `revised_text`（以及 `partial` 采纳时的 `revised_text_quote`）必须实质吸纳与 `issue`/`decision_impact` 关联的新增替换词项；未改写或偏离建议须显式记为 `resolution="disagreement"`。新案例默认 `blind=true` 并在案例级冻结，报告中显式记录审查者输入清单（`input_manifest`）。

---

## 五分钟快速上手与常用命令

### 1. 运行离线端到端合成演示

无需联网或配置模型，直接体验完整的“建档 → 冻结 → 盲审包生成 → 双审提交 → 裁决 → 锚点验证 → 原子导出”闭环（输出目录须尚不存在）：

```powershell
python -m parrhesia demo --output .\artifacts\my-demo
```
运行后将在 `.\artifacts\my-demo` 下生成交互式只读报告 `review.html`、Markdown 裁决报告、完整调用记录 `workflow-transcript.json` 与 `.parrhesia/state.sqlite3`。*（注：演示数据为预置合成样例，合成证据在门控下仅用于描述性记录演示，临床效用主张被明确判为 `insufficient_evidence`。）*

### 2. 核心 CLI 工具速查

```powershell
# 查看当前运行时版本与完整 JSON 契约
python -m parrhesia contract

# 生成全 unknown / not_run 的诚实 v2 主张骨架，并预览当前检查上限 check_ceilings
python -m parrhesia call scaffold_claim --workspace C:\YourWorkspace --input docs/examples/claim-v2-unknown.json

# 执行本地分析脚本、捕获真实标准输出/错误与退出码、自动登记为 observed 证据并输出 execution 溯源卡
python -m parrhesia record-exec --workspace C:\YourWorkspace --case-id <case_id> --card-id exec-1 -- python your_analysis.py

# 启动 stdio MCP 服务（供宿主客户端挂载）
python -m parrhesia serve --workspace C:\YourWorkspace
```

### 3. 规则单源生成、Stage 0 对照评估与打包验证

```powershell
# 检查所有派生规则文件（AGENTS.md、各宿主模板、SKILL.md、ChatGPT 模板）是否与唯一规则源一致
python scripts/generate-policy.py --check

# 修改 policy/parrhesia-policy.md 后重新生成全部派生文件
python scripts/generate-policy.py

# 运行 Stage 0 机械评估套件（验证 24 个 L2 案例 + 6 个 L1-Explore 案例，并导出 A / B-精简 / B-全文 / E 四组提示词包）
python scripts/run-stage0-eval.py --report-out docs/verification/stage0-evaluation.md
python scripts/run-stage0-eval.py --mode prompt-export --output-dir artifacts/stage0-prompts --report-out docs/verification/stage0-evaluation.md

# 运行完整自动化测试套件（117 项测试：116 通过、1 跳过）
python -m unittest discover -s tests -v

# 构建确定性分发 ZIP 包（自动校验 plugin.json / pyproject.toml / 运行时与兼容清单版本一致性）
python scripts/build-release.py --output dist/parrhesia-0.2.0.zip
```

---

## 自身证据边界声明（Practicing What We Preach）

Parrhesia 坚持“让结论与证据相称”，对自身 `0.2.0` 版本的成熟度同样严格按 `engineering` 与 `computational` 证据等级如实披露：

| 评估维度 | 当前状态与证据定位 | 可支持的结论与客观边界 |
| :--- | :--- | :--- |
| **本地状态机、机械门控与发布一致性**<br>(`engineering × test_passed`，支持) | 117 项自动化测试（116 通过、1 跳过，见 [0.2.0 核验记录](docs/verification/release-0.2.0.md)）；Stage 0 机械套件 24 个 L2 案例与 6 个 `L1-Explore` 探索案例全部通过（见 [Stage 0 评估报告](docs/verification/stage0-evaluation.md)） | 证明本地 SQLite 状态机、v2 逐级递进门控、反橡皮图章硬化（无证据 `pass` 拦截、中英敷衍占位词与冲突短语拦截、9 大设计包必选检查覆盖、ANSI 日志支持与超 128 KiB 引文自动窗口化、实质性意见落实校验，见 [绕过修复核验](docs/verification/gate-bypass-hardening-20261019.md)）、旧版 `LEGACY_UNGATED` 兼容恢复与独立 ZIP 解压启动按契约工作 |
| **多宿主配置同步与历史握手记录**<br>(`engineering × test_passed`，支持；`0.2.0` 原生编排待复验) | `install-codex.py --check`、插件市场清单校验及 [ChatGPT 套件核验](docs/verification/chatgpt-adapter.md)已通过；[Grok 1.0.48 原生握手](docs/verification/grok-native.json)为 `0.1.0` 历史记录 | 证明安装包结构、清单 schema 与本地 MCP 进程握手有效；不把 `0.1.0` 的历史宿主握手记录冒充为 `0.2.0` 真实宿主端到端独立双审已验收 |
| **真实大模型行为净收益对照评估**<br>(`computational × unassessed`，证据不足 / `not_run`) | 已冻结 [对照评价方案](docs/evaluation-plan.md) 并导出 `A_baseline`、`B_compact`、`B_full`、`E_full_l2_workflow` 四臂提示词包，但外部付费 LLM 调用状态为 `not_run` | **尚未在真实盲评保留集上测量**引入 Parrhesia 后模型夸大率、过度免责率与空泛中立率的统计学改善幅度（检出 15–20 个百分点绝对提升预计需 120–160 个独立案例） |
| **确定性交叉门控 vs. 科学语义真理性**<br>(系统固有边界) | 引擎校验 SHA-256 哈希、原文唯一 `quote` 与主张词项/数值关联、设计包逐级必选检查、`pass` 证据 ID 绑定及文本显式 `kind` 冲突，并记录 `input_manifest` | **确定性交叉核验不等于深层科学真理性证明**：门控能拦截无证据 `pass`、敷衍填表、相邻等级混用、无关 `quote` 与显式矛盾的证据 `kind`；但不能脱离外部可复现执行钩子（`record-exec` / `reproducible-science`）独立证伪精心捏造的源文件文本，也不替代深度科学语义同行评审 |

---

## 文档导航

- **核心规范与设计**
  - [唯一规则源 (`policy/parrhesia-policy.md`)](policy/parrhesia-policy.md)：所有规则、档位契约、设计包、校准锚点与生成模板的唯一真源（SSOT）。
  - [产品设计说明 (`docs/product-design.md`)](docs/product-design.md)：三种偏倚解耦原理、模块职责、盲审边界与产品验收分层。
  - [运行时接口契约 (`docs/contract.md`)](docs/contract.md)：Claim Schema v2、`gate_version=1` 机械门控与全部工作流 Action 的输入输出规范。
  - [从 0.1.0 升级说明 (`docs/migration-0.2.md`)](docs/migration-0.2.md)：新旧字段对照、迁移步骤与历史 `LEGACY_UNGATED` 案例兼容策略。
  - [对照评价方案 (`docs/evaluation-plan.md`)](docs/evaluation-plan.md)：Stage 0 探索与正式保留集盲评方案、非劣效检验框架与指标定义。
- **宿主集成与技能**
  - [L2 审查工作流 Skill (`skills/parrhesia-review/SKILL.md`)](skills/parrhesia-review/SKILL.md) · [L2 科学审查参考 Skill (`skills/parrhesia-l2-reference/SKILL.md`)](skills/parrhesia-l2-reference/SKILL.md)
  - [Grok 项目适配指南 (`docs/grok-integration.md`)](docs/grok-integration.md) · [ChatGPT 文字交接指南 (`docs/chatgpt-integration.md`)](docs/chatgpt-integration.md)
  - [仓库精简 `AGENTS.md`](AGENTS.md) · [通用完整规则模板](templates/AGENTS.parrhesia.md) · [Codex 精简模板](templates/AGENTS.parrhesia.codex.md) · [ChatGPT 模板](templates/AGENTS.parrhesia.chatgpt.md)
- **核验与审计记录**
  - [0.2.0 交付核验 (`docs/verification/release-0.2.0.md`)](docs/verification/release-0.2.0.md)
  - [Stage 0 对照评估报告 (`docs/verification/stage0-evaluation.md`)](docs/verification/stage0-evaluation.md)
  - [反空转门控核验 (`docs/verification/anti-stall-gates.md`)](docs/verification/anti-stall-gates.md) · [门控绕过硬化核验 (`docs/verification/gate-bypass-hardening-20261019.md`)](docs/verification/gate-bypass-hardening-20261019.md)
  - [Claim Schema v2 核验 (`docs/verification/claim-schema-v2.md`)](docs/verification/claim-schema-v2.md) · [规则生成核验 (`docs/verification/policy-generation.md`)](docs/verification/policy-generation.md)

---

## 许可证与代码仓库

- **许可协议**：[Apache-2.0 License](LICENSE)
- **代码仓库**：[https://github.com/HERRY423/Parrhesia](https://github.com/HERRY423/Parrhesia)
