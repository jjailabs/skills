#!/usr/bin/env python3
# Feeds Stop-hook inputs to hooks/done-gate.py and checks the result.
# Each case runs in a temp copy of fixtures/ with its own .git, so nothing above leaks in.
# If `ruby` is on PATH, also runs the original Ruby hook (fixtures/done-gate.rb):
# identical stdout + exit code on the passing cases it shares, same decision on BAD and FLOW.
# Run: python3 tests/test_done_gate.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
PY_HOOK = os.path.join(HERE, "..", "hooks", "done-gate.py")
RB_HOOK = os.path.join(FIX, "done-gate.rb")
TMP = tempfile.TemporaryDirectory()  # removed at exit


def run(cmd, payload, env_extra, lock=None):  # lock: a path set to chmod 000 for this run only
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_DONE_GATE"}
    env.update(env_extra)
    if lock:
        mode = os.stat(lock).st_mode
        os.chmod(lock, 0)
    try:  # timeout: a hook that hangs (e.g. on a FIFO) fails the case instead of the run
        p = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=5)
    finally:
        if lock:
            os.chmod(lock, mode)
    assert PY_HOOK not in cmd or p.stderr == "", p.stderr
    return p.stdout, p.returncode


def project(name, fixture=None):  # temp dir with .git, plus a copy of fixtures/<fixture>/.done
    p = os.path.join(TMP.name, name)
    os.makedirs(os.path.join(p, ".git"))
    if fixture:
        shutil.copytree(os.path.join(FIX, fixture, ".done"), os.path.join(p, ".done"))
    return p


def report(path, text=None, mtime=None, old="r1.yaml"):  # rename/rewrite a report in place
    if old:
        os.rename(os.path.join(os.path.dirname(path), old), path)
    if text is not None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    if mtime:
        os.utime(path, (mtime, mtime))


def review(ts):
    return f'contract_id: t1\ncontract_revision: 1\nassessment_timestamp: "{ts}"\nstatus: NEEDS_REVIEW\n'


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def no_stamp(path):  # report text without its assessment_timestamp line (v0.7 style)
    return "".join(l for l in read(path).splitlines(True) if not l.startswith("assessment_timestamp:"))


T0, T1, FUTURE = "2026-10-01T00:00:00Z", "2026-10-01T01:00:00Z", "9999-01-01T00:00:00Z"
OLD_MTIME, NEW_MTIME, FUTURE_MTIME = 1_000_000_000, 1_790_820_000, 4_070_908_800  # 2001, T1 + 1 h, 2099
BAD_REASON = "t1: contract.r1.yaml hashes to 2fea2d712328 but active_sha256 is 2d711642b726"
STATUS_REASON = "cannot be parsed (or has an unrecognized status)"
FUTURE_REASON = "has a future assessment_timestamp; fix it"
ERROR_REASON = "define-done gate error in "

bad, good, flow, none = project("bad", "bad"), project("good", "good"), project("flow", "flow"), project("none")
subdir = os.path.join(bad, "src", "deep")
os.makedirs(subdir)

repo = project(os.path.join("outer", "repo"))  # .done sits one level above the git root
shutil.copytree(os.path.join(FIX, "bad", ".done"), os.path.join(TMP.name, "outer", ".done"))
os.makedirs(os.path.join(repo, "sub"))

# Fake HOME with a bad .done and no .git below it: ignored from a subfolder, checked when cwd is HOME.
home = os.path.join(TMP.name, "home")
shutil.copytree(os.path.join(FIX, "bad", ".done"), os.path.join(home, ".done"))
os.makedirs(os.path.join(home, "work", "sub"))

# Old bad DONE report: newest mtime and last file name, but the older timestamp. Newer NEEDS_REVIEW wins.
review_wins = project("review_wins", "bad")
r = os.path.join(review_wins, ".done", "t1", "reports")
report(os.path.join(r, "z-old-done.yaml"), mtime=NEW_MTIME)
report(os.path.join(r, "a-new-review.yaml"), review(T1), OLD_MTIME, old=None)

