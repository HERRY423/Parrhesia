"""Frozen anti-stall gates. Enforces structure, never certifies scientific truth."""
import hashlib
import re
import unicodedata
from .claims import NON_PRIMARY_FAILED_FORK_ROLES, TYPE_LEVELS, needs_causal_basis
from .contracts import ContractError, array, enum, fail, fields, ids, obj, string
from .text_advisories import explicit_generated_source, explicit_pending_outcome, scoped_evidence_clauses
from .text_anchors import (
    ANSI_ESCAPE_RE,
    BINARY_SIGNATURES,
    CJK_STOPWORDS,
    DECREASE_POLARITY_RE,
    INCREASE_POLARITY_RE,
    MIN_CJK_QUOTE_CHARS,
    MIN_QUOTE_CHARS,
    QUOTE_STOPWORDS,
    WINDOW_DELIMITER_LINE_RE,
    _authenticated_quote_status,
    _authenticated_source_text,
    _claimed_effect_numbers,
    _claimed_effect_tokens,
    _clause_bounds,
    _extract_floats,
    _extract_signed_tokens,
    _mask_metadata_noise,
    _number_matches_source,
    _parse_authenticated_windows,
    _priority_text_for_evidence,
    _split_clauses,
    _strip_nonprimary_clauses,
    _token_matches_source,
    _val_close,
    effect_numbers_anchored,
    quote_length,
    quote_links_to_claim,
    quote_status,
    strip_terminal_escapes,
    strip_window_markers,
    text_content,
)

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
    "confounding/robustness checks pass). Every stance and decision requires a concrete evidence/check-backed rationale "
    "(and concrete scope/assumption condition when partially_supported), and every decision requires a concrete observable reversal_condition "
    "stating what specific outcome, threshold, direction change, or check/evidence event would alter the judgment (generic future-study deferrals "
    "such as '未来有更多研究时，再重新评估' or 're-evaluate when more studies are available' are rejected). "
    "Adjudication binds each finding to its claim's decision with an incorporated revised_text_quote "
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


