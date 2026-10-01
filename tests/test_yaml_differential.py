#!/usr/bin/env python3
# Differential test: the gate's YAML reader (hooks/done-gate.py) against Ruby's Psych, a real YAML parser.
# Mutates the GOOD, BAD and legacy (no timestamp) report fixtures with tricky snippets. For each mutation:
# if Psych raises, the reader must reject the file; if the reader accepts it, Psych must read a mapping
# with the same FIELDS. Same means: a Psych string equals the reader's text; a Psych mapping or list
# ("<container>") never matches, so the reader must reject; a Psych time or date is the instant the gate's
# own stamp() reads; a Psych null or other type is not a state (status), gives the same stamp() (timestamp),
# and is null for the reader only when Psych's is null (the contract fields, which the gate compares as text).
# Psych runs at UTC+05:30, so a time read in local time instead of UTC would show up as a mismatch.
# Skips when ruby is missing.
# Run: python3 tests/test_yaml_differential.py [seed]
import ast
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 20261001
N = 20000

RUBY = "/usr/bin/ruby" if os.path.exists("/usr/bin/ruby") else shutil.which("ruby")
if not RUBY:
    print("note: differential test skipped: ruby is not installed")
    sys.exit(0)

# The gate runs on import, so take only its imports, constants and functions.
with open(os.path.join(HERE, "..", "hooks", "done-gate.py"), encoding="utf-8") as f:
    tree = ast.parse(f.read())
keep = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef))
        or isinstance(n, ast.Assign) and all(getattr(t, "id", "x").isupper() for t in n.targets)]
gate = {}
exec(compile(ast.Module(body=keep, type_ignores=[]), "done-gate.py", "exec"), gate)

FIELDS = ("status", "assessment_timestamp", "contract_revision", "contract_sha256_checked")
PSYCH = r'''
def tag(v)
  case v
  when nil then nil
  when Hash, Array then {"c" => "<container>"}
  when String then {"s" => v}
  when Time then {"t" => v.to_f}
  when Date then {"t" => Time.utc(v.year, v.month, v.day).to_f}
  else {"o" => v.to_s}
  end
end
STDIN.each_line do |l|
  r = begin
    d = YAML.safe_load(JSON.parse(l)[0], permitted_classes: [Date, Time])
    h = d.is_a?(Hash)
    {"ok" => true, "hash" => h, "f" => h ? %w[''' + " ".join(FIELDS) + r'''].map { |k| tag(d[k]) } : nil}
  rescue Exception => e
    {"ok" => false, "err" => "#{e.class}: #{e.message}"[0, 120].scrub}
  end
  puts JSON.generate(r)
end
'''


def read(*parts):
    with open(os.path.join(FIX, *parts), encoding="utf-8") as f:
        return f.read()


GOOD, BAD = read("good", ".done", "t1", "reports", "r1.yaml"), read("bad", ".done", "t1", "reports", "r1.yaml")
LEGACY = "".join(l for l in BAD.splitlines(True) if not l.startswith("assessment_timestamp:"))
SNIPS = ["\u00a0", "\u2028", "\u2029", "\u0085", "\u3000", "\u200b", "\u1680", "\u202f", "\ufeff", "\x0b", "\x7f",
         "'", '"', "''", '"x', "'x", "x'", "\\", '"\\u0044"', " #", "#", " # c", " #'", ' #"',
         "[", "{", "[]", "{}", "[a, b]", "{a: b}", "]", "}", "&a ", "*a", "!!str ", "!x ", "|", ">", "|-", ">-",
         "---", "...", ": ", ":", "? ", "- ", "-", "<<: ", "%YAML 1.1", "@", "`", ",",
         "\t", "\r", "\r\n", "\n", "  ", " ", "x", " DONE", "NEEDS_REVIEW",
         "\n  DONE", "\n  status: NEEDS_REVIEW", "\n  - x", "\n  assessment_timestamp: 2001-01-01T00:00:00Z",
         "\nstatus: NEEDS_REVIEW", "\nassessment_timestamp: 2001-01-01T00:00:00Z", "\n---\n", "\n...\n",
         "\n  k: v", "\n  - DONE", "\n- DONE", "\n  -", "\n  k:"]
STAMPS = ["2026-10-1T0:00:00Z", "2026-10-01", "2026-10-01 00:00:00", "2026-10-01T00:00:00", "2026-10-01 00:00:00Z",
          "2026-10-01T00:00:00.5Z", "2026-10-01T00:00:00.123Z", "2026-10-01T00:00:00.123456Z",
          "2026-10-01T00:00:00.1234567Z", "2026-10-01T00:00:00+02:00", "2026-10-01T00:00:00-05:30",
          "2026-10-01T00:00:00 +02:00", "2026-10-01T00:00:00+0200", "2026-10-01T00:00:00+02", "2026-10-01t00:00:00z",
          "20261001T000000Z", "2026-13-01T00:00:00Z", "2026-02-30T00:00:00Z", "2026-10-01T24:00:00Z",
          "2026-10-01T00:00:60Z", "0001-01-01T00:00:00Z", "1582-10-10T00:00:00Z", "9999-12-31T23:59:59-01:00",
          "2026-10-01T00:00:00+24:00", "12:30:00", "1790812800", "null", "~", "Null", "NULL", "nil", "''", '""']
NEW_LINES = ["status: NEEDS_REVIEW", "status: DONE", "assessment_timestamp: 2001-01-01T00:00:00Z", "# c", "---",
             "...", "- x", "x", "status:", "summary: ok", "status:\n  - DONE", "assessment_timestamp:\n  k: v"]
CONTAINERS = ["\n  k: v", "\n  - DONE", "\n- DONE", " # c\n  - 2001-01-01T00:00:00Z", "\n  - k: v\n    j: w",
              "\n    k:\n      - x", "\n  k: v\nstatus: NEEDS_REVIEW"]


