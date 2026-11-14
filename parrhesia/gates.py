"""Frozen anti-stall gates. Enforces structure, never certifies scientific truth."""
import hashlib
import re
import unicodedata
from .claims import NON_PRIMARY_FAILED_FORK_ROLES, TYPE_LEVELS, needs_causal_basis
from .contracts import ContractError, array, enum, fail, fields, ids, obj, string

GATE_VERSION = 1
MIN_QUOTE_CHARS = 12
MIN_CJK_QUOTE_CHARS = 6
GATE_GUIDANCE = (
    " Current gate_version=1: submit exactly one original-claim stance per claim, even with zero findings, "
    "and acknowledge every unread source in unread_evidence_ids. Positive references each require a unique "
    "quote of at least 12 non-whitespace units (6 CJK characters or 12 ASCII characters) linked to the claim and location; "
    "synthetic cannot support empirical positives. "
    "Respect check_ceilings, level-progressive design/statistical check requirements, evidenced pass rules, and evidence-kind compatibility "
    "(observational evidence may conditionally support causal_effect only as partially_supported when causal_basis and observational "
    "confounding/robustness checks pass). Adjudication binds each finding to its claim's decision with an incorporated revised_text_quote "
    "or explicit disagreement. Blind is frozen case-wide."
)
ESSENTIAL_DESIGN_CHECKS = {
    "observational": ("sampling_temporality", "confounding_selection"),
    "quasi_experimental": ("assignment_rule", "identification"),
    "randomized": ("randomization_concealment", "analysis_population"),
    "prediction": ("target_horizon", "splits_leakage"),
    "ml": ("data_contamination", "splits_tuning"),
    "mechanism": ("causal_model", "specificity_controls"),
    "evidence_synthesis": ("protocol_search", "eligibility_selection"),
    "theory": ("definitions_assumptions", "proof"),
    "qualitative": ("epistemic_position", "sampling_context"),
}
FAMILY_TIER_CHECKS = {
    "observational": {
        1: ("sampling_temporality", "measurement"),
        2: ("sampling_temporality", "measurement", "confounding_selection"),
        3: ("sampling_temporality", "measurement", "confounding_selection", "missingness", "robustness"),
    },
    "quasi_experimental": {
        1: ("assignment_rule", "identification"),
        2: ("assignment_rule", "identification", "diagnostics_placebos"),
        3: ("assignment_rule", "identification", "diagnostics_placebos", "local_scope", "sensitivity"),
    },
    "randomized": {
        1: ("randomization_concealment", "analysis_population"),
        2: ("randomization_concealment", "analysis_population", "adherence_attrition"),
        3: ("randomization_concealment", "analysis_population", "adherence_attrition", "interference", "harms"),
    },
    "prediction": {
        1: ("target_horizon", "calibration_discrimination"),
        2: ("target_horizon", "calibration_discrimination", "splits_leakage"),
        3: ("target_horizon", "calibration_discrimination", "splits_leakage", "validation_shift"),
        4: ("target_horizon", "calibration_discrimination", "splits_leakage", "validation_shift", "utility"),
    },
    "ml": {
        1: ("baselines_budget", "splits_tuning"),
        2: ("baselines_budget", "splits_tuning", "data_contamination", "seeds_uncertainty"),
        3: ("baselines_budget", "splits_tuning", "data_contamination", "seeds_uncertainty", "ablations_compute"),
    },
    "mechanism": {
        1: ("causal_model",),
        2: ("causal_model", "specificity_controls", "temporal_chain"),
        3: ("causal_model", "specificity_controls", "temporal_chain", "rescue_orthogonal", "rival_pathways"),
    },
    "evidence_synthesis": {
        1: ("protocol_search", "eligibility_selection"),
        2: ("protocol_search", "eligibility_selection", "bias_dependence", "heterogeneity"),
        3: ("protocol_search", "eligibility_selection", "bias_dependence", "heterogeneity", "certainty_missing_studies"),
    },
    "theory": {
        1: ("definitions_assumptions", "proof"),
        2: ("definitions_assumptions", "proof", "boundary_counterexamples", "independent_check"),
        3: ("definitions_assumptions", "proof", "boundary_counterexamples", "independent_check"),
    },
    "qualitative": {
        1: ("epistemic_position", "sampling_context"),
        2: ("epistemic_position", "sampling_context", "reflexivity_ethics", "analysis_audit"),
        3: ("epistemic_position", "sampling_context", "reflexivity_ethics", "analysis_audit", "negative_cases_transfer"),
    },
}
LEVEL_TIERS = {
    "description": {"measurement_checked": 1, "replicated": 2},
    "association": {"unadjusted": 1, "adjusted": 2, "robust_association": 3},
    "prediction": {"apparent": 1, "internally_validated": 2, "externally_validated": 3, "prospectively_evaluated": 4},
    "causal_effect": {"identified_under_assumptions": 2, "sensitivity_supported": 3},
    "mechanism": {"compatible": 1, "component_tested": 2, "causal_chain_tested": 3},
    "necessity": {"bounded_test": 2, "counterfactual_supported": 3},
    "sufficiency": {"bounded_test": 2, "counterfactual_supported": 3},
    "synthesis": {"mapped": 1, "critically_appraised": 2, "synthesized_with_uncertainty": 3},
    "theory": {"proved_under_assumptions": 1, "independently_checked": 3},
    "qualitative": {"situated_description": 1, "interpretation_audited": 2, "triangulated": 3},
    "computational": {"benchmark_measured": 1, "reproduced": 2, "externally_evaluated": 3},
    "engineering": {"test_passed": 1, "host_accepted": 2, "user_impact": 3},
}
ESSENTIAL_STAT_CHECKS = ("units_sample_size", "estimate_uncertainty")
PLACEHOLDER_TOKENS = {
    "UNKNOWN", "NA", "N/A", "N.A.", "NONE", "NULL", "NIL", "NAN",
    "NOT_RUN", "NOT RUN", "NOT_IDENTIFIABLE", "NOT IDENTIFIABLE",
    "NOT_APPLICABLE", "NOT APPLICABLE", "UNSPECIFIED", "UNDEFINED",
    "UNDETERMINED", "UNCLEAR", "TBD", "TBA", "TBC", "TODO", "WIP",
    "PENDING", "OMITTED", "MISSING", "EMPTY", "BLANK", "PLACEHOLDER",
    "SEE ABOVE", "SEE_ABOVE", "SAME AS ABOVE", "AS ABOVE", "SEE BELOW",
    "SEE_BELOW", "DITTO", "IBID", "IBIDEM", "ETC",
    "未知", "未明", "不详", "不明", "不清楚", "不确定", "未定",
    "无", "暂无", "空白", "空", "缺", "缺失", "缺省", "省略", "略",
    "待定", "待填", "待补充", "待核实", "待确认", "待办", "待考",
    "未运行", "未执行", "未评估", "未检验", "未测试", "未识别", "不可识别",
    "不适用", "无适用", "见上", "见上文", "同上", "如上", "见前", "同前",
    "见下", "见下文", "如下", "无内容", "占位", "占位符",
}
TRIVIAL_REASONS = PLACEHOLDER_TOKENS | {
    "OK", "OKAY", "PASS", "PASSED", "YES", "Y", "GOOD", "FINE", "DONE",
    "VALID", "CHECKED", "TRUE", "VERIFIED", "SURE",
    "好", "好的", "可以", "行", "通过", "合格", "没问题", "已查", "已核", "正确", "对", "是",
}
QUOTE_STOPWORDS = {
    "this", "that", "with", "from", "were", "have", "been", "only", "text",
    "file", "line", "page", "copyright", "reserved", "rights", "header",
    "footer", "note", "document", "section", "author", "date", "time",
    "version", "status", "some", "more", "than", "into", "upon", "also",
    "such", "when", "what", "where", "which", "while", "there", "their",
    "about", "under", "after", "before",
}
DISPOSITION_BOILERPLATE = {
    "note", "noted", "notes", "remark", "remarks", "comment", "comments",
    "added", "addition", "additional", "supplement", "supplemental", "appendix",
    "see", "here", "above", "below", "also", "further", "furthermore", "moreover",
}
CJK_STOPWORDS = {"以下", "这个", "可以", "进行", "通过", "由于", "因此", "一个", "我们", "没有", "备注", "补充", "说明"}
CONTRADICTING_RELATIONS = (
    "unsupported", "contradicts", "contradict", "contradictory", "contradiction",
    "refutes", "refute", "refuted", "opposes", "oppose", "disproves", "disprove",
    "falsifies", "falsify", "counterevidence",
    "不支持", "反对", "矛盾", "相悖", "相冲突", "冲突", "反驳", "证伪", "推翻", "否定",
)
CONTRADICTING_PHRASES = (
    "does not support", "do not support", "doesn't support", "don't support",
    "did not support", "didn't support", "cannot support", "can't support",
    "could not support", "fails to support", "fail to support", "failed to support",
    "insufficient to support", "unable to support", "not supported",
    "no support", "no empirical support", "no evidence to support", "lacks support",
    "lack of support", "without support", "contrary to", "inconsistent with",
    "conflicts with", "conflict with", "at odds with", "against the claim",
    "against claim", "refutes the claim", "contradicts the claim",
    "无法支持", "不能支持", "不足以支持", "未能支持", "未支持", "不予支持",
    "无证据支持", "没有证据支持", "缺乏支持", "并无支持", "毫无支持",
    "与主张矛盾", "与结论矛盾", "与主张相悖", "与结论相反", "与主张相反",
    "不一致", "不相符", "相抵触",
)
NON_CONTRADICTING_NEGATIONS = (
    "does not contradict", "do not contradict", "doesn't contradict",
    "does not refute", "do not refute", "doesn't refute",
    "not contradictory", "no contradiction", "without contradiction",
    "不矛盾", "无矛盾", "不冲突", "无冲突", "并不矛盾", "并未反驳",
)
NULL_OR_REFUTING_EVIDENCE_PHRASES = (
    *CONTRADICTING_PHRASES,
    "null primary effect", "null primary finding", "null effect on primary",
    "null association", "null effect", "no effect observed", "no measurable effect",
    "no statistically significant effect", "no significant effect on primary",
    "no statistically significant association", "no significant association observed", "no significant association found",
    "no statistically significant difference", "no significant difference",
    "did not reach statistical significance", "not statistically significant",
    "failed to achieve statistical significance", "no treatment benefit",
    "no survival benefit", "no clinical benefit", "no net benefit",
    "no significant improvement", "did not improve", "failed to improve",
    "no improvement over", "effect size negligible", "hazard ratio near 1",
    "null result across", "failed to replicate", "fails to replicate",
    "零效应", "未见显著效应", "无统计学显著相关", "无显著相关", "未能重复",
    "无显著差异", "未达统计学意义", "无临床获益", "未见明显改善", "无明显改善", "未改善",
)
OUTCOME_STRIPPED_EVIDENCE_PHRASES = (
    "outcome data not yet collected", "outcomes not yet collected",
    "outcomes not collected", "endpoints not yet reported",
    "primary results pending", "results pending collection",
    "endpoint data not yet available", "awaiting outcome follow-up",
    "waiting for outcome data", "outcome follow-up incomplete",
    "primary endpoint table omitted", "endpoint table omitted",
    "outcome table omitted", "primary outcome omitted",
    "outcome results omitted", "primary results omitted", "endpoint results omitted",
    "protocol only without outcome", "baseline registration only without outcome",
    "no outcome data collected", "结局数据尚未采集", "结果待采集",
    "仅研究方案无结局数据", "结局指标数据缺失", "主要终点结果缺失",
    "主要终点未报告", "尚无结局结果",
)
NO_RANDOMIZATION_RE = re.compile(
    r"\b(?:no|without|lacks?|lack of|lacking)\s+random(?:ization|isation|ized|ised| allocation| assignment)\b"
    r"(?!(?:\s+(?:bias|failure|loss|compromise|violation)))"
    r"|\b(?:non[- ]?random(?:ized|ised)?|unrandom(?:ized|ised)?|pseudo[- ]?random(?:ized|ised)?|quasi[- ]?random(?:ized|ised)?)\b"
    r"|非随机|未随机|无随机|没有随机|伪随机",
    re.I,
)
_FUTURE_PREFIX_RE = (
    r"(?:future|planned|pending|needed|needs|need\s+for|requires|required|awaiting|waiting\s+for|"
    r"no|without|lacks?|lack\s+of|absence\s+of|lacking|missing|omitted)"
)
_VALIDATION_NOUNS_RE = (
    r"(?:validation|cohort|testing|evaluation|hospital|hospitals|study|studies|"
    r"follow[- ]?up|dataset|datasets|data|set|sets|sites?|centers?|centres?|replication|enrollment|collection)"
)
_PENDING_SUFFIX_RE = (
    r"(?:"
    r"(?:(?:is|are|was|were|remains?|stay(?:s)?)\s+)?"
    r"(?:(?:still|currently|presently|as\s+yet|yet)\s+)?"
    r"(?:needed|required|pending|planned|awaited|lacking|absent|omitted|missing|"
    r"unavailable|untested|unperformed|incomplete|not\s+(?:yet\s+)?(?:done|performed|conducted|completed|available))"
    r"|(?:(?:is|are|was|were|has|have|had)\s+)not\s+(?:yet\s+)?(?:been\s+)?"
    r"(?:done|performed|conducted|completed|carried\s+out|undertaken|established|assessed|evaluated|tested|validated|available)"
    r"|(?:(?:is|are|was|were|remains?|has|have|had)\s+)?(?:(?:still|currently)\s+)?(?:yet\s+)?to\s+(?:be\s+)?"
    r"(?:done|performed|conducted|completed|validated|tested|evaluated)"
    r")"
)
FUTURE_OR_NO_EXTERNAL_RE = re.compile(
    rf"\b{_FUTURE_PREFIX_RE}\s+"
    r"(?:(?:an?|any|further|additional|prior)\s+)?"
    r"(?:(?:independent|multi[- ]?center|multicentre|multi[- ]?institutional|prospective)\s+){0,2}"
    r"(?:external|out[- ]of[- ]hospital|independent\s+hospital)"
    r"(?:\s+(?:independent|multi[- ]?center|multicentre|multi[- ]?institutional|prospective))?"
    rf"(?:\s+{_VALIDATION_NOUNS_RE}){{1,3}}\b"
    rf"|\b{_FUTURE_PREFIX_RE}\s+(?:(?:an?|any|further|additional|prior)\s+)?independent\s+"
    r"(?:(?:multi[- ]?center|multicentre|multi[- ]?institutional)\s+)?"
    r"(?:validation|cohort|testing|evaluation|hospital|study)(?:\s+(?:validation|cohort|testing|evaluation|study)){0,2}\b"
    r"|\b(?:(?:independent|multi[- ]?center|multicentre|multi[- ]?institutional)\s+){0,2}"
    r"(?:external|out[- ]of[- ]hospital|independent\s+hospital)"
    r"(?:\s+(?:independent|multi[- ]?center|multicentre|multi[- ]?institutional|prospective))?"
    rf"(?:\s+{_VALIDATION_NOUNS_RE}){{1,3}}\s+{_PENDING_SUFFIX_RE}\b"
    r"|\bindependent\s+(?:(?:multi[- ]?center|multicentre|multi[- ]?institutional)\s+)?"
    rf"(?:validation|cohort|testing|evaluation)(?:\s+(?:validation|cohort|testing|evaluation)){{0,2}}\s+{_PENDING_SUFFIX_RE}\b"
    r"|\b(?:not(?:\s+yet)?|never|(?:is|are|was|were|has|have|had)\s+not(?:\s+yet)?(?:\s+been)?)\s+"
    r"externally\s+(?:validated|tested|evaluated)\b"
    r"|(?:尚需|尚待|有待|缺乏|无|未来|尚未完成|未开展|未进行)外部(?:医院)?(?:队列)?(?:验证|测试|评估)"
    r"|外部(?:医院)?(?:队列)?(?:验证|测试|评估)(?:尚|仍|目前)?(?:尚待|仍待|有待|待完成|待开展|待进行|尚需|需要|缺乏|缺失|未完成|未开展|未进行|尚未完成|尚未开展|尚未进行)",
    re.I,
)
FUTURE_OR_NO_PROSPECTIVE_RE = re.compile(
    rf"\b{_FUTURE_PREFIX_RE}\s+"
    r"(?:(?:an?|any|further|additional|prior)\s+)?"
    r"(?:(?:independent|multi[- ]?center|multicentre|multi[- ]?institutional|external)\s+){0,2}"
    r"prospective(?:ly)?"
    rf"(?:(?:\s+(?:independent|multi[- ]?center|multicentre|multi[- ]?institutional|external))?(?:\s+{_VALIDATION_NOUNS_RE}){{1,3}}|(?!\s+(?:randomi[sz]|blind|mask))\b)"
    r"|\bprospective(?:ly)?"
    r"(?:\s+(?:independent|multi[- ]?center|multicentre|multi[- ]?institutional|external))?"
    rf"(?:\s+{_VALIDATION_NOUNS_RE}){{1,3}}\s+{_PENDING_SUFFIX_RE}\b"
    r"|\b(?:not(?:\s+yet)?|never|(?:is|are|was|were|has|have|had)\s+not(?:\s+yet)?(?:\s+been)?)\s+"
    r"prospectively\s+(?:validated|evaluated|tested|collected|enrolled|followed|assessed|studied)\b"
    r"|(?:尚需|尚待|有待|缺乏|无|未来|非|尚未完成|未开展|未进行)前瞻(?:性)?(?:独立|多中心)?(?:队列|研究|验证|评估|随访|收集)?"
    r"|前瞻(?:性)?(?:独立|多中心)?(?:队列|研究|验证|评估|随访|收集){1,3}(?:尚|仍|目前)?(?:尚待|仍待|有待|待完成|待开展|待进行|尚需|需要|缺乏|缺失|未完成|未开展|未进行|尚未完成|尚未开展|尚未进行)",
    re.I,
)
NONPRIMARY_CLAUSE_RE = re.compile(
    r"\b(?:negative[- ]control|falsification[- ](?:outcome|endpoint|test)|"
    r"secondary[- ](?:endpoint|outcome|analysis|analyses|objective)|"
    r"exploratory[- ](?:endpoint|outcome|analysis|analyses|subgroup)|"
    r"safety[- ](?:endpoint|outcome)|prior[- ](?:work|study|studies|report|reports)|"
    r"previously[- ]reported|background[- ]literature)\b"
    r"|阴性对照|次要终点|次要结局|探索性终点|既往研究",
    re.I,
)
PRIMARY_CLAUSE_OVERRIDE_RE = re.compile(
    r"\bprimary[- ](?:endpoint|outcome|analysis|result|effect|finding|hypothesis)\b|主要终点|主要结局|主要结果",
    re.I,
)
METADATA_LABEL_RE = re.compile(
    r"\b(?:Table|Tab\.?|Fig\.?|Figure|Appendix|Supplementary\s+(?:Table|Figure)|Section|Sec\.?)\s*S?\d+(?:\.\d+)?[a-zA-Z]?\b",
    re.I,
)
ALPHA_LEVEL_RE = re.compile(r"(?:\balpha\b|α)\s*(?:=|<|<=|of|at|:)\s*0?\.\d+", re.I)
DECREASE_POLARITY_RE = re.compile(
    r"\b(?:reduc(?:ed|es|ing|tion)|lower(?:ed|s|ing)?|decreas(?:ed|es|ing)|drop(?:ped|s)?|"
    r"declin(?:ed|es|ing)|shorter|faster|abolish(?:ed|es)?|block(?:ed|s)?|attenuat(?:ed|es)?|fewer)\b"
    r"|\bless\s+(?:risk|mortality|morbidity|death|deaths|pain|bleeding|recurrence|relapse|"
    r"progression|incidence|prevalence|toxicity|burden|harm|harms|error|errors|latency|runtime|hazard)\b"
    r"|下降|降低|减少|缩短|减轻|阻断|抑制",
    re.I,
)
INCREASE_POLARITY_RE = re.compile(
    r"\b(?:increas(?:ed|es|ing)|gain(?:ed|s)?|higher|elevat(?:ed|es|ing)|ris(?:e|en|es|ing))\b"
    r"|升高|增加|提高|上升",
    re.I,
)
MULTI_FORK_EXECUTION_PATTERNS = (
    r"case execution fork #(\d+)",
    r"\bfork_count\s*[:=]\s*(\d+)",
    r"\b(\d+)\s+(?:execution|analysis|subgroup|hyperparameter|model|seed)\s+(?:forks|runs|trials|sweeps|configs|configurations|variants)\b",
    r"\b(?:screened|evaluated|tested|ran)\s+(\d+)\s+(?:random\s+seeds|seeds|subgroups|hyperparameter\s+configs|execution\s+forks|candidate\s+models)\b",
    r"共\s*(\d+)\s*(?:个|次)?(?:执行分叉|分析分叉|随机种子|超参配置|亚组检验)",
)
SELECTIVE_EXECUTION_OMISSION_PHRASES = (
    "omitted failed fork", "omitted failed forks", "omitted failed run", "omitted failed runs",
    "excluded failed seed", "excluded failed seeds", "excluded negative run", "excluded negative runs",
    "dropped negative fork", "dropped negative forks", "cherry-picked seed", "cherry-picked run",
    "cherry-picked fork", "selected best seed out of", "selected best run out of",
    "selected best fork out of", "reported only the passing run", "reported only passing fork",
    "best of 5 seeds without", "best of 10 seeds without", "unreported execution forks",
    "隐瞒失败分叉", "隐瞒失败运行", "剔除阴性运行", "仅报告最优种子", "仅报告通过的分叉",
)
FALSE_SINGLE_RUN_MULTIPLICITY_PHRASES = (
    "single run", "single execution", "single test only", "single primary test only",
    "only one run", "only one execution", "no multiple testing", "no multiplicity",
    "not applicable", "n/a", "single model run",
    "单一运行", "单次执行", "仅单次运行", "无多重检验", "不适用",
)
MULTIPLICITY_ADJUSTMENT_MARKERS = (
    "holm", "bonferroni", "benjamini", "hochberg", "fdr", "false discovery rate",
    "fwer", "family-wise", "familywise", "sidak", "šidák", "dunnett", "tukey", "scheffe",
    "permutation", "westfall", "romano", "wolf", "split-sample", "sample-split",
    "holdout", "held-out", "lockbox", "nested cv", "nested cross-validation",
    "cross-fitting", "hierarchical", "gatekeeping", "alpha spending", "obrien-fleming",
    "pocock", "across all", "all forks", "all seeds", "all runs", "mean±sd", "mean +/- sd",
    "pooled across", "prespecified primary endpoint", "pre-registered primary endpoint",
    "holm-bonferroni", "多重校正", "错误发现率", "族错误率", "留出集", "嵌套交叉验证",
    "全部运行", "全部分叉", "所有种子", "均值±标准差",
)
ANSI_ESCAPE_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[@-Z\\-_]"
)
WINDOW_DELIMITER_LINE_RE = re.compile(r"^<<<PARRHESIA_EXCERPT_WINDOW\b[^\r\n]*>>>$")
BOILERPLATE_OVERHEDGING_RE = re.compile(
    r"(无法得出确定结论|尚无法得出确定结论|难以得出明确结论|仅供参考|尚无法下结论|"
    r"cannot draw (?:any )?(?:firm|definitive) conclusions?|no firm conclusions? can be drawn|"
    r"for reference only|remains inconclusive pending)",
    re.I,
)
BINARY_SIGNATURES = (
    b"%PDF-",
    b"PK\x03\x04",
    b"\x89PNG",
    b"\xff\xd8\xff",
    b"\x1f\x8b",
    b"GIF8",
    b"\x7fELF",
)
EVIDENCE_KINDS = (
    "observation", "intervention", "quasi_experiment", "mechanistic_assay",
    "prediction_fit", "prediction_internal", "prediction_external", "prediction_prospective",
    "benchmark", "benchmark_replication", "benchmark_external", "systematic_review",
    "theoretical_proof", "qualitative_material", "test_log", "host_acceptance", "user_outcome",
    "synthetic", "unknown",
)
BASES = ("empirical", "synthetic", "formal")
POSITIVE = ("supported", "partially_supported")
ALL_KNOWN = tuple(k for k in EVIDENCE_KINDS if k not in ("unknown", "synthetic"))
CAUSAL_KINDS = ("intervention", "quasi_experiment")
COMPATIBILITY = {
    "description": {"recorded": (*ALL_KNOWN, "synthetic"), "measurement_checked": ALL_KNOWN, "replicated": ALL_KNOWN},
    "association": {k: ("observation", *CAUSAL_KINDS) for k in ("unadjusted", "adjusted", "robust_association")},
    "prediction": {
        "apparent": ("prediction_fit", "prediction_internal", "prediction_external", "prediction_prospective"),
        "internally_validated": ("prediction_internal", "prediction_external", "prediction_prospective"),
        "externally_validated": ("prediction_external", "prediction_prospective"),
        "prospectively_evaluated": ("prediction_prospective",),
    },
    "causal_effect": {k: CAUSAL_KINDS for k in ("identified_under_assumptions", "sensitivity_supported")},
    "mechanism": {"compatible": ("observation", "mechanistic_assay", *CAUSAL_KINDS), "component_tested": ("mechanistic_assay", *CAUSAL_KINDS), "causal_chain_tested": CAUSAL_KINDS},
    "necessity": {k: CAUSAL_KINDS for k in ("bounded_test", "counterfactual_supported")},
    "sufficiency": {k: CAUSAL_KINDS for k in ("bounded_test", "counterfactual_supported")},
    "synthesis": {k: ("systematic_review",) for k in ("mapped", "critically_appraised", "synthesized_with_uncertainty")},
    "theory": {k: ("theoretical_proof",) for k in ("proved_under_assumptions", "independently_checked")},
    "qualitative": {k: ("qualitative_material",) for k in ("situated_description", "interpretation_audited", "triangulated")},
    "computational": {"benchmark_measured": ("benchmark", "benchmark_replication", "benchmark_external", "synthetic"), "reproduced": ("benchmark_replication", "benchmark_external"), "externally_evaluated": ("benchmark_external",)},
    "engineering": {"test_passed": ("test_log", "host_acceptance", "user_outcome"), "host_accepted": ("host_acceptance", "user_outcome"), "user_impact": ("user_outcome",)},
}