# Reverse: the newer timestamp is the bad DONE report, so it is checked and blocks.
done_wins = project("done_wins", "bad")
r = os.path.join(done_wins, ".done", "t1", "reports")
report(os.path.join(r, "a-new-done.yaml"), read(os.path.join(r, "r1.yaml")).replace(T0, T1), OLD_MTIME)
report(os.path.join(r, "z-old-review.yaml"), review(T0), NEW_MTIME, old=None)

# Bad DONE report with no timestamp, written after a timestamped NEEDS_REVIEW: dated by mtime, so it is checked.
untimestamped = project("untimestamped", "bad")
r = os.path.join(untimestamped, ".done", "t1", "reports")
report(os.path.join(r, "b.yaml"), no_stamp(os.path.join(r, "r1.yaml")), NEW_MTIME)
report(os.path.join(r, "a.yaml"), review(T1), OLD_MTIME, old=None)  # b.yaml mtime is after T1

# Old (v0.7) bad DONE report with no timestamp and an old mtime: the newer timestamped NEEDS_REVIEW wins.
legacy = project("legacy", "bad")
r = os.path.join(legacy, ".done", "t1", "reports")
report(os.path.join(r, "z-legacy-done.yaml"), no_stamp(os.path.join(r, "r1.yaml")), OLD_MTIME)
report(os.path.join(r, "a-new-review.yaml"), review(T1), OLD_MTIME, old=None)

# The newest report has a newer NEEDS_REVIEW (stop_hook_active must not hide that it resolves the block).
resolved = project("resolved", "bad")
r = os.path.join(resolved, ".done", "t1", "reports")
report(os.path.join(r, "r2.yaml"), review(T1), old=None)

# The bad DONE report with its status written in forms the reader must not take as a plain state.
odd = {}
for name, line in [("folded", "status: >-\n  DONE"), ("escaped", 'status: "DON\\u0045"'),
                   ("tagged", "status: !!str DONE"), ("unknown", "status: COMPLETE"),
                   ("quoted_review", 'status: "NEEDS_REVIEW"'), ("quote_then_text", 'status: "NEEDS_REVIEW" DONE'),
                   ("continued", "status: NEEDS_REVIEW\n  DONE"), ("next_line", "status:\n  DONE"),
                   ("list", "status:\n  - DONE")]:
    odd[name] = project("status_" + name, "bad")
    r1 = os.path.join(odd[name], ".done", "t1", "reports", "r1.yaml")
    report(r1, read(r1).replace("status: DONE", line), old=None)
odd["flow_escaped"] = project("status_flow_escaped", "bad")
report(os.path.join(odd["flow_escaped"], ".done", "t1", "reports", "r1.yaml"),
       '{"contract_id": "t1", "contract_revision": 1, "assessment_timestamp": "2026-10-01T00:00:00Z", '
       '"status": "\\u0044ONE"}\n', old=None)

# A NEEDS_REVIEW dated far in the future would hide the bad DONE report forever.
future_review = project("future_review", "bad")
report(os.path.join(future_review, ".done", "t1", "reports", "r2.yaml"), review(FUTURE), old=None)

# A supported DONE report dated in the future (good contract, so only the date can block).
future_done = project("future_done", "good")
r1 = os.path.join(future_done, ".done", "t1", "reports", "r1.yaml")
report(r1, read(r1).replace(T0, FUTURE), old=None)

# A NEEDS_REVIEW with no timestamp and a file time in 2099 would hide the bad DONE report forever.
future_mtime = project("future_mtime", "bad")
report(os.path.join(future_mtime, ".done", "t1", "reports", "r2.yaml"),
       "contract_id: t1\ncontract_revision: 1\nstatus: NEEDS_REVIEW\n", FUTURE_MTIME, old=None)

# A dangling symlink among the reports (good contract, so only the read error can block).
broken = project("broken", "good")
os.symlink(os.path.join(broken, "nowhere.yaml"), os.path.join(broken, ".done", "t1", "reports", "zz.yaml"))

# Same assessment_timestamp: the later write (mtime) is the newest, whatever the file names say.
tie_done = project("tie_done", "bad")
r = os.path.join(tie_done, ".done", "t1", "reports")
report(os.path.join(r, "a-new.yaml"), mtime=NEW_MTIME)
report(os.path.join(r, "z-old.yaml"), review(T0), OLD_MTIME, old=None)

