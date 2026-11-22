# 从稿件与实际产物起草台账

这组入口减少重复抄录，不自动裁决科学主张。全部使用本地 stdlib，无模型调用、联网、文档宏或代码执行。原文中的指令始终只是待审材料。

## 1. 从稿件生成可审阅的骨架

- **新增格式与边界（纯标准库只读）**：除 Markdown / LaTeX / DOCX / Quarto 外，现已支持未加密 `.pdf`（常规 xref、非增量文档，按 Catalog/Kids 页树和当前 `Tf` 字体读取；无压缩流、`FlateDecode` 与可解析的 `/ToUnicode`/简单字体编码；不明确的结构或编码显式拒绝）、`.html`/`.htm`/`.xhtml`（剥离 `<script>`/`<style>`/注释）、JATS `.xml`/`.nxml` 与 Jupyter `.ipynb` markdown 叙事单元。LaTeX `\input`/`\include` 仅在工作区内受限展开（深度 `<= 8`、文件数 `<= 32`、禁用符号链接/越界/循环引用，子文件定位 `{path}:L{n}`）。混合因果/预测/机制句子会在 `source_map` 标注 `detected_claim_types` 与 `split_recommended`（仍默认选主类型，不代为改写命题）。

宿主可调用 `parrhesia_draft_manuscript`，也可通过 CLI 的通用入口：

```json
{"path":"paper.qmd","case_id":"<实际 case_id>","max_claims":5}
```

将请求保存为 `draft-request.json` 后执行：

```powershell
python -m parrhesia call draft_manuscript --workspace C:\YourWorkspace --input draft-request.json
```

支持 `.md` / `.markdown`、`.tex`、`.docx`、`.qmd`、`.rmd` 和 UTF-8 `.txt`。不支持旧二进制 `.doc`；不会展开 LaTeX/Quarto 外部 include。DOCX 读取主文档段落和表格文字，脚注、尾注、图像、嵌入对象和修订语义未读时显式列入 `omitted`。限 8 MiB 文件/解压主 XML、100 万文本字符。

返回 `claims`、`source_map`（原文、行/段位置、源文件 SHA-256）、`check_ceilings`，指定 `case_id` 时还返回可送入 `set_ledger` 的 `ledger_payload`。入口只读，不覆盖已有台账。默认按结果章节、结论词和数值线索排序候选；这是确定性候选筛选，不是完整语义抽取。宿主读稿后可以用 `selections` 精确选择原文并指定 `claim_type`：

```json
{"path":"paper.md","max_claims":3,"selections":[{"quote":"原文中完整且精确的一条命题。","location":"L12","claim_type":"causal_effect"}]}
```

每条科学主张包含设计包、八项统计报告、四类溯源卡、`causal_basis` 和空 `effect_records`；general 工程主张不强填因果设计。检查为 `unknown`，执行/检索卡为 `not_run`，等级为 `unassessed`；不会把稿件声称的随机化、显著性或外部验证当作已核实事实。研究者只需确认候选主张和补充对应证据，不必手写骨架 JSON。

## 2. 读取已有产物，或随实际运行采集

- **扩展产物格式与细粒度元数据**：`artifact_format` 新增 `"xlsx"`（多 sheet 列头、行数与 `formula_cached_values` 缓存公式警示；不求值公式）与 `"parquet"`（`PAR1` 魔数与有限 Thrift `FileMetaData` 列模式/总行数摘要，不解码数据页 `data_content_verified=false`）。`.ipynb` 增加 `out_of_order_execution`、`markdown_cells` 与脱敏 `kernelspec`；`.rmd`/`.qmd` 增加 `chunk_languages` 与受限标量 YAML 头字段；`.dvc` / `dvc.lock` 对可解析的本地工作区内常规非 `.dir` 文件实际计算 MD5/SHA-256 校验 `data_content_verified`（缺失/不匹配/`.dir`/远端对象保留 `false`）。

`parrhesia_import_artifact` / `call import_artifact` 的最小请求：

```json
{"case_id":"<实际 case_id>","path":"results/fit.csv","artifact_format":"statistics"}
```