def gated(case):
    schema = case.get("schema_version", 1)
    if type(schema) is not int or schema not in (1, 2):
        fail("unsupported_contract_version", "stored schema_version is unsupported; no legacy fallback")
    if "gate_version" not in case:
        return False
    version = case["gate_version"]
    if type(version) is not int or version != GATE_VERSION or schema != 2:
        fail("unsupported_contract_version", "stored gate_version/schema combination is unsupported; no legacy fallback")
    return True


def strip_window_markers(text):
    if not isinstance(text, str) or not text:
        return ""
    if "<<<PARRHESIA_EXCERPT_WINDOW" not in text:
        return text
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not WINDOW_DELIMITER_LINE_RE.match(line.rstrip("\r\n"))
    )


def _parse_authenticated_windows(ev):
    """Verify sequential chunk headers and SHA-256 slices against ev['excerpt_windows']."""
    if not isinstance(ev, dict) or ev.get("source_text_status") != "truncated":
        return None
    rendered = ev.get("source_text")
    windows = ev.get("excerpt_windows")
    if not isinstance(rendered, str) or not isinstance(windows, list) or not windows:
        return None
    parsed = []
    pos = 0
    total = len(rendered)
    for idx, win in enumerate(windows):
        if not isinstance(win, dict):
            return None
        w_index = win.get("index")
        w_roles = win.get("roles")
        start_char = win.get("start_char")
        end_char = win.get("end_char")
        start_line = win.get("start_line")
        end_line = win.get("end_line")
        total_chars = win.get("total_chars")
        text_sha256 = win.get("text_sha256")
        if (
            type(w_index) is not int
            or w_index != idx + 1
            or not isinstance(w_roles, list)
            or not all(isinstance(r, str) for r in w_roles)
            or type(start_char) is not int
            or type(end_char) is not int
            or type(start_line) is not int
            or type(end_line) is not int
            or type(total_chars) is not int
            or not (0 <= start_char <= end_char <= total_chars)
            or start_line < 1
            or end_line < start_line
            or not isinstance(text_sha256, str)
        ):
            return None
        header = (
            f"<<<PARRHESIA_EXCERPT_WINDOW index={w_index} role={','.join(w_roles)} "
            f"chars={start_char}-{end_char} lines={start_line}-{end_line} of total_chars={total_chars}>>>\n"
        )
        if not rendered.startswith(header, pos):
            return None
        pos += len(header)
        body_len = end_char - start_char
        if pos + body_len > total:
            return None
        body = rendered[pos : pos + body_len]
        if hashlib.sha256(body.encode("utf-8")).hexdigest() != text_sha256:
            return None
        pos += body_len
        if idx + 1 < len(windows):
            if not rendered.startswith("\n", pos):
                return None
            pos += 1
        parsed.append((win, body))
    if pos != total:
        return None
    return parsed


