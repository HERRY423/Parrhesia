# 分发、同步与已有案例报告

不同安装方式按宿主职责分发；技能完整性与运行时文档清单由 `parrhesia/adapters.py` 统一声明。文件安装通过不等于宿主已发现工具，也不等于科研结论或用户收益通过验证。

| 路径 | 安装内容 | 不包含的动作 |
| --- | --- | --- |
| `scripts/install-codex.py` | `AGENTS.md` 精简块、`parrhesia-review/` 完整入口与 references、`parrhesia-l2-reference/` | 不注册 MCP，不修改插件缓存 |
| Grok / Antigravity 安装器 | 共用运行时、文档与两个完整技能目录，再写各自宿主配置 | 不证明宿主已调用工具或审查者独立 |
| Python wheel | `parrhesia` 包、`parrhesia` CLI、契约与 artifact-ingestion 文档 | 不安装宿主技能，不修改任何宿主配置 |
| 发布 ZIP | 源码、安装脚本、技能、文档与宿主清单 | 解压本身不完成宿主验收 |

## Codex 分层技能同步

在完整源码包中运行：

```powershell
python scripts/install-codex.py
python scripts/install-codex.py --check
```

可用 `--codex-home <目录>` 指向另一个已存在的 Codex 配置目录，`--source <目录>` 指向完整源码。同步至少检查以下六个文件：

- `AGENTS.md`
- `skills/parrhesia-review/SKILL.md`
- `skills/parrhesia-review/references/basics.md`
- `skills/parrhesia-review/references/workflow.md`
- `skills/parrhesia-review/references/integrations.md`
- `skills/parrhesia-l2-reference/SKILL.md`

源技能树里的其他文件也一起同步。缺少必需参考文件时，在写入目标前失败；目标链接路径会被拒绝。`--check` 逐文件比较当前源码预期内容，缺文件或内容漂移返回非零，不执行修复。

更新使用 `.parrhesia-codex-sync.json` 记录文件指纹，并在 `.parrhesia-backups/<批次>/` 保留被替换文件的原始字节；写入失败会回滚已经替换的文件。旧版同步记录可升级，旧备份和用户自建文件保留。第二次同步无变化时，不重写文件或更新时间。

需要恢复时先查看命令返回的 `backup_directory`，比较该批次备份与当前文件，再恢复明确选中的文件；不要用整目录覆盖抹掉后续用户修改。无备份表示该次没有替换已有文件。安装完成后，宿主是否重新发现技能仍须在相应宿主中核对。

## 隔离 wheel 验收

```powershell
python scripts/check-wheel.py --output <尚不存在的结果目录>
```

脚本在仓库外复制有边界的构建输入，默认使用 PEP 517 构建隔离，然后新建不继承 system-site-packages 的 venv，以 `--no-index --no-deps` 安装刚构建的 wheel。清除继承的 Python 路径，并从源码和 venv 之外的工作目录运行：

1. 核对 wheel 中代码和文档与构建快照逐字节一致。
2. 使用 `python -I` 确认导入来自 venv，排除源码导入；确认两条源码式契约路径不存在，实际通过 `distribution("parrhesia-review")` 定位契约。工作目录放置错误的同名文档，验证不会遮蔽安装文档。
3. 验证安装后的 console script、模块入口和版本，以及 stdio MCP 初始化、工具发现与契约调用。
4. 运行固定合成工作流，再对保存的案例生成 HTML，检查数据库字节保持不变。

`--no-build-isolation` 供已有构建后端的离线本机使用：仅跳过构建后端隔离，不跳过全新 venv 安装和运行隔离。报告单独记录该选项；不能把这种本地运行写成“PEP 517 构建隔离已验收”。每条命令限时 180 秒。

结果目录保存 wheel、逐步日志和 `report.json`（失败也保存），临时构建目录及 venv 自动清理。CI 在 Windows / Ubuntu、Python 3.11 上独立运行该检查，并始终上传结果。CI 配置合入不代表远端任务已经通过，应以实际 job 结果为准。

## 已有案例的可审视报告

```powershell
python -m parrhesia report --workspace C:\YourWorkspace --case-id case_... --output reports/review.html
```

wheel 安装后可用 `parrhesia report` 同样调用。输入必须是已有工作区中已裁定、等待导出或已导出的案例。命令直接读取一致的 SQLite 只读快照，不创建状态库、不迁移数据库，也不执行普通写事务。只读连接本身禁止写 SQL；冻结内容、审查与裁定摘要、事件链异常时拒绝报告，保留异常原记录供排查。

HTML 包含原命题、修订、意见及处理、证据与设计字段、审查输入和已保存用户决定，可展开查看。报告时间、案例快照摘要、案例状态和核验范围一并显示。`unknown`、`not_run`、非独立审查和未接受状态保留；生成页面不会重新核验源文件，不登记用户接受。输出限定为工作区内新的 `.html` / `.htm`，拒绝路径逃逸、内部状态目录、链接路径与覆盖旧报告。

此入口适用于真实已有案例；分发验收使用固定合成案例验证工程行为。后者不构成真实科研案例的审查结论、宿主模型行为或用户效果证据。
