#!/usr/bin/env python3
# done-gate.py: Stop hook
# Blocks the stop when the newest define-done report in a .done/<task>/reports/ says
# status: DONE but the contract files don't check out (revision, file hash,
# active_sha256, and a matching approval must all agree). Also blocks when any report
# cannot be parsed or its status is not one plain recognized state, any report is dated
# in the future, or reading a .done fails, a report is not a regular file, or the check runs
# past 8 s (fail closed). Every other stop passes. It checks again on a stop that follows its own
# block (stop_hook_active); a newer non-DONE report ends the block. After 5 blocks in a row in one
# session, the next blocked stop halts the agent instead (continue: false), without accepting the claim.
# Checks every .done walking up from cwd, stopping at the git root; never checks a
# folder above $HOME, and checks $HOME itself only when it is cwd.
# Newest = latest assessment_timestamp (a report without one is dated by its file
# mtime), then latest mtime, then a DONE report, then file name.
#
# Reversibility:
#   DONE_GATE=0 (or CLAUDE_DONE_GATE=0)  -> disable instantly, no settings edit
#   disable the jjai plugin in Claude Code or Codex -> permanent off
import hashlib
import json
import os
import re
import signal
import stat
import sys
import tempfile
from datetime import datetime, timezone

if "0" in (os.environ.get("DONE_GATE"), os.environ.get("CLAUDE_DONE_GATE")):
    sys.exit(0)

# ponytail: strict allow-list reader, not a YAML parser (upgrade = PyYAML safe_load). After line breaks
# become \n, every line must fully match one of: blank, comment, `---` (once, before any content), `...`
# (then only blank or comment lines), `key: VALUE` (or `- key: VALUE` in a list), or `- VALUE`. Indent
# is spaces only; VALUE may be left out after `key:`; a ` #` comment may follow. Blocks must nest by
# indent and a key may appear once per mapping. Anything else, valid YAML or not, is unparseable (None):
# tabs, anchors, aliases, tags, merge or `?` keys, block scalars, flow collections, escapes, multi-line
# values, a BOM, a NOT_ALLOWED character, a SEMANTIC value that is not pure ASCII, a SCALAR key holding a
# mapping or list (block, [] or {}), or an assessment_timestamp that is not null and not a TIMESTAMP naming a real time.
# Returns the top-level keys; a list under a top-level key keeps its `- VALUE` items and one level of
# `- key: VALUE` maps. Deeper content is checked, not kept (None). Values stay text (no int/date coercion).
KEY = r"[A-Za-z_][A-Za-z0-9_]{0,127}"  # libyaml rejects a key over 1024 characters
VALUE = (r"'(?:[^']|'')*'|\"[^\"\\]*\"|\[\]|\{\}"  # 'it''s', "no backslash", [] and {} (kept raw)
         r"|[^-?:,\[\]{}#&*!|>'\"%@` ](?:[^ :]|:(?=[^ ])| +(?=[^ #]))*")  # plain: no `: `, ` #`, end `:`
LINE = re.compile(rf"( *)(?:(- )?({KEY}):(?: +({VALUE}))?|(- )({VALUE}))(?: +#.*)? *")
MARK = re.compile(r"(---|\.\.\.)(?: +#.*)? *")
# The one form Psych and fromisoformat (3.9 reads 0, 3 or 6 fraction digits) date the same way
TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
                       r"(?:\.[0-9]{3}(?:[0-9]{3})?)?(?:Z|[+-][0-9]{2}:[0-9]{2})")
# Not printable in YAML, a tab, DEL, a C1 control, or a space or line-break look-alike that Python and
# YAML (or YAML versions) treat differently: U+00A0, U+1680, U+2000-U+200B, U+2028, U+2029, U+202F,
# U+205F, U+3000, U+FEFF
NOT_ALLOWED = re.compile("[^\n -~\xa1-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]"
                         "|[\u1680\u2000-\u200b\u2028\u2029\u202f\u205f\u3000\ufeff]")
SEMANTIC = ("status", "assessment_timestamp", "contract_revision", "contract_sha256_checked", "active_revision",
            "active_sha256", "revision", "sha256", "base_revision", "base_sha256")  # must be pure ASCII
