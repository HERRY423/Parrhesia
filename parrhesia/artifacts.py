"""Read existing workflow artifacts without executing them or trusting their claims."""
from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Callable
import math
from pathlib import Path
import re
from typing import Any

from .binary_artifacts import inspect_parquet_metadata, list_xlsx_sheets
from .contracts import enum, fail
from .gates import EVIDENCE_KINDS
from .manuscript import safe_xml
from .stat_import import ALIASES, parse_statistics, strict_json

ARTIFACT_FORMATS = ("auto", "notebook", "rmarkdown", "quarto", "nextflow_trace", "snakemake_stats",
                    "container_inspect", "dvc", "slurm_sacct", "pbs_json", "junit", "dataset_metadata",
                    "statistics", "xlsx", "parquet")


def _parse_tsv_header_and_rows(content: bytes) -> tuple[list[str], list[list[str]]] | None:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    if not text.strip():
        return None
    reader = csv.reader(io.StringIO(text), delimiter="\t", strict=True)
    try:
        header = [h.strip() for h in next(reader)]
        rows = [row for row in reader if row]
    except (StopIteration, csv.Error):
        return None
    if len(header) < 2 or not all(header) or len(set(h.casefold() for h in header)) != len(header):
        return None
    if any(len(row) != len(header) for row in rows):
        return None
    return header, rows


def _is_statistics_tsv(content: bytes) -> bool:
    parsed = _parse_tsv_header_and_rows(content)
    if parsed is None:
        return False
    header, rows = parsed
    folded = [h.casefold() for h in header]
    ep_aliases = {a.casefold() for a in ALIASES["endpoint"]}
    est_aliases = {a.casefold() for a in ALIASES["estimate"]}
    ep_matches = [i for i, h in enumerate(folded) if h in ep_aliases]
    est_matches = [i for i, h in enumerate(folded) if h in est_aliases]
    if len(ep_matches) != 1 or len(est_matches) != 1:
        return False
    ep_name = folded[ep_matches[0]]
    est_name = folded[est_matches[0]]
    extra_aliases = {a.casefold() for k, vals in ALIASES.items() if k not in ("endpoint", "estimate") for a in vals}
    if ep_name in ("endpoint", "term", "outcome") or est_name in ("estimate", "coef", "coefficient") or any(h in extra_aliases for h in folded):
        return True
    est_idx = est_matches[0]
    for row in rows:
        raw_val = row[est_idx].strip().replace("\u2212", "-")
        try:
            num = float(raw_val)
        except ValueError:
            continue
        if math.isfinite(num):
            return True
    return False


def _is_nextflow_trace_tsv(content: bytes) -> bool:
    parsed = _parse_tsv_header_and_rows(content)
    if parsed is None:
        return False
    header, rows = parsed
    return bool(rows) and {"task_id", "status", "exit"} <= set(header)


def recognizable_artifact(content: bytes, path: str) -> str | None:
    """Identify supported structured sources on the legacy registration route too."""
    suffix = Path(path).suffix.lower()
    json_candidate = content.removeprefix(b"\xef\xbb\xbf").lstrip().startswith((b"{", b"["))
    if suffix == ".json" or json_candidate:
        try:
            value = strict_json(content.decode("utf-8-sig"))
        except (ValueError, UnicodeError):
            value = None
        if isinstance(value, dict):
            if {"a", "b", "c", "d"} <= value.keys() or {"treated_events", "treated_n", "control_events", "control_n"} <= value.keys():
                return "statistics"
            if "nbformat" in value:
                return "notebook"
            if "synthetic" in value or "data_origin" in value:
                return "dataset_metadata"
            if "Jobs" in value:
                return "pbs_json"
            if (
                "rows" in value
                or {"tp", "tn", "fp", "fn"} <= value.keys()
            ):
                return "statistics"
            if "RepoDigests" in value:
                return "container_inspect"
        if isinstance(value, list) and value and isinstance(value[0], dict):
            if "RepoDigests" in value[0]:
                return "container_inspect"
            if "estimate" in value[0] or "coef" in value[0]:
                return "statistics"
    known = {".ipynb": "notebook", ".rmd": "rmarkdown", ".qmd": "quarto", ".dvc": "dvc",
             ".csv": "statistics", ".xlsx": "xlsx", ".parquet": "parquet"}
    if suffix in known:
        return known[suffix]
    if suffix == ".tsv":
        if _is_statistics_tsv(content):
            return "statistics"
        if _is_nextflow_trace_tsv(content):
            return "nextflow_trace"
        return None
    if Path(path).name.lower() == "dvc.lock":
        return "dvc"
    if suffix == ".xml" and re.search(rb"<testsuites?(?:\s|>)", content):
        return "junit"
    return None


