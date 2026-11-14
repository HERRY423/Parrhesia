# Parrhesia

**让证据决定表达强度，让裁决结束空泛中立。**

**语言 / Language**：简体中文 · **[English](README.en.md)**

**Parrhesia** 是遵循 [Agent Plugins 1.0.0](https://agent-plugins.org/) 规范的**本地证据校准与独立双审裁决插件**，配套单源生成的跨平台规则体系 `AGENTS.md`。它通过**认知分工解耦**与**确定性本地状态机（零第三方依赖，仅需 Python 3.11+ 标准库）**，解决大模型在科研分析、工程评测与技术决策中常见的“越级夸大、免责通胀、和稀泥”三大顽疾。

> **当前版本：`0.3.0`**（Claim Schema `v2` · 反空转机械门控 `gate_version=1` · SQLite 事件哈希链 `user_version=2`）
> - **最新宿主验收（2026-11-14）**：Windows 11 Codex 桌面端实际加载 `0.3.0`，在固定合成场景下完成伤害方向主张审查/导出、待裁定后继状态保持、校准来源绑定、CLI 失败收据→宿主读回及原生文件符号链接拒绝，达到限定范围 **`engineering × host_accepted`**（详见 [0.3.0 宿主验收摘要](docs/verification/release-0.3.0.md) · [0.3 升级说明](docs/migration-0.3.md) · [版本变更记录](CHANGELOG.md)）。

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

**三条不可逾越的底线**（详见 [唯一规则源](policy/parrhesia-policy.md#唯一优先级)）：
1. **权限与取舍顺序**：平台系统指令 > 平台开发者指令 > 用户消息；在此边界内，**数据保密与花费上限 > 证据真实 > 强度匹配 > 完整表达已支持的贡献 > 效率**。
2. **绝不伪造确定性，也不把缺证据当反证**：严禁编造数据、数字、引文、执行或检索。证据不足时明确判为 `insufficient_evidence`（这是正式结论而非逃避），既不包装成“支持”，也不把“尚无证据”混同于“不支持（`unsupported`）”。
3. **用户期望不是证据**：用户可以决定任务范围、输出格式、语言和流程简化，但不能指定证据等级或判定结果。

---

## 最小化认知负担：四档渐进工作流（`L0` / `L1` / `L1-Explore` / `L2`）

Parrhesia **不为简单任务制造流程负担，也不在关键结论上放水**。日常使用无需记住复杂的工具参数，Agent 会按任务性质自动分流并在首行标明当前档位：

| 档位标签 | 适用场景 | 交互体验与输出要求 | 是否动用数据库与双审？ |
| :--- | :--- | :--- | :--- |
| **`[L0]`** | 翻译、排版、单一可核对事实、局部代码修改、纯数值计算 | **直接给结果**，零额外结构与标签负担 | 否 |
| **`[L1]`**<br>*(默认)* | 日常解释、方案比较、证据判断、阶段性小结 | 自然组织内容，包含五要素：**① 开头给判定与 `claim_type × evidence_level + scope` · ② 可核对依据与最强竞争解释 · ③ 可观察改判条件 · ④ 下一步动作 · ⑤ 底线失败例外**（通过项不啰嗦） | 否（轻量内联自查） |
| **`[L1-Explore]`** | 头脑风暴、假说生成、机制推演、实验/统计识别设计 | 维护 **2–3 张轻量探索假说卡**（显式标 `exploratory`），每张卡固定五项：**① 最强对手 · ② 区分实验 · ③ 成本 · ④ 停止规则 · ⑤ 杀死条件** | 否（释放探索推演空间） |
| **`[L2]`** | 写入图注/摘要/正文/汇报/投稿材料、正式审查核心论点、回应质疑 | **每次仅审 3–5 条核心主张**（不审全文）：建档登记证据 → 冻结盲审包 → 两个干净上下文独立执行夸大/低估审查 → 主代理逐条裁决 → 溯源校验并原子导出报告 | **是**（SQLite 持久状态机 + 机械门控） |

> 💡 **推荐的日常使用心法**：
> **探索阶段全程用 `L1-Explore`** 快速收敛假说与证伪实验 → **确证阶段只把 3–5 条核心主张送入 `L2`** → 只有写入图注、摘要、正文或正式汇报时才走完整双审。

---

## 安装与多平台接入指南

运行本地 MCP 服务与 CLI 仅需 **Python 3.11+**（纯标准库实现，**零第三方依赖**，无需 `pip install` 任何外部包）。

### 方式一：Codex 插件市场安装（图形界面 / CLI）

#### 1. 图形界面“添加插件市场”（推荐）

在 Codex 桌面端的插件管理页面点击 **添加插件市场**（*从 GitHub 仓库、Git URL 或本地文件夹添加*），按弹窗字段填写：

| 弹窗字段 | 填写内容 | 说明 |
| :--- | :--- | :--- |
| **来源** | `HERRY423/Parrhesia`<br>*(或 `https://github.com/HERRY423/Parrhesia.git`)* | 若使用离线包或本地克隆，可直接选择包含 `.agents/plugins/marketplace.json` 的本地仓库根目录（如 `C:\Parrhesia`） |
| **Git 引用** | `main` | 使用主分支获取最新 `0.3.0` 更新；如需固定版本可填写对应 commit 或 tag |
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

Codex 采用“**常驻精简规则块（`< 10 KiB`） + 按需加载 `parrhesia-l2-reference` 技能 + 角色包隔离双审**”架构，避免常驻近 `48 KiB` 全文规则挤占日常上下文：

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

支持 Agent Plugins 1.0.0 规范的宿主可直接加载根目录 `plugin.json`、`mcp.json` 与 `skills/`，通过 stdio MCP 自动发现 **22 个本地工具**、只读资源与角色提示词：
- **18 个按动作划分的强类型工具（`parrhesia_<action>`）**：覆盖完整生命周期（`create_case`、`register_evidence`、`register_hypothesis`、`scaffold_claim`、`set_ledger`、`freeze`、`review_packet`、`submit_review`、`adjudication_packet`、`submit_adjudication`、`verify`、`get_case`、`export`、`record_human_decision`、`claim_graph`、`evaluate_triggers`、`record_calibration_outcome`、`calibration_report`），各带独立 JSON Schema 与权限注解。
- **`parrhesia_validate`**：零副作用只读预检工具（在 SQLite 事务内试运行并自动 `ROLLBACK`，失败时返回结构化修复建议 `repair_hint`）。
- **3 个向后兼容通用工具**：`parrhesia_contract`、`parrhesia_select_workspace`、`parrhesia_workflow`。
- **只读 MCP 资源与角色 Prompt 模板**：资源 `parrhesia://contract`、`parrhesia://cases`、`parrhesia://claim-graph`、`parrhesia://calibration`，模板 `parrhesia://cases/{case_id}`、`/ceilings`、`/triggers`、`/packet/{role}`，以及角色提示词 `parrhesia_review_overclaim`、`parrhesia_review_underclaim`、`parrhesia_adjudicate`。

---

### 方式三：Grok Build CLI 项目级适配

针对 Grok Build CLI，提供幂等安装脚本，同步 `parrhesia-review` 与 `parrhesia-l2-reference` 双技能、自动备份已有文件、安全合并项目 `.mcp.json`，并维护默认精简 `AGENTS.md` 规则块（可通过 `--policy full` 切换全文）：

```powershell
# 安装到目标项目（或运行 & .\scripts\install-grok.ps1 -Project C:\YourProject）
python scripts/install-grok.py --project C:\YourProject

# 只读校验文件哈希、MCP 配置、双技能与来源一致性，或安全卸载
python scripts/install-grok.py --project C:\YourProject --check
python scripts/install-grok.py --project C:\YourProject --uninstall

# 在项目内检验 Grok 配置发现
grok --cwd C:\YourProject inspect
```
*详见 [Grok 接入说明](docs/grok-integration.md)。*

---

### 方式四：Antigravity 宿主工程适配

针对 Google Antigravity（Antigravity IDE / Antigravity 2.0 / `agy` CLI），提供自含工程适配器，生成合规的 `.agents/plugins/parrhesia/` 插件包（严格白名单 `plugin.json`、`mcp_config.json`、`< 24,000 B` 无 frontmatter 精简 `rules/parrhesia.md`、双技能及静默只读 `SessionStart` SQLite 状态钩子），绝不触碰 `~/.gemini/config/config.json`：

```powershell
# 安装到目标项目（或运行 & .\scripts\install-antigravity.ps1 -Project C:\YourProject）
python scripts/install-antigravity.py --project C:\YourProject

# 只读校验规范上限与完整性 / 安全卸载 / 安装到显式隔离目录
python scripts/install-antigravity.py --project C:\YourProject --check
python scripts/install-antigravity.py --project C:\YourProject --uninstall
python scripts/install-antigravity.py --scope user --target C:\CustomAntigravityHome
```
*详见 [Antigravity 接入说明](docs/antigravity-integration.md)。*

---

### 方式五：ChatGPT 网页端 / 自定义 GPT 纯文字协议（零本地依赖）

无需本地运行 Python 或 MCP，即可在网页端通过多会话隔离运行 L2 双审协议：
1. 将 [ChatGPT 规则模板](templates/AGENTS.parrhesia.chatgpt.md) 粘贴至 ChatGPT Project Instructions 或 Custom GPT Instructions。
2. 生成标准交接模板套件（输出目录须尚不存在）：
   ```powershell
   python scripts/prepare-chatgpt.py --output artifacts/chatgpt-kit
   ```
3. 按 [ChatGPT 接入说明](docs/chatgpt-integration.md) 执行跨会话交接：`01-frozen-input.md`（或盲审版 `01-frozen-input-blind.md`）冻结台账 → 分别在两个新建独立会话中粘贴 `02-overclaim.md` 与 `03-underclaim.md` → 回到主会话用 `04-adjudication.md` 裁决 → 用 `05-handoff-record.md` 归档。

---

## 核心功能与架构设计（`0.3.0` 四大支柱）

### 支柱一：二维证据坐标 `claim_type × evidence_level + scope`（告别单一线性阶梯）

传统五级阶梯（描述→相关→预测→机制→因果）错误地暗示“预测低人一等”或“多次相关就能升格为因果”。Parrhesia 采用 **12 类主张 × 类型内证据等级 + 适用范围**，并显式区分依据性质 `claim_basis`（`empirical` 经验观测 / `synthetic` 合成示例 / `formal` 形式证明）：

| 主张类型 (`claim_type`) | 类型内证据等级（均含最低级 `unassessed`） | 措辞与授权边界 |
| :--- | :--- | :--- |
| **描述** `description` | `recorded` · `measurement_checked` · `replicated` | 仅描述已观察对象，不外推总体或机制 |
| **关联** `association` | `unadjusted` · `adjusted` · `robust_association` | 写“与……相关”；协变量调整或稳健性不等于消除未测混杂 |
| **预测** `prediction` | `apparent` · `internally_validated` · `externally_validated` · `prospectively_evaluated` | 写明目标、时点与人群；外部区分度不等于临床效用或因果机制 |
| **因果效应** `causal_effect` | `unidentified` · `identified_under_assumptions` · `sensitivity_supported` | 仅对指定 `estimand`、设计族与识别假设作因果表述 |
| **机制** `mechanism` | `compatible` · `component_tested` · `causal_chain_tested` | 共表达/富集仅算 `compatible` 线索；完整链条须排查替代通路 |
| **必要性** `necessity` | `bounded_test` · `counterfactual_supported` | 指定背景移除 $X$ 后 $Y$ 是否仍可发生；**绝不等于充分性** |
| **充分性** `sufficiency` | `bounded_test` · `counterfactual_supported` | 指定背景提供 $X$ 能否产生 $Y$；**绝不等于必要性** |
| **证据综合** `synthesis` | `mapped` · `critically_appraised` · `synthesized_with_uncertainty` | 继承原研究偏倚与依赖结构；合并分析不能凭空制造因果识别 |
| **理论** `theory` | `conjectured` · `proved_under_assumptions` · `independently_checked` | 强制 `claim_basis="formal"`；数值例子不代替证明 |
| **质性** `qualitative` | `situated_description` · `interpretation_audited` · `triangulated` | 保留情境与反例，不强套总体频率或显著性 $p$ 值 |
| **计算性能** `computational` | `benchmark_measured` · `reproduced` · `externally_evaluated` | 交代数据集、同预算基线与随机种子；榜单表现不等于真实部署收益 |
| **工程** `engineering` | `test_passed` · `host_accepted` · `user_impact` | 单元测试通过不代替真实宿主验收，握手成功不等于用户实际收益 |

- **命题支持与效应方向解耦**：`supported` 代表**所陈述命题获得证据支持**，不默认等于“正向获益（`benefit`）”。伤害（`harm`）或零效应命题在证据扎实且 `claim_direction` 与实测一致时同样可获 `supported`；方向相反则被确定性拦截。
- **经验因果与观察性条件支持**：无条件 `supported` 的经验因果要求干预或准实验证据（`intervention` / `quasi_experiment`）；纯观察性证据若具备完整 `causal_basis`（明确 `estimand`、识别假设与证伪/敏感度分析均通过并绑定证据）、通过观察性设计包核心检查，且在 `condition` 中写明所依赖的不可检验假设，可获 **`partially_supported`（条件性支持）**。

---

### 支柱二：结构化科学底盘与可计算效应核验（`effect_records`）

在 `L2` 台账中，可用 `scaffold_claim` 一键生成全 `unknown` / `not_run` 的诚实主张骨架，按实际研究设计挂载结构化记录：
- **9 大设计包 (`design_packages`)**：`observational`、`quasi_experimental`、`randomized`、`prediction`、`ml`、`mechanism`、`evidence_synthesis`、`theory`、`qualitative`。各包核心检查严禁用 `not_applicable` 规避，同一类型内相邻等级绑定逐级递进的检查门槛。
- **8 项统计报告 (`statistical_report`) 与 4 类溯源卡 (`provenance_cards`)**：覆盖样本量/独立重复单位、目标量与尺度、效应与不确定性、模型假设、缺失排除、多重比较、基线直接比较与稳健性限制；挂载 `citation`、`number`、`execution`、`search` 四类溯源卡。
- **可计算效应核验 (`effect_records`)**：显式分离主终点（`primary` / `benchmark`）与次要/安全/探索终点（`secondary` / `safety` / `exploratory` / `sensitivity`），在声明适用前提下执行确定性核验：
  - **区间与 $p$ 值自洽性**：对显式声明匹配双侧未调整 `inference_method="wald" | "log_wald"` 的记录，校验点估计、置信区间与 $p$ 值数学兼容性（其他或未声明方法诚实记为 `unassessed`，不伪造通过）。
  - **GRIM 与整数分母粒度校验**：对声明 `count_basis="unweighted_binary"` 的比例/准确率指标，校验样本量 $n$、事件数与小数位数的整数可实现性。
  - **主终点跨零值拦截与次要终点解耦**：有方向的 `primary` / `benchmark` 命题若置信区间越过无效值（`primary_effect_crosses_null`）则阻断正向判定；已验证的主终点获益允许搭配无显著差异的 `secondary` / `safety` 终点。

---

### 支柱三：反空转与反橡皮图章机械门控（`gate_version=1`）

```text
初稿 + 原始证据文件快照 (防符号链接/越界) + 诚实主张骨架 (scaffold_claim) + 结论台账 (Ledger v2)
                                      │
                                      ▼  freeze（计算 SHA-256 修订摘要，案例级锁定 blind=true）
                    ┌─────────────────┴─────────────────┐
                    ▼ 独立干净上下文 1                  ▼ 独立干净上下文 2
          夸大审查包 (Overclaim Packet)       低估审查包 (Underclaim Packet)
          [0–3 条实质问题 + 逐主张 stance]    [0–3 条实质问题 + 逐主张 stance]
                    └─────────────────┬─────────────────┘
                                      ▼  双审齐备（任一侧 >3 条实质问题则 needs_split 阻塞拆分）
                            单一裁决 (Adjudication)
              [逐主张最终判定 + 逐意见实质改写锚点 revised_text_quote 或显式分歧]
                                      │
                                      ▼  verify & export（确定性门控 + 非阻塞 symmetry_audit）
                只读 HTML 报告 / Markdown 报告 / SQLite 事件哈希链留痕
```

为防止模型“空手填 `pass`、理由写 `'ok'`、截取页眉充当引用、嘴上说采纳却不改正文”，内核在提交时执行严格的确定性拦截（拒绝时不推进状态机）：

| 门控维度 | 拦截的典型作弊 / 空转行为 | 确定性核验机制 |
| :--- | :--- | :--- |
| **证据绑定与反占位符** | 填 `pass` 却无证据 ID，或理由写 `"ok"` / `"通过"` / `"见上"` / `"TBD"` | 所有 `pass` 检查必须含非空 `evidence_ids` 与实质理由；正向裁决必须显式引用支撑必选检查的证据 ID（`uncited_check_evidence`） |
| **证据类型与合成隔离** | 把观察性数据标为 `intervention`；拿 `synthetic` 合成数据支撑真实经验结论 | 强校验 `kind` 与 `claim_type × evidence_level` 兼容矩阵；合成证据正判定仅限 `description × recorded` 与 `computational × benchmark_measured` |
| **唯一原文锚点与词项关联** | 编造引用或随便截取一段无关页眉/版权声明凑数 | 正向引用须含 $\ge 6$ 个汉字或 $\ge 12$ 个 ASCII 可见字符、在原文**唯一匹配**的 `quote`，且必须与主张共享定量数值、领域实词或溯源卡定位（`unlinked_evidence_quote`） |
| **大文本四角色分窗与血缘** | 日志含 ANSI 颜色码被拒；$>128\text{ KiB}$ 长文件尾部反证被截断掩盖；派生表洗白合成祖先 | 自动剥离 ANSI 控制序列；超 $128\text{ KiB}$ 文本凭唯一 `quote` 生成保留头部元数据、主引用、锚点与**尾部摘要**的预算内窗口；`derived_from_evidence_ids` 追踪上游哈希与合成属性 |
| **实质性意见落实与对称审计** | 标记 `incorporated` 却原封不动保留原句或只改虚词；无反证却一味降级弃权 | 要求 `revised_text_quote` 在建议文与修订文中唯一出现、不在原句中，并实质替换受批词项，否则须记为 `disagreement`；同时输出**非阻塞** `symmetry_audit` 提示过度免责与空弃权 |

---

### 支柱四：零泄漏执行溯源、跨时间主张图谱与事后概率校准

1. **无密钥泄漏的命令溯源与防篡改事件链（`record-exec` & `events` Hash Chain）**
   - `python -m parrhesia record-exec` 自动采集执行命令、Git 提交/脏状态、锁文件哈希、运行前后 `--input-file` / `--output-file` SHA-256，以及环境变量**存在性标记（仅记录键名状态，绝不写入密钥值）**。
   - **失败收据保留**：命令超时（返回码 `124`）、启动失败（返回码 `127`）或非零退出均保留持久失败日志、证据快照与事件记录，绝不覆盖历史日志；引擎按 `claim_id` / `run_group` 拦截隐藏失败分支（`selective_execution_omission`）与未校正多分支择优（`unadjusted_execution_multiplicity`）。
   - **SQLite 事件哈希链（`PRAGMA user_version = 2`）**：每条案例事件记录 `prev_event_hash` 与 `event_hash`，在 `verify` 与 `get_case` 中实时核验 `event_chain_status`（`verified` / `legacy_unhashed` / `mixed_verified` / `tampered`）。
2. **跨时间主张演化图谱（`claim_graph`）与可执行改判触发器（`reversal_triggers`）**
   - **只追加纵向 DAG**：通过 `prior_case_ids`、`supersedes_case_id` 与主张级 `prior_claim_links`（`replicates` / `refines` / `narrows` / `extends` / `supersedes` / `reverses` / `refutes`）串联后续研究，**绝不篡改已冻结旧案**。草稿、冻结中或待裁定的后继关系保持 `pending`，仅在后继完成有效裁决后更新 `active_standing`。
   - **5 类可执行改判触发器**：支持 `effect_metric`、`check_status`、`evidence_status`、`execution_outcome`、`replication_verdict` 五类精确谓词，裁决时拦截自相矛盾的当期自触发（`self_triggering_reversal_condition`），随访时通过 `evaluate_triggers` 判定 `fired` / `unfired` / `pending_data`。
3. **来源绑定的事后概率校准（`record_calibration_outcome` & `calibration_report`）**
   - 裁决可附 `[0.0, 1.0]` 显式 `forecast_probability`；事后通过只追加的 `record_calibration_outcome` 登记复现结局（必须绑定已核对的 `external_evidence` 或有效裁决的 `follow_up_case`；未绑定或失效来源保持 `pending`，不计入已解析评分）。
   - `calibration_report` 严格将**显式预测概率的恰当评分**（`explicit_brier_score` / `explicit_log_score`、5 档可靠性分箱 `ECE`/`MCE`）与**定性置信度启发式映射**（`heuristic_scores`）分栏，并将**已知真值区间覆盖率（`known_truth`）**与**复现点估计包含率（`replication_point_containment_rate`）及前提齐备下的 `z_difference`** 严格分栏。

---

## 五分钟快速上手与常用命令

### 1. 体验离线端到端演示（零配置）

无需联网或配置大模型，直接运行内置合成案例，体验完整的“建档 → 冻结 → 盲审包生成 → 双审提交 → 裁决 → 锚点验证 → 原子导出”闭环（输出目录须尚不存在）：

```powershell
python -m parrhesia demo --output .\artifacts\my-demo
```
运行后将在 `.\artifacts\my-demo` 下生成交互式只读报告 `review.html`、Markdown 裁决报告、完整调用记录 `workflow-transcript.json` 与 `.parrhesia/state.sqlite3`。

### 2. 日常核心 CLI 速查

```powershell
# 查看当前运行时版本与完整 JSON 契约
python -m parrhesia contract

# 生成全 unknown / not_run 的诚实 v2 主张骨架（可附 include_effect_records 预览门控上限 check_ceilings）
python -m parrhesia call scaffold_claim --workspace C:\YourWorkspace --input docs/examples/claim-v2-unknown.json

# 执行本地分析脚本、自动采集 git/lockfile/输入输出哈希与非密钥环境标记，并生成隔离的 execution 溯源卡
python -m parrhesia record-exec --workspace C:\YourWorkspace --case-id <case_id> --claim-id C1 --card-id exec-1 --input-file data/clean.csv --output-file results/metrics.json -- python your_analysis.py

# 启动本地 stdio MCP 服务（供宿主客户端挂载）
python -m parrhesia serve --workspace C:\YourWorkspace
```

<details>
<summary><b>🔧 开发者命令：规则单源生成、Stage 0 评估套件与分发打包（点击展开）</b></summary>

```powershell
# 1. 检查或重新生成所有派生规则文件（AGENTS.md、各宿主模板、SKILL.md、ChatGPT 模板）
python scripts/generate-policy.py --check
python scripts/generate-policy.py

# 2. 运行零泄漏静态审计与 Stage 0 机械评估套件
python scripts/check-eval-leakage.py --strict
python scripts/run-stage0-eval.py --mode mechanical --report-out docs/verification/stage0-evaluation.md
python scripts/run-stage0-eval.py --mode counterfactual
python scripts/run-stage0-eval.py --mode fork-multiplicity
python scripts/run-stage0-eval.py --mode symmetry
python scripts/run-stage0-eval.py --mode lineage-window
python scripts/run-stage0-eval.py --mode heldout
python scripts/run-stage0-eval.py --mode metamorphic
python scripts/run-stage0-eval.py --mode p1-effects
python scripts/run-stage0-eval.py --mode p2-longitudinal
python scripts/run-stage0-eval.py --mode prompt-export --output-dir artifacts/stage0-prompts

# 3. 运行自动化单元测试套件
python -m unittest discover -s tests -v

# 4. 构建确定性分发 ZIP 包（自动校验所有清单与运行时版本一致性）
python scripts/build-release.py --output dist/parrhesia-0.3.0.zip
```
</details>

---

## 自身证据边界声明（Practicing What We Preach）

Parrhesia 坚持“让结论与证据相称”，对自身 `0.3.0` 版本的成熟度同样严格按 `engineering` 与 `computational` 证据等级如实披露：

| 评估维度 | 当前等级与判定 | 已核实的证据与明确边界 |
| :--- | :--- | :--- |
| **Windows Codex 桌面宿主集成与原生符号链接拒绝**<br>(`engineering × host_accepted`，**支持**；限定范围) | 2026-11-14 于 Windows 11 + Python 3.13.9 + Codex 桌面端实际加载 `0.3.0` 冻结包（[验收摘要](docs/verification/release-0.3.0.md)）：完成伤害方向（`harm`）主张审查/裁定/导出、待裁定后继状态保持 `pending`、校准来源核验与失效剔除、CLI 超时/启动失败/非零退出收据→宿主读回，以及开启开发者模式后原生文件符号链接拒绝（原测试 1 通过、0 跳过；拒绝前后证据与事件零变动） | 证明在所测 Windows Codex 桌面会话与固定合成材料下，本地 MCP 工具链、状态机、事件哈希链与路径安全边界按契约运行。**边界**：角色内容为同上下文固定合成 fixture，不代表独立模型科学审查、其他宿主平台验收、全部 reparse point/并发竞态覆盖或真实用户净收益（`user_impact`） |
| **本地状态机、机械门控、可计算效应、纵向校准与多宿主适配测试**<br>(`engineering × test_passed`，**支持**) | `0.3.0` 修复了命题支持与获益方向解耦、统计检查显式前提（`wald`/`log_wald` 与 `unweighted_binary`）、草稿后继 `pending` 状态、结局来源硬绑定、显式概率与启发式映射分栏、真值覆盖率与复现点包含率分栏及超时/启动失败收据保留（[0.3 升级说明](docs/migration-0.3.md)）。修复前历史快照包含 184 项单元测试与 Stage 0 五栏评估套件（[Stage 0 报告](docs/verification/stage0-evaluation.md) · [0.2.0 核验](docs/verification/release-0.2.0.md)） | 证明 SQLite ACID 事务、`events` SHA-256 哈希链、22 个 MCP 工具（含 `parrhesia_validate` 预检与 `repair_hint`）、反橡皮图章门控（[绕过硬化核验](docs/verification/gate-bypass-hardening-20261019.md)）及 Codex / Claude / Grok / Antigravity / ChatGPT 适配器结构与契约校验有效。历史快照数字不直接冒充每次修复后的重跑计数 |
| **真实大模型行为净收益对照评估**<br>(`computational × unassessed`，**证据不足** / `not_run`) | 已冻结 [对照评价方案](docs/evaluation-plan.md) 并导出经零泄漏审计的四臂盲评提示词包（`A_baseline`、`B_compact`、`B_full`、`E_full_l2_workflow`，共 `279` 份），但外部付费 LLM 盲评调用状态为 `not_run` | **尚未在真实盲评保留集上测量**引入 Parrhesia 后模型夸大率、过度免责率与空泛中立率的统计学改善幅度（检出 15–20 个百分点绝对提升预计需 120–160 个独立案例） |
| **确定性交叉门控 vs. 科学语义真理性**<br>*(系统固有架构边界)* | 引擎核验文件 SHA-256、唯一原文 `quote` 与主张词项/数值关联、设计包逐级必选检查、`pass` 证据绑定、显式研究设计冲突及 `input_manifest` | **确定性交叉核验不等于深层科学真理性证明**：门控能拦截敷衍填表、无证据 `pass`、相邻等级混用与未绑定结局，但不能脱离可复现执行链路独立识别精心伪造的原始文件，也不替代领域同行评审 |

---

## 文档导航

- **核心规范与契约**
  - [唯一规则源 (`policy/parrhesia-policy.md`)](policy/parrhesia-policy.md) · [产品设计说明 (`docs/product-design.md`)](docs/product-design.md) · [运行时接口契约 (`docs/contract.md`)](docs/contract.md)
  - [0.3.0 升级说明 (`docs/migration-0.3.md`)](docs/migration-0.3.md) · [0.2.0 升级说明 (`docs/migration-0.2.md`)](docs/migration-0.2.md) · [对照评价方案 (`docs/evaluation-plan.md`)](docs/evaluation-plan.md)
- **宿主集成与技能**
  - [L2 审查工作流 Skill (`skills/parrhesia-review/SKILL.md`)](skills/parrhesia-review/SKILL.md) · [L2 科学审查参考 Skill (`skills/parrhesia-l2-reference/SKILL.md`)](skills/parrhesia-l2-reference/SKILL.md)
  - [Antigravity 接入说明 (`docs/antigravity-integration.md`)](docs/antigravity-integration.md) · [Grok 接入说明 (`docs/grok-integration.md`)](docs/grok-integration.md) · [ChatGPT 接入说明 (`docs/chatgpt-integration.md`)](docs/chatgpt-integration.md)
  - [仓库精简 `AGENTS.md`](AGENTS.md) · [通用完整规则模板](templates/AGENTS.parrhesia.md) · [Codex 精简模板](templates/AGENTS.parrhesia.codex.md) · [ChatGPT 模板](templates/AGENTS.parrhesia.chatgpt.md)
- **核验与审计记录**
  - [0.3.0 桌面宿主验收摘要 (`docs/verification/release-0.3.0.md`)](docs/verification/release-0.3.0.md) · [0.2.0 交付核验 (`docs/verification/release-0.2.0.md`)](docs/verification/release-0.2.0.md)
  - [Stage 0 对照评估报告 (`docs/verification/stage0-evaluation.md`)](docs/verification/stage0-evaluation.md) · [反空转门控核验 (`docs/verification/anti-stall-gates.md`)](docs/verification/anti-stall-gates.md) · [门控绕过硬化核验 (`docs/verification/gate-bypass-hardening-20261019.md`)](docs/verification/gate-bypass-hardening-20261019.md)

---

## 许可证与代码仓库

- **许可协议**：[Apache-2.0 License](LICENSE)
- **代码仓库**：[https://github.com/HERRY423/Parrhesia](https://github.com/HERRY423/Parrhesia)