SCALAR = SEMANTIC + ("approved_by", "evidence")  # at the top level or in an approvals item: one-line values only
STATES = ("RUNNING", "DONE", "BLOCKED", "NEEDS_REVIEW", "STOPPED", "FAILED")  # SKILL.md section 6
SKEW = 300  # ponytail: 5 min is the clock-skew allowance before a timestamp counts as future
LIMIT = 5  # blocks in a row per session before the gate halts instead (Codex has no loop cap of its own)


def scalar(v):
    if v is None or v in ("~", "null", "Null", "NULL"):
        return None
    return v[1:-1].replace("''", "'") if v[0] == "'" else v[1:-1] if v[0] == '"' else v


# Raises OSError when the file cannot be read or is not a regular file.
def load_yaml(path):
    if not stat.S_ISREG(os.stat(path).st_mode):  # a FIFO or device can stall the read
        raise OSError(f"{path} is not a regular file")
    # text mode turns \r\n and a lone \r into \n, as YAML does. A BOM is not allowed, not even first:
    # Psych reads a string that starts with one as ending after its first line.
    with open(os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)), encoding="utf-8") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):  # replaced after the stat
            raise OSError(f"{path} is not a regular file")
        try:
            src = f.read()
        except ValueError:  # not UTF-8
            return None
    if NOT_ALLOWED.search(src):
        return None
    doc = {}
    stack = [(0, False, set(), doc)]  # open blocks: (column, is a list, keys seen, where to store or None)
    opened, started, ended = None, False, False  # opened: (mapping, key) of a `key:` line with no value

    def held(m):  # the top level or an approvals item: where the gate reads SCALAR keys
        return m is not None and (m is doc or any(m is a for a in doc.get("approvals") or []))

    for line in src.split("\n"):  # never splitlines(): it also splits on characters YAML keeps in a line
        if re.fullmatch(r" *(?:#.*)?", line):
            continue
        mark = MARK.fullmatch(line)
        if ended or (mark and mark[1] == "---" and started):
            return None
        started, ended = True, bool(mark) and mark[1] == "..."
        if mark:
            continue
        m = LINE.fullmatch(line)
        if not m:
            return None
        ind, dash, key, val = len(m[1]), bool(m[2] or m[5]), m[3], m[4] if m[3] else m[6]
        if opened and (ind > opened[0][0] or dash and ind == opened[0][0]):  # the empty key's value
            if opened[1] in SCALAR and held(opened[0][3]):
                return None  # a mapping or list where the gate reads one value: not left out as if empty
            into = [] if dash and opened[0][3] is doc else None  # only a top-level key's list is kept
            if into is not None:
                doc[opened[1]] = into
            stack.append((ind, dash, set(), into))
        opened = None
        while stack[-1][0] > ind:
            stack.pop()
        if stack[-1][1] and not dash and stack[-2][0] == ind:  # a list at its key's column ends
            stack.pop()
        col, is_list, keys, into = stack[-1]
        if col != ind or is_list != dash:
            return None
        if dash and key is None:  # `- VALUE`
            if into is not None:
                into.append(scalar(val))
            continue
        if dash:  # `- key: VALUE` starts a mapping at the key's column
            item = None if into is None else {}
            if item is not None:
                into.append(item)
            keys, into = set(), item
            stack.append((ind + 2, False, keys, into))
        if key in keys or key in SCALAR and val in ("[]", "{}") and held(into):  # [] or {}: also not one value
            return None
        keys.add(key)
        if into is not None:
            into[key] = scalar(val)
        if val is None:
            opened = (stack[-1], key)
    maps = [doc] + [a for a in doc.get("approvals") or [] if isinstance(a, dict)]
    if any(not str(m.get(k, "")).isascii() for m in maps for k in SEMANTIC):
        return None
    ts = doc.get("assessment_timestamp")
    if ts is not None and not (isinstance(ts, str) and TIMESTAMP.fullmatch(ts) and stamp(doc) is not None):
        return None
    return doc or None


