# CONTEXT.md — WezTerm control

Background for picking this work back up. How to use the helper is in `AGENTS.md`; this file holds the why, the gotchas
and the state of the work.

## Purpose
An agent (Claude Code, running in a separate terminal) drives a pane in the operator's live WezTerm through
`wezterm cli`, so the operator can watch every keystroke and take over at any time. It is meant to be generic for any
interactive CLI. The main target is telnet sessions to lab devices.

## Decisions and why
- **Anchor spawns to the operator's focused pane.** A plain `wezterm cli spawn` can land in a different window or a hidden
  workspace (this machine has a second `ctx` workspace). `spawn` splits beside the pane the GUI client is focused on, and
  kills the new pane if it lands elsewhere.
- **One persistent `agent` pane (`ensure`).** It is reused across tasks and never closed automatically. On reuse it requires
  a clean `[wez]$` prompt (otherwise a human is mid-command: stop), then runs `cd <dir> && clear`.
- **Always bash.** Panes run `bash --norc --noprofile` with a fixed prompt. The operator's rule is bash only, and a fixed
  prompt keeps matching deterministic.
- **Only touch panes the helper spawned** (registry at `~/.cache/wez_expect/panes`). Never the operator's own panes.
- **Destructive commands need `--confirmed`** after the operator approves in chat. Covers erase, reload, format, delete,
  `rm -r`, shutdown/reboot and similar. Console sessions on network gear can brick or wipe hardware.
- **`--no-paste` and `\r`.** Bracketed paste or LF can stall console prompts.

## Gotchas
- `clear` wipes the screen, which breaks the before/after output tracking, so reset waits for a bare prompt instead.
- `send` appends CR unless `--no-enter` is passed (needed for control keys such as telnet's `\x1d`).
- Pager prompts (`--More--`, `(END)`) are answered automatically with a space.
- Tests once closed the pane and ran too fast to watch. Live tests now leave the agent pane open and take `WEZ_PACE`.
- Run Python with `uv run --no-project` (never bare `uv run`; it would sync the global venv to this project).

## Status
- Verified: local bash flows, unit tests, the live suite, and telnet connect / escape / quit.
- Not verified: a real telnet login, `Router>` / `Router#` prompts, a `--More--` pager in real device output, a device
  that stops responding, more than one operator window, and several agent panes visible at once.

## Open questions
- **Passwords.** Anything typed through `send` lands in the pane's scrollback and in tool output. Needs a design.
- **Many devices.** One pane per device (`spawn`), or one pane that visits devices in turn?
- **Timeouts.** Should a timeout trigger an automatic human-takeover notice?

## Resuming
- Unit tests: `uv run --no-project --with pytest pytest`
- Live tests (watch the operator window): `WEZ_LIVE=1 WEZ_PACE=2 uv run --no-project --with pytest pytest tests/test_live.py -v -s`
- Layout: `scripts/wez_expect.py` (helper), `tests/` (unit and live), `hello.py` (test-task output).

## Keeping this repo public-safe
No real device IPs, hostnames or credentials in tracked files. Put lab specifics in `*.scratch.md` (globally gitignored).