tie_review = project("tie_review", "bad")
r = os.path.join(tie_review, ".done", "t1", "reports")
report(os.path.join(r, "z-old.yaml"), mtime=OLD_MTIME)
report(os.path.join(r, "a-new.yaml"), review(T0), NEW_MTIME, old=None)

# Same timestamp and same mtime: the DONE report is the one checked.
tie_exact = project("tie_exact", "bad")
r = os.path.join(tie_exact, ".done", "t1", "reports")
report(os.path.join(r, "a.yaml"))
report(os.path.join(r, "z.yaml"), review(T0), old=None)
for f in ("a.yaml", "z.yaml"):
    os.utime(os.path.join(r, f), ns=(OLD_MTIME * 10**9, OLD_MTIME * 10**9))

# An empty .done in the subfolder must not hide the bad one at the project root.
nested = project("nested", "bad")
os.makedirs(os.path.join(nested, "src", ".done"))

# cwd above HOME: its .done is never read, even though cwd is where the walk starts.
above = os.path.join(TMP.name, "above")
shutil.copytree(os.path.join(FIX, "bad", ".done"), os.path.join(above, ".done"))
os.makedirs(os.path.join(above, "user"))

# A quoted string running onto the next line hides a second status (Codex's payload). Real YAML: status DONE.
multiline = project("multiline", "bad")
r1 = os.path.join(multiline, ".done", "t1", "reports", "r1.yaml")
report(r1, read(r1) + 'summary: "text\nstatus: NEEDS_REVIEW #"\n', old=None)

# The same disguised DONE, with the newer real timestamp (T1) but an old file time, next to a valid
# NEEDS_REVIEW (T0). The reader cannot know its real date, so it must block even though it sorts as older.
old_disguise = project("old_disguise", "bad")
r = os.path.join(old_disguise, ".done", "t1", "reports")
report(os.path.join(r, "r1.yaml"), read(os.path.join(r, "r1.yaml")).replace(T0, T1) +
       'summary: "text\nstatus: NEEDS_REVIEW #"\n', OLD_MTIME, old=None)
report(os.path.join(r, "z-review.yaml"), review(T0), OLD_MTIME, old=None)

duplicate = project("duplicate", "bad")
r1 = os.path.join(duplicate, ".done", "t1", "reports", "r1.yaml")
report(r1, read(r1) + "status: NEEDS_REVIEW\n", old=None)

# A bad DONE report with no timestamp and a new file time, where a line the reader would take as an old
# assessment_timestamp is really inside a string, a [..], or a second document. Real YAML: no timestamp.
hidden = {}
for name, tail in [("quoted", "criteria_results:\n  - criterion_id: C1\n    evidence_refs:\n      - 'x\n"
                               "assessment_timestamp: 2001-01-01T00:00:00Z #'\n"),
                   ("flow", "summary: [a,\nassessment_timestamp: 2001-01-01T00:00:00Z # x\n  ]\n"),
                   ("document", "---\nassessment_timestamp: 2001-01-01T00:00:00Z\n")]:
    hidden[name] = project("hidden_" + name, "bad")
    r = os.path.join(hidden[name], ".done", "t1", "reports")
    report(os.path.join(r, "b.yaml"), no_stamp(os.path.join(r, "r1.yaml")) + tail, NEW_MTIME)
    report(os.path.join(r, "a.yaml"), review(T0), OLD_MTIME, old=None)

# Codex's payload: the `]` is in a comment, so the flow runs on and the timestamp line is inside it.
# Real YAML: no timestamp, so the DONE report is dated by its new file time and is the newest.
bracket_comment = project("bracket_comment", "bad")
r = os.path.join(bracket_comment, ".done", "t1", "reports")
report(os.path.join(r, "b.yaml"), "status: DONE\nsummary: [ok, # ]\nassessment_timestamp: 2001-01-01T00:00:00Z\n  ]\n",
       NEW_MTIME)
report(os.path.join(r, "a.yaml"), review("2026-01-01T00:00:00Z"), OLD_MTIME, old=None)

