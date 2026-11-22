# Antigravity 宿主工程适配

本适配面向 Google Antigravity（Antigravity IDE / Antigravity 2.0 / `agy` CLI），按官方插件目录规范生成自含插件包、MCP 配置、严格低于 `24,000 B` 限额的精简规则、`parrhesia-review` 与 `parrhesia-l2-reference` 双技能及只读 `SessionStart` 生命周期钩子。本适配不修改 `~/.gemini/config/config.json`，不调用受限本地状态 RPC，不安装外部依赖，也不自动调用大模型。

真实 Antigravity 宿主中的交互式多代理隔离编排与模型净收益为 **NOT_RUN** / **NOT_MEASURED**；本地工程核验（规范字段校验、规则大小上限、Windows/POSIX Shell 钩子执行、只读 SQLite 提示与独立 MCP 进程握手）通过自动化测试验证，不能替代真实科研场景验收。

## 快速接入（推荐项目级作用域）

在目标项目已存在的前提下，从仓库根目录（或分发 ZIP 解压目录）执行：

```powershell
# 1. 项目级安装（默认：仅写入 <project>/.agents/plugins/parrhesia/ 与 .agents/parrhesia/）
python scripts/install-antigravity.py --project C:\YourProject

# PowerShell 等价封装（可显式指定 Python 3.11+ 解释器）
& .\scripts\install-antigravity.ps1 -Project C:\YourProject -Python python

# 2. 只读核验安装完整性、规范限制与规则来源一致性
python scripts/install-antigravity.py --project C:\YourProject --check

# 3. 安全卸载托管文件（自动备份并保留用户已有配置）
python scripts/install-antigravity.py --project C:\YourProject --uninstall
```

如需隔离的自定义全局目录（`--scope user`），可通过 `--target` 或环境变量 `PARRHESIA_ANTIGRAVITY_HOME` 指定目录（默认 `~/.gemini/config`）；**安装器只写 `<target>/plugins/parrhesia/` 与 `<target>/parrhesia/`，绝不读写 `config.json`、全局 `mcp_config.json` 或账户凭据**：

```powershell
python scripts/install-antigravity.py --scope user --target C:\CustomAntigravityHome
python scripts/install-antigravity.py --scope user --target C:\CustomAntigravityHome --check
```

为避免同名的 `parrhesia` stdio MCP 服务在不同作用域重复注册，同一项目启用时请在项目级与用户级中仅保留一份。

## 写入布局与职责边界

以默认 `--scope project` 为例，安装器写入以下受控文件并把清单、运行时与备份置于 `.agents/plugins/parrhesia/` 之外，避免插件加载器误读备份或清单：

| 路径 | 职责与契约对齐 |
| :--- | :--- |
| `.agents/plugins/parrhesia/plugin.json` | 严格遵循 Antigravity 允许字段集（`name`、`displayName`、`version`、`description`、`author`、`homepage`、`repository`、`suggestedPrompts`），不含未识别扩展键 |
| `.agents/plugins/parrhesia/mcp_config.json` | Antigravity 原生 `mcpServers.parrhesia` 配置，指向项目内隔离运行时 `run-mcp.py` 并固定 `--workspace <project>`（用户作用域无固定工作区时使用 `--default-workspace`） |
| `.agents/plugins/parrhesia/rules/parrhesia.md` | 同步 `compact_core` 精简规则与 Antigravity 隔离/溯源约定，**无 YAML frontmatter**，严格低于 `24,000 B` 单文件上限（约 `10 KB`） |
| `.agents/plugins/parrhesia/skills/parrhesia-review/SKILL.md` | L2 工作流与工具契约操作技能（按需加载） |
| `.agents/plugins/parrhesia/skills/parrhesia-l2-reference/SKILL.md` | 完整 L2 九大设计包、八项统计报告、四类溯源卡与校准锚点参考（仅 L2 / 深度查阅按需加载） |
| `.agents/plugins/parrhesia/hooks.json` | 只读 `SessionStart` 生命周期配置（可用 `--no-hooks` 禁用）；Windows 上采用 `call` 引号安全包裹，避免带空格路径在 `cmd /c` 下被去引号 |
| `.agents/plugins/parrhesia/hooks/parrhesia_hook.py` | 纯 stdlib 只读 SQLite（`?mode=ro`）状态检测；按 `events` 序列定位最近活跃案例并引导读取 `parrhesia://cases/{case_id}` / `parrhesia_get_case` / `parrhesia_verify`；若无 `.parrhesia/state.sqlite3` 或案例数为 0，静默返回 `{}` |
| `.agents/parrhesia/runtime/` | 自含 `parrhesia/*.py`、`scripts/run-mcp.py`、`plugin.json`、`mcp.json` 与 `docs/contract.md`，移动或删除原仓库不影响已安装项目 |
| `.agents/parrhesia/installation.json` / `backups/` | SHA-256 所有权清单与带时间戳备份；更新、切换选项或卸载前先核验摘要，检测到未托管冲突或手工篡改即拒绝写入 |