def _authenticated_source_text(ev):
    if not isinstance(ev, dict):
        return ""
    parsed = _parse_authenticated_windows(ev)
    if parsed is not None:
        return "\n".join(body for _, body in parsed)
    raw = ev.get("source_text")
    return raw if isinstance(raw, str) else ""


def _authenticated_quote_status(quote, ev):
    parsed = _parse_authenticated_windows(ev)
    if parsed is None:
        return quote_status(quote, ev.get("source_text") if isinstance(ev, dict) else ev)
    if quote is None:
        return "not_supplied"
    clean_quote = strip_terminal_escapes(quote)
    if quote_length(clean_quote) < MIN_QUOTE_CHARS:
        return "too_short"
    total_hits = 0
    for _, body in parsed:
        first = body.find(clean_quote)
        if first >= 0:
            total_hits += 1
            if total_hits > 1 or body.find(clean_quote, first + 1) >= 0:
                return "ambiguous"
    if total_hits == 0:
        return "mismatch"
    return "matched"


def strip_terminal_escapes(text):
    if not isinstance(text, str):
        return ""
    cleaned = ANSI_ESCAPE_RE.sub("", text)
    return "".join(c for c in cleaned if c not in "\x07\x08\x0b\x0c\ufeff")


def text_content(content):
    # PDF/archives and NUL-bearing buffers must not masquerade as read UTF-8 text.
    if content.startswith(BINARY_SIGNATURES) or b"\x00" in content:
        return None
    try:
        value = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    value = strip_terminal_escapes(value)
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        return None
    return value


def _is_cjk_char(ch):
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
        or 0xF900 <= code <= 0xFAFF
    )


def is_placeholder(value):
    if not isinstance(value, str):
        return True
    visible = "".join(c for c in value if not unicodedata.category(c).startswith("C")).strip()
    if not visible:
        return True
    upper = visible.upper()
    if upper in PLACEHOLDER_TOKENS:
        return True
    stripped = re.sub(r"^[\W_]+|[\W_]+$", "", upper, flags=re.UNICODE)
    normalized = re.sub(r"[\s_\-]+", " ", stripped).strip()
    if not stripped or stripped in PLACEHOLDER_TOKENS or normalized in PLACEHOLDER_TOKENS:
        return True
    return False


def is_contradicting_relation(value):
    if not isinstance(value, str):
        return False
    norm = re.sub(r"[\s_\-]+", " ", value.strip().lower())
    if not norm:
        return False
    for safe in NON_CONTRADICTING_NEGATIONS:
        norm = norm.replace(safe, " ")
    norm = re.sub(r"\s+", " ", norm).strip()
    if norm in CONTRADICTING_RELATIONS:
        return True
    if any(phrase in norm for phrase in CONTRADICTING_PHRASES):
        return True
    tokens = set(re.findall(r"[a-z]+", norm))
    if tokens & {
        "unsupported", "contradicts", "contradict", "contradictory", "contradiction",
        "refutes", "refute", "refuted", "opposes", "oppose", "disproves", "disprove",
        "falsifies", "falsify", "counterevidence",
    }:
        return True
    return any(term in norm for term in ("不支持", "反对", "相悖", "反驳", "证伪", "推翻"))


def meaningful(value):
    if not isinstance(value, str) or is_placeholder(value):
        return False
    visible = "".join(c for c in value if not unicodedata.category(c).startswith("C")).strip()
    return quote_length(visible) > 0


def substantive_reason(value):
    if not meaningful(value):
        return False
    visible = "".join(c for c in value if not unicodedata.category(c).startswith("C")).strip()
    cleaned = "".join(c for c in visible if c.isalnum() or c.isspace()).strip().upper()
    if not cleaned or cleaned in TRIVIAL_REASONS:
        return False
    return quote_length(visible) >= 6


def effective_status(record, require_evidence=True):
    status = record.get("status", "unknown")
    if status == "fail":
        return "fail"
    if not substantive_reason(record.get("reason")):
        return "unknown"
    if status != "pass":
        return status
    if require_evidence and not record.get("evidence_ids"):
        return "unknown"
    return "pass"


def quote_length(value):
    # Whitespace, format controls, standalone combining marks and private-use
    # codepoints cannot pad a short anchor. CJK ideographs carry ~2x lexical
    # density per codepoint relative to ASCII letters, so each CJK character
    # counts as 2 units (6 CJK characters == 12 units == MIN_QUOTE_CHARS).
    total = 0
    for c in value:
        if c.isspace() or unicodedata.category(c)[0] in "CM":
            continue
        total += 2 if _is_cjk_char(c) else 1
    return total


def quote_status(quote, source):
    if quote is None:
        return "not_supplied"
    clean_quote = strip_terminal_escapes(quote)
    if quote_length(clean_quote) < MIN_QUOTE_CHARS:
        return "too_short"
    if source is None:
        return "not_text"
    first = source.find(clean_quote)
    if first < 0:
        return "mismatch"
    if source.find(clean_quote, first + 1) >= 0:
        return "ambiguous"
    return "matched"


def contradictory_evidence_kind(ev, counterfactual_gates=True):
    kind = ev.get("kind")
    parts = [
        _authenticated_source_text(ev),
        str(ev.get("quote") or ""),
        str(ev.get("label") or ""),
    ]
    text = " ".join(p for p in parts if p).lower()
    if not text.strip():
        return None
    if counterfactual_gates and ev.get("provenance") != "synthetic" and kind != "synthetic":
        syn_markers = (
            "synthetic simulation", "synthetic toy", "toy monte carlo",
            "monte carlo simulation only", "in-silico simulation only",
            "simulated toy dataset", "no empirical observations",
            "合成模拟数据", "蒙特卡洛模拟数据", "纯合成模拟",
        )
        if any(m in text for m in syn_markers):
            return "synthetic_source_declared_as_empirical"
    if kind == "intervention":
        obs_markers = (
            "observational cohort", "observational study", "observational registry",
            "cross-sectional observational", "retrospective observational", "non-randomized",
            "nonrandomized", "观察性队列", "观察性研究", "非随机",
        )
        obs_scrubbed = re.sub(
            r"\b(?:prior|previous|earlier|historical|past|initial|preliminary|unlike(?:\s+(?:prior|previous|earlier|historical))?)\s+"
            r"(?:observational|non[- ]randomized|nonrandomized|retrospective)\b",
            " ",
            text,
        )
        obs_scrubbed = re.sub(r"(?:既往|此前|先前|早期|不同于)观察性", " ", obs_scrubbed)
        scrubbed = NO_RANDOMIZATION_RE.sub(" ", text)
        for neg in ("not randomized", "unrandomized", "未随机"):
            scrubbed = scrubbed.replace(neg, " ")
        int_markers = (
            "random", "rct", "interven", "knockout", "crispr", "perturb",
            "double-blind", "placebo-controlled", "sham-controlled",
            "随机", "干预", "敲除", "盲法", "安慰剂对照",
        )
        has_obs_or_no_rand = any(m in obs_scrubbed for m in obs_markers) or bool(NO_RANDOMIZATION_RE.search(obs_scrubbed))
        if has_obs_or_no_rand and not any(m in scrubbed for m in int_markers):
            return "observational_source_declared_as_intervention"
    elif kind == "quasi_experiment":
        if any(m in text for m in ("cross-sectional observational comparison without pre-policy", "purely cross-sectional observational", "纯横断面观察")):
            return "cross_sectional_source_declared_as_quasi_experiment"
    elif kind in ("prediction_external", "prediction_prospective"):
        int_cv_markers = (
            "internal cross-validation", "internal 5-fold", "internal validation only",
            "no external validation", "no external cohort", "仅内部交叉验证", "无外部验证",
        )
        ext_markers = (
            "external cohort", "external validation", "external hospital", "external test",
            "external dataset", "external site", "independent hospital", "independent cohort",
            "independent validation", "independent dataset", "geographic validation",
            "prospective cohort", "外部验证", "外部队列", "外部测试", "独立验证", "独立队列", "前瞻性",
        )
        ext_scrubbed = FUTURE_OR_NO_PROSPECTIVE_RE.sub(" ", FUTURE_OR_NO_EXTERNAL_RE.sub(" ", text))
        has_int_only = any(m in text for m in int_cv_markers) or bool(FUTURE_OR_NO_EXTERNAL_RE.search(text))
        if has_int_only and not any(m in ext_scrubbed for m in ext_markers):
            return "internal_validation_declared_as_external"
    elif counterfactual_gates and kind == "mechanistic_assay":
        if any(m in text for m in (
            "co-expression correlation only", "observational correlation only",
            "no mechanistic assay", "no perturbation performed",
            "仅共表达相关", "无机制实验",
        )):
            return "observational_correlation_declared_as_mechanistic_assay"
    elif counterfactual_gates and kind in ("benchmark_replication", "benchmark_external"):
        if any(m in text for m in (
            "single unseeded run only", "no benchmark replication",
            "internal split only; no external benchmark", "no external benchmark dataset",
            "无外部基准", "仅内部划分无外部基准",
        )):
            return "unreplicated_or_internal_source_declared_as_benchmark"
    if kind == "prediction_prospective":
        prosp_scrubbed = FUTURE_OR_NO_PROSPECTIVE_RE.sub(" ", text)
        if (
            any(
                m in text
                for m in (
                    "retrospective cohort",
                    "retrospective validation",
                    "retrospective chart",
                    "retrospective review",
                    "retrospective study",
                    "retrospective analysis",
                    "回顾性",
                )
            )
            or bool(FUTURE_OR_NO_PROSPECTIVE_RE.search(text))
        ) and "prospective" not in prosp_scrubbed and "前瞻" not in prosp_scrubbed:
            return "retrospective_source_declared_as_prospective"
    return None


def _split_clauses(raw):
    if not isinstance(raw, str) or not raw:
        return []
    clauses = []
    buf = []
    depth = 0
    n = len(raw)
    for idx, ch in enumerate(raw):
        if ch in "([":
            depth += 1
        elif ch in ")]" and depth > 0:
            depth -= 1
        is_sep = ch in "\n;；。" or (depth == 0 and ch in ",，")
        if not is_sep and ch == ".":
            prev_is_d = idx > 0 and raw[idx - 1].isdigit()
            next_is_d = idx + 1 < n and raw[idx + 1].isdigit()
            if not (prev_is_d and next_is_d):
                is_sep = True
        if is_sep:
            part = "".join(buf).strip()
            if part:
                clauses.append(part)
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        clauses.append(tail)
    return clauses


_SAFETY_OR_HOSP_CLAUSE_RE = re.compile(
    r"(?:\b(?:serious\s+)?adverse\s+events?\b|\b(?:treatment[- ]emergent\s+)?aes?\b|"
    r"\btoxicit(?:y|ies)\b|\btolerability\b|\bsafety(?:\s+(?:outcome|endpoint|profile|event|analysis)s?)?\b|"
    r"\bhospitalizations?\b|\bhospitalisations?\b|\brehospitalizations?\b|\breadmissions?\b|\blength\s+of\s+stay\b|"
    r"不良事件|毒性反应|安全性|再住院|住院率|住院时间)",
    re.I,
)
_PRIMARY_EFFICACY_SIGNAL_RE = re.compile(
    r"(?:\b(?:primary|overall|progression[- ]free|disease[- ]free)\s+(?:endpoint|outcome|survival|mortality|efficacy)\b|"
    r"\b(?:mortality|survival|pfs|dfs|mace|remission|efficacy|auroc|auc)\b|"
    r"(?:\b(?:hr|or|rr|rd|beta|delta|auroc|auc)\s*(?:=|of|:)\s*[-+]?\d|\bp\s*[<≤]\s*0\.0\d)|"
    r"主要终点|总生存|无进展生存|死亡率|疗效)",
    re.I,
)
_REJECTED_NULL_RE = re.compile(
    r"(?:(?:the\s+)?null\s+(?:hypothesis|effect|model|assumption|value)?\s*(?:\([^)]*\))?\s*"
    r"(?:of\s+(?:no\s+effect|no\s+difference|(?:hr|or|rr)\s*=\s*1(?:\.0+)?)\s*)?"
    r"(?:\([^)]*\)\s*)?(?:was|is|were|are|can\s+be|could\s+be)?\s*"
    r"(?:cleanly\s+|decisively\s+|statistically\s+|strongly\s+)?"
    r"(?:rejected|falsified|refuted|ruled\s+out|disproved|overturned)|"
    r"(?:rejected|falsified|refuted|ruled\s+out|disproved|disproves|rejects|refutes)\s+"
    r"(?:the\s+)?null(?:\s+hypothesis)?(?:\s*\([^)]*\))?(?:\s+of\s+(?:no\s+effect|no\s+difference))?|"
    r"(?:hr|or|rr)\s*=\s*1(?:\.0+)?\s+(?:was|is|were)\s+(?:rejected|excluded|ruled\s+out)|"
    r"零假设被拒绝|拒绝零假设|拒绝无效应假设|排除无效假设)",
    re.I,
)
_PRIOR_LITERATURE_CONTRAST_RE = re.compile(
    r"(?:\b(?:inconsistent|contrary|discordant)\s+(?:with|to)\s+(?:an?\s+)?"
    r"(?:earlier|prior|previous|preceding|historical|initial|preliminary|small(?:er)?|"
    r"uncontrolled|observational|retrospective|case[- ]series|animal|preclinical|single[- ]center|pilot)\b|"
    r"与(?:此前|先前|早期|以往)(?:小样本|回顾性|观察性)?(?:研究|报告)不一致)",
    re.I,
)