NO_REVERSAL_REFUSAL_RE = re.compile(
    r"(?:"
    r"无需(?:改判|重新评估|调整|修改)|不会(?:改判|改变|推翻)|不可(?:改判|推翻)|无改判条件|不存在改判条件|此结论(?:不会改变|永远成立|不变)|暂不(?:改判|做改判)"
    r"|\bno\s+(?:reversal|condition|change)\b|\bcannot\s+be\s+(?:reversed|changed|overturned)\b|\bwill\s+not\s+(?:change|reverse)\b|\bnever\s+(?:changes|reverses)\b"
    r")",
    re.I,
)
VACUOUS_DEFERRAL_RE = re.compile(
    r"(?:"
    r"(?:未来|今后|日后|后续|将来|以后|待|有待|尚待|需待|等待|当|若|如果|一旦|随着)?[\u4e00-\u9fff，,、\s]{0,12}"
    r"(?:有|出现|获得|取得|积累|补充|开展|进行|完成|发表|公布|提供)?(?:了)?"
    r"(?:更多|进一步|更大规模|多中心|后续|未来|新|新的|额外|更充分|深入|长期)(?:的)?"
    r"(?:研究|数据|证据|资料|试验|实验|样本|队列|结果|分析|观察|工作|文献|报告|验证|确认|探索)"
    r"|(?:有待|尚待|需待|等待|待|需要|尚需|仍需|有赖于|取决于|视)[\u4e00-\u9fff，,、\s]{0,12}"
    r"(?:进一步|更多|后续|未来|深入|长期)?(?:的)?"
    r"(?:研究|数据|证据|资料|试验|实验|样本|验证|确认|评估|评价|观察|探索|分析|工作|讨论|探讨|考察|检验|情况)"
    r"|(?:再|重新|另行|日后|未来|后续|进一步)(?:进行|作|予以|加以)?(?:重新)?"
    r"(?:评估|评价|评判|判断|裁决|考量|审视|确认|验证|研究|讨论|探讨|分析|定论)"
    r"|(?:以后再看|日后再议|目前尚不明确|尚不明确|尚难判断|尚难定论|看后续情况)"
    r"|\b(?:when|once|after|if|as|until|pending|awaiting|upon|with|subject\s+to)?\s*(?:there\s+(?:are|is)\s+)?"
    r"(?:more|further|additional|future|larger|broader|subsequent|new|later|extended|follow[- ]?up|confirmatory)\s+"
    r"(?:(?:independent|external|multi[- ]?center|multicentre|clinical|prospective|empirical|scientific)\s+)*"
    r"(?:studies|study|research|data|evidence|trials?|experiments?|samples?|cohorts?|analyses|analysis|results?|investigations?|work|literature|reports?|observations?|validation|confirmation|replication|evaluations?)\b"
    r"|\b(?:more|further|additional|future)\s+(?:studies|study|research|data|evidence|trials?|validation|confirmation|investigation|work|evaluation)\s+"
    r"(?:are|is|will\s+be|would\s+be|may\s+be)?\s*(?:needed|required|necessary|warranted|awaited|pending|conducted|available|obtained|collected)\b"
    r"|\b(?:re[- ]?evaluat(?:e|ed|ing|ion)|reassess(?:ed|ing|ment)?|reconsider(?:ed|ing)?|revisit(?:ed|ing)?|review(?:ed|ing)?|clarif(?:y|ied)|determin(?:e|ed)|confirm(?:ed)?|verif(?:y|ied))\s+"
    r"(?:in\s+the\s+future|later|when\s+more|once\s+more|with\s+more|with\s+further|after\s+further|after\s+more|pending\s+further)\b"
    r"|\b(?:wait\s+and\s+see|remains?\s+to\s+be\s+seen|to\s+be\s+determined(?:\s+later)?|it\s+depends|depends\s+on\s+future)\b"
    r")",
    re.I,
)
CONCRETE_REVERSAL_SIGNAL_RE = re.compile(
    r"(?:"
    r"\b\d+\.\d+\b"
    r"|(?:[<>≤≥≠=]+|below|above|exceeds|under|over)\s*[-+]?\d+(?:\.\d+)?\s*%"
    r"|\b(?:hr|or|rr|irr|rd|auroc|auc|rmse|mae|r2|f1|logfc|beta|p|alpha|ci|effect|estimate|hazard|odds|risk|correlation)\s*(?:[<>≤≥≠=]+|is|exceeds|below|above|drops|rises)\s*[-+]?\d"
    r"|\b(?:hr|rr|irr|rd|risk\s+diff\w*|mean\s+diff\w*|odds\s+ratio|hazard\s+ratio|auroc|auc|rmse|mae|r2|f1|logfc|beta|p[-_ ]?value|ci|confidence\s+interval|credible\s+interval|e[- ]?value|i\^?2|alpha|threshold|margin|bound|bounds|band)\b"
    r"|\b(?:null|zero|no\s+effect|no\s+difference|no\s+benefit|no\s+association|no\s+phosphorylation|non[- ]?significant|insignificant|fail|fails|failed|failure|drop|drops|dropped|decline|declines|decrease|decreases|lower|higher|increase|increases|reverse|reversed|reverses|bias\s+reversal|reversal\s+trigger|flip|flips|flipped|opposite|contrary|contradict\w*|refut\w+|falsif\w+|disprov\w+|inconsistent|mismatch\w*|discrepanc\w+|alter|altered|corrupt\w*|tamper\w*|bias\w*|confound\w*|inflation|attenuat\w+|abolish\w+|harm|harms|toxicity|adverse|negative|positive|worse|inferior|non[- ]?inferior|equivalen\w+|invalid\w*|violat\w*|breach\w*|counterexample\w*|deviat\w*|shift\w*|off[- ]?target|error\w*|crash\w*|overturn\w*|withdraw\w*|retract\w*|cross(?:es|ed|ing)?\s+(?:null|reversal|trigger)|exclud(?:es|ed|ing)?\s+null)\b"
    r"|\b(?:check|checks|quality|batch|unit|assumptions|multiplicity|leakage|baseline|sensitivity|placebo|negative[- ]control|estimand|calibration|utility|checksum|sha256|hash|quote|anchor\w*|excerpt\w*|binary|extract\w*|fork\w*|seed\w*|non[- ]?synthetic|empirical|concrete\s+test|readable|tail\s+summary|tail\s+consistency|different\s+(?:fixture|source|run|primary\s+observation|value|result|direction|outcome|estimate|record)|chang(?:e|es|ed|ing)\s+(?:direction|sign|verdict|status|outcome|estimate|result)|mutant|knockout|perturbation|rescue|ablation|holdout|cross[- ]?validation|decontaminat\w*|lemma|theorem|proof|axiom|member[- ]?checking|triangulat\w*|coding|regression|smoke\s+test|preregister\w*|protocol|trigger)\b"
    r"|(?:置信区间|可信区间|跨零|包含零|排除零|效应量|效应值|风险比|比值比|相对危险度|相关系数|区分度|校准|决策效用|效用|阈值|界值|下限|上限|非劣|等效)"
    r"|(?:零效应|无效应|无显著|无差异|不显著|无获益|未见|消失|减弱|衰减|偏离|偏移|失败|未通过|不通过|不达标|未达|失效|下降|降低|跌破|低于|高于|升高|上升|超过|不足|反转|逆转|相反|反向|推翻|证伪|反驳|否定|矛盾|相悖|冲突|不一致|不符|偏差|偏倚|混杂|伪影|泄漏|篡改|损坏|缺失|阴性|阳性|有害|毒性|不良|恶化|无效|不成立|撤回|反例|漏洞|错误|误差|崩溃|异常|仍发生|不同(?:数值|结果|方向|结论|记录|来源|样本))"
    r"|(?:质控|批次|独立重复|分析单位|方法前提|多重比较|多重校正|基线|阴性对照|安慰剂|敏感度|哈希|校验和|摘录|锚点|二进制|提取|分叉|种子|非合成|真实经验|可读|敲除|突变|脱靶|救援|正交|引理|定理|证明|公理|三角互证|编码|污染|去污染|回归测试|单元测试|集成测试|宿主验收|预注册|复测)"
    r")",
    re.I,
)
UPPER_OR_METRIC_RE = re.compile(r"\bOR\b")
# Stronger observable falsification signals required to rescue a text that also contains generic deferral phrasing.
STRONG_REVERSAL_SIGNAL_RE = re.compile(
    r"(?:"
    r"\b\d+\.\d+\b"
    r"|(?:[<>≤≥≠=]+|below|above|exceeds|under|over)\s*[-+]?\d+(?:\.\d+)?\s*%"
    r"|\b(?:hr|or|rr|irr|rd|auroc|auc|rmse|mae|r2|f1|logfc|beta|p|alpha|ci|e[- ]?value|deff|icc|mde|tost)\s*(?:[<>≤≥≠=]+|is|exceeds|below|above|drops|rises)\s*[-+]?\d"
    r"|\b(?:hr|rr|irr|rd|auroc|auc|rmse|mae|r2|f1|logfc|e[- ]?value|i\^?2|tost|mde|deff)\b"
    r"|\b(?:cross(?:es|ed|ing)?\s+(?:null|1(?:\.0+)?|0(?:\.0+)?)|exclud(?:es|ed|ing)?\s+null|reverse[sd]?|flip(?:s|ped)?|abolish(?:es|ed)?|fail(?:s|ed)?\s+(?:check|replication|sensitivity|placebo|negative[- ]control)|negative[- ]control\s+(?:signal|positive|fails?)|knockout|perturbation|rescue|ablation|counterexample)\b"
    r"|(?:置信区间|可信区间|跨零|包含零|排除零|风险比|比值比|相对危险度|区分度|校准斜率|效用|阈值|界值|非劣|等效)"
    r"|(?:跌破|低于|高于|超过|反转|逆转|推翻|证伪|反例|敲除|突变|脱靶|救援|正交|阴性对照(?:阳性|失败|出现信号)|检验失败|检查(?:失败|变更|不通过))"
    r")",
    re.I,
)
FALSE_BALANCE_RE = re.compile(
    r"(?:"
    r"\bboth\s+(?:sides|views|explanations|hypotheses)\s+(?:have\s+merit|(?:are|remain)\s+equally\s+(?:plausible|possible|supported))\b"
    r"|\b(?:is|are|remains?)\s+just\s+as\s+(?:well\s+supported|plausible|likely)\b"
    r"|(?:两种|各方)(?:解释|观点|假说)(?:均有道理|同样可能|同等有据)"
    r"|(?:解释|观点|假说)(?:也|仍)同样(?:可能|有据|得到支持)"
    r")",
    re.I | re.S,
)


