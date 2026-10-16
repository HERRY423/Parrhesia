# 安装与宿主适配

Parrhesia 的主分发格式是 **Agent Plugins 1.0.0**。Grok Build 是附加适配路径；根目录的 `plugin.json`、`mcp.json` 和 `skills/` 才是可移植包，不以 `.claude-plugin` 或 `.grok-plugin` 代替它们。

## 可移植插件

在支持 Agent Plugins 1.0.0 的客户端中，按该客户端的本地插件安装界面选择本目录或解压后的完整发行目录。标准没有统一安装命令，也不统一决定权限、信任和插件商店。

运行条件：`python` 能启动 Python 3.11 或更新版本。运行时只使用标准库，无须 `pip install`。客户端把根 `mcp.json` 映射成自己的 MCP 配置，展开 `${PLUGIN_ROOT}` 与 `${PLUGIN_DATA}`，再启动 `scripts/run-mcp.py`。包内代码可以位于只读目录；案件状态写入客户端持久数据目录的 `workspace/.parrhesia/`。

首次使用先读取 `parrhesia_contract`。如果要审查现有科研项目，请明确选择该项目，再通过 `parrhesia_select_workspace` 切换；重新启动服务后需重新选择。选择结果和合同均回显活动工作区，所有相对证据路径以该目录为基准。标准没有 `${PROJECT_ROOT}` 变量，本插件不猜测客户端当前打开的项目。

需要固定工作区时，可在启动客户端前由用户设置 `PARRHESIA_WORKSPACE` 为已存在的绝对路径。优先级为启动参数 `--workspace`、用户环境变量、客户端提供的默认数据目录。未展开的占位符和相对路径会明确报错。不要把本地路径写入公开发行版。

可移植标准只定义技能与 MCP 发现；它没有承诺自动读取插件附带的 AGENTS 文件。请把 `templates/AGENTS.parrhesia.md` 作为补充合并到所选项目的 `AGENTS.md`，保留原有规则。插件技能与工具负责执行和留痕，AGENTS 补充负责触发条件、责任边界和最终表达。

格式依据：[Agent Plugins manifest](https://agent-plugins.org/plugin-authors/manifest)、[MCP 配置](https://agent-plugins.org/plugin-authors/mcp-servers)、[规范 1.0.0](https://agent-plugins.org/specification)。支持该格式的客户端不等于已经对本插件完成实测；本仓库的验证记录只覆盖实际执行的路径。

## Grok Build 项目适配

已检查本机 `grok 1.0.48 (b94d5072c95f)` 的 CLI 契约。该版本的原生插件使用旧式 `.mcp.json` 配置。为避免把可移植包与宿主配置混在一起，提供明确的项目安装脚本：

```powershell
& C:\Parrhesia\scripts\install-grok.ps1 -Project 'C:\YourResearchProject'
```

如果 `python` 不指向 Python 3.11+，用 `-Python 'C:\path\to\python.exe'`。目标必须是已存在的项目。脚本执行以下本地变更：

| 位置 | 作用 |
| --- | --- |
| `.grok/parrhesia/runtime/` | 独立复制 Python 运行时源码、启动器和工具合同；移动原始下载目录不会破坏安装 |
| `.grok/skills/parrhesia-review/` | Grok 项目技能 |
| `.mcp.json` 的 `mcpServers.parrhesia` | 使用安装时选定的 Python 和明确的项目路径启动服务 |
| `AGENTS.md` 的受管理注释块 | 追加补充规则，保留项目已有内容；`-SkipAgents` 可跳过 |
| `.grok/parrhesia/installation.json` | 文件归属与校验记录 |
| `.grok/parrhesia/backups/` | 变更前的原文件副本，可能包含项目私有配置；留在本地 |

重复执行没有变化时返回 `unchanged`。已有同名 MCP 配置、未受管理文件或被用户修改过的受管理文件会在写入前停止，要求人工合并。它不会覆盖其他 MCP 服务，也不会执行 `grok plugin install`、修改用户级配置、安装 Python 包、连接模型或授予更宽的宿主权限。备份和项目案件目录不应纳入公开发布。

先在 Grok 中完成该项目的目录信任，然后用技能菜单调用 `/parrhesia-review`。未信任时，Grok 1.0.48 会隐藏项目技能和 AGENTS 指令；虽然 `inspect` 仍列出 MCP，`doctor` 不会启动它。安装脚本不替用户授予目录信任。用户检查过目标项目后，可在 Grok 首次打开时确认信任，或自行使用顶层参数 `grok --cwd 'C:\YourResearchProject' --trust inspect`。该授权涉及整个项目的本地能力，不只是 Parrhesia。

完成信任后，刷新扩展列表或开启新会话；使用前可运行：

```powershell
grok --cwd 'C:\YourResearchProject' inspect
grok --cwd 'C:\YourResearchProject' mcp doctor parrhesia --json
```

`inspect` 证明发现了配置；`doctor` 验证本地服务连接及工具枚举。两者都不证明模型遵守双审查、不发生中性回避或科学结论正确。Grok 原生插件的信任/安装功能与本脚本的项目适配是不同路径，本脚本不宣称已做原生插件商店安装验收。

Grok 依据：[MCP 项目配置](https://docs.x.ai/build/features/mcp-servers)、[技能和插件发现](https://docs.x.ai/build/features/skills-plugins-marketplaces)。官方文档可能领先于安装版本，实际参数应再看本机 `grok <command> --help`。

## 更新、停用与边界

更新时对同一项目重新运行脚本；发生冲突时先保留自己的修改，再对照备份合并。安装程序不会删除旧文件、案件或证据。需要停用时，在宿主中禁用该 MCP 服务，并撤回项目技能与 AGENTS 受管理块；按照 `installation.json` 的清单逐项处理，保留 `.parrhesia/` 和备份。不要把整个项目 `.grok/`、`.mcp.json` 或 `AGENTS.md` 删除。

此插件不调用 Grok API，也不包含外部模型凭据。审查推理由当前宿主执行，其模型费用、数据传输和上下文隔离由宿主管理。工作流校验无法强制宿主创建真正独立的模型会话；若只有同一上下文可用，必须将隔离状态如实记为未建立，而不能把角色名差异当作独立审查。

本地打包测试包括可移植占位符展开后的 stdio 握手、合同读取、安装副本启动、保留已有规则与 MCP、重复安装和冲突保护。具体通过情况以本次测试输出和交付说明为准；真实 Grok 推理效果仍需经批准的对照试用。

## 本次实际宿主检查

2026-10-09，在仓库内的独立测试项目和独立 `GROK_HOME` 中完成：Grok 1.0.48 发现 `parrhesia-review` 技能和项目 AGENTS 文件；`mcp doctor parrhesia --json` 完成本地服务启动、协议 `2025-11-25` 握手及 **3 个工具发现**，健康数 1、失败数 0。未信任目录的对照检查按预期拒绝启动服务。原生检查未发送模型请求。结果摘要保存在 [grok-native.json](verification/grok-native.json)，详细本地输出在 `artifacts/grok-native/`。

注意该安装版本把 `--trust` 解析为顶层参数：`grok --trust ... mcp doctor` 有效，`grok mcp doctor --trust` 会拒绝该参数。此测试的信任记录只写入独立测试 `GROK_HOME`，未改变用户日常 Grok 的信任记录。