def _strip_nonprimary_clauses(raw):
    clauses = _split_clauses(raw)
    if not clauses:
        return raw or ""
    kept = [
        cl for cl in clauses
        if not (NONPRIMARY_CLAUSE_RE.search(cl) and not PRIMARY_CLAUSE_OVERRIDE_RE.search(cl))
    ]
    if not kept:
        return raw or ""
    if len(kept) >= 2 and any(
        _PRIMARY_EFFICACY_SIGNAL_RE.search(cl) and not _SAFETY_OR_HOSP_CLAUSE_RE.search(cl)
        for cl in kept
    ):
        primary_filtered = [
            cl for cl in kept
            if not (_SAFETY_OR_HOSP_CLAUSE_RE.search(cl) and not PRIMARY_CLAUSE_OVERRIDE_RE.search(cl))
        ]
        if primary_filtered:
            kept = primary_filtered
    return "; ".join(kept)


def contradictory_positive_evidence_text(ev, include_outcome_stripped=True):
    parts = [
        _strip_nonprimary_clauses(str(ev.get("quote") or "")),
        _strip_nonprimary_clauses(_authenticated_source_text(ev)),
    ]
    raw = " ".join(p for p in parts if p).lower()
    norm = re.sub(r"[\s_\-]+", " ", raw).strip()
    if not norm:
        return None
    norm = _REJECTED_NULL_RE.sub(" ", norm)
    norm = _PRIOR_LITERATURE_CONTRAST_RE.sub(" ", norm)
    for safe in NON_CONTRADICTING_NEGATIONS:
        norm = norm.replace(safe, " ")
    norm = re.sub(r"\s+", " ", norm).strip()
    if any(phrase in norm for phrase in NULL_OR_REFUTING_EVIDENCE_PHRASES):
        return "null_or_contradicting_evidence"
    if include_outcome_stripped and any(phrase in norm for phrase in OUTCOME_STRIPPED_EVIDENCE_PHRASES):
        return "outcome_stripped_or_pending_evidence"
    return None


def _mask_metadata_noise(text):
    if not isinstance(text, str) or not text:
        return ""
    cleaned = METADATA_LABEL_RE.sub(" ", text)
    cleaned = ALPHA_LEVEL_RE.sub(" ", cleaned)
    return cleaned


def _clause_bounds(text, pos):
    left = 0
    for idx in range(pos - 1, -1, -1):
        ch = text[idx]
        if ch in "\n;；。" or (ch == "." and not (idx > 0 and idx + 1 < len(text) and text[idx - 1].isdigit() and text[idx + 1].isdigit())):
            left = idx + 1
            break
    right = len(text)
    for idx in range(pos, len(text)):
        ch = text[idx]
        if ch in "\n;；。" or (ch == "." and not (idx > 0 and idx + 1 < len(text) and text[idx - 1].isdigit() and text[idx + 1].isdigit())):
            right = idx
            break
    return text[left:right]


def _extract_signed_tokens(text, reduction_hint=False):
    if not isinstance(text, str) or not text:
        return []
    norm = text.replace("\u2212", "-")
    tokens = []
    for m in re.finditer(r"(?<![A-Za-z])(\d+(?:,\d{3})*(?:\.\d+)?)(?![A-Za-z])", norm):
        start = m.start()
        val = float(m.group(1).replace(",", ""))
        sign = None
        if start > 0 and norm[start - 1] in "+-":
            prev = norm[start - 2] if start >= 2 else " "
            if not prev.isdigit() and prev != "%":
                sign = norm[start - 1]
        prefix = norm[max(0, start - 20):start]
        is_pval = bool(re.search(r"(?:\bp\b(?:\s*-?\s*value)?|pval)\s*(?:=|<|>|<=|>=|:|\bof\b)\s*[+-]?$", prefix, re.I))
        clause = _clause_bounds(norm, start)
        has_inc = bool(INCREASE_POLARITY_RE.search(clause))
        has_red = bool(DECREASE_POLARITY_RE.search(clause)) or (reduction_hint and sign is None and not has_inc)
        has_inc = has_inc and not has_red
        tokens.append({
            "val": val,
            "sign": sign,
            "is_pval": is_pval,
            "reduction": has_red,
            "increase": has_inc,
            "start": start,
        })
    return tokens


def _extract_floats(text):
    return [tok["val"] for tok in _extract_signed_tokens(text)]


def _claimed_effect_tokens(claim, decision):
    tokens = []
    est_text = str(claim.get("effect", {}).get("estimate") or "")
    unc_text = str(claim.get("effect", {}).get("uncertainty") or "")
    rev_text = str(decision.get("revised_text") or claim.get("text") or "")
    rev_primary = _strip_nonprimary_clauses(rev_text)
    claim_has_red = bool(DECREASE_POLARITY_RE.search(est_text) or DECREASE_POLARITY_RE.search(rev_primary))
    for tok in _extract_signed_tokens(est_text, reduction_hint=claim_has_red):
        if tok["val"] != 0.0 or tok["sign"] is not None:
            tokens.append(tok)
    for m in re.finditer(r"(?:95%|90%|99%)\s*CI\s*(\[[^\]]+\]|[^\n;)]*)", unc_text, re.I):
        tokens.extend(_extract_signed_tokens(m.group(1), reduction_hint=claim_has_red))
    for m in re.finditer(r"(?:95%|90%|99%)\s*CI\s*(\[[^\]]+\]|[^\n;)]*)", rev_text, re.I):
        clause = _clause_bounds(rev_text, m.start())
        tokens.extend(_extract_signed_tokens(m.group(1), reduction_hint=bool(DECREASE_POLARITY_RE.search(clause))))
    rev_norm = rev_text.replace("\u2212", "-")
    metric_patterns = (
        r"\b(?:HR|OR|RR|RD|ATT|LATE|AUROC|AUC|F1|macro-F1|O/E|slope|Brier|delta|difference|effect|estimate|gain)\b"
        r"\s*(?:=|:|\bis\b|\bof\b|\bwas\b|达|为)?\s*([+-]?\d+(?:,\d{3})*(?:\.\d+)?)(?![A-Za-z])",
        r"\b(?:by|reduction|reduced|reduces|improves|improved|increased|increases|blocks|abolishes|lowers|lowered|decreased|decreases|gain)\s+"
        r"(?:[\w\-]+\s+){0,4}?(?:by\s+|of\s+)?([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:%|percentage points|points|mmHg|days|minutes)\b",
        r"([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*%\s*(?:reduction|increase|improvement|drop|gain|decrease)",
        r"(?:^|[\s(=,:\[;])([+-]\d+(?:,\d{3})*(?:\.\d+)?)(?![A-Za-z])",
    )
    for pat in metric_patterns:
        for m in re.finditer(pat, rev_norm, re.I):
            raw_num = m.group(1)
            sign = raw_num[0] if raw_num[0] in "+-" else None
            val = float((raw_num[1:] if sign else raw_num).replace(",", ""))
            clause = _clause_bounds(rev_norm, m.start(1))
            has_red = bool(DECREASE_POLARITY_RE.search(clause))
            has_inc = bool(INCREASE_POLARITY_RE.search(clause)) and not has_red
            tokens.append({
                "val": val,
                "sign": sign,
                "is_pval": False,
                "reduction": has_red,
                "increase": has_inc,
            })
    seen = set()
    unique = []
    for tok in tokens:
        key = (round(tok["val"], 6), tok["sign"], tok["is_pval"], tok["reduction"], tok["increase"])
        if key not in seen:
            seen.add(key)
            unique.append(tok)
    return unique


def _claimed_effect_numbers(claim, decision):
    return [tok["val"] for tok in _claimed_effect_tokens(claim, decision)]


def _val_close(target_val, src_val):
    tol = 0.5 if target_val >= 10.0 and float(target_val).is_integer() else 0.05
    return abs(target_val - src_val) <= tol


def _number_matches_source(target_val, source_floats):
    return any(_val_close(target_val, src_val) for src_val in source_floats)


def _token_matches_source(claimed, source_tokens):
    if claimed["is_pval"]:
        return any(_val_close(claimed["val"], s["val"]) for s in source_tokens)
    cands = [s for s in source_tokens if not s["is_pval"] and _val_close(claimed["val"], s["val"])]
    if not cands:
        return False
    if claimed["val"] == 0.0 and claimed["sign"] is None:
        return True
    if claimed["sign"] == "-":
        return any(s["sign"] == "-" or (s["sign"] is None and s["reduction"]) for s in cands)
    if claimed["sign"] == "+" or (claimed["sign"] is None and claimed["increase"]):
        return any(s["sign"] in ("+", None) and not s["reduction"] for s in cands)
    if claimed["reduction"]:
        return any(s["sign"] == "-" or (s["sign"] is None and not s["increase"]) for s in cands)
    return any(s["sign"] in ("+", None) and not s["reduction"] for s in cands)


def _priority_text_for_evidence(ev, linked_locators):
    chunks = []
    quote = str(ev.get("quote") or "")
    if quote:
        chunks.append(_mask_metadata_noise(_strip_nonprimary_clauses(quote)))
    parsed = _parse_authenticated_windows(ev)
    if parsed is not None:
        if quote:
            for _, body in parsed:
                pos = body.find(quote)
                if pos >= 0:
                    win_slice = body[max(0, pos - 120):min(len(body), pos + len(quote) + 300)]
                    chunks.append(_mask_metadata_noise(_strip_nonprimary_clauses(win_slice)))
                    break
        if linked_locators:
            line_map = {}
            for win, body in parsed:
                cur_line = win["start_line"]
                for ln in body.split("\n"):
                    if cur_line <= win["end_line"]:
                        line_map[cur_line] = ln.rstrip("\r")
                    cur_line += 1
            for loc in linked_locators:
                for m in re.finditer(r"(?:line|:L)\s*(\d+)", loc, re.I):
                    line_no = int(m.group(1))
                    if line_no in line_map:
                        chunks.append(_mask_metadata_noise(_strip_nonprimary_clauses(line_map[line_no])))
    else:
        src_raw = str(ev.get("source_text") or "")
        if quote and src_raw:
            pos = src_raw.find(quote)
            if pos >= 0:
                win = src_raw[max(0, pos - 120):min(len(src_raw), pos + len(quote) + 300)]
                chunks.append(_mask_metadata_noise(_strip_nonprimary_clauses(win)))
        if linked_locators and src_raw:
            lines = src_raw.split("\n")
            for loc in linked_locators:
                for m in re.finditer(r"(?:line|:L)\s*(\d+)", loc, re.I):
                    idx = int(m.group(1)) - 1
                    if 0 <= idx < len(lines):
                        chunks.append(_mask_metadata_noise(_strip_nonprimary_clauses(lines[idx].rstrip("\r"))))
    return "\n".join(c for c in chunks if c)


def effect_numbers_anchored(claim, decision, cited_evidence):
    claimed_tokens = _claimed_effect_tokens(claim, decision)
    if not claimed_tokens:
        return True
    decision_refs = set(decision.get("evidence_ids") or ())
    linked_num_cards = [
        c for c in claim.get("provenance_cards", {}).get("number", [])
        if isinstance(c, dict)
        and c.get("status") in ("reported", "checked")
        and (set(c.get("evidence_ids") or ()) & decision_refs)
    ]
    linked_locators = [
        str(c.get("details", {}).get("locator") or "")
        for c in linked_num_cards
        if isinstance(c.get("details"), dict)
    ]
    priority_tokens = []
    source_tokens = []
    for ev in cited_evidence:
        p_text = _priority_text_for_evidence(ev, linked_locators)
        if p_text:
            priority_tokens.extend(_extract_signed_tokens(p_text))
        s_clean = _mask_metadata_noise(_strip_nonprimary_clauses(_authenticated_source_text(ev)))
        q_clean = _mask_metadata_noise(_strip_nonprimary_clauses(str(ev.get("quote") or "")))
        if s_clean:
            source_tokens.extend(_extract_signed_tokens(s_clean))
        if q_clean:
            source_tokens.extend(_extract_signed_tokens(q_clean))
    if not source_tokens and not priority_tokens:
        return False
    all_source = priority_tokens + source_tokens
    for card in linked_num_cards:
        if card.get("status") != "checked" or not isinstance(card.get("details"), dict):
            continue
        card_text = " ".join(str(card["details"].get(k) or "") for k in ("value", "uncertainty"))
        for ctok in _extract_signed_tokens(_mask_metadata_noise(card_text)):
            if _token_matches_source(ctok, all_source):
                priority_tokens.append(ctok)
    for tok in claimed_tokens:
        has_priority_mag = any(
            (tok["is_pval"] or not s["is_pval"]) and _val_close(tok["val"], s["val"])
            for s in priority_tokens
        )
        if has_priority_mag:
            if not _token_matches_source(tok, priority_tokens):
                return False
        elif not _token_matches_source(tok, all_source):
            return False
    return True


def is_recorded_exec_evidence(ev):
    if not isinstance(ev, dict):
        return False
    text = "\n".join(str(ev.get(k) or "") for k in ("quote", "source_text"))
    has_cmd = bool(re.search(r"(?:^|\n)\s*command:\s*\S+", text))
    has_exit = bool(re.search(r"(?:^|\n)\s*exit_status:\s*[-+]?\d+", text))
    if has_cmd and has_exit:
        return True
    label = str(ev.get("label") or "").strip().lower()
    return label == "recorded command execution log" and (has_cmd or has_exit)


def _exec_text_tag(text, key):
    m = re.search(rf"(?:^|\n)\s*{key}:\s*(\S[^\r\n]*)", text)
    return m.group(1).strip() if m else None