def has_concrete_reversal_signal(value):
    if not isinstance(value, str):
        return False
    if NO_REVERSAL_REFUSAL_RE.search(value):
        return False
    return bool(CONCRETE_REVERSAL_SIGNAL_RE.search(value) or UPPER_OR_METRIC_RE.search(value))


def has_strong_reversal_signal(value):
    if not isinstance(value, str):
        return False
    if NO_REVERSAL_REFUSAL_RE.search(value):
        return False
    return bool(STRONG_REVERSAL_SIGNAL_RE.search(value) or UPPER_OR_METRIC_RE.search(value))


def is_vacuous_reversal_condition(value):
    if not substantive_reason(value):
        return True
    if BOILERPLATE_OVERHEDGING_RE.search(value) or NO_REVERSAL_REFUSAL_RE.search(value):
        return True
    if VACUOUS_DEFERRAL_RE.search(value) and not has_strong_reversal_signal(value):
        return True
    return not has_concrete_reversal_signal(value)


def validate_abstention_justification(value, known_evidence, label="decision.abstention_justification"):
    """Validate structured justification required to rebut enforced symmetry challenges."""
    rec = obj(value, label)
    fields(rec, {"blocking_gaps", "counterevidence_ids", "reason"}, {"blocking_gaps", "reason"}, label)
    gaps = array(rec["blocking_gaps"], f"{label}.blocking_gaps", minimum=1, maximum=10)
    cleaned_gaps = []
    for idx, gap in enumerate(gaps):
        txt = validate_non_placeholder_text(gap, f"{label}.blocking_gaps[{idx}]")
        if BOILERPLATE_OVERHEDGING_RE.search(txt) or (VACUOUS_DEFERRAL_RE.search(txt) and not has_strong_reversal_signal(txt)):
            fail(
                "invalid_abstention_justification",
                f"{label}.blocking_gaps[{idx}] must name a concrete unmodeled flaw, confounder, or missing empirical test, not generic deferral boilerplate",
            )
        cleaned_gaps.append(txt)
    reason = validate_rationale(rec["reason"], f"{label}.reason")
    if BOILERPLATE_OVERHEDGING_RE.search(reason):
        fail(
            "invalid_abstention_justification",
            f"{label}.reason cannot rely on generic over-hedging boilerplate",
        )
    ce_ids = ids(rec.get("counterevidence_ids", []), f"{label}.counterevidence_ids", minimum=0, maximum=50)
    if not set(ce_ids) <= set(known_evidence):
        fail("unknown_reference", f"{label}.counterevidence_ids references unregistered evidence IDs")
    return {"blocking_gaps": cleaned_gaps, "counterevidence_ids": ce_ids, "reason": reason}


