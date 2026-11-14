# 0.2.0 到 0.3.0 本地升级说明

0.3.0 为 2026-11-14 修复后的明确软件版本。Claim Schema v2、gate_version=1 和 Agent Plugins 1.0.0 是不同层面的版本，保持原值。以发布包 RELEASE-MANIFEST.json 的文件摘要和 ZIP SHA-256 标识具体构建，不只依赖 Git HEAD；工作树可能包含未提交改进。

## 保留旧记录

升级不删除旧缓存、证据、失败日志或 SQLite 案例，不自动迁移冻结输入、裁决摘要与用户接受状态。保留旧包、安装配置来源及新的安装执行记录。新包应在独立验收目录中验证，避免将合成测试案例混入研究工作区。

## 调用方需要调整的语义

- `supported` 支持的是命题，不等于疗效有益。`claim_direction` 明确命题方向；缺失时保留未核对，不猜测。
- `inference_method=wald|log_wald` 声明适用的配对双侧未调整 CI/检验；其他方法未做数值核验。`count_basis=unweighted_binary` 只用于准确二项分母。不要为通过门控而改写来源的方法。
- 草稿、未完成有效裁决或被暂停的关系保持 pending，不替代当前有效结论。
- 结局必须绑定可核对的注册来源；数值结局需指定原 `effect_record_id` 与 `metric`。缺失或失效来源的旧记录保留内容，但不计入已解析评分。
- 显式概率的可评分二元结局使用 `proper_scores.explicit_brier_score` / `explicit_log_score`；启发式映射在 `heuristic_scores` 中。旧 `proper_scores.combined_brier_score` / `combined_log_score` 返回 null。
- 复现点使用 `replication_point_containment_rate`，不与名义 CI 水平等同；只有声明的 known_truth 参考值参与真值覆盖率。`z_difference` 在双方方法与独立性/协方差条件具备时计算；旧 `z_drift` / `mean_absolute_z_drift` 返回 null。
- `record-exec` 的超时与启动失败 wrapper 分别返回 124/127，未知子进程退出码为 null。正常非零子进程仍生成失败卡，wrapper 0 仅表示收据生成；自动化应读取收据状态。

## 验收范围

安装/包身份、真实宿主发现与调用、完整工作流、符号链接路径拒绝应分别记录。独立 MCP 子进程握手只支持相应集成测试；真实宿主调用也不证明审查者独立性、科学语义有效性或用户净收益。不要把旧版本的历史测试结果重新标成新版本结果。