def execution_fork_info(claim, evidence, exec_events=None):
    claim_id = claim.get("id")
    raw_cards = claim.get("provenance_cards", {}).get("execution", [])
    card_groups = {
        c.get("details", {}).get("run_group")
        for c in raw_cards
        if isinstance(c, dict) and isinstance(c.get("details"), dict) and c["details"].get("run_group")
    }
    exec_cards = [
        c for c in raw_cards
        if isinstance(c, dict) and c.get("status") not in ("not_run", "not_applicable")
    ]
    card_ev_ids = {
        ref
        for c in exec_cards
        for ref in (c.get("evidence_ids") or ())
    }
    has_not_run_card = any(
        isinstance(c, dict) and c.get("status") == "not_run"
        for c in raw_cards
    )

    def _matches_scope(ev_cid, ev_rg):
        if ev_cid is not None:
            return ev_cid == claim_id
        if ev_rg is not None:
            return ev_rg in card_groups
        return True

    relevant_events = []
    explicit_scoped_events = []
    ev_scope_from_events = {}
    for ev_rec in (exec_events or ()):
        if not isinstance(ev_rec, dict):
            continue
        ev_cid = ev_rec.get("claim_id")
        ev_rg = ev_rec.get("run_group")
        ev_ref = ev_rec.get("evidence_id")
        if ev_ref:
            ev_scope_from_events[ev_ref] = (ev_cid, ev_rg)
        if _matches_scope(ev_cid, ev_rg):
            relevant_events.append(ev_rec)
            if ev_cid is not None or ev_rg is not None:
                explicit_scoped_events.append(ev_rec)

    case_exec_ev_ids = set()
    for ev_id, ev in (evidence or {}).items():
        if not is_recorded_exec_evidence(ev):
            continue
        if ev_id in ev_scope_from_events:
            ev_cid, ev_rg = ev_scope_from_events[ev_id]
        else:
            ev_text = "\n".join(str(ev.get(k) or "") for k in ("quote", "source_text"))
            ev_cid = _exec_text_tag(ev_text, "claim_id")
            ev_rg = _exec_text_tag(ev_text, "run_group")
        if _matches_scope(ev_cid, ev_rg):
            case_exec_ev_ids.add(ev_id)

    for ev_rec in relevant_events:
        if ev_rec.get("evidence_id"):
            case_exec_ev_ids.add(ev_rec["evidence_id"])

    claim_ev_ids = set(claim.get("evidence_ids") or ())
    uses_exec = (
        bool(exec_cards)
        or bool(claim_ev_ids & case_exec_ev_ids)
        or bool(explicit_scoped_events)
        or (bool(relevant_events) and (has_not_run_card or claim.get("claim_type") in ("computational", "engineering")))
    )
    unaccounted_ev_ids = (
        sorted(case_exec_ev_ids - card_ev_ids)
        if (uses_exec and (len(case_exec_ev_ids) > 1 or bool(relevant_events)))
        else []
    )

    explicit_fork_counts = [
        len(exec_cards),
        len(case_exec_ev_ids) if uses_exec else 0,
        len(relevant_events) if uses_exec else 0,
    ]
    texts_to_scan = []
    for c in exec_cards:
        texts_to_scan.append(str(c.get("reason") or ""))
        details = c.get("details") or {}
        if isinstance(details, dict):
            texts_to_scan.extend(str(v or "") for v in details.values())
    for ev_id in (claim_ev_ids & set((evidence or {}).keys())):
        ev = evidence[ev_id]
        if is_recorded_exec_evidence(ev) or ev_id in card_ev_ids:
            texts_to_scan.append(str(ev.get("quote") or ""))
            texts_to_scan.append(str(ev.get("source_text") or ""))
    combined_exec_text = "\n".join(texts_to_scan)
    for pattern in MULTI_FORK_EXECUTION_PATTERNS:
        for m in re.finditer(pattern, combined_exec_text, re.I):
            try:
                explicit_fork_counts.append(int(m.group(1)))
            except (IndexError, ValueError):
                pass
    fork_count = max(explicit_fork_counts) if explicit_fork_counts else 0
    return {
        "exec_cards": exec_cards,
        "card_ev_ids": card_ev_ids,
        "case_exec_ev_ids": case_exec_ev_ids,
        "relevant_events": relevant_events,
        "uses_exec": uses_exec,
        "unaccounted_ev_ids": unaccounted_ev_ids,
        "fork_count": fork_count,
        "combined_exec_text": combined_exec_text,
    }


def validate_execution_forks(decision, claim, evidence, exec_events=None):
    info = execution_fork_info(claim, evidence, exec_events=exec_events)
    for card in info["exec_cards"]:
        exit_code = str(card.get("details", {}).get("exit_status", "0")).strip()
        if card.get("status") == "checked" and exit_code not in ("0", "UNKNOWN"):
            fail(
                "selective_execution_omission",
                f"checked execution card '{card['id']}' reports non-zero exit_status={exit_code}",
            )
    if info["unaccounted_ev_ids"]:
        fail(
            "selective_execution_omission",
            f"case has {len(info['case_exec_ev_ids'])} recorded execution logs but claim.provenance_cards.execution omits: {', '.join(info['unaccounted_ev_ids'])}",
        )
    unlinked_events = [e for e in info["relevant_events"] if not e.get("evidence_id")]
    if info["uses_exec"] and unlinked_events and len(info["relevant_events"]) > len(info["exec_cards"]):
        fail(
            "selective_execution_omission",
            f"case recorded {len(info['relevant_events'])} execution events for this claim scope but claim.provenance_cards.execution only accounts for {len(info['exec_cards'])}",
        )
    if info["fork_count"] > 1:
        mult_check = claim.get("checks", {}).get("multiplicity", {})
        if effective_status(mult_check, require_evidence=False) != "pass":
            fail(
                "unadjusted_execution_multiplicity",
                f"execution fork_count={info['fork_count']} requires checks.multiplicity to pass",
            )
        mult_stat = claim.get("statistical_report", {}).get("multiplicity_selection", {})
        if effective_status(mult_stat, require_evidence=True) != "pass":
            fail(
                "unadjusted_execution_multiplicity",
                f"execution fork_count={info['fork_count']} requires evidenced statistical_report.multiplicity_selection='pass'",
            )
        if not (set(mult_stat.get("evidence_ids") or ()) <= set(decision.get("evidence_ids", []))):
            fail(
                "unadjusted_execution_multiplicity",
                "positive decision must cite evidence backing statistical_report.multiplicity_selection",
            )


def collect_lexical_advisories(record, claim, evidence, exec_events=None):
    """Collect non-blocking lexical-cue advisories for positive claims without failing mechanical gates."""
    record = record if isinstance(record, dict) else {}
    claim = claim if isinstance(claim, dict) else {}
    verdict = record.get("verdict") if "verdict" in record else record.get("stance")
    if verdict is not None and verdict not in POSITIVE:
        return []
    if isinstance(evidence, dict):
        by_evidence = {eid: e for eid, e in evidence.items() if isinstance(e, dict)}
    else:
        by_evidence = {
            e["evidence_id"]: e
            for e in (evidence or ())
            if isinstance(e, dict) and e.get("evidence_id")
        }
    cid = record.get("claim_id") or claim.get("id") or claim.get("claim_id") or ""
    refs = list(dict.fromkeys(record.get("evidence_ids") or claim.get("evidence_ids") or ()))
    advisories = []
    seen = set()

    def _add(hook_code, detail_code, message, ev_ids):
        clean_ids = [r for r in ev_ids if r]
        key = (cid, hook_code, detail_code, tuple(clean_ids))
        if key in seen:
            return
        seen.add(key)
        advisories.append({
            "claim_id": cid,
            "hook_code": hook_code,
            "detail_code": detail_code,
            "severity": "advisory",
            "non_blocking": True,
            "message": message,
            "evidence_ids": clean_ids,
        })

    for ref in refs:
        ev = by_evidence.get(ref)
        if not ev:
            continue
        kind_contra = contradictory_evidence_kind(ev)
        if kind_contra:
            _add(
                "possible_evidence_kind_mismatch",
                kind_contra,
                f"Evidence '{ref}' contains lexical cues potentially conflicting with declared kind '{ev.get('kind')}' ({kind_contra}).",
                [ref],
            )
        text_contra = contradictory_positive_evidence_text(ev, include_outcome_stripped=True)
        if text_contra == "outcome_stripped_or_pending_evidence":
            _add(
                "possible_outcome_pending_text",
                text_contra,
                f"Evidence '{ref}' contains lexical cues suggesting uncollected, omitted, or pending outcome data ({text_contra}).",
                [ref],
            )
        elif text_contra:
            _add(
                "possible_contradictory_evidence_text",
                text_contra,
                f"Evidence '{ref}' contains lexical cues suggesting null, non-significant, or refuting results ({text_contra}).",
                [ref],
            )

    info = execution_fork_info(claim, by_evidence, exec_events=exec_events)
    cited_text = "\n".join(
        str(by_evidence[ref].get("source_text") or "")
        for ref in refs
        if ref in by_evidence
    )
    scan_text = f"{info['combined_exec_text']}\n{cited_text}".lower()
    if any(phrase in scan_text for phrase in SELECTIVE_EXECUTION_OMISSION_PHRASES):
        _add(
            "possible_execution_omission_text",
            "selective_execution_omission_phrase",
            "Execution log or provenance card text mentions potential selective fork/seed omission.",
            list(dict.fromkeys([*info["card_ev_ids"], *refs])),
        )
    if info["fork_count"] > 1:
        mult_check = claim.get("checks", {}).get("multiplicity", {})
        mult_stat = claim.get("statistical_report", {}).get("multiplicity_selection", {})
        reasons_lower = f"{mult_check.get('reason', '')} {mult_stat.get('reason', '')}".lower()
        accounting_text = f"{reasons_lower} {record.get('revised_text', '')} {record.get('condition', '')}".lower()
        fork_ev_ids = list(dict.fromkeys([*(mult_stat.get("evidence_ids") or ()), *info["card_ev_ids"], *refs]))
        if any(phrase in reasons_lower for phrase in FALSE_SINGLE_RUN_MULTIPLICITY_PHRASES):
            _add(
                "possible_unadjusted_multiplicity_text",
                "false_single_run_multiplicity_phrase",
                f"Multiplicity text claims single run or no multiplicity despite fork_count={info['fork_count']}.",
                fork_ev_ids,
            )
        elif not any(marker in accounting_text for marker in MULTIPLICITY_ADJUSTMENT_MARKERS):
            _add(
                "possible_unadjusted_multiplicity_text",
                "missing_multiplicity_marker_text",
                f"Multiplicity accounting for fork_count={info['fork_count']} lacks common explicit adjustment keywords.",
                fork_ev_ids,
            )
    return advisories


def quote_links_to_claim(ev, claim, decision):
    quote = ev.get("quote") or ""
    ev_id = ev.get("evidence_id")
    parts = [
        claim.get("text", ""),
        decision.get("revised_text", ""),
        claim.get("scope", ""),
        decision.get("scope", ""),
        claim.get("contribution", ""),
        claim.get("effect", {}).get("estimate", ""),
        claim.get("effect", {}).get("uncertainty", ""),
    ]
    for cards in claim.get("provenance_cards", {}).values():
        for card in cards:
            if card.get("status") == "checked" and (not ev_id or ev_id in card.get("evidence_ids", [])):
                parts.extend(str(v) for v in card.get("details", {}).values())
    target = " ".join(str(p) for p in parts if p)
    q_nums = set(re.findall(r"\d+(?:\.\d+)?", quote))
    t_nums = set(re.findall(r"\d+(?:\.\d+)?", target))
    if q_nums & t_nums:
        return True
    q_words = {w for w in re.findall(r"[a-zA-Z]{4,}", quote.lower()) if w not in QUOTE_STOPWORDS}
    t_words = {w for w in re.findall(r"[a-zA-Z]{4,}", target.lower()) if w not in QUOTE_STOPWORDS}
    if q_words & t_words or ({w[:5] for w in q_words if len(w) >= 5} & {w[:5] for w in t_words if len(w) >= 5}):
        return True
    q_cjk = "".join(c for c in quote if "\u4e00" <= c <= "\u9fff")
    t_cjk = "".join(c for c in target if "\u4e00" <= c <= "\u9fff")
    q_bigrams = {q_cjk[i:i + 2] for i in range(len(q_cjk) - 1)} - CJK_STOPWORDS
    t_bigrams = {t_cjk[i:i + 2] for i in range(len(t_cjk) - 1)} - CJK_STOPWORDS
    return bool(q_bigrams & t_bigrams)


def validate_basis(value):
    basis = enum(value["claim_basis"], BASES, "claim_basis")
    kind = value["claim_type"]
    if basis == "formal" and kind != "theory":
        fail("basis_mismatch", "formal basis is reserved for theory claims")
    if kind == "theory" and basis != "formal":
        fail("basis_mismatch", "theory claims require formal basis")
    if basis == "synthetic" and kind not in ("description", "computational"):
        fail("basis_mismatch", "synthetic positive scope is limited to description/computational demonstrations")


def critical_paths(kind, level):
    """Minimum fixed checks; callers cannot relabel essential checks as optional."""
    if level in ("unassessed", "unidentified", "conjectured"):
        return ()
    if kind == "description" and level == "recorded":
        return ()  # Literal anchored record only; not verified measurement or inference.
    common = ("checks.quality", "checks.unit", "checks.assumptions")
    if kind == "theory":
        if level == "proved_under_assumptions":
            return ("checks.assumptions", "checks.unit")
        return ("checks.assumptions", "checks.unit", "checks.quality", "checks.baseline")
    if kind == "qualitative":
        if level == "situated_description":
            return ("checks.quality", "checks.unit")
        if level == "interpretation_audited":
            return ("checks.quality", "checks.unit", "checks.assumptions", "checks.batch")
        return ("checks.quality", "checks.unit", "checks.assumptions", "checks.batch", "checks.multiplicity", "checks.baseline")
    if kind == "synthesis":
        if level == "mapped":
            return common
        return common + ("checks.batch", "checks.multiplicity", "checks.baseline")
    if kind == "engineering":
        if level == "test_passed":
            return ("checks.quality", "checks.baseline")
        if level == "host_accepted":
            return ("checks.quality", "checks.baseline", "checks.unit")
        return ("checks.quality", "checks.baseline", "checks.unit", "checks.assumptions")
    if kind == "description":
        return ("checks.quality", "checks.unit") + (("checks.batch",) if level == "replicated" else ())
    if kind == "association":
        if level == "unadjusted":
            return common
        return common + ("checks.batch", "checks.multiplicity", "checks.baseline")
    if kind == "mechanism":
        if level == "compatible":
            return common
        return common + ("checks.batch", "checks.multiplicity", "checks.baseline")
    if kind in ("prediction", "computational"):
        return common + ("checks.leakage", "checks.baseline", "checks.multiplicity")
    return common + ("checks.batch", "checks.multiplicity", "checks.baseline")


