# 两阶段 `estimate_first`、子进程隔离边界与三层语义队列去重：本地工程核验记录

日期：2026-11-21（America/Los_Angeles）。范围：`0.4.0` 版本（`v0.4.0`）发布前工作树在完成三项硬化改进后的本地代码、协议、单元测试、规则生成、泄漏审计与临时打包核验；**不代表桌面宿主实机验收或真实付费大模型科学效果评测**。

**本轮工程判定：`engineering × test_passed`（支持，限当前工作树本地验证）**；历史已冻结版本桌面集成仍仅限 `0.3.0` Windows Codex 会话（`engineering × host_accepted`）；外部付费 LLM 盲评对照组尚未执行（`computational × unassessed`，`external_llm_status="not_run"`）。

## 1. 本轮硬化实现摘要（保持单包 / 纯 Python 标准库交付）

1. **真实两阶段 `estimate_first` Commit-Then-Reveal（仍保留单包向后兼容）**
   - `parrhesia/packets.py` 与 `parrhesia/core.py`：`review_packet`、`Engine.get_packet` 与 CLI `isolate-packet` 新增可选参数 `stage="full" | "evidence_only"`（默认 `"full"` 保持原冻结包 JSON 与哈希字节完全兼容）。`stage="evidence_only"` 强制剥离 `question`、`draft`、`hypotheses`、作者主张文本/分类/等级/范围以及 `effect_records[].claim_direction`，并将 `packet_nonce` 绑定为 `{role}:evidence_only`（若将 Stage 1 包回放至 `submit_review`，会在签名/HMAC 前即被 `invalid_isolation_receipt` 拒绝）。
   - `parrhesia/isolation.py`：`validate_stage1_estimates` 严格校验 Stage 1 输出（`protocol="estimate_first_stage1_v1"`、全冻结主张覆盖、类型与类型内等级枚举、数值有限性与区间排序），计算规范 `stage1_estimate_sha256`；`compute_runner_seal` 条件性将 `two_stage_blind`、`stage1_estimate_sha256`、`stage1_transcript_sha256`、`os_sandbox` 与 `workspace_untouched` 纳入工作区 HMAC-SHA256 密封。
   - `parrhesia/isolated_runner.py` 与 `parrhesia/cli.py`：`run-isolated` 与 `run-dual-review` 新增 `--two-stage-blind`。开启时，Stage 1 在独立临时沙箱（`PARRHESIA_PACKET_STAGE=evidence_only`）锁定 `stage1_locked_estimates.json`；失败、超时、越界或校验未通过则直接中止且**绝不揭示 Stage 2 作者主张**。通过后在第二个全新沙箱挂载只读 `stage1_locked_estimates.json` 并运行 Stage 2 完整复核。

2. **OS 子进程隔离边界加固与诚实披露（不虚报内核外安全保证）**
   - `parrhesia/isolated_runner.py`：扩展 `_RESERVED_RUNNER_ENV_KEYS`，阻断 `--allow-env` 注入 `LD_PRELOAD`、`LD_LIBRARY_PATH`、`DYLD_*`、`PYTHONPATH`、`PYTHONHOME`、`PYTHONSTARTUP`、`PYTHONUSERBASE`、`APPDATA`、`LOCALAPPDATA`、`XDG_*` 与运行器协议变量；将 `APPDATA`、`LOCALAPPDATA`、`XDG_CONFIG_HOME`、`XDG_CACHE_HOME`、`XDG_DATA_HOME`、`XDG_STATE_HOME` 重定向至 `sandbox_dir/home`。
   - 新增 `--offline-env`（注入回环代理 `127.0.0.1:9` 及 `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1`/`PIP_NO_INDEX=1`）、只读权限挂载临时输入文件并在子进程退出后重校验未篡改（并在 `finally` 恢复权限以便 Windows 安全清理）、`close_fds=True` + 进程组/新会话隔离、运行前后 `.parrhesia/state.sqlite3` / `state.sqlite3-wal` / `runner.key` 快照比对（篡改直接返回 `sandbox_boundary_violation` 且拒绝签发 `isolation_receipt`）。
   - 新增 `--sandbox-mode standard | strict_os`：在 Linux 调用 `bwrap`（只读根挂载 + `--bind sandbox_dir` + 可选 `--unshare-net`）、在 macOS 调用 `sandbox-exec`（禁止工作区与系统写入），在 Windows 或缺少后端的宿主上**显式以 `sandbox_unavailable` 拒绝执行，绝不静默降级**。`compute_isolation_grade` 同步输出 `two_stage_blind_verified`、`os_sandbox`、`workspace_untouched` 及 `boundaries: {"enforced": [...], "not_enforced": [...]}`，并写入 Markdown 与离线 HTML 报告。

