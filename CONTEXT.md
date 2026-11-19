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
- **One dedicated WezTerm, one pane.** `scripts/start_wezterm.sh` starts a separate WezTerm process from
  `wezterm/agent_wezterm.lua`: a single window with a single bash pane titled `agent`. The operator's regular WezTerm and
  `wezterm.lua` are never used or edited. Tried and dropped: a split layout with an operator pane inside the agent's
  window, and a gui-startup change to the operator's own `wezterm.lua`. An unanchored `wezterm cli` could land in the
  wrong window, and the earlier `ensure` split a new pane on every launch (three panes).
- **Several named instances.** `start_wezterm.sh NAME` runs WezTerm with `--class wezctl-NAME`; a duplicate name fails.
  `wezterm cli --class` does not work for these: `--always-new-process` creates no `default-<class>` symlink. So the
  helper finds the GUI by its command line (`--class wezctl-NAME` gives the pid, hence `gui-sock-<pid>`). No state file.
- **The helper needs an instance name** (`--instance` / `WEZ_INSTANCE`), no default and no auto-pick, so a session can't
  drive the wrong WezTerm. Closed or unknown names fail loudly. The start script prints a pasteable prompt carrying the name.
- **`ensure` reuses the agent pane** and never creates panes unless `--spawn-if-missing`. On reuse it requires a clean
  `wez(bash)$` prompt (otherwise a human is mid-command: stop), then runs `cd <dir>`. It never clears the screen: the operator wants to watch, so history and the banner stay.
  While testing, `--announce` (or `WEZ_ANNOUNCE=1`) prints `# == agent: <op> ==` marker lines in the pane; off by default so real
  work isn't noisy.
- **Closing the only pane closes the window.** The instance is gone and must be restarted with the start script.
- **Registry keyed by instance name and WezTerm process.** Pane ids restart on each launch, so stale entries could match unrelated panes.
- **`status` proves the agent pane runs bash** (title, tty, processes on the tty).
- **Always bash.** Panes run `bash --norc --noprofile` with a fixed prompt. The operator's rule is bash only, and a fixed
  prompt keeps matching deterministic.
- **Only touch panes the helper spawned** (registry at `~/.cache/wez_expect/panes`). Never the operator's own panes.
- **Destructive commands need `--confirmed`** after the operator approves in chat. Covers erase, reload, format, delete,
  `rm -r`, shutdown/reboot and similar. Console sessions on network gear can brick or wipe hardware.
- **`--no-paste` and `\r`.** Bracketed paste or LF can stall console prompts.

## Gotchas
- An earlier reset ran `clear`, which erased the banner and made `ensure` look like a flash with nothing to see; removed.
- `send` appends CR unless `--no-enter` is passed (needed for control keys such as telnet's `\x1d`).
- Pager prompts (`--More--`, `(END)`) are answered automatically with a space.
- Tests once closed the pane and ran too fast to watch. Live tests now leave the agent pane open and take `WEZ_PACE`.
- Run Python with `uv run --no-project` (never bare `uv run`; it would sync the global venv to this project).

## Status
- Verified: the start script (one agent pane, bash, refuses a second start), the live suite in a throwaway instance,
  local bash flows, unit tests, and telnet connect / escape / quit.
- Not verified: a real telnet login, `Router>` / `Router#` prompts, a `--More--` pager in real device output, a device
  that stops responding, more than one operator window, and several agent panes visible at once.

## Open questions
- **Passwords.** Anything typed through `send` lands in the pane's scrollback and in tool output. Needs a design.
- **Many devices.** One pane per device (`spawn`), or one pane that visits devices in turn?
- **Restart workflow.** `start_wezterm.sh NAME` refuses if NAME is running; `--list` exists, `--stop` and `--restart` are deferred.
- **Timeouts.** Should a timeout trigger an automatic human-takeover notice?

## Resuming
- Unit tests: `uv run --no-project --with pytest pytest`
- Live tests (watch the operator window): `WEZ_LIVE=1 WEZ_PACE=2 uv run --no-project --with pytest pytest tests/test_live.py -v -s`
- Live tests start their own throwaway dedicated instance and quit it afterward; run them outside WezTerm.
- Layout: `scripts/wez_expect.py` (helper), `scripts/start_wezterm.sh` + `wezterm/` (dedicated instance and layout), `tests/`, `hello.py`.

## Keeping this repo public-safe
No real device IPs, hostnames or credentials in tracked files. Put lab specifics in `*.scratch.md` (globally gitignored).