# The good report with one line changed: flow values (only an empty [] or {} is allowed), document markers,
# and YAML outside the reader's allow-list (a BOM, tab indents, anchors and aliases, merge and `?` keys, tags).
edited = {}
for name, old, new in [("empty_flow_comment", "limitations: []", "limitations: [] # unmatched ["),
                       ("nonempty_flow", "limitations: []", "limitations: [a, b]"),
                       ("quote_in_flow", "summary: Replied ok.", 'summary: ["x, ]'),
                       ("leading_doc_start", "# Synthetic", "---\n# Synthetic"),
                       ("leading_bom", "# Synthetic", "\ufeff# Synthetic"),  # Psych misreads text after a BOM
                       ("tab_indent", "    verdict: PASS", "\t\t\t\tverdict: PASS"),
                       ("anchor_alias", '    observed_result: "reply was ok"',
                        "    observed_result: &a ok\n    verifier: *a"),
                       ("merge_key", "limitations: []", "limitations: &a {}\n<<: *a"),
                       ("complex_key", "status: DONE", "? status\n: DONE"),
                       ("tagged_value", "summary: Replied ok.", "summary: !!str Replied ok."),
                       ("single_quote_escape", "summary: Replied ok.", "summary: 'It''s ok.'")]:
    edited[name] = project("edited_" + name, "good")
    r1 = os.path.join(edited[name], ".done", "t1", "reports", "r1.yaml")
    report(r1, read(r1).replace(old, new, 1), old=None)
legacy_end = project("legacy_end", "good")  # v0.7 style (no timestamp), ending with `...`
r1 = os.path.join(legacy_end, ".done", "t1", "reports", "r1.yaml")
report(r1, no_stamp(r1) + "...\n# end of report\n\n", old=None)

# A newer NEEDS_REVIEW whose status sits after `...` or a second `---`. Real YAML: the first document has
# no status, so it does not replace the bad DONE report.
after_end = {}
for name, text in [("content_after_end", review(T1).replace("status:", "...\nstatus:")),
                   ("second_start", "---\n---\n" + review(T1))]:
    after_end[name] = project(name, "bad")
    report(os.path.join(after_end[name], ".done", "t1", "reports", "r2.yaml"), text, old=None)

# Read errors (chmod 000 while the case runs): a task folder that cannot be searched, and an unreadable
# DONE report whose real timestamp (T1) is newer than the NEEDS_REVIEW (T0) next to it.
unsearchable = project("unsearchable", "bad")
unreadable = project("unreadable", "bad")
r = os.path.join(unreadable, ".done", "t1", "reports")
report(os.path.join(r, "r1.yaml"), read(os.path.join(r, "r1.yaml")).replace(T0, T1), OLD_MTIME, old=None)
report(os.path.join(r, "z-review.yaml"), review(T0), OLD_MTIME, old=None)
LOCKED = {"UNSEARCHABLE_TASK_DIR": os.path.join(unsearchable, ".done", "t1"),
          "UNREADABLE_REPORT": os.path.join(r, "r1.yaml")}

# An older named pipe among the reports: opening it would wait for a writer forever.
fifo = project("fifo", "bad")
if hasattr(os, "mkfifo"):
    os.mkfifo(os.path.join(fifo, ".done", "t1", "reports", "old.yaml"))
    os.utime(os.path.join(fifo, ".done", "t1", "reports", "old.yaml"), (OLD_MTIME, OLD_MTIME))

# The bad DONE report (new file time) with its timestamp continued on an indented line, next to an older
# NEEDS_REVIEW. Real YAML: the timestamp is one invalid string, so the DONE report is dated by its file time.
cont_ts = project("cont_timestamp", "bad")
r = os.path.join(cont_ts, ".done", "t1", "reports")
report(os.path.join(r, "r1.yaml"), read(os.path.join(r, "r1.yaml")).replace(
    f'assessment_timestamp: "{T0}"', "assessment_timestamp: 2001-01-01T00:00:00Z\n  not-a-timestamp"), old=None)
report(os.path.join(r, "a-review.yaml"), review("2002-01-01T00:00:00Z"), OLD_MTIME, old=None)