| `artifact_format` | 接受的产物 | 能直接记录的内容 |
|---|---|---|
| `notebook` | nbformat 4 `.ipynb` | 代码单元 execution_count、保存输出数、错误、未执行单元 |
| `rmarkdown` / `quarto` | `.Rmd` / `.qmd` | 源代码块数；执行状态保持未知 |
| `nextflow_trace` | 有 task_id/status/exit 的 TSV | task_id、native_id、状态、退出值、容器字段 |
| `snakemake_stats` | 含 rules/runtime 的统计 JSON | 原有规则/运行时间字段 |
| `container_inspect` | image inspect JSON | Id/RepoDigests 中不可变 SHA-256，不抄出 Config.Env |
| `dvc` | `.dvc` / `dvc.lock` | 支持的字面 md5/sha256 字段；不解析任意 YAML、不下载数据 |
| `slurm_sacct` | JobID/State/ExitCode 的 `|` 分隔表 | 保存的作业状态与 ID |
| `pbs_json` | qstat JSON 的 Jobs 对象 | 作业 ID、状态和已有退出字段 |
| `junit` | testsuite/testsuites XML | testcase、失败、错误、跳过计数；失败不删除 |
| `dataset_metadata` | JSON | synthetic/data_origin/version 等有限字段 |
| `statistics` | CSV/TSV/JSON/Markdown 表格 | 可解析行数、有效行数及未解决行 |

`auto` 仅识别无歧义扩展名；JSON/XML/日志建议显式指定格式。不把 notebook 的旧输出、Nextflow 的 `CACHED`、HPC 的提交记录或镜像摘要冒充本轮成功执行。

运行采集示例：

```powershell
python -m parrhesia record-exec --workspace C:\YourWorkspace --case-id <case_id> --input-file data/clean.csv --metadata-file dataset_metadata=data/metadata.json --artifact statistics=results/fit.csv --artifact notebook=results/executed.ipynb -- python run_analysis.py
```

`--artifact FORMAT=path` 可重复：自动纳入运行前后输出快照，运行后检查并登记产物。`--metadata-file FORMAT=path` 可重复：在运行前读取并哈希已有元数据。已有的 git 提交/dirty 状态、lockfile、输入输出哈希保持采集；仅增加白名单 scheduler job ID，不枚举环境变量。命令只运行用户明确指定的程序，导入器不自动安装或启动 Jupyter、R、Nextflow、Snakemake、容器或 HPC 作业。

只有同一案例中的 `record_exec` 成功完成、退出 0，且产物匹配已声明输出的路径、SHA-256 和 `created`/`modified` 状态时，才生成 `execution_binding`。可在导入请求中给 `execution_evidence_id` 显式绑定。`unchanged` 即使文件存在、哈希正确，也不能证明新生成；未绑定导入保持 `reported`。失败运行仍保留日志、部分产物和错误；CLI 延续原有非零子进程返回值的 JSON 报告约定，使用 `exit_status` / `execution_card.status` 判断分析成功。

## 3. 自动提取并对照稿件数值

PDF 的页码来自实际 Catalog/Pages/Kids 页树，不来自对象存储顺序。字体资源按页面继承与当前 `Tf` 绑定；不能确定当前编码时拒绝读取，不合并所有字体的 ToUnicode 映射。xref/object streams、增量更新、未知编码与 ActualText 替代文字不在支持范围；XObjects 的未读部分列入 `omitted`，保留 partial 状态，不进行 OCR 或 Form 遍历。需要更广 PDF 支持时，先用可信阅读器核对并导出文本再登记，不把当前有限解析范围称为完整 PDF 支持。

- **扩展输入与对齐选项**：`format` 新增 `"contingency_json"`（2×2 列联表提取及 Fisher 精确检验/OR/RR/RD 预计算）与 `"xlsx"`（支持可选 `sheet_name` 选表；默认优先识别含终点与效应列的工作表并标记 `omitted_sheets` 与缓存公式警示）。对照稿件时支持可选 `assumed_reported_scale`（`"auto"|"unit"|"percentage"`）：百分比数据源在稿件省略 `%` 时默认保留 `ambiguous_scale`，仅在调用方显式指定尺度时按声明换算；且 `verify` 对 `.xlsx` 的 `artifact_binding` 传入原始 `snapshot_bytes` 做行级重锚定。

