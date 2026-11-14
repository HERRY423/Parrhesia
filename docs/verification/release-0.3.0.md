# 0.3.0 桌面宿主验收摘要 / Desktop host acceptance

2026-11-14：支持以下限定场景达到 **engineering × host_accepted**。环境为 Windows 11、Python 3.13.9、Codex 桌面会话实际加载的 Parrhesia 0.3.0；使用固定合成软件材料。此页是本地执行结果的公开摘要，原始工具返回、数据库、测试及失败日志保留本地，未随文档发布，不能仅凭此摘要独立重建全部验收。

| 已验收场景 | 实际观察与范围 |
|---|---|
| 伤害方向主张审查→裁定→导出 | harm 命题完成双角色审查包、裁定、verify、导出和读回；错误声明为 benefit 的负控被拒绝。角色内容是同上下文固定 fixture，不是独立模型审查。 |
| 待裁定后继版本 | 后继 case 在 draft 和 frozen 阶段，原结论保持 current；原冻结输入、裁定摘要与导出不变。 |
| 校准来源绑定 | 不存在的来源被拒绝；缺失来源保持 pending、不进入评分；有效绑定后可评分，来源被故意修改后退出评分，历史 outcomes 保留。复现点包含不冒充名义区间覆盖；结果语义仍由调用者报告。 |
| 失败执行记录 | 已安装 CLI 实际运行超时、启动失败、非零退出，原生宿主读回三条证据和三个 record_exec 事件，事件链 verified。范围为 CLI→宿主读回，MCP 不提供任意命令执行动作。 |
| Windows 原生文件符号链接 | 用户开启开发者模式后实际创建链接；原始测试 1 通过、0 跳过。本地 v2 与原生宿主均返回 unsafe_path；宿主拒绝前后证据数为 0、事件未变。同一普通源文件正对照登记成功，事件链 verified。 |

四条工作流保存 42 次原生工具调用；符号链接补验另保存 10 次。宿主 contract 返回 0.3.0；安装包 98 个清单文件匹配。冻结验收包的 ZIP SHA-256 为 `dc329a0296abeceda2816172e52ccf4434b20d3c1a365ba6611aa7067e28129a`，RELEASE-MANIFEST.json SHA-256 为 `84032cd449920b485a0703d44ebcb2fbd41e6671d96d774853f6588892953bbf`。这些标识对应当时的本地冻结包，不声称后续文档提交或重新构建的包具有相同摘要；本次同步不创建 GitHub Release 或重新打包。

## 历史与限制

- 保留原来的宿主未刷新、WinError 1314 权限不足、测试跳过及首次安装目录写入 WinError 5 记录。权限问题由后续真实创建及拒绝测试解除，不把旧失败改写为成功；原有 2,925 个证据文件核对无变动。
- host_accepted 只涵盖上述当前桌面版本与场景，不涵盖其他宿主或所有平台。符号链接项不等于所有 reparse point、目录 junction 或并发替换竞态已测试。
- 没有建立审查者独立性、科学有效性、真实结局语义或 user_impact，也没有代用户登记 human accept。
- README 中 184 项测试及既有 Stage 0 数字仍是修复前历史快照，不是本次全量回归结果。
- 后续版本需重跑对应工作流；若错误接受链接、拒绝后改变状态、失效来源仍参与评分或待裁定后继使原结论提前失效，应撤回或收窄对应验收结论。

## English summary

The five rows above are **engineering × host_accepted** for the tested Windows 11 Codex desktop session running Parrhesia 0.3.0 with fixed synthetic fixtures: harm-proposition review/adjudication/export; pending successor standing; calibration source binding and invalidation; installed CLI failure receipts read back through native host tools; and native Windows file-symlink rejection after Developer Mode was enabled. Ordinary-file registration succeeded as a positive control. The original symlink test passed without skips, and rejected registration changed neither evidence nor events.

This is not independent scientific review, semantic outcome validation, user acceptance or measured user impact. It does not cover other hosts, every reparse-point kind or race conditions. Raw evidence and historical failures remain local; this public summary is not a self-contained reproducibility bundle. Package hashes identify the frozen local acceptance artifact, not a newly rebuilt archive or a GitHub Release. Earlier test and Stage 0 totals remain historical.