def level_essential_design_checks(kind, level, fam):
    tier = LEVEL_TIERS.get(kind, {}).get(level, 0)
    if tier <= 0:
        return ()
    fam_tiers = FAMILY_TIER_CHECKS.get(fam, {})
    if not fam_tiers:
        return ESSENTIAL_DESIGN_CHECKS.get(fam, ())
    max_tier = max(fam_tiers)
    return fam_tiers.get(min(tier, max_tier), ESSENTIAL_DESIGN_CHECKS.get(fam, ()))


def level_essential_stat_checks(kind, level):
    tier = LEVEL_TIERS.get(kind, {}).get(level, 0)
    if tier <= 0 or kind == "theory":
        return ()
    if kind == "description":
        return ESSENTIAL_STAT_CHECKS if level == "replicated" else ()
    if kind == "qualitative":
        return ("units_sample_size", "robustness_limits") if level == "triangulated" else ("units_sample_size",)
    if kind == "engineering":
        return ESSENTIAL_STAT_CHECKS if level == "user_impact" else ()
    if kind == "synthesis":
        if level == "mapped":
            return ("units_sample_size",)
        if level == "critically_appraised":
            return ("units_sample_size", "estimate_uncertainty", "model_assumptions")
        return ("units_sample_size", "estimate_uncertainty", "model_assumptions", "comparisons_baselines", "robustness_limits")
    if tier == 1:
        return ESSENTIAL_STAT_CHECKS
    if tier == 2:
        return ("units_sample_size", "estimate_uncertainty", "model_assumptions", "comparisons_baselines")
    return ("units_sample_size", "estimate_uncertainty", "model_assumptions", "comparisons_baselines", "robustness_limits")


def _is_disclosed_failed_fork(card, all_exec_cards):
    if not isinstance(card, dict) or card.get("status") != "failed":
        return False
    details = card.get("details") or {}
    if not isinstance(details, dict) or details.get("fork_role") not in NON_PRIMARY_FAILED_FORK_ROLES:
        return False
    if not substantive_reason(card.get("reason")):
        return False
    return any(
        isinstance(other, dict)
        and other is not card
        and other.get("status") in ("checked", "reported")
        and str((other.get("details") or {}).get("exit_status", "")).strip() == "0"
        and not (isinstance(other.get("details"), dict) and other["details"].get("fork_role") in NON_PRIMARY_FAILED_FORK_ROLES)
        for other in all_exec_cards
    )


def required_records(claim, kind, level):
    paths = critical_paths(kind, level)
    records = [(path, {"status": effective_status(claim["checks"][path.split(".")[1]], require_evidence=False)}) for path in paths]
    if level in ("unassessed", "unidentified", "conjectured"):
        return records
    causal_needed = needs_causal_basis({"claim_type": kind, "evidence_level": level})
    # All selected design packages enforce level-progressive essential checks; core checks cannot be bypassed via N/A.
    for package in claim["design_packages"]:
        fam = package["family"]
        checks = package["checks"]
        if paths:
            if checks and all(v["status"] == "not_applicable" for v in checks.values()):
                records.append((f"design.{fam}._all_not_applicable", {"status": "fail"}))
            essential_design = set(level_essential_design_checks(kind, level, fam))
            for name, value in checks.items():
                eff = effective_status(value, require_evidence=True)
                if name in essential_design and eff != "pass":
                    records.append((f"design.{fam}.{name}", {"status": "fail" if eff == "fail" else "unknown"}))
                else:
                    records.append((f"design.{fam}.{name}", {"status": eff, "evidence_ids": value.get("evidence_ids", [])}))
        else:
            for name, value in checks.items():
                if effective_status(value, require_evidence=True) == "fail":
                    records.append((f"design.{fam}.{name}", {"status": "fail"}))
    essential_stats = set(level_essential_stat_checks(kind, level))
    if essential_stats or kind not in ("description", "theory", "qualitative", "engineering"):
        for key, value in claim["statistical_report"].items():
            eff = effective_status(value, require_evidence=True)
            if key in essential_stats and eff != "pass":
                records.append(("statistics." + key, {"status": "fail" if eff == "fail" else "unknown"}))
            else:
                records.append(("statistics." + key, {"status": eff, "evidence_ids": value.get("evidence_ids", [])}))
    else:
        for key, value in claim["statistical_report"].items():
            if effective_status(value, require_evidence=True) == "fail":
                records.append(("statistics." + key, {"status": "fail"}))
    all_exec_cards = claim.get("provenance_cards", {}).get("execution", [])
    for card_kind, cards in claim.get("provenance_cards", {}).items():
        for idx, card in enumerate(cards):
            if card_kind == "execution" and _is_disclosed_failed_fork(card, all_exec_cards):
                continue
            if card["status"] in ("failed", "missing"):
                records.append((f"provenance_cards.{card_kind}[{idx}]", {"status": "fail"}))
            elif card_kind == "citation" and card["status"] in ("reported", "checked"):
                rel = card.get("details", {}).get("support_relation", "")
                if is_contradicting_relation(rel):
                    records.append((f"provenance_cards.citation[{idx}].support_relation", {"status": "fail"}))
    if causal_needed:
        basis = claim.get("causal_basis")
        if not basis:
            records.append(("causal_basis", {"status": "unknown"}))
        else:
            if basis["design_family"] not in ("observational", "quasi_experimental", "randomized", "mechanism", "evidence_synthesis"):
                records.append(("causal_basis.design_family", {"status": "unknown"}))
            require_sensitivity = level in ("sensitivity_supported", "counterfactual_supported", "causal_chain_tested")
            causal_records = [("assessment", basis["assessment"], True)]
            causal_records += [(f"assumptions[{i}]", value, True) for i, value in enumerate(basis["assumptions"])]
            causal_records += [(f"falsification_sensitivity[{i}]", value, require_sensitivity) for i, value in enumerate(basis["falsification_sensitivity"])]
            if kind in ("necessity", "sufficiency"):
                causal_records.append((kind + "_test", basis[kind + "_test"], True))
            for key, value, must_pass in causal_records:
                eff = effective_status(value, require_evidence=True)
                if must_pass:
                    records.append(("causal_basis." + key, {"status": "pass", "evidence_ids": value.get("evidence_ids", [])} if eff == "pass" else {"status": "fail" if eff == "fail" else "unknown"}))
                elif eff == "fail":
                    records.append(("causal_basis." + key, {"status": "fail"}))
            for key, value in basis["estimand"].items():
                if key != "intercurrent_events" and (not meaningful(value) or value.strip().upper() == "NOT_IDENTIFIABLE"):
                    records.append(("causal_basis.estimand." + key, {"status": "unknown"}))
    return records


def observational_causal_eligible(decision, claim):
    if decision.get("verdict") != "partially_supported" or not meaningful(decision.get("condition")):
        return False
    if decision["claim_type"] != "causal_effect" or decision["evidence_level"] not in ("identified_under_assumptions", "sensitivity_supported"):
        return False
    basis = claim.get("causal_basis")
    if not basis or basis.get("design_family") != "observational":
        return False
    obs_pkg = next((p for p in claim.get("design_packages", []) if p["family"] == "observational"), None)
    if not obs_pkg:
        return False
    for key in ("sampling_temporality", "confounding_selection", "robustness"):
        chk = obs_pkg["checks"].get(key, {})
        if effective_status(chk, require_evidence=True) != "pass":
            return False
    return True


def ceiling(claim, kind=None):
    kind = kind or claim["claim_type"]
    allowed, blocked = [], {}
    for level in TYPE_LEVELS[kind]:
        blockers = []
        fixed = set(critical_paths(kind, level))
        for path, record in required_records(claim, kind, level):
            # Essential global checks cannot be opted out; design/stat N/A retains a reason.
            if record["status"] in ("unknown", "fail") or (path in fixed and record["status"] != "pass"):
                blockers.append({"path": path, "status": record["status"]})
        if blockers:
            blocked[level] = blockers
        else:
            allowed.append(level)
    return {"claim_type": kind, "allowed_levels": allowed, "blocked_levels": blocked,
            "verdict_ceiling": "nonpositive_only" if not any(x in COMPATIBILITY[kind] for x in allowed) else "positive_possible_subject_to_evidence_gates"}


def evidence_lineage(evidence_id, by_evidence):
    ancestors = []
    seen = set()
    visiting = set()
    cycle_detected = False
    unknown_parents = []

    def dfs(cur_id):
        nonlocal cycle_detected
        cur = by_evidence.get(cur_id)
        if cur is None:
            return
        for pid in cur.get("derived_from_evidence_ids") or ():
            if pid not in by_evidence:
                if pid not in unknown_parents:
                    unknown_parents.append(pid)
                continue
            if pid in visiting or pid == evidence_id:
                cycle_detected = True
                continue
            if pid not in seen:
                seen.add(pid)
                ancestors.append(pid)
                visiting.add(pid)
                dfs(pid)
                visiting.remove(pid)

    if evidence_id in by_evidence:
        visiting.add(evidence_id)
        dfs(evidence_id)
        visiting.remove(evidence_id)
    else:
        unknown_parents.append(evidence_id)
    return {"ancestors": ancestors, "cycle_detected": cycle_detected, "unknown_parents": unknown_parents}


def validate_mechanical(decision, claim, evidence, counterfactual_gates=True, fork_gates=True, exec_events=None):
    validate_basis(decision)
    kind, level = decision["claim_type"], decision["evidence_level"]
    limits = ceiling(claim, kind)
    if level not in limits["allowed_levels"]:
        fail("critical_check_ceiling", f"{kind} × {level} exceeds frozen critical-check ceiling; blocked: {limits['blocked_levels'][level]}")
    if decision["verdict"] not in POSITIVE:
        return
    if decision["claim_basis"] == "synthetic" and (kind, level) not in (("description", "recorded"), ("computational", "benchmark_measured")):
        fail("synthetic_ceiling", "synthetic scope permits only recorded descriptions or measured synthetic benchmarks")
    obs_causal_ok = observational_causal_eligible(decision, claim)
    compatible = COMPATIBILITY[kind].get(level, ())
    if obs_causal_ok:
        compatible = (*compatible, "observation")
    for ref in decision["evidence_ids"]:
        ev = evidence[ref]
        lineage = evidence_lineage(ref, evidence)
        if lineage["cycle_detected"]:
            fail("invalid_lineage", f"evidence '{ref}' derived lineage contains a cycle")
        if lineage["unknown_parents"]:
            fail("unknown_reference", f"evidence '{ref}' derived lineage references unknown ancestor(s): {lineage['unknown_parents']}")
        chain_evs = [ev, *(evidence[aid] for aid in lineage["ancestors"])]
        synthetic = any(e.get("provenance") == "synthetic" or e.get("kind") == "synthetic" for e in chain_evs)
        if synthetic and decision["claim_basis"] != "synthetic":
            fail("synthetic_empirical_support", "synthetic evidence cannot support empirical or formal positive judgments")
        if ev["kind"] not in compatible:
            fail("incompatible_evidence_kind", f"{ev['kind']} cannot support {kind} × {level}")
        status = ev.get("source_text_status")
        windowed_ok = status == "truncated" and bool(ev.get("excerpt_window", {}).get("quote_anchored"))
        if status != "complete" and not windowed_ok:
            fail("unread_positive_evidence", "positive references require readable source text (or a quote-anchored window in a >128 KiB text source); binary or unanchored truncated sources cannot support positives")
        if _authenticated_quote_status(ev.get("quote"), ev) != "matched" or not meaningful(ev.get("location")):
            fail("unanchored_positive_evidence", "each positive reference needs a unique quote of at least 12 non-whitespace units (6 CJK or 12 ASCII characters) and a concrete location")
        if not quote_links_to_claim(ev, claim, decision):
            fail("unlinked_evidence_quote", f"positive reference '{ref}' quote does not share quantitative values, domain terms, or checked-card anchors with the claim")
    if counterfactual_gates and not effect_numbers_anchored(claim, decision, [evidence[ref] for ref in decision["evidence_ids"]]):
        fail("unanchored_effect_estimate", "positive decision quantitative effect/uncertainty estimates are not anchored in the cited evidence text")
    if claim.get("effect_records"):
        from .effects import verify_effect_computations
        verify_effect_computations(claim, decision, evidence)
    if fork_gates:
        validate_execution_forks(decision, claim, evidence, exec_events=exec_events)
    allowed_causal_kinds = (*CAUSAL_KINDS, "observation") if obs_causal_ok else CAUSAL_KINDS
    if needs_causal_basis(decision) and not all(evidence[ref]["kind"] in allowed_causal_kinds for ref in decision["evidence_ids"]):
        fail("incompatible_evidence_kind", "causal positives require intervention/quasi-experiment evidence (or observational evidence with partially_supported verdict, condition, and evidenced confounding/robustness checks)")
    # Positive decisions must cite the evidence backing their required passing design and statistical checks.
    decision_refs = set(decision["evidence_ids"])
    for path, record in required_records(claim, kind, level):
        if (path.startswith("design.") or path.startswith("statistics.")) and record.get("status") == "pass":
            check_refs = set(record.get("evidence_ids") or ())
            if check_refs and not (check_refs <= decision_refs):
                fail("uncited_check_evidence", f"positive decision must cite evidence backing passing check '{path}'")
    for card_kind in ("number", "execution", "citation"):
        for card in claim.get("provenance_cards", {}).get(card_kind, []):
            if card["status"] == "checked" and not (set(card["evidence_ids"]) & set(decision["evidence_ids"])):
                fail("uncited_checked_card", f"positive decision must cite evidence backing checked {card_kind} card '{card['id']}'")