def validate_statistical_source_kind(evidence: dict, content: bytes) -> str | None:
    """Reject historical kind upgrades without rewriting frozen registration metadata."""
    detected = recognizable_artifact(content, evidence.get("path", ""))
    if detected in ("statistics", "xlsx") and evidence.get("kind") not in ("unknown", "synthetic"):
        fail(
            "artifact_kind_conflict",
            f"Evidence {evidence.get('evidence_id')} was registered as kind={evidence.get('kind')}, "
            f"but its {detected} snapshot cannot establish that study design. "
            "The frozen record is unchanged; register it as unknown in a new case and cite separate design evidence.",
        )
    return detected if detected in ("statistics", "xlsx") else None


def _format(path: str, format: str, content: bytes | None = None) -> str:
    enum(format, ARTIFACT_FORMATS, "artifact_format")
    if format != "auto":
        return format
    suffix = Path(path).suffix.lower()
    name = Path(path).name.lower()
    inferred = {".ipynb": "notebook", ".rmd": "rmarkdown", ".qmd": "quarto", ".dvc": "dvc",
                ".csv": "statistics", ".xlsx": "xlsx", ".parquet": "parquet"}.get(suffix)
    if suffix == ".tsv" and content is not None and _is_statistics_tsv(content):
        inferred = "statistics"
    if name == "dvc.lock":
        inferred = "dvc"
    if not inferred:
        fail("unsupported_format", "Specify artifact_format; ambiguous JSON/XML/TSV/log names are not classified from filenames")
    return inferred


def restrict_kind(inferred: str, requested: str | None) -> str:
    if requested is None or requested == "auto":
        return inferred
    enum(requested, EVIDENCE_KINDS, "kind")
    # Synthetic is a sticky restriction, never an upgrade to observed data.
    if inferred == "synthetic":
        if requested != "synthetic":
            fail("kind_upgrade_forbidden", "Synthetic source cannot be relabeled; retain synthetic provenance")
        return "synthetic"
    if requested in (inferred, "unknown", "synthetic"):
        return requested
    fail("kind_upgrade_forbidden", f"Artifact supports kind={inferred}; a reported kind={requested} cannot upgrade it")


_RMD_YAML_KEYS = ("title", "author", "date", "format", "output", "engine")


def _clean_yaml_scalar(raw: str) -> str | None:
    text = raw.strip()
    if not text or text.startswith("!"):
        return None
    if text[0] in ("'", '"') and len(text) >= 2 and text[-1] == text[0]:
        inner = text[1:-1].strip()
        return None if not inner or inner.startswith("!") else inner
    if "#" in text:
        text = text.split("#", 1)[0].strip()
    if not text or text.startswith("!"):
        return None
    return text


def _extract_rmd_yaml_header(text: str) -> dict[str, str]:
    m = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.S)
    if not m:
        return {}
    out: dict[str, str] = {}
    lines = m.group(1).splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or line[0].isspace():
            continue
        km = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not km:
            continue
        key, raw_val = km.group(1).lower(), km.group(2)
        if key not in _RMD_YAML_KEYS:
            continue
        cleaned = _clean_yaml_scalar(raw_val)
        if cleaned is not None:
            out[key] = cleaned[:256]
        elif key in ("format", "output") and idx + 1 < len(lines) and lines[idx + 1].startswith("  "):
            sub = lines[idx + 1].strip()
            sm = re.match(r"^([A-Za-z0-9_-]+):", sub)
            if sm:
                out[key] = sm.group(1)[:64]
        if len(out) >= 16:
            break
    return out


