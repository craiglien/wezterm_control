# AGENTS.md — WezTerm PTY bridge

Agents run in a non-interactive Bash tool, so they cannot hold an interactive session open across calls. Drive a live
WezTerm GUI pane through `wezterm cli` instead; the human watches it and can take over at any time.

Applies to any interactive CLI (telnet, serial console, ssh, REPL, installer). Telnet to network gear is just one example.

## Hard rules
- Bash only. Panes are spawned as `bash --norc --noprofile` (prompt `[wez]$ `). Never zsh or another shell.
- Use the helper, `scripts/wez_expect.py`, run as `uv run --no-project python3 -I scripts/wez_expect.py ...`.
- Check `wezterm cli list` first. If no GUI is running, stop and ask the operator to launch WezTerm.
- Only touch panes you spawned (the helper enforces this via a registry). Never the operator's own panes.
- The point is operator visibility. `spawn` finds the pane the operator's GUI client is focused on (`list-clients`) and
  splits beside it, in their window and workspace. Unanchored `wezterm cli spawn` can land in another window or
  workspace (this machine has a second, hidden `ctx` workspace). If the new pane isn't in the operator's window, the
  helper kills it and errors. Use `where` to see what it will target, `--anchor PANE` to choose, `--tab` for a new tab.
- Always pin the pane id. Without it `wezterm cli` falls back to the focused pane, and commands leak.
- Destructive commands (`erase`, `write erase`, `reload`, `format`, `rm -r`, ...) are refused unless the operator approved
  them in chat and you pass `--confirmed`.
- Human takeover: on an unexpected state (`rommon >`, password recovery, a prompt you don't recognize, a timeout), stop
  sending and tell the operator.

## Reusable pattern: one agent pane
Start every task with `P=$(wez_expect.py ensure --cwd "$PWD")`, not `spawn`.
- Reuses the registered agent pane in the operator's window (titled `agent`), or spawns it if missing or closed.
- On reuse it first requires a clean `[wez]$` prompt (otherwise the human is mid-command: stop and ask), then does
  `cd <cwd> && clear`.
- The pane stays open between tasks. Only the operator, or an explicit `close`, removes it.
- `spawn` is the low-level call (extra panes, `--tab`, or a non-bash command such as telnet).

## Helper commands
    P=$(wez_expect.py spawn [--cwd DIR] [-- CMD...])   # prints pane id; default CMD is the bash above
    wez_expect.py where                                # operator's visible pane/workspace
    wez_expect.py send $P "<cmd>" [--expect RE] [--timeout S] [--confirmed]
    wez_expect.py read $P [--lines N]
    wez_expect.py close $P

- `send` types the command plus `\r` with `--no-paste` (CR, not LF; bracketed paste can stall console prompts), then polls
  until `--expect` matches. The default is the `[wez]$ ` prompt. For a telnet session, pass the device prompt, e.g.
  `--expect 'Router[>#]\s*$'`.
- `--no-enter` sends text without the CR, for control keys: `send $P $'\x1d' --no-enter --expect 'telnet>\s*$'` is telnet's
  escape, then `send $P quit`.
- It prints only the new output since the call: the echoed command line, the output, then the prompt.
- `--More--` and `(END)` pagers are answered with a space automatically.
- `get-text` returns plain text (no ANSI), so regexes are stable.
- To run something else (e.g. telnet), `spawn -- telnet <host> <port>`, then `send` with that device's prompt regex.
  Spawning a bare `bash` is the usual case.

## Worked example (test task: Ken Thompson-style hello world)
    P=$(wez_expect.py spawn --cwd "$PWD")
    wez_expect.py send $P "printf 'import sys\nsys.stdout.write(\"hello, world\\\\n\")\n' > hello.py"
    wez_expect.py send $P "python3 hello.py"      # -> hello, world
    wez_expect.py close $P

Thompson's original (the B tutorial) is lowercase with a comma, no capitals, and no `print`-style sugar:
`main( ) { putchar('hello, world*n'); }`. Keep the Python equally bare.

## Tests
`uv run --no-project --with pytest pytest` runs the pure-logic tests. `WEZ_LIVE=1 ... pytest tests/test_live.py -v -s` runs
the live suite against the running WezTerm (watch the window); it closes the panes it creates.