3. **三层语义队列去重护栏（`parrhesia/synthesis.py`、`parrhesia/effects.py`、`parrhesia/report.py`）**
   - `effect_records` 新增可选字段 `cohort_id`（`effects.py` 与 `mcp_schemas.py` 校验 <= 200 字符非空文本）。
   - **Layer 1 硬排除**：除同案重复与直接证据快照 SHA-256 外，遍历 `derived_from_evidence_ids` 追溯上游原始数据祖先 SHA-256（`ancestor_evidence_sha256`）；比对规范化 `cohort_id`（`explicit_cohort_id`）；抽取并标准化试验注册号与公共库号（`NCT`/`ISRCTN`/`EudraCT`/`ChiCTR`/`ACTRN`/`CRD`/`GSE`/`PRJNA`/`PRJEB`/`SRP`/`phs` 去除 `.vN` 版本后缀/`EGAS`/`E-MTAB`/`TCGA-*`/`MIMIC-III|IV`）以及来源 DOI。当两案均声明**明确不同的 `cohort_id`** 时，允许共用同一文献 DOI 或注册文本的不同队列合法进入独立合并，否则硬排除并记录 `overlap_mechanism` 与 `cohort_identifier`。
   - **Layer 2 嫌疑筛查与状态降级**：检测 `n >= 20` 且样本量/点估计/CI 完全一致的定量克隆（`exact_sample_and_effect_clone`），以及剔除数字与通用统计套话后 ≥10 词且 3-gram Jaccard ≥ 0.65 的高重合文献描述（`high_text_shingle_overlap`，若已声明不同显式 `cohort_id` 则跳过文本模糊告警）。命中项记入 `deduplication_guard.suspected_cohort_overlaps`，附加高优先级 `verify_cohort_independence` 建议，阻止综合状态直接判定 `replicated_consistent`（转为 `suspected_duplicate_cohort_review_needed`），并在 `parrhesia synthesize` 离线 HTML 报告中单独渲染。

## 2. 实测验证结果（全量通过、无跳过、零外部付费 API 调用）

| 检查项 | 命令与作用域 | 实测结果 |
| :--- | :--- | :--- |
| 规则单源生成一致性 | `python -X utf8 scripts/generate-policy.py --check` | 退出码 `0`（`Policy outputs are consistent.`；`policy/parrhesia-policy.md` 79,945 B < 80,000 B） |
| 评测集零泄漏审计 | `python -X utf8 scripts/check-eval-leakage.py --strict` | 退出码 `0`（`strict_passed: true`，`heldout_overlap_count: 0`，`no_case_literals: true`） |
| MCP Schema 压缩与 Draft 2020-12 校验 | `python -X utf8 -m unittest discover -s tests -p "test_schema_compaction.py" -v` | `6/6` 通过（含 `$defs/sha256` 复用与 stdio 校验） |
| 两阶段盲审 / 隔离边界 / 队列去重专项测试 | `python -X utf8 -m unittest discover -s tests -p "test_moats_3_and_4.py" -v` | `12/12` 通过 |
| 完整自动化回归套件 | `python -X utf8 -m unittest discover -s tests -v` | **`423/423` 通过**，`0` 失败、`0` 错误、`0` 跳过（277.653 秒） |
| 分发 ZIP 与离线纯环境 Wheel 验证 | 临时目录运行 `build-release.py` 与 `check-wheel.py --no-build-isolation` | 运行通过并已清理临时目录（`wheel` `stdio_tools=28`、`import_inside_venv=true`、`case_report_read_only=true`） |

### MCP 工具配置档线缆体积实测（紧凑 UTF-8 JSON，单位：字节）

| 对象 | 实测字节数 | 契约上限 | 裕量 |
| :--- | ---: | ---: | ---: |
| `full`（全部 28 个工具） | `81,519 B` | `< 82,000 B` | `481 B` |
| `compact`（10 个工具） | `18,668 B` | `< 20,000 B` | `1,332 B` |
| `explore`（5 个工具） | `11,634 B` | `< 12,000 B` | `366 B` |
| `review`（5 个工具） | `10,892 B` | `< 12,000 B` | `1,108 B` |
| `adjudication`（5 个工具） | `14,042 B` | `< 15,000 B` | `958 B` |
| `parrhesia_set_ledger` | `21,312 B` | `< 25,000 B` | `3,688 B` |
| `parrhesia_upsert_claim` | `3,596 B` | `< 4,500 B` | `904 B` |
| `parrhesia_draft_manuscript` | `4,366 B` | `< 4,800 B` | `434 B` |

## 3. 明确的诚实边界与待验证项

1. **OS 沙箱在 Windows 下的核验边界**：当前测试机为 Windows，本轮已在实际测试中验证 `standard` 沙箱的环境剥离、`APPDATA`/`XDG_*` 重定向、`--offline-env`、`.parrhesia` 快照防篡改（`sandbox_boundary_violation`）及 `strict_os` 不可用时的显式失败（`sandbox_unavailable`）；`bwrap`（Linux）与 `sandbox-exec`（macOS）的命令行参数封装已做单元测试，真实内核执行仍待 Linux/macOS 环境实测。
2. **模型独立性与真实效果边界**：两阶段沙箱物理分离保证 Stage 1 看不到作者主张文本、且 HMAC `runner_seal` 可防止同工作区后验篡改，但仍受限于工作区读写模型（`isolation_grade.boundaries.not_enforced` 明示 `no_hardware_enclave` 与 `separate_model_weights_not_proven`）。`0.4.0` 桌面宿主端到端验收（`host_accepted`）与真实大模型对照评估（`computational`）仍待后续执行。