def validate_evidence_dominance(value, label="decision.evidence_dominance"):
    """Validate optional structured dominance assessment opposing hollow-neutrality false balance."""
    rec = obj(value, label)
    required = {"favored_explanation", "rival_explanation", "asymmetry_status", "basis"}
    fields(rec, required, required, label)
    return {
        "favored_explanation": validate_non_placeholder_text(rec["favored_explanation"], f"{label}.favored_explanation"),
        "rival_explanation": validate_non_placeholder_text(rec["rival_explanation"], f"{label}.rival_explanation"),
        "asymmetry_status": enum(
            rec["asymmetry_status"],
            ("dominant", "conditionally_dominant", "balanced_unresolved", "genuinely_unresolved"),
            f"{label}.asymmetry_status",
        ),
        "basis": validate_rationale(rec["basis"], f"{label}.basis"),
    }


def is_vacuous_rationale(value):
    if not meaningful(value):
        return True
    visible = "".join(c for c in value if not unicodedata.category(c).startswith("C")).strip()
    cleaned = "".join(c for c in visible if c.isalnum() or c.isspace()).strip().upper()
    if not cleaned or cleaned in TRIVIAL_REASONS:
        return True
    if NO_REVERSAL_REFUSAL_RE.search(value):
        return True
    if VACUOUS_DEFERRAL_RE.search(value) and not has_concrete_reversal_signal(value) and not BOILERPLATE_OVERHEDGING_RE.search(value):
        return True
    return False