def validate_unread_ack(value, evidence):
    ack = ids(value, "unread_evidence_ids")
    unread = {e["evidence_id"] for e in evidence if e["source_text_status"] != "complete"}
    if set(ack) != unread:
        fail("unread_ack_required", "explicitly acknowledge every binary, truncated or missing source in unread_evidence_ids")


def validate_stances(value, claims, evidence, exec_events=None):
    seen = []
    by_evidence = {e["evidence_id"]: e for e in evidence}
    for stance in array(value, "claim_stances", minimum=1, maximum=100):
        obj(stance, "stance")
        keys = {"claim_id", "stance", "rationale", "evidence_ids"}
        fields(stance, keys | {"condition"}, keys, "stance")
        cid = string(stance["claim_id"], "stance.claim_id")
        if cid not in claims:
            fail("unknown_claim", "stance refers to a non-frozen claim")
        seen.append(cid)
        enum(stance["stance"], ("supported", "partially_supported", "unsupported", "insufficient_evidence"), "stance")
        if stance["stance"] == "partially_supported" and not meaningful(stance.get("condition")):
            fail("missing_stance_condition", "a conditionally supportive stance must specify its actual condition")
        if "condition" in stance and not meaningful(stance["condition"]):
            fail("missing_stance_condition", "condition cannot be empty, invisible or an unknown placeholder")
        string(stance["rationale"], "stance.rationale")
        refs = ids(stance["evidence_ids"], "stance.evidence_ids", minimum=1 if stance["stance"] in POSITIVE else 0)
        if not set(refs) <= set(claims[cid]["evidence_ids"]):
            fail("unknown_reference", "stance references evidence outside its claim")
        # A stance evaluates the original claim, never silently a proposed revision.
        if stance["stance"] in POSITIVE:
            from .claims import validate_support
            decision = {**claims[cid], "verdict": stance["stance"], "evidence_ids": refs}
            if "condition" in stance:
                decision["condition"] = stance["condition"]
            validate_support(decision, claims[cid])
            validate_mechanical(decision, claims[cid], by_evidence, exec_events=exec_events)
    ids(seen, "stance claim IDs")
    if set(seen) != set(claims):
        fail("incomplete_stances", "every frozen claim needs exactly one stance")


def _substantive_tokens(text):
    if not isinstance(text, str) or not text:
        return set()
    tokens = set(re.findall(r"\d+(?:\.\d+)?", text))
    words = {
        w for w in re.findall(r"[a-zA-Z]{4,}", text.lower())
        if w not in QUOTE_STOPWORDS and w not in DISPOSITION_BOILERPLATE
    }
    tokens |= words
    tokens |= {w[:5] for w in words if len(w) >= 5}
    tokens |= {w[:4] for w in words if len(w) >= 4}
    cjk = "".join(c for c in text if "\u4e00" <= c <= "\u9fff")
    tokens |= {cjk[i:i + 2] for i in range(len(cjk) - 1)} - CJK_STOPWORDS
    return tokens


def validate_disposition(disposition, finding, decision, original):
    if disposition["claim_id"] != finding["claim_id"] or disposition["claim_id"] != decision["claim_id"]:
        fail("finding_decision_mismatch", "disposition must bind finding and decision for the same claim")
    resolution = enum(disposition["resolution"], ("incorporated", "disagreement"), "disposition.resolution")
    if resolution == "disagreement":
        if not meaningful(disposition.get("disagreement")):
            fail("missing_disagreement", "an explicit, substantive disagreement is required")
        if "revised_text_quote" in disposition:
            fail("contradictory_resolution", "disagreement cannot claim an incorporated text anchor")
        return
    if disposition["disposition"] == "rejected":
        fail("contradictory_resolution", "rejected findings must record disagreement")
    if "disagreement" in disposition:
        fail("contradictory_resolution", "incorporation cannot also claim disagreement")
    anchor = string(disposition.get("revised_text_quote"), "disposition.revised_text_quote")
    if quote_status(anchor, decision["revised_text"]) != "matched" or quote_status(anchor, finding["proposed_text"]) != "matched" or anchor.lower() in original["text"].lower():
        fail("finding_not_incorporated", "anchor must uniquely identify new proposed wording in revised_text, not a preexisting original fragment (at least 12 visible non-whitespace units)")
    orig_text = original["text"].strip()
    prop_text = finding["proposed_text"].strip()
    rev_text = decision["revised_text"].strip()
    if rev_text == orig_text:
        fail("finding_not_incorporated", "unchanged wording cannot be marked incorporated; record disagreement explicitly")
    if orig_text and orig_text.lower() not in prop_text.lower() and orig_text.lower() in rev_text.lower():
        fail("finding_not_incorporated", "revised_text retains the unrevised original claim verbatim while only appending text; rewrite the claim or record disagreement")
    orig_tokens = _substantive_tokens(orig_text)
    prop_tokens = _substantive_tokens(prop_text)
    rev_tokens = _substantive_tokens(rev_text)
    anchor_tokens = _substantive_tokens(anchor)
    issue_tokens = _substantive_tokens(finding.get("issue", ""))
    issue_impact_tokens = _substantive_tokens(
        f"{finding.get('issue', '')} {finding.get('decision_impact', '')}"
    )
    removed_tokens = orig_tokens - prop_tokens
    if removed_tokens and removed_tokens <= rev_tokens:
        fail("finding_not_incorporated", "revised_text retains all substantive original terms that proposed_text replaced")
    removed_criticized = removed_tokens & issue_tokens
    if removed_criticized and (removed_criticized & rev_tokens):
        fail("finding_not_incorporated", "revised_text retains criticized terms from the original claim that the finding's proposed_text removed")
    added_tokens = prop_tokens - orig_tokens
    if not anchor_tokens or (added_tokens and not (anchor_tokens & added_tokens)):
        fail("finding_not_incorporated", "revised_text_quote must anchor substantive new terms introduced by proposed_text, not boilerplate filler")
    salient_new = added_tokens & issue_impact_tokens
    if salient_new:
        if not (rev_tokens & salient_new):
            fail("finding_not_incorporated", "revised_text must incorporate the finding's issue-linked replacement terms")
        if disposition["disposition"] == "partial" and not (anchor_tokens & salient_new):
            fail("finding_not_incorporated", "partial incorporation revised_text_quote must anchor the finding's issue-linked replacement terms, not an unrelated clause")
    if disposition["disposition"] == "accepted":
        if finding["proposed_text"] not in decision["revised_text"]:
            fail("finding_not_incorporated", "accepted incorporation requires the proposed text; deviations need explicit disagreement or partial adoption")
        for key in ("claim_type", "evidence_level", "scope", "claim_basis"):
            if finding["proposed_" + key] != decision[key]:
                fail("finding_not_incorporated", "accepted classification/scope must match the decision, or record disagreement")


def _iter_claim_check_records(claim):
    checks = claim.get("checks") or {}
    if not isinstance(checks, dict):
        return
    for key, val in checks.items():
        if key in ("design", "statistics") and isinstance(val, dict):
            for rec in val.values():
                if isinstance(rec, dict):
                    yield rec, True
        elif isinstance(val, dict):
            yield val, False


def _has_contradicting_card(claim):
    cards_by_kind = claim.get("provenance_cards") or {}
    if not isinstance(cards_by_kind, dict):
        return False
    for cards in cards_by_kind.values():
        if not isinstance(cards, list):
            continue
        for card in cards:
            if not isinstance(card, dict):
                continue
            status = str(card.get("status") or "").strip().lower()
            if status in ("fail", "failed", "contradicted", "refuted"):
                return True
            details = card.get("details") or {}
            if not isinstance(details, dict):
                continue
            if is_contradicting_relation(details.get("support_relation")) or is_contradicting_relation(details.get("relation")):
                return True
            detail_text = " ".join(str(v) for v in details.values() if v is not None)
            cleaned_detail = _strip_nonprimary_clauses(detail_text)
            cleaned_detail = _REJECTED_NULL_RE.sub(" ", cleaned_detail)
            cleaned_detail = _PRIOR_LITERATURE_CONTRAST_RE.sub(" ", cleaned_detail).lower()
            norm = re.sub(r"[\s_\-]+", " ", cleaned_detail).strip()
            norm = _REJECTED_NULL_RE.sub(" ", norm)
            norm = _PRIOR_LITERATURE_CONTRAST_RE.sub(" ", norm)
            for safe in NON_CONTRADICTING_NEGATIONS:
                norm = norm.replace(safe, " ")
            norm = re.sub(r"\s+", " ", norm).strip()
            if any(phrase in norm for phrase in NULL_OR_REFUTING_EVIDENCE_PHRASES):
                return True
    return False


def _has_failed_check(claim):
    for rec, require_ev in _iter_claim_check_records(claim):
        if rec.get("status") == "fail" or effective_status(rec, require_evidence=require_ev) == "fail":
            return True
    return False


def _has_failed_check_or_contradiction(claim, candidate_evs, *, check_numeric_mismatch=False):
    if _has_failed_check(claim) or _has_contradicting_card(claim):
        return True
    if check_numeric_mismatch and candidate_evs and _claimed_effect_tokens(claim, claim):
        ev_ids = [e.get("evidence_id") for e in candidate_evs if e.get("evidence_id")]
        if ev_ids and not effect_numbers_anchored(claim, {**claim, "evidence_ids": ev_ids}, candidate_evs):
            return True
    for ev in candidate_evs:
        if contradictory_positive_evidence_text(ev, include_outcome_stripped=False):
            return True
    return False


def _passes_positive_candidate(claim, record, candidate_refs, by_evidence, exec_events=None, *, verdict="supported", claim_type=None, evidence_level=None, claim_basis=None, scope=None, revised_text=None):
    from .claims import validate_support
    c_type = claim_type or record.get("claim_type") or claim.get("claim_type")
    c_level = evidence_level or record.get("evidence_level") or claim.get("evidence_level")
    c_basis = claim_basis or record.get("claim_basis") or claim.get("claim_basis")
    c_scope = scope or record.get("scope") or claim.get("scope")
    if c_type not in TYPE_LEVELS or c_level not in TYPE_LEVELS[c_type] or c_basis not in BASES:
        return False
    if not candidate_refs or not all(ref in by_evidence for ref in candidate_refs):
        return False
    candidate = {
        **claim,
        "claim_id": claim.get("id") or claim.get("claim_id") or record.get("claim_id"),
        "claim_type": c_type,
        "evidence_level": c_level,
        "claim_basis": c_basis,
        "scope": c_scope or claim.get("scope") or "",
        "verdict": verdict,
        "evidence_ids": list(candidate_refs),
        "revised_text": revised_text or record.get("revised_text") or claim.get("text") or "",
    }
    if verdict == "partially_supported":
        cond = record.get("condition") or c_scope or claim.get("scope") or "Bounded to evidenced scope"
        candidate["condition"] = cond
    try:
        validate_basis(candidate)
        validate_support(candidate, claim)
        validate_mechanical(candidate, claim, by_evidence, exec_events=exec_events)
    except (ContractError, KeyError, TypeError, ValueError):
        return False
    return True


def _normalize_audit_inputs(records, claims, evidence, findings, dispositions):
    if isinstance(claims, dict):
        by_claim = {cid: c for cid, c in claims.items() if isinstance(c, dict)}
    else:
        by_claim = {}
        for c in claims or ():
            if isinstance(c, dict):
                cid = c.get("id") or c.get("claim_id")
                if cid:
                    by_claim[cid] = c
    if isinstance(evidence, dict):
        by_evidence = {eid: e for eid, e in evidence.items() if isinstance(e, dict)}
    else:
        by_evidence = {
            e["evidence_id"]: e
            for e in (evidence or ())
            if isinstance(e, dict) and e.get("evidence_id")
        }
    findings_list = []
    if isinstance(findings, dict):
        for role, block in findings.items():
            items = block.get("findings") if isinstance(block, dict) else block
            if isinstance(items, list):
                for f in items:
                    if isinstance(f, dict):
                        findings_list.append({**f, "role": f.get("role", role)})
    elif isinstance(findings, list):
        findings_list = [f for f in findings if isinstance(f, dict)]
    disp_by_finding = {
        d["finding_id"]: d
        for d in (dispositions or ())
        if isinstance(d, dict) and d.get("finding_id")
    }
    records_list = list(records.values()) if isinstance(records, dict) else [r for r in (records or ()) if isinstance(r, dict)]
    return by_claim, by_evidence, findings_list, disp_by_finding, records_list


