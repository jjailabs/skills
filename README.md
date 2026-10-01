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

Each time Claude stops, the hook reads the newest report in `<project>/.done/<task>/reports/`. If the report says `status: DONE`, the hook checks that:

- `active.yaml` names a revision, and `contract.r<N>.yaml` for that revision exists
- the SHA-256 of that file equals `active_sha256`
- an approval for that revision and hash has both `approved_by` and `evidence`
- the report's `contract_revision` and `contract_sha256_checked` match

If a check fails, the hook blocks the stop and tells Claude what is wrong. Every other stop goes through.

To turn the gate off for one session, set `CLAUDE_DONE_GATE=0`. To turn it off for good, run `claude plugin disable jjai@jjailabs`.

A correct block also shows "Stop hook error occurred". That is normal. Press ctrl+o to see the reason.

## Trust

The hook runs on every stop with your user permissions. Read `hooks/done-gate.py` before you install. It is about 140 lines of standard-library Python and makes no network calls. `python3 tests/test_done_gate.py` runs it against sample fixtures.

## Known limits

- Only `<project>/.done/` is checked. The skill's fallback location, `~/.claude/done/<project>/`, is not gated.
- "Newest report" means the file with the newest modification time. Touching or copying an old report changes which one is checked.
- The hook reads YAML with a small built-in reader, not a full parser. It handles the block style the skill's templates use. If approvals are written in flow style (`[{...}]`), the gate blocks. If a whole report is written in flow style, the gate does not read it and lets the stop through.

## License

MIT. See [LICENSE](LICENSE).

---

Built by JJAI Labs — jjailabs.io. First shown in Chase AI+.