仓库根目录另提供 `.antigravity-plugin/plugin.json`，已纳入 `scripts/build-release.py` 版本一致性校验与确定性分发 ZIP。

## 可选参数说明

- `--rules-target {plugin,root,both,none}`：默认 `plugin`（仅写入 `.agents/plugins/parrhesia/rules/parrhesia.md`，不改动项目根目录已有 `AGENTS.md`）。选 `root` 或 `both` 时会在项目 `AGENTS.md` 中维护带起止标记的精简受管区块，同样严守 `< 24,000 B` 限制（`user` 作用域不允许 `root`/`both`）。
- `--no-hooks`：跳过 `hooks.json` 与 `hooks/parrhesia_hook.py`，仅部署清单、MCP、规则与技能；若先前已安装钩子，再次带 `--no-hooks` 运行会自动备份并安全移除旧钩子文件。
- `--python <path>`：显式绑定 Python 3.11+ 解释器路径并立即校验版本，写入 `mcp_config.json` 与 `hooks.json`。
- `--workspace <path>`：显式指定 MCP 与 `SessionStart` 钩子观察的工作区目录。

## Antigravity 隔离双审与执行溯源映射

在 Antigravity 宿主中运行 Parrhesia 时，按以下宿主原语对齐最新 `0.4.0` 契约（Claim Schema v2、25 个强类型与兼容 MCP 工具及只读资源）：

1. **规则分流**：日常 L0/L1/L1-Explore 仅依赖精简 `rules/parrhesia.md`；仅在进入 `L2` 或核对完整设计/统计清单时读取 `parrhesia-l2-reference`。
2. **审查者上下文隔离**：在 `L2` 阶段分派夸大审查与低估审查子代理时，使用 `invoke_subagent`（默认新对话，不继承起草聊天）或 `swarm` 的 `add`（**不传 `fork`**），并**仅**提交对应角色的 `review_packet` 与已授权阅读的证据正文；在反馈和 `input_manifest` 中如实记录 `inherited_history: false`、实际 `memory_read` 状态、`packet_id`、`input_digest`、`blind`、`evidence_ids` 与 `unread_evidence_ids`。
3. **本地执行溯源**：通过 `run_command` 运行分析、基准或复现脚本并欲将其输出作为证据时，使用 `python -m parrhesia record-exec --workspace <project> -- <cmd>` 生成真实运行日志并登记为 `execution` 溯源卡，禁止把未绑定日志的终端片段冒充为已登记证据。

## 核验范围说明

`tests/test_adapters.py` 自动化验证：Antigravity 清单严格键集合与版本号、`rules/parrhesia.md` 无 frontmatter 且 `<= 24,000 B`、双技能打包、Windows `cmd /c` / POSIX `sh -c` 对含空格路径的真实钩子执行（无案例时静默 `{}`、有案例时只读返回 `injectSteps` 且零数据库变更）、隔离目录 MCP `initialize`/`tools/list`/`parrhesia_contract` 握手、`--check` 只读漂移识别、`--rules-target` / `--no-hooks` 迁移、`--scope user` 不触碰 `config.json`，以及 `--uninstall` 后重装幂等性。真实 Antigravity IDE / CLI 会话中的自动插件加载与跨子代理防记忆泄露效果仍需宿主内实测。
