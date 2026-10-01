#!/usr/bin/env python3
# Feeds Stop-hook inputs to hooks/done-gate.py and checks the result.
# If `ruby` is on PATH, also runs the original Ruby hook (fixtures/done-gate.rb)
# on the same inputs and asserts identical stdout + exit code.
# Run: python3 tests/test_done_gate.py
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
PY_HOOK = os.path.join(HERE, "..", "hooks", "done-gate.py")
RB_HOOK = os.path.join(FIX, "done-gate.rb")


def run(cmd, payload, env_extra):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_DONE_GATE"}
    env.update(env_extra)
    p = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True, env=env)
    assert cmd[1] != PY_HOOK or p.stderr == "", p.stderr
    return p.stdout, p.returncode


bad = os.path.join(FIX, "bad")
cases = [  # name, payload, extra env, expect block?
    ("BAD", {"cwd": bad}, {}, True),
    ("GOOD", {"cwd": os.path.join(FIX, "good")}, {}, False),
    ("NONE", {"cwd": FIX}, {}, False),  # fixtures/ itself has no .done/
    ("KILL_SWITCH", {"cwd": bad}, {"CLAUDE_DONE_GATE": "0"}, False),
    ("STOP_HOOK_ACTIVE", {"cwd": bad, "stop_hook_active": True}, {}, False),
]
ruby = shutil.which("ruby")
for name, payload, env_extra, blocks in cases:
    out, code = run([sys.executable, PY_HOOK], payload, env_extra)
    assert code == 0, (name, code, out)
    if blocks:
        res = json.loads(out)
        assert res["decision"] == "block", (name, out)
        assert "t1: contract.r1.yaml hashes to 2fea2d712328 but active_sha256 is 2d711642b726" in res["reason"], out
    else:
        assert out == "", (name, out)
    note = "no ruby, parity skipped"
    if ruby:
        assert run([ruby, RB_HOOK], payload, env_extra) == (out, code), (name, "differs from Ruby hook")
        note = "matches Ruby hook"
    print(f"ok {name}: {'block' if blocks else 'pass'}, {note}")
print(f"all {len(cases)} passed")
