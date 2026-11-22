# ChatGPT 项目与自定义 GPT 适配

本适配提供可复制的指令和双审交接模板；无需 API key，也不需要安装 Python 就能手动使用。它不自动配置账户、不上传资料、不部署远程 MCP，也不会因为粘贴指令而运行本地 SQLite 引擎。ChatGPT 原生流程验收为 **NOT_RUN**，模型收益为 **NOT_MEASURED**。

## 三步开始

1. 把 [ChatGPT 指令](../templates/AGENTS.parrhesia.chatgpt.md) 的正文粘贴到所选项目的指令，保留项目已有规则。文件名只是仓库命名约定，不依赖 ChatGPT 自动读取 AGENTS.md。
2. 在主会话中描述任务。一般判断默认 L1；正式审查时再提供套件内的 [L2 参考](../skills/parrhesia-l2-reference/SKILL.md)，**默认用盲审版模板** [01-frozen-input-blind.md](../templates/chatgpt/01-frozen-input-blind.md)（`blind=true`，不含初稿正文、当前最佳解释与区分检验设计，避免起草叙事与押注先入为主）整理 3–5 条核心主张与可读证据；仅在明确需要审查初稿全文时，才改用非盲审版 [01-frozen-input.md](../templates/chatgpt/01-frozen-input.md)。资料仍需用户授权提供给 ChatGPT。
3. 由操作者将同一冻结资料分别配上 [夸大提示词](../templates/chatgpt/02-overclaim.md) 和 [低估提示词](../templates/chatgpt/03-underclaim.md)（两份提示词均自含 12 类 `claim_type × evidence_level` 枚举与 AUROC 0.84 校准锚点，独立会话无需再加载主指令），交给两个干净会话。两份反馈原样带回主会话，按 [裁决提示词](../templates/chatgpt/04-adjudication.md) 处理（含 4 项手工 `symmetry_audit` 反误弃权核对、`≥ 6 个汉字或 ≥ 12 个 ASCII 可见字符` 引用锚点及观察性因果条件支持规则）。

可直接在主会话发送：

> 请按 Parrhesia L2 文字协议整理这份材料的 3–5 条核心主张，默认按盲审版 `01-frozen-input-blind.md` 生成同版本的夸大/低估审查包。暂不替两位审查者回答；我会分别交接后把反馈带回。保留未知和反证，不执行新分析。

请同时保存 [交接记录](../templates/chatgpt/05-handoff-record.md)。缺少一侧、版本不一致或证据未读时，不宣布完成双审。此处的 Markdown 格式面向人工交接，**不是** `submit_review` 的 JSON 入参；如以后接入真实工具，应按运行时契约转换并校验，不伪造工具包标识或摘要哈希。

## 文字模式溯源（`session_anchored` 与 Code Interpreter）

[L2 参考](../skills/parrhesia-l2-reference/SKILL.md) 将数字与引文溯源分为三级：`tool_bound`（命令行 `record-exec` 或钩子绑定的哈希核对输出）、`session_anchored`（文字协议 / ChatGPT 适用）与 `unanchored`（未核实记忆或推算，一律标 `未知`/`未核实`）。

在没有本地命令行工具的 ChatGPT 环境中，**以下两类来源属于授权的 `session_anchored` 溯源**，无需因为缺少 `record-exec` 而全部判为 `UNKNOWN`：

- **Code Interpreter 实测标准输出（stdout）**：在同一轮实际运行 Python 沙盒计算得到的统计量、区间、检验结果或表图摘要，需保留输入范围、计算方式与输出定位。
- **用户逐字提供的原文摘录或表格定位**：来自用户授权上传文件或粘贴原文的精确摘录、页码、表号或行号，且与主张中的数值/实体可核对关联。

文字模式记录 `session_anchored` 证据时，须显式标注“无机械哈希核对”，不冒充 `tool_bound` 哈希校验或本地引擎门控。

## 项目上下文与审查隔离

