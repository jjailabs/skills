# define-done for Claude Code

You hand Claude a task. Later it tells you the task is done. Sometimes that is true. Sometimes the tests never ran, the feature works only on the easy path, or the goal shrank along the way until it fit what got built. You hear "done" in both cases, and you can't tell which one you got without doing the checking yourself.

define-done moves that checking to the start. Before Claude plans or builds anything, it writes down what done means. The outcome. The scope. How far the work has to go: a reviewable draft, a tested local artifact, staging, or production. A pass/fail check for each criterion, and the evidence that proves it. And the ways to stop that are not success: BLOCKED, NEEDS_REVIEW, STOPPED, FAILED.

That written definition is the contract. You approve it, or an agent that neither wrote it nor will do the work does. Whoever does the work should not also set the bar.

Once approved, the contract is fixed. Its hash is recorded, and any change becomes a new revision that needs its own approval. The finish line stays where you put it.

In Claude Code, a gate backs this up. Each time Claude stops, a Stop hook reads the latest report. If the report says DONE but does not point to the approved contract, unchanged, Claude can't stop on that claim. It has to fix the mismatch, or write a new report that says what went wrong.

The skill only defines done. Doing the work is a separate ask.

It is built for people who hand real work to Claude Code and need "done" to mean something when they hear it: long loops, delegated subagents, research, repair loops that keep retrying, release checks, and audits of someone else's "it's done." On claude.ai or Claude Desktop, the skill comes as a zip. You get the contract, but not the gate.

## 📦 Install

**In Claude Code:**

```
/plugin marketplace add jjailabs/skills
/plugin install jjai@jjailabs
```

Then run `/reload-plugins` or restart Claude Code. Run the skill as `/jjai:define-done`.

**🔄 Upgrade**

In a terminal:

```
claude plugin marketplace update jjailabs
claude plugin update jjai@jjailabs
```

Then restart Claude Code.

## 💻 claude.ai and Claude Desktop

Download `define-done.zip` from the Releases page and upload it as a skill. You get the skill only. The gate is a Claude Code hook, so it does not run there.

## Requirements

- Claude Code
- Python 3 for the gate (standard library only). Without Python, you will see "Stop hook error occurred" each time Claude stops, and the gate does nothing.

## How the gate works

Each time Claude stops, the hook looks for `.done/` folders. It starts in Claude's working folder and moves up one folder at a time, to the folder that holds `.git`, checking every `.done/` on the way. It never checks a folder above your home folder, and it checks your home folder only when Claude starts there.

In each `.done/<task>/reports/`, the newest report is the one with the latest `assessment_timestamp`, such as `2026-10-01T06:30:00Z`. A report with no timestamp, or with `null` (for example, from v0.7), is dated by its file time. Any other value must take this exact form: date, `T`, time with seconds, then `Z` or an offset such as `+02:00`. An optional `.123` or `.123456` may follow the seconds. A value in any other form, such as `2026-10-01`, makes the report unparseable. If two reports have the same time, the one written last counts. If they still tie, the hook checks the DONE report.

The hook blocks the stop when:

- any report's `status`, old or new, is not exactly one of RUNNING, DONE, BLOCKED, NEEDS_REVIEW, STOPPED, or FAILED, written as a plain value. Quotes are fine. Block scalars (`|`, `>`), tags (`!!str`), escapes, and flow style (`{...}`) are not.
- the hook cannot parse a report, old or new. Its reader handles only the simple block-style YAML the skill tells Claude to write. Anything else makes a report unparseable, because it could hide a line from the reader.
- any report is dated more than 5 minutes in the future. The date is its `assessment_timestamp`, or its file time if it has none.
- the newest report says `status: DONE` and one of these checks fails:
  - `active.yaml` names a revision, and `contract.r<N>.yaml` for that revision exists
  - the SHA-256 of that file equals `active_sha256`
  - an approval for that revision and hash has both `approved_by` and `evidence`
  - the report's `contract_revision` and `contract_sha256_checked` match
- the hook finds a `.done/` folder but cannot read part of it: a task folder it cannot open, any report it cannot read (old or new), or a broken symlink. The reason names the folder and the error.
- a report is not a regular file, such as a named pipe. The hook does not open it.
- the check takes more than 8 seconds.

The block reason tells Claude what is wrong. Every other stop goes through.

These checks cover the contract files and the approval record. They do not test the work. The report, and the person who reads it, decide whether the work meets the contract.

The hook checks again when Claude tries to stop right after a block, so retrying does not get past it. A block ends in one of three ways:

- Claude writes a new report with status NEEDS_REVIEW (or BLOCKED, STOPPED, or FAILED) that explains the problem. That newer report replaces the DONE claim. It does not end a block caused by an unparseable report or a report dated in the future. Fix that report instead.
- You interrupt Claude.
- You turn the gate off.

To turn the gate off for one session, set `CLAUDE_DONE_GATE=0`. To turn it off for good, run `claude plugin disable jjai@jjailabs`.

A correct block also shows "Stop hook error occurred". That is normal. Press ctrl+o to see the reason.

## Trust

The hook runs on every stop with your user permissions. Read `hooks/done-gate.py` before you install. It is about 285 lines of standard-library Python and makes no network calls. `python3 tests/test_done_gate.py` runs it against sample fixtures. `python3 tests/test_yaml_differential.py` compares its YAML reader with Ruby's YAML parser.

## License

MIT. See [LICENSE](LICENSE).

---

Built by JJAI Labs — [jjailabs.io](https://jjailabs.io). First shown in [Chase AI+](https://www.skool.com/chase-ai).