def validate_non_placeholder_text(value, label):
    txt = string(value, label)
    if not meaningful(txt):
        fail("invalid_value", f"{label} cannot be empty, invisible, or a placeholder token")
    visible = "".join(c for c in txt if not unicodedata.category(c).startswith("C")).strip()
    cleaned = "".join(c for c in visible if c.isalnum() or c.isspace()).strip().upper()
    if not cleaned or cleaned in TRIVIAL_REASONS:
        fail("invalid_value", f"{label} must be a substantive statement, not a trivial label")
    return txt


def validate_rationale(value, label="decision.rationale"):
    txt = string(value, label)
    if is_vacuous_rationale(txt):
        fail(
            "invalid_rationale",
            f"{label} must state a concrete evidence- or check-grounded reason, not a placeholder, trivial label, or generic future-study deferral",
        )
    return txt


def validate_condition_text(value, label="decision.condition", *, missing_code="invalid_condition"):
    txt = string(value, label)
    if not meaningful(txt):
        fail(missing_code, f"{label} must state an actual condition, not unknown or invisible text")
    if (
        not substantive_reason(txt)
        or BOILERPLATE_OVERHEDGING_RE.search(txt)
        or NO_REVERSAL_REFUSAL_RE.search(txt)
        or (VACUOUS_DEFERRAL_RE.search(txt) and not has_concrete_reversal_signal(txt))
    ):
        fail(
            "invalid_condition",
            f"{label} must state a concrete scope or assumption condition, not a trivial label or generic future-study deferral",
        )
    return txt


def validate_reversal_condition(value, label="decision.reversal_condition", *, decision=None, claim=None):
    txt = string(value, label)
    if is_vacuous_reversal_condition(txt):
        fail(
            "invalid_reversal_condition",
            f"{label} must state a concrete observable outcome, metric/threshold, direction change, or check/evidence event that would alter the judgment, not a placeholder or generic future-study deferral",
        )
    norm = " ".join(txt.split()).strip().lower()
    duplicate_targets = []
    if isinstance(decision, dict):
        for k in ("revised_text", "rationale", "boundary"):
            v = decision.get(k)
            if isinstance(v, str) and v.strip():
                duplicate_targets.append((f"decision.{k}", " ".join(v.split()).strip().lower()))
    if isinstance(claim, dict):
        v = claim.get("text")
        if isinstance(v, str) and v.strip():
            duplicate_targets.append(("claim.text", " ".join(v.split()).strip().lower()))
    for dup_label, dup_norm in duplicate_targets:
        if norm == dup_norm:
            fail(
                "invalid_reversal_condition",
                f"{label} must state what observation or event would change the judgment, not duplicate {dup_label}",
            )
    return txt


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


