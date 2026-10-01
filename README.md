# jjai: define-done for Claude Code

`/jjai:define-done` turns a task into a written definition of done: the outcome, the scope, the checks that prove it, and the ways to stop that are not success. A Stop hook then keeps Claude from stopping when a report says DONE but the contract it points to does not check out.

## Install

```
/plugin marketplace add jjailabs/skills
/plugin install jjai@jjailabs
```

Then run `/reload-plugins` or restart Claude Code. Run the skill as `/jjai:define-done`.

## claude.ai and Claude Desktop

Download `define-done.zip` from the Releases page and upload it as a skill. You get the skill only. The gate is a Claude Code hook, so it does not run there.

## Requirements

- Claude Code
- Python 3 for the gate (standard library only). Without Python you will see "Stop hook error occurred" each time Claude stops, and the gate does nothing.

## How the gate works

Each time Claude stops, the hook looks for `.done/` folders. It starts in Claude's working folder and goes up one folder at a time, to the folder that holds `.git`. It checks every `.done/` it finds on the way. It never checks a folder above your home folder. It checks your home folder only when Claude starts there.

In each `.done/<task>/reports/`, the newest report is the one with the latest `assessment_timestamp`, such as `2026-10-01T06:30:00Z`. A report without one, or with `null` (for example, from v0.7), is dated by its file time. Any other value must have this exact form: date, `T`, time with seconds, then `Z` or an offset such as `+02:00`. An optional `.123` or `.123456` may follow the seconds. A value in another form, such as `2026-10-01`, makes the report unparseable. If two reports have the same time, the one written last counts. If they still tie, the hook checks the DONE report.

The hook blocks the stop when:

- any report's `status`, old or new, is not exactly one of RUNNING, DONE, BLOCKED, NEEDS_REVIEW, STOPPED, or FAILED, written as a plain value. Quotes are fine. Block scalars (`|`, `>`), tags (`!!str`), escapes, and flow style (`{...}`) are not.
- the hook cannot parse a report, old or new. The hook reads only a small part of YAML (see Known limits). Anything outside it makes a report unparseable, because it could hide a line from the hook's reader.
- any report is dated more than 5 minutes in the future. The date is its `assessment_timestamp`, or its file time if it has none.
- the newest report says `status: DONE` and one of these checks fails:
  - `active.yaml` names a revision, and `contract.r<N>.yaml` for that revision exists
  - the SHA-256 of that file equals `active_sha256`
  - an approval for that revision and hash has both `approved_by` and `evidence`
  - the report's `contract_revision` and `contract_sha256_checked` match
- the hook finds a `.done/` folder but cannot read part of it: a task folder it cannot open, any report it cannot read (old or new), or a broken symlink. The reason names the folder and the error.
- a report is not a regular file, for example a named pipe. The hook does not open it.
- the check takes more than 8 seconds.

The block reason tells Claude what is wrong. Every other stop goes through.

These checks cover the contract files and the approval record. They do not test the work. The report and the person who reads it decide whether the work meets the contract.

The hook checks again when Claude tries to stop right after a block, so retrying does not get past it. A block ends in one of three ways:

- Claude writes a new report with status NEEDS_REVIEW (or BLOCKED, STOPPED, or FAILED) that explains the problem. That newer report replaces the DONE claim. It does not end a block caused by a report the hook cannot parse or a report dated in the future. Fix that report instead.
- You interrupt Claude.
- You turn the gate off.

To turn the gate off for one session, set `CLAUDE_DONE_GATE=0`. To turn it off for good, run `claude plugin disable jjai@jjailabs`.

A correct block also shows "Stop hook error occurred". That is normal. Press ctrl+o to see the reason.

## Trust

The hook runs on every stop with your user permissions. Read `hooks/done-gate.py` before you install. It is about 285 lines of standard-library Python and makes no network calls. `python3 tests/test_done_gate.py` runs it against sample fixtures. `python3 tests/test_yaml_differential.py` compares its YAML reader with Ruby's YAML parser.

## Known limits

- `.done/` must be inside the git project. The hook ignores a `.done/` above the folder that holds `.git`. Outside a git project there is no `.git` to stop at, so the hook goes up until the next folder would be your home folder or a folder above it.
- A report without an `assessment_timestamp`, or with `null`, is ordered by its file time, as in v0.7. Touching or copying such a report can change which report counts as newest. The skill tells Claude to always write the timestamp, so this mostly affects older or hand-written reports.
- The hook trusts any `assessment_timestamp` that is not in the future. A wrong past time can make a report look older than it is.
- The hook reads YAML with a small built-in reader, not a full parser. It accepts only these lines:
  - blank lines and `#` comment lines
  - one `---` before the first key, and one `...` at the end, with only blank lines and comments after it
  - `key: value`, `- key: value`, and `- value`, indented with spaces

  A key is letters, digits, and `_`. A value is one of these, on the same line as its key:
  - plain text that does not start with a symbol such as `-`, `[`, `{`, `&`, `*`, `!`, `|`, `>`, `#`, `@`, or a quote, and does not contain `: ` or ` #`
  - text in single quotes; write a `'` inside as `''`
  - text in double quotes with no backslash
  - an empty `[]` or `{}`

  A ` #` comment may follow a value. A key with no value may have a list or more keys on the lines under it. A key may appear only once under the same parent. At the top of a file and in each approval entry, these keys must hold a single-line value, not a list, more keys, `[]`, or `{}`: `status`, `assessment_timestamp`, `contract_revision`, `contract_sha256_checked`, `active_revision`, `active_sha256`, `revision`, `sha256`, `base_revision`, `base_sha256`, `approved_by`, and `evidence`.

  Everything else makes the file unparseable, even valid YAML: tabs, a byte order mark (BOM), anchors and aliases, tags, `|` and `>` multi-line text, flow style such as `[a, b]` or `{a: b}`, escapes, a value that runs onto the next line, control characters, and any space or line-break character other than an ASCII space and a newline, such as a no-break space. If any report is unparseable, old or new, the gate blocks. If `active.yaml` is unparseable, the gate blocks a DONE claim.
- Windows has no 8-second limit, because Python cannot set an alarm signal there. The regular-file check still runs. A read that stalls runs into the 10-second hook timeout instead.
- The hook checks that the files agree with each other. It cannot tell who wrote them. Anyone who can edit `.done/`, Claude included, can add an approval entry. The skill's approval rule and your review of `active.yaml` catch that.

## License

MIT. See [LICENSE](LICENSE).

---

Built by JJAI Labs — [jjailabs.io](https://jjailabs.io). First shown in [Chase AI+](https://www.skool.com/chase-ai).
