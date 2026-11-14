# Grok Build CLI 项目级适配

本适配面向 Grok Build CLI（已在 `grok 1.0.48` 验证部分项目发现行为），提供自含、幂等且可只读校验与安全卸载的工程安装器：仅操作目标项目目录，从不读写 `~/.grok`，不自动信任项目，也不调用任何模型。

真实大模型在 Grok CLI 会话内的行为效果为 **NOT_MEASURED**，端到端多代理 `0.2.0` 编排为 **NOT_RUN**；`0.1.0` 时代的原生 `grok inspect` / `mcp doctor` 握手记录保留在 [docs/verification/grok-native.json](verification/grok-native.json)，本版本另外新增 `grok 1.0.48` 下的清单校验与隔离仓库探测检查（见下文核验范围）。

## 快速接入（`0.2.0` 推荐配置）

在目标项目已存在的前提下执行：

```powershell
# 1. 默认安装（compact 精简规则块 < 10 KB + parrhesia-review & parrhesia-l2-reference 双技能 + MCP）
python scripts/install-grok.py --project C:\YourProject

# PowerShell 等价封装（支持指定 Python 3.11+、策略模式、校验与卸载）
& .\scripts\install-grok.ps1 -Project C:\YourProject -Python python

# 2. 只读校验已安装文件哈希、MCP 配置、双技能注册与仓库规则一致性
python scripts/install-grok.py --project C:\YourProject --check

# 3. 安全卸载（备份并剥离受管区块与 MCP 服务项，完整保留用户内容与第三方服务器）
python scripts/install-grok.py --project C:\YourProject --uninstall
```

若需要向 `AGENTS.md` 写入完整单文件规则（`46,669 B`）而非默认精简块（`8,770 B` + 按需读取 `parrhesia-l2-reference`），可传 `--policy full`；若目标项目已有人工维护的规则，可传 `--skip-agents`。

## 写入项目的内容（`0.2.0` 完整包）

| 路径 | 用途与安全边界 |
| :--- | :--- |
| `.grok/skills/parrhesia-review/SKILL.md` | 核心触发决策、五要素输出契约与 L2 工具流程技能 |
| `.grok/skills/parrhesia-l2-reference/SKILL.md` | `0.2.0` 新增：L2 九大设计包、八项统计报告、溯源卡片与隔离配方完整参考 |
| `.grok/parrhesia/runtime/` | 完整自含的 `parrhesia/*.py`（含 `adapters.py`、`claims.py`、`gates.py`、`policy.py` 等）、`scripts/run-mcp.py`、`plugin.json`、`mcp.json`、`docs/contract.md` |
| `.grok/parrhesia/installation.json` | 维护模式标识、所有权摘要（SHA-256）、`policy_mode`、`python_executable` 与 `mcp_server` 快照 |
| `.grok/parrhesia/backups/` | 修改或卸载已有文件前生成的带时间戳原件备份 |
| `.mcp.json` | 仅合并或更新 `mcpServers.parrhesia`，保留同级其他服务器与自定义顶级字段 |
| `AGENTS.md` | 仅操作 `<!-- parrhesia:managed:start -->` 至 `<!-- parrhesia:managed:end -->` 之间的受管区块；默认注入 `compact_core`（`8,770 B`），可选 `--policy full`（`46,669 B`） |

若检测到下列情形，安装器在写入任何文件之前报错中止：
- 目标或父路径包含符号链接或 Windows reparse point；
- 已有受管文件、`AGENTS.md` 受管区块或 `mcpServers.parrhesia` 被外部工具或用户手工改动；
- 待写入位置存在未被本适配器登记过的文件。

## 在 Grok 中启用与校验

1. 运行安装后，打开 Grok Build CLI 对该项目的信任并核对配置发现状态：
   ```powershell
   grok --cwd C:\YourProject inspect
   grok --cwd C:\YourProject mcp doctor parrhesia --json
   ```
   注：Grok 在未信任项目目录中会延迟激活项目指令与本地技能，但会先在 `grok inspect --json` 中列出 `.mcp.json`；本安装器不会代用户修改 `~/.grok` 中的项目信任状态。
2. 在仓库或分发目录校验插件清单格式：
   ```powershell
   grok plugin validate .
   ```

## `0.1.0` 到 `0.2.0` 适配变更说明

相对 `0.1.0`：
1. 修复遗漏 `.grok/skills/parrhesia-l2-reference/SKILL.md` 的缺陷，现同步安装双技能；
2. 默认 `AGENTS.md` 注入改为 `compact` 精简块（降低日常上下文占用并减少 L0/L1 越级泄露），保留 `--policy full` 兼容切换（从 `0.1.0` 旧安装升级时自动备份旧 `AGENTS.md` 并平滑迁移）；
3. 新增 `--check`（纯只读完整性及来源漂移检查）、`--uninstall`（安全剥离受管项与重装兼容）及 `--python <path>`。

## 核验范围与诚实边界

- **已执行并记录**：
  - `tests/test_adapters.py` 与 `tests/test_packaging.py`：检验双技能安装、`--policy compact|full` 与 `--skip-agents` 切换备份、`--check` 篡改与版本漂移检测、`--uninstall` 清理与用户内容保留、冲突拒绝写前中止，以及离开仓库目录的 stdio MCP 握手；
  - `grok 1.0.48` 本机静态与发现校验：`grok plugin validate c:\Parrhesia` 校验清单，以及在独立 `git` 临时项目执行 `grok inspect --json` 核实 `.mcp.json` 中 `parrhesia` 服务发现；
  - `0.1.0` 历史记录保留于 [docs/verification/grok-native.json](verification/grok-native.json)，不将其改写为 `0.2.0` 验收结果。
- **未执行（`NOT_RUN` / `NOT_MEASURED`）**：真实 Grok 交互会话中模型对 L0/L1/L1-Explore/L2 规则的遵循度、跨子代理隔离质量与净误差改善。