def _parse_dvc_entries(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []

    def _valid_hash(algo: str, val: str | None) -> str | None:
        if val is None:
            return None
        al = algo.lower()
        core = val[:-4] if val.lower().endswith(".dir") else val
        expected_len = 32 if al == "md5" else 64
        if len(core) == expected_len and re.fullmatch(r"[0-9a-fA-F]+", core):
            return val
        return None

    def _flush(item: dict[str, Any] | None) -> None:
        if not item:
            return
        fields = item["fields"]
        for algo in ("sha256", "md5"):
            if algo in fields:
                digest, loc = fields[algo]
                rec: dict[str, str] = {"algorithm": algo, "digest": digest, "location": loc}
                if "path" in fields:
                    rec["path"] = fields["path"]
                entries.append(rec)
                break

    def _ingest_kv(fields: dict[str, Any], raw_kv: str, lineno: int) -> None:
        km = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", raw_kv.strip())
        if not km:
            return
        key, raw_val = km.group(1).lower(), km.group(2)
        cleaned = _clean_yaml_scalar(raw_val)
        if key in ("md5", "sha256"):
            digest = _valid_hash(key, cleaned)
            if digest is not None:
                fields[key] = (digest, f"L{lineno}")
        elif key == "path" and cleaned is not None:
            fields["path"] = cleaned

    current: dict[str, Any] | None = None
    for lineno, raw_line in enumerate(text.splitlines(), 1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        dash = re.match(r"^(\s*)-\s+(.*)$", raw_line)
        if dash:
            _flush(current)
            current = {"indent": len(dash.group(1)), "fields": {}}
            _ingest_kv(current["fields"], dash.group(2), lineno)
            continue
        if current is not None:
            lead = len(raw_line) - len(raw_line.lstrip(" "))
            if lead > current["indent"]:
                _ingest_kv(current["fields"], stripped, lineno)
                continue
            _flush(current)
            current = None
        km = re.match(r"^\s*(md5|sha256):\s*(.+?)\s*$", raw_line)
        if km:
            cleaned = _clean_yaml_scalar(km.group(2))
            digest = _valid_hash(km.group(1), cleaned)
            if digest is not None:
                entries.append({"algorithm": km.group(1).lower(), "digest": digest, "location": f"L{lineno}"})
    _flush(current)
    return entries


def inspect_artifact(content: bytes, path: str, format: str = "auto", requested_kind: str | None = None,
                     *, dvc_path_resolver: Callable[[str, str, str], dict[str, Any]] | None = None) -> dict:
    format = _format(path, format, content)
    is_binary = format in ("xlsx", "parquet") or (
        format == "statistics" and (Path(path).suffix.lower() == ".xlsx" or content[:4] == b"PK\x03\x04")
    )
    text = ""
    if not is_binary:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            fail("invalid_source", "Artifact adapter requires UTF-8 text")
    details: dict[str, Any] = {}
    warnings: list[str] = []
    inferred = "unknown"
    if format == "notebook":
        value = strict_json(text)
        if not isinstance(value, dict) or value.get("nbformat") != 4 or not isinstance(value.get("cells"), list):
            fail("invalid_source", "Expected nbformat 4 notebook cells")
        cells = value["cells"]
        counts, errors, outputs, unexecuted, markdown_cells = [], [], 0, 0, 0
        for i, cell in enumerate(cells):
            if not isinstance(cell, dict):
                fail("invalid_source", "Invalid notebook cell")
            ctype = cell.get("cell_type")
            if ctype == "markdown":
                markdown_cells += 1
            elif ctype == "code":
                count = cell.get("execution_count")
                if count is not None and (type(count) is not int or count < 1):
                    fail("invalid_source", "Invalid notebook execution_count")
                counts.append(count)
                unexecuted += count is None
                cell_outputs = cell.get("outputs", [])
                if not isinstance(cell_outputs, list) or not all(isinstance(o, dict) for o in cell_outputs):
                    fail("invalid_source", "Invalid notebook outputs")
                outputs += len(cell_outputs)
                errors.extend({"cell_index": i, "ename": o.get("ename"), "evalue": o.get("evalue")} for o in cell_outputs if o.get("output_type") == "error")
        executed_counts = [c for c in counts if c is not None]
        out_of_order = any(b <= a for a, b in zip(executed_counts, executed_counts[1:]))
        meta = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
        ks_raw = meta.get("kernelspec") if isinstance(meta.get("kernelspec"), dict) else {}
        safe_ks = {k: ks_raw[k] for k in ("name", "display_name", "language") if isinstance(ks_raw.get(k), str) and ks_raw[k]}
        details = {"cells": len(cells), "code_cells": len(counts), "markdown_cells": markdown_cells,
                   "execution_counts": counts, "out_of_order_execution": out_of_order,
                   "unexecuted_cells": unexecuted, "saved_output_count": outputs, "errors": errors,
                   "kernelspec": safe_ks or None}
        if out_of_order:
            warnings.append("Notebook code cell execution_counts are non-monotonic or duplicated (out_of_order_execution=True).")
        warnings.append("Saved execution counts/outputs do not prove this notebook ran in the recorded command or in order.")
    elif format in ("rmarkdown", "quarto"):
        chunk_langs = sorted({m.lower() for m in re.findall(r"^\s*```\s*\{\s*([A-Za-z0-9_+-]+)", text, re.M)})
        yaml_header = _extract_rmd_yaml_header(text)
        details = {"code_chunk_count": len(re.findall(r"^\s*```\s*\{", text, re.M)),
                   "chunk_languages": chunk_langs,
                   "yaml_header": yaml_header,
                   "execution_status": "unknown"}
        warnings.append("Source chunks are not executed; provide rendered/statistical outputs separately.")
    elif format in ("nextflow_trace", "slurm_sacct"):
        delimiter = "\t" if format == "nextflow_trace" else "|"
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        required = {"task_id", "status", "exit"} if format == "nextflow_trace" else {"JobID", "State", "ExitCode"}
        if not reader.fieldnames or not required <= set(reader.fieldnames) or len(set(reader.fieldnames)) != len(reader.fieldnames):
            fail("invalid_source", f"Expected {format} headers {sorted(required)}")
        keep = ("task_id", "native_id", "hash", "name", "status", "exit", "container") if format == "nextflow_trace" else ("JobID", "State", "ExitCode", "Start", "End", "Elapsed")
        rows = []
        for row in reader:
            if None in row or any(row.get(key) is None for key in required):
                fail("invalid_source", "Malformed workflow trace row")
            rows.append({key: row[key] for key in keep if key in row})
        if not rows or len(rows) > 10000:
            fail("invalid_source", "Workflow trace requires 1–10000 records")
        details = {"records": rows, "record_count": len(rows)}
        warnings.append("Task/job states are reported by this saved artifact; submission and CACHED states do not attest a fresh successful analysis.")
    elif format == "snakemake_stats":
        value = strict_json(text)
        if not isinstance(value, dict) or not ({"rules", "total_runtime", "rule_stats", "runtime"} & set(value)):
            fail("invalid_source", "Expected Snakemake statistics JSON with rules/runtime fields")
        details = {key: value[key] for key in ("total_runtime", "runtime", "rules", "rule_stats") if key in value}
        warnings.append("Statistics are imported historical output, not a new workflow execution attestation.")
    elif format == "container_inspect":
        value = strict_json(text)
        rows = value if isinstance(value, list) else [value]
        digests = []
        for row in rows:
            if not isinstance(row, dict):
                fail("invalid_source", "Expected container image inspect objects")
            # Never copy Config.Env or any arbitrary configuration into metadata output.
            for item in [row.get("Id"), *(row.get("RepoDigests") or [])]:
                if isinstance(item, str) and re.fullmatch(r"(?:[^\s@]+@)?sha256:[0-9a-fA-F]{64}", item):
                    digests.append(item)
        if not digests:
            fail("invalid_source", "No immutable sha256 image digest found; tags are not digests")
        details = {"image_digests": sorted(set(digests)), "running_image_match": "unknown"}
        warnings.append("An inspect export identifies an image; it does not prove the command used it. Source snapshot stays local and may contain private configuration.")
    elif format == "dvc":
        # Deliberately bounded YAML subset: retain literal checksum fields, never load/execute tags.
        hashes = _parse_dvc_entries(text)
        if not hashes:
            fail("unsupported_format", "No supported literal DVC md5/sha256 fields; remote objects/YAML tags are not resolved")
        if dvc_path_resolver is not None:
            for entry in hashes:
                if entry["digest"].lower().endswith(".dir"):
                    entry["verification"] = "unverified_dir"
                elif "path" not in entry:
                    entry["verification"] = "unverified_no_path"
                else:
                    res = dvc_path_resolver(path, entry["path"], entry["algorithm"])
                    if res.get("status") == "hashed":
                        actual = str(res["actual_digest"]).lower()
                        if "resolved_path" in res:
                            entry["resolved_path"] = res["resolved_path"]
                        if "size" in res:
                            entry["size"] = res["size"]
                        if actual == entry["digest"].lower():
                            entry["verification"] = "matched"
                        else:
                            entry["verification"] = "mismatch"
                            entry["actual_digest"] = actual
                    else:
                        entry["verification"] = str(res.get("status") or "unverified")
                        if "reason" in res:
                            entry["reason"] = res["reason"]
        else:
            for entry in hashes:
                entry["verification"] = "unverified"
        matched_count = sum(1 for h in hashes if h.get("verification") == "matched")
        mismatch_count = sum(1 for h in hashes if h.get("verification") == "mismatch")
        unverified_count = len(hashes) - matched_count - mismatch_count
        verified_all = bool(hashes) and matched_count == len(hashes)
        details = {
            "recorded_checksums": hashes,
            "data_content_verified": verified_all,
            "verified_count": matched_count,
            "mismatch_count": mismatch_count,
            "unverified_count": unverified_count,
        }
        if mismatch_count > 0:
            warnings.append("One or more local regular DVC-tracked files mismatch the recorded DVC digest (data_content_verified=False).")
        elif verified_all:
            warnings.append("Recorded local regular DVC-tracked files matched disk digests; remote storage and upstream execution provenance remain unverified.")
        else:
            warnings.append("DVC checksum fields are recorded metadata. Declare local data as --input-file to measure its SHA-256; no remote data are fetched.")
    elif format == "pbs_json":
        value = strict_json(text)
        jobs = value.get("Jobs") if isinstance(value, dict) else None
        if not isinstance(jobs, dict) or not jobs:
            fail("invalid_source", "Expected PBS qstat JSON Jobs object")
        if not all(isinstance(row, dict) for row in jobs.values()):
            fail("invalid_source", "Invalid PBS job record")
        details = {"jobs": [{"job_id": job_id, **{k: row[k] for k in ("job_state", "Exit_status", "stime", "mtime") if k in row}} for job_id, row in jobs.items()]}
        warnings.append("Saved scheduler state is not live scheduler verification; omitted exit status remains unknown.")
    elif format == "junit":
        root = safe_xml(content)
        if root.tag not in ("testsuites", "testsuite"):
            fail("invalid_source", "Expected JUnit testsuite/testsuites")
        cases = list(root.iter("testcase"))
        if not cases:
            fail("invalid_source", "JUnit report contains no testcases")
        details = {"testcases": len(cases), "failures": sum(c.find("failure") is not None for c in cases),
                   "errors": sum(c.find("error") is not None for c in cases), "skipped": sum(c.find("skipped") is not None for c in cases)}
        inferred = "test_log"
        warnings.append("test_log denotes the artifact format, not test success or scientific validity; failures are retained.")
    elif format == "dataset_metadata":
        value = strict_json(text)
        if not isinstance(value, dict):
            fail("invalid_source", "Dataset metadata must be a JSON object")
        if value.get("synthetic") is True or value.get("data_origin") in ("synthetic", "simulated"):
            inferred = "synthetic"
        details = {key: value[key] for key in ("synthetic", "data_origin", "version", "sha256", "unit", "sample_size") if key in value}
        warnings.append("Metadata can restrict a source to synthetic; cohort labels cannot establish intervention, external validation or independent replication.")
    elif format == "statistics":
        parsed = parse_statistics(content, path, "preview")
        if text.lstrip().startswith("{"):
            metadata = strict_json(text)
            if metadata.get("synthetic") is True or metadata.get("data_origin") in ("synthetic", "simulated"):
                inferred = "synthetic"
        details = {"input_row_count": parsed["input_row_count"], "valid_effect_count": len(parsed["effect_records"]), "issues": parsed["issues"]}
        warnings.append("A statistical table does not establish the study design or real/synthetic data origin.")
    elif format == "xlsx":
        wb = list_xlsx_sheets(content)
        sheet_names = wb["sheet_names"]
        sheet_summaries = {
            name: {
                "columns": info["header"],
                "row_count": len(info["rows"]),
                "formula_cached_values": info["formula_cached_values"],
            }
            for name, info in wb["sheets"].items()
        }
        any_formulas = any(info["formula_cached_values"] for info in wb["sheets"].values())
        details = {
            "sheet_names": sheet_names,
            "sheet_count": len(sheet_names),
            "sheets": sheet_summaries,
            "any_formula_cached_values": any_formulas,
        }
        if any_formulas:
            warnings.append("XLSX workbook contains cached formula values; formulas are not evaluated and cached values may be stale.")
        warnings.append("Spreadsheet summaries do not establish the study design or real/synthetic data origin.")
    elif format == "parquet":
        details = inspect_parquet_metadata(content)
        warnings.append("Parquet FileMetaData summarizes schema and row counts from the footer; data pages are not decoded or audited.")
    kind = restrict_kind(inferred, requested_kind)
    return {"format": format, "path": path, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content),
            "kind": kind, "inferred_kind": inferred, "kind_basis": "artifact_structure_with_conservative_restrictions",
            "details": details, "warnings": warnings, "execution_attestation": "not_established_by_import"}
