# Parrhesia 0.2.0 pilot 本地交付核验

日期：2026-10-19（America/Los_Angeles）。源码整理基线：`5da772b`；本记录对应工作目录中的 0.2.0，未创建发布提交或 tag。软件版 0.2.0、新案例 schema v2、gate_version=1 与 Agent Plugins 格式 1.0.0 分别核对。

## 改动范围

完整清单见 [CHANGELOG](../../CHANGELOG.md)，客户端更新见 [升级说明](../migration-0.2.md)。本次将此前规则、v2 主张结构、门控及绕过修复纳入同一软件版本，并同步清单、Python 包、报告页脚、README、产品说明、契约和分发脚本。

生成规则仍只源自 `policy/parrhesia-policy.md`。旧案例、旧发布包和历史核验记录保留；不把历史 Grok、Linux 或其他宿主测试改写成本版结果。

## 实际测试

环境：Windows，Python **3.13.9**。执行：

```powershell
$env:TEMP='C:\Parrhesia\artifacts\policy-test-tmp'
$env:TMP='C:\Parrhesia\artifacts\policy-test-tmp'
python -X utf8 -m unittest discover -s tests -v
python scripts/generate-policy.py --check
python scripts/install-codex.py --check
python scripts/run-stage0-eval.py --report-out docs/verification/stage0-evaluation.md
git diff --check
```

完整套件 **111 项：110 通过、1 跳过、0 失败**，耗时 **14.260 秒**。跳过项为 `test_symlink_source_rejected_if_host_permits_creation`：当前账户不能创建符号链接，未计作通过。原子硬链接导出测试使用已获准的本地沙箱外运行，测试临时数据限定工作区。

本地完整日志：`artifacts/release-0.2.0-tests.log`，SHA-256：`1b9bb092269266483df2a227658f3f299223786c3bab84d29a7eb273d6c9e3fd`。日志是本地执行产物，不包含于分发包。生成一致性、Codex 精简块与 `parrhesia-l2-reference` skill 同步检查、Stage 0 机械评估套件（24 个 L2 案例 + 6 个 `L1-Explore` 探索案例）及 diff 空白检查均通过。

| 检查 | 结果及覆盖范围 |
|---|---|
| v2 主张与机械门控 | 类型/等级、关键检查、证据兼容、观察性因果条件支持（`partially_supported`）与无条件支持拦截、合成隔离、反橡皮图章门控、逐主张立场、未读确认、采纳落实及拒绝不推进状态 |
| 脚手架与执行记录 | `scaffold_claim` 全 `unknown`/`not_run` 诚实骨架与门控上限返回；`python -m parrhesia record-exec` 捕获命令输出、自动登记证据并产出 `execution` 溯源卡 |
| 精简规则与 Codex 同步 | 仓库根 `AGENTS.md` 与 `templates/AGENTS.parrhesia.codex.md` 改为精简块（含 `L1-Explore` 轻量探索台账与日常工作流），连同 `skills/parrhesia-l2-reference/SKILL.md` 纳入 `policy/parrhesia-policy.md` 单源生成与 `install-codex.py --check` 校验 |
| 审查者隔离与输入清单 | 审查者隔离配方写入规则与 Skill；Markdown 与 HTML 报告显式记录 `input_manifest` / `reviewer_input_manifests`（`packet_id`、`input_digest`、`blind`、覆盖主张与证据 ID、未读证据、历史继承与记忆读取状态） |
| Stage 0 对照评估套件 | `scripts/run-stage0-eval.py` 验证 24 个 L2 案例与 6 个 `L1-Explore` 探索案例机械门控全部通过，导出 `A_baseline`、`B_compact`、`B_full`、`E_full_l2_workflow` 四组提示词包（见 [Stage 0 核验报告](stage0-evaluation.md)） |
| 绕过回归与历史兼容 | 新建 v1 拒绝、真实 condition、新改写锚点、不可见字符、未知版本拒绝；已有 v1/未门控 v2 摘要与恢复 |
| MCP 与安装副本 | 实际 Python 子进程握手、契约读取、旧版请求被拒绝后的恢复、安装副本独立启动；不等同原生宿主模型编排 |
| 报告与演示 | 合成演示、条件显示、HTML 转义；页脚使用运行时版本 |
| 发布一致性 | plugin.json / pyproject.toml / Python 版本一致；任一旧版混入时构建失败且不写输出 |
| ZIP 内容与可移植性 | 两次构建字节相同、逐文件摘要、LICENSE/CHANGELOG 收录、私有运行目录排除；解压后规则检查与 MCP 启动；握手版本等于清单 |
| 文字套件 | 白名单生成、不覆盖已填写套件、解压副本可独立生成交接模板；不代表 ChatGPT 原生验收 |
| 分发格式 | 用仓库保存的 Agent Plugins 1.0.0 官方 schema 校验清单；未重新联网获取 schema |

## 新版分发

```powershell
python scripts/build-release.py --output dist/parrhesia-0.2.0.zip
```

包内 `RELEASE-MANIFEST.json` 记录版本与逐文件摘要，包含源码、模板、契约、升级说明、变更记录、许可证及测试。`artifacts/`、`dist/`、工作区数据、虚拟环境和私有配置不进入分发。构建器拒绝覆盖同名不同内容的文件；相同字节可重复核对。

实际分发 ZIP 的 SHA-256 与解压读回结果保存在包外 `dist/parrhesia-0.2.0.sha256` 和 `artifacts/release-0.2.0-package-check.json`，避免让 ZIP 的摘要自引用。重新生成交接套件使用本版包内 `scripts/prepare-chatgpt.py`，不继续使用旧 0.1.0 套件冒充新版。

## 未建立的证据

本版尚未重新执行 Linux 或 Python 3.11 的测试矩阵；CI 配置存在不代表已运行。未执行真实宿主的独立双审、外部模型行为改善评价或科学/临床验证。旧 Grok 握手记录仅作历史资料。当前版本保留 pilot 状态；本地整理与构建不代表已安装到用户宿主、上传发布或记录用户接受。