# A newer-mtime NEEDS_REVIEW whose timestamp sits on the line after its key. Real YAML: dated 2001, older
# than the bad DONE report (T0), so the DONE report is the newest. The reader must not date it by file time.
next_ts = project("next_line_timestamp", "bad")
report(os.path.join(next_ts, ".done", "t1", "reports", "r2.yaml"), review(T1).replace(
    f'assessment_timestamp: "{T1}"', "assessment_timestamp:\n  2001-01-01T00:00:00Z"), NEW_MTIME, old=None)

# Good contract: an approval's evidence continued on an indented line (unparseable), and the same approvals
# written with `- ` at column 0 (PyYAML's default style), whose sibling keys sit at the column after `- `.
cont_approval = project("cont_approval", "good")
a = os.path.join(cont_approval, ".done", "t1", "active.yaml")
report(a, read(a).replace('    evidence: "fixture: synthetic approval for the gate test"',
                          "    evidence: x\n      more"), old=None)
siblings = project("list_item_siblings", "good")
a = os.path.join(siblings, ".done", "t1", "active.yaml")
report(a, read(a).replace("\n  ", "\n"), old=None)
# A newer NEEDS_REVIEW next to the older bad DONE report, its timestamp not in the one strict form (Psych and
# fromisoformat can date other forms differently): unparseable, so it blocks. A null timestamp (v0.7 template) is fine.
loose = {}
for name, ts in [("loose", "2026-10-1T1:00:00Z"), ("date_only", "2026-10-02")]:
    loose[name] = project(name + "_timestamp", "bad")
    report(os.path.join(loose[name], ".done", "t1", "reports", "r2.yaml"), review(T1).replace(f'"{T1}"', ts), old=None)
null_ts = project("null_timestamp", "good")
r1 = os.path.join(null_ts, ".done", "t1", "reports", "r1.yaml")
report(r1, read(r1).replace(f"assessment_timestamp: {T0}", "assessment_timestamp: null"), old=None)
nested_map = project("nested_map", "good")  # a key with no value, then nested keys: a mapping, so it parses
r1 = os.path.join(nested_map, ".done", "t1", "reports", "r1.yaml")
report(r1, read(r1).replace("verified_environment: local", "verified_environment:\n  host: local"), old=None)

# Codex's payload: a DONE report (file time 2026-01-02, no active.yaml) next to a NEEDS_REVIEW dated 2026-01-01,
# with a Unicode look-alike. Real YAML keeps it in the scalar, so the DONE report is the newest; Python's
# whitespace rules would read an old timestamp or a second status.
lookalike = {}
for name, text in [("nbsp", "status: DONE\nassessment_timestamp: 2001-01-01T00:00:00Z #junk\n"),
                   ("line_sep", "status: DONE\nsummary: x status: NEEDS_REVIEW\n"),
                   ("line_sep_ts", "status: DONE\nsummary: x assessment_timestamp: 2001-01-01T00:00:00Z\n"),
                   ("fullwidth", "status: DONE\nassessment_timestamp: ２００１-01-01T00:00:00Z\n")]:
    lookalike[name] = project("lookalike_" + name)
    r = os.path.join(lookalike[name], ".done", "t1", "reports")
    os.makedirs(r)
    report(os.path.join(r, "b.yaml"), text, 1_767_312_000, old=None)
    report(os.path.join(r, "a.yaml"), review("2026-01-01T00:00:00Z"), OLD_MTIME, old=None)
unicode_ok = project("unicode_evidence", "good")  # non-ASCII letters in free text are fine
r1 = os.path.join(unicode_ok, ".done", "t1", "reports", "r1.yaml")
report(r1, read(r1).replace("- transcript", "- café — transcript"), old=None)
a = os.path.join(unicode_ok, ".done", "t1", "active.yaml")
report(a, read(a).replace('"fixture: synthetic', '"café — synthetic'), old=None)

