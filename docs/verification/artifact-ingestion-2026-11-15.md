# 稿件与产物导入：本地工程核验记录

日期：2026-11-15。范围：当前工作树的本地实现与工程测试；不属于科研结论裁决或真实用户效果评估。

**支持限定实现达到 `engineering × test_passed`**：稿件候选骨架、产物读取、运行与输出绑定、逐行/公式数值提取及相应拒绝边界已有实际运行记录。核心入口位于 `parrhesia/manuscript.py`、`parrhesia/artifacts.py`、`parrhesia/stat_import.py`，由 CLI、Engine 和 MCP 接入。

## 已运行的检查

| 检查 | 实测结果 | 记录 |
|---|---|---|
| 最终完整本地回归 | 230 passed、102 subtests passed；0 failures；177.48 秒 | `artifacts/artifact-ingestion-complete-tests.xml` |
| 新增三个 MCP 入口的独立 stdio 进程调用 | draft_manuscript / import_artifact / extract_effects 均成功，输入与输出通过 JSON Schema 校验 | `artifacts/artifact-ingestion-mcp-smoke.json` |
| 规则生成一致性 | `python scripts/generate-policy.py --check` 通过 | 规则由 `policy/parrhesia-policy.md` 生成，未手工改派生文件 |
| 源码语法与补丁空白检查 | compileall 与 git diff --check 通过 | 本地命令输出 |
| 源码身份 | 最终回归期间保存的 23 个源文件哈希，在测试完成后重新核对一致 | `artifacts/artifact-ingestion-source-manifest.json` |
| 合成端到端示例 | 生成 1 条未知主张骨架，运行命令生成表格，提取 1 条效应，检出稿件故意写错的数字 | `artifacts/ingestion-demo-20261115-384fce7d/demo-result.json` |

合成示例中，源表 HR=0.71，稿件故意写 HR=0.73，比较输出 `mismatch`；CI/p 分项另行保留。metadata 中的 synthetic 限制传到日志和产物。示例数字不是研究结果。可从该目录的 `SUMMARY.md` 查看输入与输出。

## 覆盖的边界

- 科学稿件骨架保持 `unassessed` / `unknown`，执行与检索卡保持 `not_run`；general 工程主张不强填因果设计。
- Word 主文档/表格文字与未读附件分开；文档代码、宏、include、内嵌指令不会执行。
- notebook、R Markdown、Quarto、Nextflow trace、Snakemake stats、容器摘要、DVC、Slurm/PBS、JUnit 和数据元数据按已说明格式读取。保存的运行状态不冒充本轮执行。
- 成功运行的 created/modified 输出才建立 execution_binding；unchanged、失败、跨案或哈希不符无法获得绑定。冻结/暂停案例拒绝先运行后报错。
- 去掉任意命令默认 benchmark 的行为；自动产物类别不能由自报升级。重登记同一来源和可识别结构文件也受限制；synthetic 沿来源链保留。
- 统计行绑定源 SHA-256、行位置与映射；混淆矩阵记录绑定可重算公式。跨行拼数、删掉 binding、缺失值补零、伪造 CI 均不被默默接受。
- 正向判断仍需相容的研究来源；执行收据或绑定统计表只能补充执行/数值依据，不能单独建立研究类别。原有科学证据、引用、合成来源、运行遗漏门控继续测试。
- 新入口的只读行为、事务回滚、原始快照保留、路径越界、源码指令隔离、打包与文档携带均有覆盖。

## 修复过程中保留的失败记录

早期完整回归暴露了旧用例依赖命令日志默认 benchmark、工具数断言仍为 22、旧 Stage 0 调用显式传 observation，以及适配器最小副本未带新增文档。已修复实现或更新用例的明确前提，保留原始测试结果：`artifacts/artifact-ingestion-full-tests.xml`、`artifacts/artifact-ingestion-final-tests.xml`、`artifacts/artifact-ingestion-targeted-tests.xml`、`artifacts/artifact-ingestion-stage0-tests.xml`。没有把失败记录改成通过。

最初在受限文件权限下运行时，原有报告导出的硬链接操作遭拒；完整回归在正常本机权限下重跑通过，未通过修改导出语义绕过该错误。

## 当前界限与下一步

稿件抽取是确定性候选筛选，不是已验证的完整语义理解。统计导入覆盖文档列出的格式；缺失或含糊输入明确保留问题，不自动猜测独立重复、外部验证资格、研究设计、主终点或获益方向。普通论文叙述的历史手工登记仍明确标为 reported；并未声称能鉴定来源真实性。

本次未把工作树发布为新版本，也未验证桌面会话加载了新工具。三个工具的独立 stdio 调用证明协议可用，不能替代桌面 `host_accepted`。真实研究者减少多少填表时间、能否稳定找全核心主张，仍需真实任务试用；如果出现候选遗漏或错误字段绑定，应收窄对应格式/解析规则并加入回归案例。

立即可用入口：在本仓库运行 `python -m parrhesia call draft_manuscript`，或按 [使用说明](../artifact-ingestion.md) 让宿主调用新入口。查看合成演示无需付费或下载数据。