def contradictory_positive_evidence_text(ev, include_outcome_stripped=True, *, focus_text=""):
    parts = scoped_evidence_clauses(ev, focus_text)
    raw = "; ".join(p for p in parts if p).lower()
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
    if include_outcome_stripped and explicit_pending_outcome(parts):
        return "outcome_stripped_or_pending_evidence"
    return None


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
    provenance_cards = claim.get("provenance_cards")
    raw_cards = provenance_cards.get("execution") if isinstance(provenance_cards, dict) else []
    if not isinstance(raw_cards, list):
        raw_cards = []
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
    rec_eids = record.get("evidence_ids")
    claim_eids = claim.get("evidence_ids")
    raw_ref_seq = rec_eids if isinstance(rec_eids, (list, tuple)) and rec_eids else (claim_eids if isinstance(claim_eids, (list, tuple)) else ())
    refs = list(dict.fromkeys(r for r in raw_ref_seq if isinstance(r, (str, int)) and not isinstance(r, bool)))
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
        focus_text = str(record.get("revised_text") or claim.get("text") or "")
        clauses = scoped_evidence_clauses(ev, focus_text)
        kind_contra = contradictory_evidence_kind(ev)
        if not kind_contra and explicit_generated_source(ev, clauses):
            kind_contra = "synthetic_source_declared_as_empirical"
        if kind_contra:
            _add(
                "possible_evidence_kind_mismatch",
                kind_contra,
                f"Evidence '{ref}' contains lexical cues potentially conflicting with declared kind '{ev.get('kind')}' ({kind_contra}).",
                [ref],
            )
        text_contra = contradictory_positive_evidence_text(ev, include_outcome_stripped=True, focus_text=focus_text)
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
        checks = claim.get("checks")
        mult_check = checks.get("multiplicity") if isinstance(checks, dict) and isinstance(checks.get("multiplicity"), dict) else {}
        stat_report = claim.get("statistical_report")
        mult_stat = stat_report.get("multiplicity_selection") if isinstance(stat_report, dict) and isinstance(stat_report.get("multiplicity_selection"), dict) else {}
        reasons_lower = f"{mult_check.get('reason', '')} {mult_stat.get('reason', '')}".lower()
        accounting_text = f"{reasons_lower} {record.get('revised_text', '')} {record.get('condition', '')}".lower()
        stat_eids = mult_stat.get("evidence_ids")
        stat_eid_seq = [r for r in (stat_eids if isinstance(stat_eids, (list, tuple)) else ()) if isinstance(r, (str, int)) and not isinstance(r, bool)]
        fork_ev_ids = list(dict.fromkeys([*stat_eid_seq, *info["card_ev_ids"], *refs]))
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
    # Runtime receipts and parsed numeric artifacts document execution/numbers,
    # never the study design. They can accompany separately compatible evidence,
    # but cannot be the sole basis for a positive classification.
    has_design_source = any(evidence[ref].get("kind") in compatible for ref in decision["evidence_ids"])
    recorded_receipts = {event.get("evidence_id") for event in (exec_events or [])}
    supplemental = set()
    if has_design_source:
        for ref in decision["evidence_ids"]:
            source = evidence[ref]
            if source.get("kind") != "unknown" or not source.get("kind_inference"):
                continue
            if ref in recorded_receipts:
                supplemental.add(ref)
            elif source.get("artifact", {}).get("format") == "statistics" and any(
                rec.get("evidence_id") == ref and rec.get("artifact_binding") for rec in claim.get("effect_records", [])
            ):
                supplemental.add(ref)
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
        if ev["kind"] not in compatible and ref not in supplemental:
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
    if needs_causal_basis(decision) and not all(evidence[ref]["kind"] in allowed_causal_kinds for ref in decision["evidence_ids"] if ref not in supplemental):
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
        fields(stance, keys | {"condition", "reversal_condition"}, keys, "stance")
        cid = string(stance["claim_id"], "stance.claim_id")
        if cid not in claims:
            fail("unknown_claim", "stance refers to a non-frozen claim")
        seen.append(cid)
        enum(stance["stance"], ("supported", "partially_supported", "unsupported", "insufficient_evidence"), "stance")
        if stance["stance"] == "partially_supported" and not meaningful(stance.get("condition")):
            fail("missing_stance_condition", "a conditionally supportive stance must specify its actual condition")
        if "condition" in stance:
            if not meaningful(stance["condition"]):
                fail("missing_stance_condition", "condition cannot be empty, invisible or an unknown placeholder")
            validate_condition_text(stance["condition"], "stance.condition", missing_code="missing_stance_condition")
        validate_rationale(stance["rationale"], "stance.rationale")
        if "reversal_condition" in stance:
            validate_reversal_condition(stance["reversal_condition"], "stance.reversal_condition", claim=claims[cid])
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
        proposed_norm = " ".join(finding["proposed_text"].split())
        revised_norm = " ".join(decision["revised_text"].split())
        if not proposed_norm or proposed_norm not in revised_norm:
            if finding["proposed_text"] not in decision["revised_text"]:
                fail("finding_not_incorporated", "accepted incorporation requires the proposed text; deviations need explicit disagreement or partial adoption")
        for key in ("claim_type", "evidence_level", "scope", "claim_basis"):
            if finding["proposed_" + key] != decision[key]:
                fail("finding_not_incorporated", "accepted classification/scope must match the decision, or record disagreement")

from .symmetry_audit import (
    _has_contradicting_card,
    _has_failed_check,
    _has_failed_check_or_contradiction,
    _is_valid_audit_id,
    _iter_claim_check_records,
    _normalize_audit_inputs,
    _passes_positive_candidate,
    audit_underclaim_and_abstention,
    enforce_symmetry_adjudication,
)