def text(v):  # Ruby's nil.to_s / to_s
    return "" if v is None else v if isinstance(v, str) else str(v)


def stamp(report):  # assessment_timestamp as UTC epoch seconds (no zone = UTC), or None
    try:
        t = datetime.fromisoformat(re.sub(r"Z$", "+00:00", report.get("assessment_timestamp")))
        return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp()
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def state(report):  # status if it is exactly one of STATES (plain, or quoted without escapes), else None
    s = report.get("status") if isinstance(report, dict) else None
    return s if s in STATES else None


try:
    data = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
if not isinstance(data, dict):
    sys.exit(0)
# No stop_hook_active exit: a retried stop is checked again. Ways out: a newer non-DONE
# report, the human interrupting, DONE_GATE=0, or the halt after LIMIT blocks in a row.

here = os.path.realpath(data.get("cwd") or os.getcwd())
home = os.path.realpath(os.path.expanduser("~")) + os.sep


def above(p):  # p is $HOME or a folder above it
    return home.startswith(p.rstrip(os.sep) + os.sep)


dones, p = [], here
while True:  # every .done from cwd up to the .git dir; $HOME only when it is cwd, never above $HOME
    if (not above(p) or p + os.sep == home) and os.path.isdir(os.path.join(p, ".done")):
        dones.append(os.path.join(p, ".done"))
    up = os.path.dirname(p)
    if os.path.exists(os.path.join(p, ".git")) or up == p or above(up):
        break
    p = up


FALLBACK = (b'{"decision":"block","reason":"define-done gate: internal error while reporting a problem; '
            b'check .done/ or set DONE_GATE=0"}')


def tally():  # (folder fd, file name) whose file size counts this session's blocks in a row, or None
    sid = data.get("session_id")
    if not isinstance(sid, str) or not sid:
        return None
    uid = getattr(os, "getuid", lambda: None)()
    folder = os.path.join(tempfile.gettempdir(), f"define-done-gate-{uid}")
    os.makedirs(folder, 0o700, exist_ok=True)
    # ponytail: the folder is used only through this fd, never through a link or someone else's folder; with no
    # O_DIRECTORY (Windows) this raises, so there is no count and every stop blocks
    dfd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    st = os.fstat(dfd)
    if not stat.S_ISDIR(st.st_mode) or uid is not None and st.st_uid != uid:
        return None
    return dfd, hashlib.sha256(sid.encode("utf-8", "surrogatepass")).hexdigest()


def halt(reason):  # counts this block; after LIMIT in a row, the output that halts the agent instead
    try:  # no count (no session_id, or it cannot be stored): None, so every stop blocks
        count = tally()
        if not count:
            return None
        dfd, name = count
        # never follow a link or wait on a FIFO (SIGALRM is off here)
        fd = os.open(name, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                return None
            if st.st_size < LIMIT:
                os.write(fd, b".")
                return None
        finally:
            os.close(fd)
        os.remove(name, dir_fd=dfd)  # reset first: if that fails, this stays a block
        return {"continue": False, "stopReason": f"define-done gate stopped the agent after {LIMIT} blocked stops "
                f"in a row. The DONE claim is NOT accepted. Last block: {reason}"}
    except Exception:
        return None


def block(reason):  # a .done exists, so nothing from here on may let the stop through
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, signal.SIG_IGN)  # no timeout block in the middle of this one
    try:  # a non-UTF-8 file name is a lone surrogate here: escape it, and write pure ASCII
        reason = reason.encode("utf-8", "backslashreplace").decode("utf-8")
        out = json.dumps(halt(reason) or {"decision": "block", "reason": reason}, separators=(",", ":")).encode("ascii")
    except Exception:
        out = FALLBACK
    sys.stdout.buffer.write(out + b"\n")
    sys.stdout.buffer.flush()
    sys.exit(0)