def pick_line(rng, lines):  # half the time a FIELDS line, when there is one
    hot = [i for i, l in enumerate(lines) if l.startswith(FIELDS)]
    return rng.choice(hot) if hot and rng.random() < 0.5 else rng.randrange(len(lines))


def mutate(rng, text):
    lines = text.split("\n")
    i = pick_line(rng, lines)
    line, op = lines[i], rng.randrange(11)
    colon = line.find(": ")
    ts = next((j for j, l in enumerate(lines) if l.startswith("assessment_timestamp: ")), None)
    if op == 0:  # snippet anywhere in the line
        at = rng.randrange(len(line) + 1)
        lines[i] = line[:at] + rng.choice(SNIPS) + line[at:]
    elif op == 1 and colon > 0:  # snippet in front of, after, or instead of the value
        key, value = line[:colon + 2], line[colon + 2:]
        lines[i] = key + rng.choice([rng.choice(SNIPS) + value, value + rng.choice(SNIPS), rng.choice(SNIPS)])
    elif op == 2:  # a new line, at some indent
        lines.insert(i, " " * rng.choice([0, 0, 1, 2, 4]) + rng.choice(NEW_LINES + SNIPS))
    elif op == 3 and colon > 0:  # the value on the next line
        lines[i] = line[:colon + 1] + "\n" + " " * rng.choice([0, 1, 2, 4]) + line[colon + 2:]
    elif op == 4 and colon > 0:  # benign: quote the value, comment, trailing spaces
        value = line[colon + 2:]
        lines[i] = line[:colon + 2] + rng.choice(["'%s'" % value.replace("'", "''"), '"%s"' % value,
                                                  value + " # note", value + "   "])
    elif op == 5:  # benign: document markers and comment lines
        lines = rng.choice([["---"] + lines, lines + ["...", "# end"], lines[:i] + ["", "  # c"] + lines[i:]])
    elif op == 6:  # an indented continuation line under this one
        lines.insert(i + 1, " " * rng.choice([1, 2, 4, 6]) + rng.choice(["DONE", "more", "- x", "k: v", "#c"]))
    elif op == 8:  # the timestamp in another form, plain or quoted (a new line when there is none)
        v = rng.choice(STAMPS)
        new = "assessment_timestamp: " + rng.choice([v, "'%s'" % v, '"%s"' % v])
        if ts is None:
            lines.insert(i, new)
        else:
            lines[ts] = new
    elif op == 10 and colon > 0:  # a block mapping or list in place of the value
        lines[i] = line[:colon + 1] + rng.choice(CONTAINERS)
    elif op == 9 and ts is not None:  # one character of the timestamp changed, dropped, or doubled
        line, at = lines[ts], rng.randrange(len("assessment_timestamp: "), len(lines[ts]) + 1)
        lines[ts] = line[:at] + rng.choice([rng.choice("0123456789:-+.TZ "), "", line[at:at + 1] * 2]) + line[at + 1:]
    else:  # whole file: BOM and line breaks
        return rng.choice(["\ufeff", ""]) + "\n".join(lines).replace("\n", rng.choice(["\r\n", "\r", "\n"]))
    return "\n".join(lines)


def agree(ours, theirs, field):
    kind, v = next(iter(theirs.items())) if theirs else ("null", None)
    if kind == "c":  # the reader has no value for a mapping or list: it must have rejected the file
        return False
    if kind == "s":
        return ours == v
    if field == "status":
        return ours not in gate["STATES"]
    if field != "assessment_timestamp":
        return (kind == "null") == (ours is None)
    t = gate["stamp"]({"assessment_timestamp": ours})
    if kind == "t":
        return t is not None and abs(t - v) < 1e-6
    return t == (None if kind == "null" else gate["stamp"]({"assessment_timestamp": v}))


rng = random.Random(SEED)
texts = []
for n in range(N):
    text = rng.choice([GOOD, BAD, LEGACY])
    for _ in range(rng.choice([1, 1, 2, 3])):
        text = mutate(rng, text)
    texts.append(text)

lines = "".join(json.dumps([t]) + "\n" for t in texts)  # ASCII JSON, one file per line
p = subprocess.run([RUBY, "-ryaml", "-rjson", "-rdate", "-e", PSYCH], input=lines, capture_output=True, text=True,
                   encoding="utf-8", env=dict(os.environ, TZ="XST-5:30"), timeout=120)
assert p.returncode == 0, p.stderr
psych = [json.loads(l) for l in p.stdout.split("\n")[:-1]]  # not splitlines(): U+2028 can be in a line
assert len(psych) == N, (len(psych), p.stderr)

equal = rejected = both_reject = 0
mismatches = []
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "r.yaml")
    for text, theirs in zip(texts, psych):
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        ours = gate["load_yaml"](path)
        if ours is None:
            rejected += 1
            both_reject += not theirs["ok"]
        elif not theirs["ok"]:
            mismatches.append(("reader accepts, Psych raises " + theirs["err"], text))
        elif not theirs["hash"]:
            mismatches.append(("reader accepts, Psych reads no mapping", text))
        elif all(agree(ours.get(k), t, k) for k, t in zip(FIELDS, theirs["f"])):
            equal += 1
        else:
            mismatches.append((f"reader {[ours.get(k) for k in FIELDS]!r}, Psych {theirs['f']}", text))

print(f"seed {SEED}: {N} mutations, {equal} accepted and equal, {rejected} rejected "
      f"({both_reject} also rejected by Psych), {len(mismatches)} mismatches")
for why, text in mismatches[:10]:
    print(f"MISMATCH {why}: {text!r}")
if mismatches:
    sys.exit(1)