def audit_underclaim_and_abstention(records, claims, evidence, findings=None, dispositions=None, exec_events=None, *, is_review=False):
    """Non-blocking advisory symmetry audit flagging potential false abstention or over-hedging.

    Never raises ContractError and never blocks review, adjudication, or export.
    """
    flags = []
    lexical_advisories = []
    seen_lexical = set()
    try:
        by_claim, by_evidence, findings_list, disp_by_finding, records_list = _normalize_audit_inputs(
            records, claims, evidence, findings, dispositions
        )
        by_record = {r.get("claim_id"): r for r in records_list if r.get("claim_id")}

        for record in records_list:
            try:
                cid = record.get("claim_id")
                claim = by_claim.get(cid)
                if not claim:
                    continue
                if is_review or ("stance" in record and "verdict" not in record):
                    observed_verdict = record.get("stance")
                else:
                    observed_verdict = record.get("verdict")
                if not observed_verdict:
                    continue

                for adv in collect_lexical_advisories(record, claim, by_evidence, exec_events=exec_events):
                    adv_key = (
                        adv.get("claim_id"),
                        adv.get("hook_code"),
                        adv.get("detail_code"),
                        tuple(adv.get("evidence_ids") or ()),
                    )
                    if adv_key not in seen_lexical:
                        seen_lexical.add(adv_key)
                        lexical_advisories.append(adv)

                raw_refs = list(record.get("evidence_ids") or ())
                claim_refs = list(claim.get("evidence_ids") or ())
                probe_refs = list(dict.fromkeys([*raw_refs, *claim_refs]))
                pos_refs = raw_refs if raw_refs else claim_refs
                probe_evs = [by_evidence[r] for r in probe_refs if r in by_evidence]
                has_blocker = _has_failed_check_or_contradiction(
                    claim,
                    probe_evs,
                    check_numeric_mismatch=(observed_verdict == "unsupported"),
                )

                frozen_type = claim.get("claim_type")
                frozen_level = claim.get("evidence_level")
                cur_type = record.get("claim_type") or frozen_type
                cur_level = record.get("evidence_level") or frozen_level
                level_downgraded = False
                if (
                    not is_review
                    and cur_type == frozen_type
                    and cur_type in TYPE_LEVELS
                    and frozen_level in TYPE_LEVELS[cur_type]
                    and cur_level in TYPE_LEVELS[cur_type]
                ):
                    level_downgraded = TYPE_LEVELS[cur_type].index(cur_level) < TYPE_LEVELS[cur_type].index(frozen_level)

                has_overclaim_justification = False
                for f in findings_list:
                    if f.get("claim_id") != cid:
                        continue
                    role = f.get("role")
                    disp = disp_by_finding.get(f.get("id"))
                    if role == "overclaim":
                        if is_review or (disp and disp.get("disposition") in ("accepted", "partial")):
                            has_overclaim_justification = True
                            break
                    elif role is None and disp and disp.get("disposition") in ("accepted", "partial"):
                        if frozen_type in TYPE_LEVELS and f.get("proposed_evidence_level") in TYPE_LEVELS[frozen_type] and frozen_level in TYPE_LEVELS[frozen_type]:
                            if TYPE_LEVELS[frozen_type].index(f["proposed_evidence_level"]) <= TYPE_LEVELS[frozen_type].index(frozen_level):
                                has_overclaim_justification = True
                                break

                if observed_verdict == "insufficient_evidence" and claim_refs and not has_blocker and not has_overclaim_justification:
                    cand_verdict = None
                    for trial_verdict in ("supported", "partially_supported"):
                        if _passes_positive_candidate(
                            claim,
                            record,
                            probe_refs,
                            by_evidence,
                            exec_events,
                            verdict=trial_verdict,
                            claim_type=frozen_type,
                            evidence_level=frozen_level,
                            claim_basis=claim.get("claim_basis"),
                            scope=claim.get("scope"),
                            revised_text=claim.get("text"),
                        ):
                            cand_verdict = trial_verdict
                            break
                    if cand_verdict is not None:
                        flags.append({
                            "claim_id": cid,
                            "hook_code": "possible_false_abstention",
                            "severity": "advisory",
                            "non_blocking": True,
                            "observed_verdict": observed_verdict,
                            "advisory_candidate_verdict": cand_verdict,
                            "advisory_candidate_level": frozen_level,
                            "message": f"Claim '{cid}' received 'insufficient_evidence' despite nonempty evidence {probe_refs} clearing support and mechanical gates for {frozen_type} x {frozen_level} ({cand_verdict}).",
                            "evidence_ids": probe_refs,
                        })

                if observed_verdict in POSITIVE and not has_blocker and not has_overclaim_justification:
                    cand_verdict = None
                    cand_level = None
                    if observed_verdict == "partially_supported":
                        if level_downgraded and _passes_positive_candidate(
                            claim, record, pos_refs, by_evidence, exec_events,
                            verdict="supported", claim_type=frozen_type, evidence_level=frozen_level,
                            claim_basis=claim.get("claim_basis"), scope=claim.get("scope"),
                        ):
                            cand_verdict, cand_level = "supported", frozen_level
                        elif _passes_positive_candidate(
                            claim, record, pos_refs, by_evidence, exec_events,
                            verdict="supported", claim_type=cur_type, evidence_level=cur_level,
                        ):
                            cand_verdict, cand_level = "supported", cur_level
                    if cand_verdict is None and level_downgraded:
                        try:
                            frozen_allowed = frozen_level in ceiling(claim, frozen_type)["allowed_levels"]
                        except (ContractError, KeyError, TypeError, ValueError):
                            frozen_allowed = False
                        if frozen_allowed and _passes_positive_candidate(
                            claim, record, pos_refs, by_evidence, exec_events,
                            verdict=observed_verdict, claim_type=frozen_type, evidence_level=frozen_level,
                            claim_basis=record.get("claim_basis") or claim.get("claim_basis"),
                            scope=record.get("scope") or claim.get("scope"),
                        ):
                            cand_verdict, cand_level = observed_verdict, frozen_level
                    if cand_verdict is not None:
                        flags.append({
                            "claim_id": cid,
                            "hook_code": "possible_unjustified_downgrade",
                            "severity": "advisory",
                            "non_blocking": True,
                            "observed_verdict": observed_verdict,
                            "advisory_candidate_verdict": cand_verdict,
                            "advisory_candidate_level": cand_level,
                            "message": f"Claim '{cid}' was downgraded to {observed_verdict} ({cur_type} x {cur_level}) without failed checks or accepted overclaim justification; {cand_verdict} at {cand_level} clears mechanical gates.",
                            "evidence_ids": pos_refs,
                        })

                emitted_effect_underclaim = False
                if observed_verdict == "unsupported" and claim.get("effect_records"):
                    try:
                        from .effects import verify_effect_computations
                        eff_probe = verify_effect_computations(
                            claim,
                            {**record, "verdict": "unsupported"},
                            by_evidence,
                        )
                    except ContractError:
                        eff_probe = None
                    eff_adv = eff_probe.get("underclaim_advisory") if eff_probe else None
                    if eff_adv and not (_has_failed_check(claim) or _has_contradicting_card(claim)):
                        prim_refs = [eid for eid in eff_adv["primary_evidence_ids"] if eid in by_evidence]
                        prim_evs = [by_evidence[eid] for eid in prim_refs]
                        if prim_evs and not any(
                            contradictory_positive_evidence_text(ev, include_outcome_stripped=False)
                            for ev in prim_evs
                        ):
                            cand_verdict = None
                            cand_level = None
                            for trial_verdict in ("supported", "partially_supported"):
                                if _passes_positive_candidate(
                                    claim, record, prim_refs, by_evidence, exec_events,
                                    verdict=trial_verdict, claim_type=frozen_type, evidence_level=frozen_level,
                                    claim_basis=claim.get("claim_basis"), scope=claim.get("scope"),
                                    revised_text=claim.get("text"),
                                ):
                                    cand_verdict, cand_level = trial_verdict, frozen_level
                                    break
                            flags.append({
                                "claim_id": cid,
                                "hook_code": "unsupported_despite_beneficial_primary_effect",
                                "severity": "advisory",
                                "non_blocking": True,
                                "observed_verdict": observed_verdict,
                                "advisory_candidate_verdict": cand_verdict or "insufficient_evidence",
                                "advisory_candidate_level": cand_level,
                                "message": eff_adv["message"],
                                "evidence_ids": prim_refs,
                                "primary_record_ids": eff_adv["primary_record_ids"],
                            })
                            emitted_effect_underclaim = True

                if observed_verdict == "unsupported" and not has_blocker and not emitted_effect_underclaim:
                    cand_verdict = None
                    cand_level = None
                    for trial_verdict in ("supported", "partially_supported"):
                        if _passes_positive_candidate(
                            claim, record, probe_refs, by_evidence, exec_events,
                            verdict=trial_verdict, claim_type=frozen_type, evidence_level=frozen_level,
                            claim_basis=claim.get("claim_basis"), scope=claim.get("scope"),
                            revised_text=claim.get("text"),
                        ):
                            cand_verdict, cand_level = trial_verdict, frozen_level
                            break
                    flags.append({
                        "claim_id": cid,
                        "hook_code": "unsupported_without_counterevidence",
                        "severity": "advisory",
                        "non_blocking": True,
                        "observed_verdict": observed_verdict,
                        "advisory_candidate_verdict": cand_verdict or "insufficient_evidence",
                        "advisory_candidate_level": cand_level,
                        "message": f"Claim '{cid}' was marked 'unsupported' without failed checks, contradicting provenance cards, or null/refuting evidence text.",
                        "evidence_ids": probe_refs,
                    })

                if (observed_verdict == "insufficient_evidence" or observed_verdict == "partially_supported" or level_downgraded) and not has_blocker:
                    rec_text = " ".join(
                        str(record.get(k) or "")
                        for k in ("rationale", "revised_text", "boundary", "condition")
                    )
                    if BOILERPLATE_OVERHEDGING_RE.search(rec_text) and probe_evs:
                        rec_rev = str(record.get("revised_text") or "")
                        claim_rev = str(claim.get("text") or "")
                        if observed_verdict == "insufficient_evidence":
                            rec_text_nums = bool(_claimed_effect_tokens({**claim, "effect": {}}, {"revised_text": rec_rev}))
                            claim_text_nums = bool(_claimed_effect_tokens({**claim, "effect": {}}, {"revised_text": claim_rev}))
                            if rec_text_nums and not claim_text_nums:
                                cand_revs = [r for r in dict.fromkeys((rec_rev, claim_rev)) if r]
                            elif claim_text_nums:
                                cand_revs = [claim_rev]
                            else:
                                cand_revs = [r for r in dict.fromkeys((claim_rev, rec_rev)) if r]
                        else:
                            cand_revs = [rec_rev or claim_rev]
                        cand_verdict = None
                        for probe_rev in cand_revs:
                            probe_dec = {**claim, **record, "verdict": "supported", "revised_text": probe_rev}
                            has_claimed_nums = bool(_claimed_effect_tokens(claim, probe_dec) or _claimed_effect_tokens(claim, claim))
                            if not (has_claimed_nums and effect_numbers_anchored(claim, probe_dec, probe_evs)):
                                continue
                            for trial_verdict in ("supported", "partially_supported"):
                                if _passes_positive_candidate(
                                    claim, record, probe_refs, by_evidence, exec_events,
                                    verdict=trial_verdict, claim_type=frozen_type, evidence_level=frozen_level,
                                    claim_basis=claim.get("claim_basis"), scope=claim.get("scope"),
                                    revised_text=probe_rev,
                                ):
                                    cand_verdict = trial_verdict
                                    break
                            if cand_verdict is not None:
                                break
                        if cand_verdict is not None:
                            flags.append({
                                "claim_id": cid,
                                "hook_code": "possible_boilerplate_overhedging",
                                "severity": "advisory",
                                "non_blocking": True,
                                "observed_verdict": observed_verdict,
                                "advisory_candidate_verdict": cand_verdict,
                                "advisory_candidate_level": frozen_level,
                                "message": f"Claim '{cid}' uses generic over-hedging boilerplate despite anchored quantitative estimates and no failed checks.",
                                "evidence_ids": probe_refs,
                            })
            except Exception:
                continue

        for f in findings_list:
            try:
                fid = f.get("id")
                disp = disp_by_finding.get(fid)
                if not disp or (disp.get("disposition") != "rejected" and disp.get("resolution") != "disagreement"):
                    continue
                role = f.get("role")
                if role is not None and role != "underclaim":
                    continue
                cid_f = f.get("claim_id")
                claim_f = by_claim.get(cid_f)
                if not claim_f:
                    continue
                dec_f = by_record.get(cid_f, {})
                cand_type = f.get("proposed_claim_type") or claim_f.get("claim_type")
                cand_level = f.get("proposed_evidence_level") or claim_f.get("evidence_level")
                if role is None:
                    cur_f_type = dec_f.get("claim_type") or claim_f.get("claim_type")
                    cur_f_level = dec_f.get("evidence_level") or claim_f.get("evidence_level")
                    if (
                        cand_type == cur_f_type
                        and cand_type in TYPE_LEVELS
                        and cand_level in TYPE_LEVELS[cand_type]
                        and cur_f_level in TYPE_LEVELS[cand_type]
                        and TYPE_LEVELS[cand_type].index(cand_level) <= TYPE_LEVELS[cand_type].index(cur_f_level)
                        and dec_f.get("verdict") in POSITIVE
                    ):
                        continue
                f_refs = list(f.get("evidence_ids") or claim_f.get("evidence_ids") or ())
                f_evs = [by_evidence[r] for r in f_refs if r in by_evidence]
                if _has_failed_check_or_contradiction(claim_f, f_evs):
                    continue
                cand_basis = f.get("proposed_claim_basis") or dec_f.get("claim_basis") or claim_f.get("claim_basis")
                cand_scope = f.get("proposed_scope") or dec_f.get("scope") or claim_f.get("scope")
                cand_verdict = None
                for trial_verdict in ("supported", "partially_supported"):
                    if _passes_positive_candidate(
                        claim_f,
                        dec_f,
                        f_refs,
                        by_evidence,
                        exec_events,
                        verdict=trial_verdict,
                        claim_type=cand_type,
                        evidence_level=cand_level,
                        claim_basis=cand_basis,
                        scope=cand_scope,
                        revised_text=f.get("proposed_text") or dec_f.get("revised_text") or claim_f.get("text"),
                    ):
                        cand_verdict = trial_verdict
                        break
                if cand_verdict is not None:
                    flags.append({
                        "claim_id": cid_f,
                        "finding_id": fid,
                        "hook_code": "rejected_underclaim_finding_advisory",
                        "severity": "advisory",
                        "non_blocking": True,
                        "observed_verdict": dec_f.get("verdict") or dec_f.get("stance"),
                        "advisory_candidate_verdict": cand_verdict,
                        "advisory_candidate_level": cand_level,
                        "message": f"Rejected underclaim finding '{fid}' on claim '{cid_f}' proposes {cand_type} x {cand_level} ({cand_verdict}), which clears support and mechanical gates.",
                        "evidence_ids": f_refs,
                    })
            except Exception:
                continue
    except Exception:
        pass
    return {
        "non_blocking": True,
        "severity": "advisory",
        "is_review": bool(is_review),
        "flag_count": len(flags),
        "flags": flags,
        "lexical_advisory_count": len(lexical_advisories),
        "lexical_advisories": lexical_advisories,
    }