# Codex's payload: a DONE report whose assessment_timestamp holds a mapping (file time 2001, no active.yaml), next to
# a NEEDS_REVIEW dated 2026-01-01. Read as "no timestamp", the DONE report would be dated 2001 and hidden behind it.
mapping_ts = project("mapping_timestamp")
r = os.path.join(mapping_ts, ".done", "t1", "reports")
os.makedirs(r)
report(os.path.join(r, "b.yaml"), "status: DONE\nassessment_timestamp:\n  invalid: x\n", OLD_MTIME, old=None)
report(os.path.join(r, "a.yaml"), review("2026-01-01T00:00:00Z"), old=None)
mapping_evidence = project("mapping_evidence", "good")  # an approval's evidence holding a mapping
a = os.path.join(mapping_evidence, ".done", "t1", "active.yaml")
report(a, read(a).replace('    evidence: "fixture: synthetic approval for the gate test"',
                          "    evidence:\n      source: chat"), old=None)

# Codex's payload: an older report whose file name is not UTF-8 (status COMPLETE), next to the unsupported DONE
# report. The name goes into the block reason; a crash while writing it would let the stop through.
non_utf8, refused = project("non_utf8", "bad"), None
try:
    report(os.fsencode(os.path.join(non_utf8, ".done", "t1", "reports")) + b"/bad\xff.yaml", "status: COMPLETE\n",
           OLD_MTIME, old=None)
except OSError as e:  # APFS (macOS) refuses a name that is not UTF-8
    refused = e.strerror
# The bad project with json.dumps broken inside the hook (run in-process): the fixed fallback block is written.
BROKEN_DUMPS = ("import json, runpy, sys; json.dumps = lambda *a, **k: 1 / 0; "
                "runpy.run_path(sys.argv[1], run_name='__main__')")
CMD = {"OUTPUT_FAILURE_FALLBACK": [sys.executable, "-c", BROKEN_DUMPS, PY_HOOK]}

