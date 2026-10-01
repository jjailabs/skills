#!/usr/bin/env python3
# done-gate.py: Stop hook
# Blocks the stop when the newest define-done report in <cwd>/.done/<task>/reports/
# says status: DONE but the contract files don't check out (revision, file hash,
# active_sha256, and a matching approval must all agree). Every other stop passes.
#
# Reversibility:
#   CLAUDE_DONE_GATE=0  -> disable instantly, no settings edit
#   /plugin disable jjai@jjailabs -> permanent off
import hashlib
import json
import os
import re
import sys

if os.environ.get("CLAUDE_DONE_GATE") == "0":
    sys.exit(0)

KEY = re.compile(r"([A-Za-z_][\w.-]*)\s*:(?:\s+(.*))?$")
QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\']|\'\')*)\'')


def scalar(v):
    v = (v or "").strip()
    m = QUOTED.match(v)
    if m:
        return m.group(1) if m.group(1) is not None else m.group(2).replace("''", "'")
    v = re.split(r"(?:^|\s)#", v, maxsplit=1)[0].strip()
    return None if v in ("", "~", "null", "Null", "NULL") else v


# ponytail: minimal YAML reader, only what this gate reads: top-level `key: scalar`,
# plus `key:` followed by a block list of flat `- k: scalar` maps (approvals).
# Scalars stay text (no int/date coercion); flow {..}/[..] and block scalars (| >)
# stay raw text; anchors, tags, multi-doc unsupported. Upgrade = PyYAML safe_load.
def load_yaml(path):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, ValueError):
        return None
    doc, key, item, col, dash = {}, None, None, None, None
    for line in lines:
        body = line.lstrip(" ")
        if not body or body[0] == "#" or line in ("---", "..."):
            continue
        ind = len(line) - len(body)
        if ind == 0 and body[0] != "-":  # top-level key
            m = KEY.match(body)
            if not m:
                return None
            key, item, dash = m.group(1), None, None
            doc[key] = scalar(m.group(2))
        elif key and re.match(r"-(\s|$)", body) and dash in (None, ind):  # list item
            if doc[key] is None:
                doc[key] = []
            if not isinstance(doc[key], list):
                continue
            dash = ind
            rest = body[1:].lstrip(" ")
            col = len(line) - len(rest) if rest else None
            m = KEY.match(rest)
            item = {m.group(1): scalar(m.group(2))} if m else ({} if not rest else None)
            doc[key].append(scalar(rest) if item is None else item)
        elif isinstance(item, dict):  # more keys of the current list item
            col = ind if col is None else col
            m = KEY.match(body)
            if m and ind == col:
                item[m.group(1)] = scalar(m.group(2))
    return doc or None


def text(v):  # Ruby's nil.to_s / to_s
    return "" if v is None else v if isinstance(v, str) else str(v)


try:
    data = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
if not isinstance(data, dict):
    sys.exit(0)
if data.get("stop_hook_active") is not None and data.get("stop_hook_active") is not False:
    sys.exit(0)  # don't loop

done = os.path.join(data.get("cwd") or os.getcwd(), ".done")
if not os.path.isdir(done):
    sys.exit(0)

problems = []
for task in sorted(os.listdir(done)):
    d = os.path.join(done, task)
    reports = os.path.join(d, "reports")
    if not os.path.isdir(reports):
        continue
    files = [os.path.join(reports, f) for f in os.listdir(reports) if f.endswith((".yaml", ".yml"))]
    if not files:
        continue
    # ponytail: skill doesn't fix report names; mtime is the proxy. Upgrade = a timestamp field in the report once the skill defines one.
    newest = max(files, key=lambda f: os.stat(f).st_mtime_ns)
    report = load_yaml(newest)
    if not isinstance(report, dict) or report.get("status") is None:
        # reader can't see a status (e.g. flow style): fail closed if the text claims DONE
        try:
            with open(newest, encoding="utf-8", errors="replace") as f:
                claims_done = re.search(r"\bDONE\b", f.read())
        except OSError:
            claims_done = None
        if claims_done:
            problems.append(f"{task}: reports/{os.path.basename(newest)} mentions DONE but the gate cannot read its "
                            "status; rewrite it in block-style YAML, one `key: value` per line, as in the skill's "
                            "references/completion-report-template.yaml")
        continue
    if report.get("status") != "DONE":  # only DONE claims are gated
        continue

    active = load_yaml(os.path.join(d, "active.yaml"))
    if not isinstance(active, dict):
        problems.append(f"{task}: active.yaml missing or unparseable")
        continue
    rev = text(active.get("active_revision"))
    asha = text(active.get("active_sha256"))
    contract = os.path.join(d, f"contract.r{rev}.yaml")
    if os.path.isfile(contract):
        with open(contract, "rb") as f:
            fsha = hashlib.sha256(f.read()).hexdigest()
        if fsha != asha:
            problems.append(f"{task}: contract.r{rev}.yaml hashes to {fsha[:12]} but active_sha256 is {asha[:12]}")
        approvals = active.get("approvals")
        ok = any(
            isinstance(a, dict) and text(a.get("revision")) == rev and text(a.get("sha256")) == fsha
            and text(a.get("approved_by")).strip() and text(a.get("evidence")).strip()
            for a in (approvals if isinstance(approvals, list) else [])
        )
        if not ok:
            problems.append(f"{task}: no approval with approved_by + evidence for r{rev} at file hash {fsha[:12]}")
    else:
        problems.append(f"{task}: contract.r{rev}.yaml missing")
    rrev = text(report.get("contract_revision"))
    if rrev != rev:
        problems.append(f"{task}: report is for r{rrev} but r{rev} is active")
    rsha = text(report.get("contract_sha256_checked"))
    if rsha != asha:
        problems.append(f"{task}: report checked {rsha[:12]} but active_sha256 is {asha[:12]}")
if not problems:
    sys.exit(0)

reason = (f"DONE is not supported: {'; '.join(problems)}. Fix the cause, or write a new report in "
          ".done/<task>/reports/ with status NEEDS_REVIEW. Do not edit the contract or active.yaml to pass this gate.")
out = json.dumps({"decision": "block", "reason": reason}, separators=(",", ":"), ensure_ascii=False)
sys.stdout.buffer.write((out + "\n").encode("utf-8"))
