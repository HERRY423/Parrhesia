# Parrhesia

**让证据决定表达强度，让裁决结束空泛中立。**

Parrhesia 是遵循 [Agent Plugins 1.0.0](https://agent-plugins.org/) 的本地审查插件，配套 AGENTS.md。它将三类问题分给不同环节：夸大审查检查越级和理想化，低估审查找出无根据的退缩与被埋没的贡献，裁决者负责逐条作出明确判断。当前交付为 **0.1.0 pilot**。

```text
初稿 → 结构化结论台账 → 冻结同一版本
                         ├─ 新上下文：夸大审查 ─┐
                         └─ 新上下文：低估审查 ─┤
                                              ↓
                           裁决 → 来源内容核对 → 报告
```

主张不足时，明确判为“不支持”或“证据不足”；已有贡献成立时，明确说清贡献。插件不以积极表态、较少限定词或反对用户作为优化目标。

## 已实现

- **可持久恢复的案例**：SQLite 保存初稿、结论、原始证据快照、假说登记、双向意见、裁决和事件。冻结后不静默改稿。
- **相同输入、分开的审查包**：冻结时同时生成两包；不带另一审查者的意见、作者上下文 ID 或额外的期望判定字段。宿主负责实际创建干净的上下文。
- **完整裁决约束**：每条结论必须有判定、理由、范围、置信理由与改判条件；每条意见必须采纳、部分采纳或驳回。两位审查者不是投票者。
- **有界审查**：每侧最多 3 条会改变判断的问题；容许零条意见。问题过多时返回 `needs_split`，不能靠截断隐藏关键问题。
- **来源核对**：保存源文件 bytes/hash，核对可选的原文锚点与当前文件；区分内容不匹配、缺失和未验证。内容不匹配阻止导出。
- **人类介入记录**：pause / challenge / defer / accept；明确为调用方转录的人类决定，未验证人类身份。接受不等于科学验证。
- **实际可运行的分发包**：标准清单、Skill、3 个 MCP 工具、Python CLI、Grok 项目适配器、离线演示、测试及打包工具。

运行时仅依赖 Python 3.11+ 标准库。不自动联网、不调用模型、不执行用户提交的代码。宿主按照技能调度审查者；没有可隔离的子代理时，使用分开的新会话手工交接。

## 快速体验

在插件目录内运行（输出目录必须尚不存在）：

```powershell
python -m parrhesia demo --output .\artifacts\my-demo
```

生成 `review.html`、裁决 Markdown、`case.json`、完整工具调用记录和持久案例。三个样例分别演示因果降级、承认直接比较支持的差异、明确证据不足。**所有数值、审查意见和判定均为预置人工样例，没有真实模型评价或科学分析。** HTML 为只读报告；可筛选结论和展开依据。

## 标准插件接入

把整个插件目录交给支持 Agent Plugins 1.0.0 的客户端加载。根目录 `plugin.json`、`mcp.json` 和 `skills/parrhesia-review/SKILL.md` 使用规范定义的位置；安装入口和授权方式由客户端决定。AGENTS.md 不是标准自动注入组件，需使用提供的模板明确追加到所选项目。

`mcp.json` 使用 `python` 启动本包的脚本，`${PLUGIN_ROOT}` 定位包、`${PLUGIN_DATA}` 定位客户端分配的数据目录。没有假定标准提供项目目录变量。

1. 让宿主加载 `parrhesia-review` 技能。
2. 调用 `parrhesia_select_workspace`，选定用户授权的现有项目目录；或使用默认插件数据工作区并明确放入证据。
3. 调用 `parrhesia_contract` 获取准确字段和当前目录。
4. 通过 `parrhesia_workflow` 执行工作流，由宿主把两个审查包分别交给干净上下文。

可直接对宿主说：

> 用 Parrhesia 审查这份初稿。以当前项目为工作区，把主张和已有证据建成台账；先独立做夸大与低估审查，再逐条裁决。不要替我补造数据或执行新分析。保留当前证据不足的判定，并写明改判条件。

## Grok Build 项目适配

适配器把自包含运行代码和技能复制到指定项目，合并一个 MCP 配置项及可识别的 AGENTS.md 规则块；保留无关内容，备份被修改的配置，拒绝覆盖不归本插件管理的内容。

```powershell
python scripts/install-grok.py --project C:\YourProject
grok --cwd C:\YourProject mcp doctor parrhesia --json
```

若只安装 MCP/Skill、不追加规则块，使用 `--skip-agents`。不修改 Grok 用户级配置，不运行模型。实际主机验证结果与限制见 [接入说明](docs/grok-integration.md)。

## 开发与验证

```powershell
python -m unittest discover -s tests -v
python scripts/build-release.py --output dist/parrhesia-0.1.0.zip
```

Windows 受限沙箱可能拒绝 Python 对新建临时目录的规范化访问。使用明确可写的项目内 TEMP/TMP；若主机仍拒绝，保留路径安全检查并在获准的本地执行环境运行测试。

分发 ZIP 采用文件白名单，包含源代码、技能、规则模板、文档和测试；排除研究数据、SQLite、案例与运行日志。解压后无需原仓库即可启动。Python 包目录是随插件运行的实现，不要求向用户环境安装依赖。

## 怎样判断产品是否有效

当前可以证明的是工作流、状态约束、打包与被实际检查的主机连接；**尚未证明 Grok 的过度防御、理想化或空泛中立有所减少**。来源哈希相同也不证明数字来自实际执行、论文支持主张或供体设计正确。

后续应在同样模型、材料和预算下比较原始 Grok、仅 AGENTS.md、单向审查、双向无裁决与完整插件，并由盲评判断证据校准、明确裁决、有效贡献保留和错误成本。真实模型调用与正式评价另按批准的计划执行。

- [产品设计](docs/product-design.md)：职责、失败模式、边界与人机交互。
- [接口契约](docs/contract.md)：所有操作的准确输入与状态约束。
- [评价方案](docs/evaluation-plan.md)：对照设计、指标和决策门槛，尚未执行。
- [交付核验](docs/verification/release-readiness.md)：本轮实际通过项、独立审阅修复与未建立的证据。
- [完整 AGENTS.md](AGENTS.md) / [项目追加模板](templates/AGENTS.parrhesia.md)。

本轮 AgentMuxer 仅用于免费能力发现，资料读取使用现有工具；未调用目录付费服务。代码没有接入计费平台。代码仓库：[HERRY423/Parrhesia](https://github.com/HERRY423/Parrhesia)。尚未发布到插件目录。