def check(d, problems):  # one .done/<task> folder; appends what is wrong
    try:
        names = sorted(os.listdir(os.path.join(d, "reports")))
    except (FileNotFoundError, NotADirectoryError):  # no reports/ here; any other error blocks
        return
    rs, n = [], len(problems)
    for f in names:
        if not f.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(d, "reports", f)
        r, st = load_yaml(path), os.stat(path)
        ts = stamp(r)
        if state(r) is None:  # its real date and status are unknown, so it blocks wherever it would sort
            problems.append(f"report {path} cannot be parsed (or has an unrecognized status); rewrite it in "
                            f"block-style YAML (one-line strings, no repeated keys), assessment_timestamp like "
                            f"2026-10-01T06:30:00Z, and status one of: {', '.join(STATES)}")
        if (st.st_mtime if ts is None else ts) > now + SKEW:  # no timestamp: its file time is its date
            problems.append(f"report {path} has a future assessment_timestamp; fix it" if ts is not None else
                            f"report {path} has no assessment_timestamp and its file time is in the future; fix it")
        rs.append(((st.st_mtime if ts is None else ts, st.st_mtime_ns, state(r) == "DONE", f), path, r))
    if not rs or len(problems) > n:
        return
    _, newest, report = max(rs)
    if state(report) != "DONE":  # only DONE claims are gated
        return

    try:
        active = load_yaml(os.path.join(d, "active.yaml"))
    except FileNotFoundError:
        active = None
    if not isinstance(active, dict):
        problems.append(f"{d}: active.yaml missing or unparseable")
        return
    rev = text(active.get("active_revision"))
    asha = text(active.get("active_sha256"))
    contract = os.path.join(d, f"contract.r{rev}.yaml")
    if os.path.isfile(contract):
        with open(contract, "rb") as f:
            fsha = hashlib.sha256(f.read()).hexdigest()
        if fsha != asha:
            problems.append(f"{d}: contract.r{rev}.yaml hashes to {fsha[:12]} but active_sha256 is {asha[:12]}")
        approvals = active.get("approvals")
        ok = any(
            isinstance(a, dict) and text(a.get("revision")) == rev and text(a.get("sha256")) == fsha
            and text(a.get("approved_by")).strip() and text(a.get("evidence")).strip()
            for a in (approvals if isinstance(approvals, list) else [])
        )
        if not ok:
            problems.append(f"{d}: no approval with approved_by + evidence for r{rev} at file hash {fsha[:12]}")
    else:
        problems.append(f"{d}: contract.r{rev}.yaml missing")
    rrev = text(report.get("contract_revision"))
    if rrev != rev:
        problems.append(f"{d}: report is for r{rrev} but r{rev} is active")
    rsha = text(report.get("contract_sha256_checked"))
    if rsha != asha:
        problems.append(f"{d}: report checked {rsha[:12]} but active_sha256 is {asha[:12]}")


def expire(signum, frame):  # blocks from wherever the check is, even an except clause or the final report
    block(f"define-done gate timed out after 8 s in {where}. Fix the files or set DONE_GATE=0 to bypass.")


now = datetime.now(timezone.utc).timestamp()
problems, where = [], None
if hasattr(signal, "SIGALRM"):  # ponytail: Windows has no SIGALRM; there the S_ISREG check is the guard
    signal.signal(signal.SIGALRM, expire)
    signal.alarm(8)  # under the 10 s timeout in hooks.json
try:  # a .done exists, so an error blocks instead of letting the stop through
    for done in dones:
        where = done
        for t in sorted(os.listdir(done)):
            where = os.path.join(done, t)
            check(where, problems)
except Exception as e:
    block(f"define-done gate error in {where}: {type(e).__name__}: {e}. "
          "Fix the files or set DONE_GATE=0 to bypass.")
if problems:
    block(f"define-done gate: {'; '.join(problems)}. Fix the cause. If you cannot support the DONE claim, do not "
          "retry the stop: write a new report in that task's reports/ folder with the current UTC "
          "assessment_timestamp and status NEEDS_REVIEW (or BLOCKED, STOPPED, or FAILED) that explains the mismatch. "
          "That newer report replaces the DONE claim and ends the block. "
          "Do not edit the contract or active.yaml to pass this gate.")
try:  # the stop passes: a later block starts a new count
    dfd, name = tally()
    os.remove(name, dir_fd=dfd)
except Exception:  # no count to reset (no session_id, no store, or Windows)
    pass