官方说明 ChatGPT 项目内的聊天共享项目文件、指令和连接来源；同时默认账户级的记忆（Memory）与历史会话引用可能造成跨会话串扰。[官方项目说明](https://learn.chatgpt.com/docs/projects)

低摩擦的推荐隔离操作：

1. **主起草项目开启 Project-Only Memory**：将起草资料、项目指令与迭代历史限制在该项目内，避免泄漏到全局账户记忆。
2. **两位审查者使用两个关闭个性化的临时聊天（Unpersonalized Temporary Chat）**：在起草项目之外分别开启两个临时聊天（关闭个性化记忆与历史聊天引用），每个临时聊天仅发送自己的角色提示词（`02-overclaim.md` 或 `03-underclaim.md`）、同版本盲审冻结资料（`01-frozen-input-blind.md`）与必要附件。

仍须核对实际记忆、历史引用、自动上下文和知识库设置并在 `05-handoff-record.md` 如实记录；不能仅凭“项目外”或模型自述断言完成隔离。不要把两个角色的提示词、两份反馈或整个起草聊天一起上传到审查项目或同一个 GPT 知识库。没有宿主可核对的隔离证据时记录“独立性未验证”；在同一会话依次扮演两角色则仅在报告开头显式标明一次“非独立审查，未排除起草偏差”（遵循同一限制只说一次）。文字协议的记录由操作者保存，不具备数据库冻结与状态门禁。

## 自定义 GPT

账户仍提供自定义 GPT 编辑器时，将相同的 ChatGPT 指令放入 Instructions，把通用交接模板作为参考资料；任务证据按次提供给相应会话。官方文档将 instructions、knowledge 和外部 actions 区分为不同配置；本适配仅使用前两类，不要求配置 Actions。[官方说明](https://developers.openai.com/api/docs/actions/introduction)

起草 GPT 的知识库不得直接复用于两位审查者；可分别使用只有角色提示词、无起草知识的 GPT，仍须记录实际上下文条件。入口是否可用以账户界面为准。若当前账户引导从自定义 GPT 迁移到插件，应按官方迁移流程核对迁移后的指令与文件；本套模板不表示完成该迁移或获得插件商店验收。[官方迁移说明](https://learn.chatgpt.com/docs/migrate-custom-gpts)

建议开场语：

- “先用 L1 判断这条结论，给出改判条件。”
- “为正式审查准备同版本的两份角色包。”
- “核对这两份反馈的版本与覆盖，再逐条裁决。”

## 本地生成交接套件（可选）

在仓库或完整分发 ZIP 的解压目录运行：

```powershell
python scripts/prepare-chatgpt.py --output artifacts/chatgpt-kit
```

输出目录必须尚不存在。命令仅复制白名单中的通用模板、本文和开始说明，写入 `KIT-MANIFEST.json`；不会读取研究工作区、案例数据库、账户设置或聊天日志，也不会联网。输出保持 `templates/` 与 `docs/` 目录结构，打开 `START-HERE.md` 即可。不要把整个套件发送给某一侧审查者；每侧只接收自己的提示词与填写好的共同冻结资料。

维护规则时只编辑仓库的 `policy/parrhesia-policy.md` 并运行 `python scripts/generate-policy.py`。生成命令会先核对源文件与派生指令的一致性；交付给用户的套件仍可直接复制使用，无需运行生成器。用户填写的冻结资料是任务记录，不是需要重新生成的规则文件。

清单的 SHA-256 仅标识**空白套件文件**，不标识用户后来填写的冻结材料，不证明模型行为、上下文隔离或人类接受。生成之后修改模板不会自动更新清单。

## 验收范围

本地测试检查白名单复制、内容摘要、已有输出不覆盖，以及完整分发 ZIP 解压后能生成套件。真实 ChatGPT 中的指令遵循、文件读取、双侧交接和用户收益需单独验收，不能用本地测试替代。

可由用户用一份已授权的公开或合成材料检查：两侧收到的主张/证据是否同版本，是否泄露另一侧意见，缺失证据是否保留 UNKNOWN，版本不匹配是否停止裁决，未明确接受时是否保留“未记录用户接受”。记录实际失败；合成任务通过仍不证明真实研究收益。本文的官方来源核对日期为 2026-10-16。