cases = [  # name, payload, extra env, expected text in block reason (None = stop passes)
    ("BAD", {"cwd": bad}, {}, BAD_REASON),
    ("GOOD", {"cwd": good}, {}, None),
    ("NONE", {"cwd": none}, {}, None),
    ("KILL_SWITCH", {"cwd": bad}, {"CLAUDE_DONE_GATE": "0"}, None),
    ("STOP_HOOK_ACTIVE", {"cwd": bad, "stop_hook_active": True}, {}, BAD_REASON),
    ("STOP_HOOK_ACTIVE_RESOLVED", {"cwd": resolved, "stop_hook_active": True}, {}, None),
    ("FLOW", {"cwd": flow}, {}, "rewrite it in block-style YAML"),
    ("SUBDIR", {"cwd": subdir}, {}, BAD_REASON),
    ("GIT_BOUNDARY", {"cwd": os.path.join(repo, "sub")}, {}, None),
    ("TIMESTAMP_ORDER_REVIEW_WINS", {"cwd": review_wins}, {}, None),
    ("TIMESTAMP_ORDER_DONE_WINS", {"cwd": done_wins}, {}, BAD_REASON),
    ("HOME_BOUNDARY", {"cwd": os.path.join(home, "work", "sub")}, {"HOME": home}, None),
    ("HOME_IS_CWD", {"cwd": home}, {"HOME": home}, BAD_REASON),
    ("UNTIMESTAMPED_DONE_CHECKED", {"cwd": untimestamped}, {}, BAD_REASON),
    ("LEGACY_OK", {"cwd": legacy}, {}, None),
    ("FOLDED_STATUS", {"cwd": odd["folded"]}, {}, STATUS_REASON),
    ("ESCAPED_STATUS", {"cwd": odd["escaped"]}, {}, STATUS_REASON),
    ("FLOW_ESCAPED", {"cwd": odd["flow_escaped"]}, {}, STATUS_REASON),
    ("TAGGED_STATUS", {"cwd": odd["tagged"]}, {}, STATUS_REASON),
    ("UNKNOWN_STATUS", {"cwd": odd["unknown"]}, {}, STATUS_REASON),
    ("QUOTED_STATUS_OK", {"cwd": odd["quoted_review"]}, {}, None),
    ("QUOTE_THEN_TEXT", {"cwd": odd["quote_then_text"]}, {}, STATUS_REASON),
    ("FUTURE_TS_REVIEW_HIDES_DONE", {"cwd": future_review}, {}, FUTURE_REASON),
    ("FUTURE_TS_DONE", {"cwd": future_done}, {}, FUTURE_REASON),
    ("FUTURE_MTIME_UNTIMESTAMPED", {"cwd": future_mtime}, {}, "file time is in the future; fix it"),
    ("BROKEN_SYMLINK_REPORT", {"cwd": broken}, {}, ERROR_REASON),
    ("TIE_LATER_DONE_WINS", {"cwd": tie_done}, {}, BAD_REASON),
    ("TIE_LATER_REVIEW_WINS", {"cwd": tie_review}, {}, None),
    ("TIE_EXACT_DONE_CHECKED", {"cwd": tie_exact}, {}, BAD_REASON),
    ("EMPTY_NESTED_DONE", {"cwd": os.path.join(nested, "src")}, {}, BAD_REASON),
    ("CWD_ABOVE_HOME", {"cwd": above}, {"HOME": os.path.join(above, "user")}, None),
    ("MULTILINE_QUOTED_DISGUISE", {"cwd": multiline}, {}, STATUS_REASON),
    ("OLD_MTIME_DISGUISED_DONE", {"cwd": old_disguise}, {}, STATUS_REASON),
    ("DUPLICATE_STATUS_KEY", {"cwd": duplicate}, {}, STATUS_REASON),
    ("HIDDEN_TIMESTAMP_QUOTED", {"cwd": hidden["quoted"]}, {}, STATUS_REASON),
    ("HIDDEN_TIMESTAMP_FLOW", {"cwd": hidden["flow"]}, {}, STATUS_REASON),
    ("HIDDEN_TIMESTAMP_DOCUMENT", {"cwd": hidden["document"]}, {}, STATUS_REASON),
    ("BRACKET_COMMENT_HIDDEN_TS", {"cwd": bracket_comment}, {}, STATUS_REASON),
    ("EMPTY_FLOW_WITH_COMMENT", {"cwd": edited["empty_flow_comment"]}, {}, None),
    ("NONEMPTY_FLOW_VALUE", {"cwd": edited["nonempty_flow"]}, {}, STATUS_REASON),
    ("QUOTE_IN_BALANCED_FLOW", {"cwd": edited["quote_in_flow"]}, {}, STATUS_REASON),
    ("LEGACY_DOC_END_MARKER", {"cwd": legacy_end}, {}, None),
    ("LEADING_DOC_START", {"cwd": edited["leading_doc_start"]}, {}, None),
    ("LEADING_BOM", {"cwd": edited["leading_bom"]}, {}, STATUS_REASON),
    ("TAB_INDENT", {"cwd": edited["tab_indent"]}, {}, STATUS_REASON),
    ("ANCHOR_ALIAS", {"cwd": edited["anchor_alias"]}, {}, STATUS_REASON),
    ("MERGE_KEY", {"cwd": edited["merge_key"]}, {}, STATUS_REASON),
    ("COMPLEX_KEY", {"cwd": edited["complex_key"]}, {}, STATUS_REASON),
    ("TAGGED_VALUE", {"cwd": edited["tagged_value"]}, {}, STATUS_REASON),
    ("SINGLE_QUOTE_ESCAPE_OK", {"cwd": edited["single_quote_escape"]}, {}, None),
    ("CONTENT_AFTER_DOC_END", {"cwd": after_end["content_after_end"]}, {}, STATUS_REASON),
    ("SECOND_DOC_START", {"cwd": after_end["second_start"]}, {}, STATUS_REASON),
    ("CONT_TIMESTAMP", {"cwd": cont_ts}, {}, STATUS_REASON),
    ("CONT_STATUS", {"cwd": odd["continued"]}, {}, STATUS_REASON),
    ("CONT_NESTED_APPROVAL", {"cwd": cont_approval}, {}, "active.yaml missing or unparseable"),
    ("LIST_ITEM_SIBLINGS_OK", {"cwd": siblings}, {}, None),
    ("NEXT_LINE_TIMESTAMP", {"cwd": next_ts}, {}, STATUS_REASON),
    ("NEXT_LINE_STATUS", {"cwd": odd["next_line"]}, {}, STATUS_REASON),
    ("LOOSE_TIMESTAMP", {"cwd": loose["loose"]}, {}, STATUS_REASON),
    ("DATE_ONLY_TIMESTAMP", {"cwd": loose["date_only"]}, {}, STATUS_REASON),
    ("NULL_TIMESTAMP_LEGACY_OK", {"cwd": null_ts}, {}, None),
    ("NESTED_MAP_OK", {"cwd": nested_map}, {}, None),
    ("NBSP_COMMENT_TIMESTAMP", {"cwd": lookalike["nbsp"]}, {}, STATUS_REASON),
    ("LINE_SEPARATOR_FAKE_KEY", {"cwd": lookalike["line_sep"]}, {}, STATUS_REASON),
    ("LINE_SEPARATOR_HIDDEN_TS", {"cwd": lookalike["line_sep_ts"]}, {}, STATUS_REASON),
    ("FULLWIDTH_DIGIT_TIMESTAMP", {"cwd": lookalike["fullwidth"]}, {}, STATUS_REASON),
    ("UNICODE_EVIDENCE_OK", {"cwd": unicode_ok}, {}, None),
    ("MAPPING_TIMESTAMP", {"cwd": mapping_ts}, {}, STATUS_REASON),
    ("LIST_STATUS", {"cwd": odd["list"]}, {}, STATUS_REASON),
    ("MAPPING_APPROVAL_EVIDENCE", {"cwd": mapping_evidence}, {}, "active.yaml missing or unparseable"),
    ("OUTPUT_FAILURE_FALLBACK", {"cwd": bad}, {}, "internal error while reporting a problem"),
]
if getattr(os, "geteuid", lambda: 0)() == 0:
    print("note: UNSEARCHABLE_TASK_DIR and UNREADABLE_REPORT skipped: root (or no geteuid) ignores chmod 000")