```json
{"case_id":"<实际 case_id>","evidence_id":"<已登记的产物 evidence_id>","manuscript_path":"paper.md"}
```

送入 `parrhesia_extract_effects` / `call extract_effects`。始终解析已登记快照，当前磁盘文件变化不会悄悄替换分析对象；`verify` 会另报源文件漂移。此入口只读，不自动把提取结果写回任何主张。

支持单表 CSV/TSV、Markdown 表、JSON 行数组或 `{"rows":[...]}`。支持 broom 风格 `term/estimate/conf.low/conf.high/p.value` 等列别名；非标准表头用 `column_map` 显式映射。一般 `estimate` 不擅自当成 HR 或 beta；没有 metric 时保留 `other`，明确 `coef/coefficient` 才映射 beta。`n` 只是表中分母，不宣称它是独立生物学重复。

示例统计表：

```csv
endpoint,metric,estimate,ci_low,ci_high,p_value,ci_level,n
mortality,HR,0.71,0.55,0.91,0.008,0.95,120
```

明确命名的二分类混淆矩阵 `{"endpoint":"test-set","tp":40,"tn":50,"fp":5,"fn":5}` 可计算 accuracy 和 F1；输出注明公式，不编造 CI。多分类、权重矩阵与未注明方向的二维数组暂不猜测，须先导出明确的表格。

2×2 列联表支持 `{a,b,c,d}` 或 `{treated_events,treated_n,control_events,control_n}`，均需明确 `endpoint`。Fisher 双侧检验按固定边际的整数权重选择概率不大于观测表的尾部，计算范围为总计数不超过 20,000 且支持表数不超过 10,000。超限时不进行该计算，保留可用点估计、略去 `p_value`，返回 `fisher_work_limit`；不能将缺失 p 值解释为不显著。严格正概率低于正常浮点精度时同样略去 `p_value`，返回 `fisher_p_underflow`、近似自然对数 `log_p_value` 及上界，不返回精确零。两个问题都进入 `issues`，状态为 `parsed_with_issues`；效应记录附有相应说明，导入和提取均保留这些限制。

返回每行 `effect_records` 与 `artifact_binding`（版本、源 SHA-256、格式、行序、列映射）。门控会重新解析绑定行或重算混淆矩阵公式；同文件另一行出现相同数字不能替代当前行。已识别统计产物不能删掉 binding 后退回宽松的全文数字匹配。每次最多 50 行，超限明确拒绝，不能静默截断以选择有利结果。

手动登记与显式导入对上述两套列联表键采用相同统计分类和研究类别限制；重命名或省略 artifact 元数据不解除约束。旧冻结证据的完整快照若显示统计产物与原研究类别冲突，审查入口返回 `artifact_kind_conflict`，不改写原记录。应新建案例，以 `unknown` 重登记统计补充来源，并独立提供相容的研究设计证据。旧公式计算（含错误的 `p=0`）若与本版重算值不同，严格绑定会报告不一致；重新提取后用于新案例，不自动修改既有冻结效应或沿用旧审查接受状态。

缺失值、非有限数、单边 CI、不一致区间、`p<0.001` 这类非精确输入均进入 `issues`，保留原行，不伪造 0 或精确 p。默认 `endpoint_role=exploratory`、`direction=neutral`，不会因区间排除零而声称获益。Wald/GRIM 等原有检查仍要求实际适用条件。

列联表点估计也受数值表示范围约束：RD/RR/OR 先用整数构成比值，避免先算比例造成下溢或除零。无法表示的效应逐项略去，分别记录 `effect_underflow` / `effect_out_of_range`，其他可表示的效应与真实零保持；不能把被略去的记录补成零。