else:
    cases += [("UNSEARCHABLE_TASK_DIR", {"cwd": unsearchable}, {}, ERROR_REASON),
              ("UNREADABLE_REPORT", {"cwd": unreadable}, {}, ERROR_REASON)]
if hasattr(os, "mkfifo"):
    cases.append(("FIFO_REPORT", {"cwd": fifo}, {}, "is not a regular file"))
else:
    print("note: FIFO_REPORT skipped: os.mkfifo is not available")
if refused:
    print(f"note: NON_UTF8_FILENAME skipped: the file system refuses the name ({refused})")
else:
    cases.append(("NON_UTF8_FILENAME", {"cwd": non_utf8}, {}, "bad\\udcff.yaml cannot be parsed"))
PARITY = {"GOOD", "NONE", "KILL_SWITCH"}  # BAD, FLOW: same decision only (the reason text changed)
ruby = shutil.which("ruby")
failed = []
for name, payload, env_extra, reason in cases:
    blocks = reason is not None
    try:
        out, code = run(CMD.get(name, [sys.executable, PY_HOOK]), payload, env_extra, LOCKED.get(name))
        assert code == 0, (name, code, out)
        if blocks:
            res = json.loads(out)
            assert res["decision"] == "block", (name, out)
            assert reason in res["reason"], (name, out)
        else:
            assert out == "", (name, out)
        note = "new behavior, no Ruby parity"
        if name in PARITY or name in ("BAD", "FLOW"):
            note = "no ruby, parity skipped"
        if ruby and name in ("BAD", "FLOW"):  # Ruby parses flow style itself; only the decision must match
            rb = run([ruby, RB_HOOK], payload, env_extra)
            assert rb[1] == 0 and json.loads(rb[0])["decision"] == "block", (name, rb)
            note = "Ruby hook also blocks"
        elif ruby and name in PARITY:
            assert run([ruby, RB_HOOK], payload, env_extra) == (out, code), (name, "differs from Ruby hook")
            note = "matches Ruby hook"
    except (AssertionError, ValueError, subprocess.TimeoutExpired) as e:
        failed.append(name)
        print(f"FAIL {name}: {e}")
        continue
    print(f"ok {name}: {'block' if blocks else 'pass'}, {note}")
if failed:
    sys.exit(f"{len(failed)} of {len(cases)} failed: {', '.join(failed)}")
print(f"all {len(cases)} passed")