稿件比较在同一文字单元中找到明确的终点和指标、且匹配唯一时才核对。拉丁字母缩写按词边界匹配，例如 `PFS` 不会命中 `iPFS`。estimate、显式 CI 与 p 按报告精度比较，支持 p 不等式。`p=0` 会返回带 `invalid_reported_p_value` 的 `mismatch`。输出还区分 `match_at_reported_precision`、`not_found`、`ambiguous`、`incomplete_comparison`，逐项列出未比较字段。重名、复杂排版与语义对应仍由研究者核对。

多工作表 XLSX 预填需要把 `extract_effects` 的选表名称作为 `effect_sources[].sheet_name` 一并传入。两张表的相同记录编号可以各自选取，返回记录的 `artifact_binding.sheet` 保留对应表名。LaTeX 展开后，`source.sha256` 绑定根文件及实际读取的子文件，并返回各文件摘要。只改子文件也要重新生成草稿与绑定。

## 4. 将来源预填到台账草稿

导入后取得 `evidence_id`，用 `extract_effects` 查看有效记录、未解析行及 `record_id`，再明确选择对应主张的记录：

```json
{"case_id":"<实际 case_id>","claim_id":"C1","text":"<待审查主张>","scope":"<明确范围>","prefill":{"design_families":["observational"],"effect_sources":[{"evidence_id":"<实际 evidence_id>","record_ids":["effect-1"]}]}}
```

送入 `scaffold_claim`。服务从已登记快照重建完整 `effect_records` 和来源绑定，返回 `claim`、`prefill_report`、`check_ceilings` 与可预检的 `ledger_payload`。无需复制数值和嵌套校验字段。可附加 `evidence_ids` 或已登记的 `hypothesis_id`；假说绑定不认证历史时序，`origin` 仍为 unknown，设计检查不自动通过。

稿件批量预填可在再次调用 `draft_manuscript` 时传入：

```json
{"path":"paper.md","case_id":"<实际 case_id>","expected_source_sha256":"<首次 draft 返回的 source.sha256>","claim_bindings":[{"claim_id":"C1","quote":"<source_map 对应原文>","location":"<source_map 对应位置>","prefill":{"effect_sources":[{"evidence_id":"<实际 evidence_id>","record_ids":["effect-1"]}]}}]}
```

保留原来的 `selections` 等选择参数。稿件变化、原文/位置不符、重复主张绑定、未知来源或无效记录会拒绝，不把旧 `C1` 静默接到新主张。报告保留未选记录 ID、原始解析问题、来源哈希及执行绑定状态；未选结果不等于不存在，也不自动证明选择合理。

这两种预填均只读。核对范围、终点方向与证据解释后，用 `parrhesia_validate(action="set_ledger", payload=ledger_payload)` 预检，再显式提交。**`set_ledger` 替换整份草稿台账**，已有其他主张须先合并；预填报告会列出当前主张 ID。缺少的分析单位、识别假设和时间范围仍须据来源填写。

## 证据类别与兼容边界

`record-exec` 的旧默认 `benchmark` 已移除，默认 `auto` 推导为 `unknown`。任意程序成功退出不足以证明科学基准、干预研究或独立验证。结构可识别的 JUnit 来源推导为 `test_log`（不意味着测试通过）；明确 synthetic 元数据及 synthetic 父来源保留合成限制。其他工作流和统计产物的研究设计保留 `unknown`。请求 `kind` 只能保留已推导类别或收窄为 unknown/synthetic，不能升级；synthetic 不可洗成 unknown/observed。

同一工作区重复登记同一 SHA-256、直接通过旧 `register_evidence` 登记可识别结构产物，也受类别限制。普通论文/叙述材料的历史手工登记契约仍保留 `registrant_report_not_execution_attestation`，不改写历史冻结记录；此功能没有声称能仅凭文件推断所有研究设计或鉴定文件真伪。事实性研究资格仍由来源与审查决定。

正向判定可以同时引用相容的研究来源与补充材料：真实记录的执行收据、含 `artifact_binding` 的统计产物可作为补充来源，但不能单独建立研究类别。补充材料仍受合成来源、可读性、引用、数值与运行遗漏门控约束；不会通过这种分工自动升级 kind。

这解决的是输入和核对负担：模板自动生成、数值由产物解析、执行与产物可绑定。它不将工程核对升级成科学真实性、实际节省时间或用户效果验证。
