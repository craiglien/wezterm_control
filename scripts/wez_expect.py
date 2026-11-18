#!/usr/bin/env python3
"""Drive a pane in a running WezTerm GUI via `wezterm cli`. Stdlib only.

Usage (global: --announce, or WEZ_ANNOUNCE=1, prints marker lines in the pane while testing):
  wez_expect.py spawn [--anchor PANE] [--tab] [--cwd DIR] [-- CMD...]   # default CMD: bash (prompt '[wez]$ ')
  wez_expect.py ensure [--anchor PANE] [--cwd DIR]   # reuse the agent pane (spawn only with --spawn-if-missing); prints pane id
  wez_expect.py status [--anchor PANE]          # prove which pane is the agent's and what it is running
  wez_expect.py where                           # show the focused pane in the dedicated WezTerm
  wez_expect.py send PANE CMD [--expect RE] [--timeout S] [--confirmed] [--no-enter]
  wez_expect.py read PANE [--lines N]
  wez_expect.py close PANE
"""
import argparse, json, os, re, shlex, subprocess, sys, time
from pathlib import Path

PROMPT_RE = r"\[wez\]\$\s*$"
PAGER_RE = r"--More--|\(END\)"
DESTRUCTIVE_RE = re.compile(
    r"\brm\s+-\w*r\w*|\b(erase|write\s+erase|reload|format|delete|mkfs|shutdown|reboot)\b|\bdd\s+if=", re.I
)
REGISTRY = Path(os.environ.get("WEZ_REGISTRY", Path.home() / ".cache/wez_expect/panes"))
SCROLLBACK = 2000
ANNOUNCE = bool(os.environ.get("WEZ_ANNOUNCE"))  # testing only: --announce or WEZ_ANNOUNCE=1


STATE = Path(os.environ.get("WEZ_STATE_DIR", Path.home() / ".cache/wez_expect")) / "instance"


def instance_socket() -> str:
    """Socket of the dedicated WezTerm started by scripts/start_wezterm.sh. Never falls back to another instance."""
    try:
        pid, sock = STATE.read_text().split()[:2]
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        sys.exit("no dedicated WezTerm running; run scripts/start_wezterm.sh first")
    return sock


def wez(*args: str) -> str:
    env = {**os.environ, "WEZTERM_UNIX_SOCKET": instance_socket()}
    return subprocess.run(["wezterm", "cli", *args], check=True, capture_output=True, text=True, env=env).stdout


def panes() -> list[dict]:
    return json.loads(wez("list", "--format", "json"))


def operator_pane() -> dict:
    """The pane the operator's GUI client is focused on (their visible window), not just any pane."""
    clients = json.loads(wez("list-clients", "--format", "json"))
    if not clients:
        sys.exit("no WezTerm GUI client attached; ask the operator to launch WezTerm")
    client = max(clients, key=lambda c: -c["idle_time"]["secs"])
    everything = panes()
    if client["focused_pane_id"] is not None:
        return next(p for p in everything if p["pane_id"] == client["focused_pane_id"])
    # GUI window has no focus (e.g. just launched): fall back to an active pane in the client's workspace.
    active = [p for p in everything if p["workspace"] == client["workspace"] and p["is_active"]]
    if not active:
        sys.exit("could not tell which pane the operator is looking at")
    return active[0]


AGENT_TITLE = "agent"
DEFAULT_CMD = [
    "bash", "-c",
    f"printf '\\033]2;{AGENT_TITLE}\\007'; printf '== AGENT PANE (bash) ==\\n'; exec env 'PS1=[wez]$ ' bash --norc --noprofile",
]


def resolve_anchor(anchor_id: str | None) -> dict:
    if not anchor_id:
        return operator_pane()
    found = next((p for p in panes() if str(p["pane_id"]) == anchor_id), None)
    if found is None:
        sys.exit(f"anchor pane {anchor_id} not found")
    return found


def spawn_pane(anchor: dict, cwd: str | None, cmd: list[str], tab: bool) -> str:
    cwd_args = ["--cwd", cwd] if cwd else []
    aid = str(anchor["pane_id"])
    # Always pin to the operator's visible window; an unanchored spawn can land in a hidden workspace/window.
    place = ["spawn", "--pane-id", aid] if tab else ["split-pane", "--right", "--pane-id", aid]
    pane = wez(*place, *cwd_args, "--", *(cmd or DEFAULT_CMD)).strip()
    new = next(p for p in panes() if str(p["pane_id"]) == pane)
    if new["window_id"] != anchor["window_id"] or new["workspace"] != anchor["workspace"]:
        wez("kill-pane", "--pane-id", pane)
        sys.exit(f"spawned pane {pane} landed outside the operator's window {anchor['window_id']}; killed it")
    register(pane)
    return pane


def find_agent_pane(anchor: dict) -> str | None:
    """The agent pane in the operator's window: a registered live pane, else one the layout titled `agent`."""
    live = {str(p["pane_id"]): p for p in panes()}
    reg = registry().read_text().split() if registry().exists() else []
    alive = [p for p in reg if p in live]
    if alive != reg:
        registry().write_text("".join(p + "\n" for p in alive))
    here = lambda p: p["window_id"] == anchor["window_id"] and p["workspace"] == anchor["workspace"]
    found = next((p for p in alive if here(live[p])), None)
    if found is None:  # started by the WezTerm startup layout, not yet seen by this helper
        found = next((i for i, p in live.items() if p["title"] == AGENT_TITLE and here(p)), None)
        if found is not None:
            register(found)
    return found


def is_clean_prompt(lines: list[str]) -> bool:
    return bool(lines) and re.fullmatch(r"\[wez\]\$", lines[-1]) is not None


def announce(pane: str, msg: str) -> None:
    """Testing aid: print a one-line comment marker in the pane so the operator can follow along. Off by default."""
    if ANNOUNCE and is_clean_prompt(get_lines(pane)):
        before = get_lines(pane)
        send(pane, f"# == agent: {msg} ==\r")
        wait_for(pane, before, PROMPT_RE, 5)


def reset_pane(pane: str, cwd: str | None) -> None:
    """Between tasks: require a clean prompt (else the human is mid-command), then cd. History stays on screen."""
    if not is_clean_prompt(get_lines(pane)):
        sys.exit(f"pane {pane} is not at a clean '[wez]$' prompt; human takeover needed")
    announce(pane, "ensure")
    before = get_lines(pane)
    send(pane, f"cd {shlex.quote(cwd or os.getcwd())}\r")
    wait_for(pane, before, PROMPT_RE, 10)


def get_lines(pane: str, n: int = SCROLLBACK) -> list[str]:
    lines = [l.rstrip() for l in wez("get-text", "--pane-id", pane, "--start-line", f"-{n}").splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def delta(before: list[str], after: list[str]) -> list[str]:
    """New lines since `before`; includes the prompt line that now holds the echoed command."""
    return after[max(len(before) - 1, 0):]


def is_destructive(cmd: str) -> bool:
    return bool(DESTRUCTIVE_RE.search(cmd))


def gui_pid() -> int:
    clients = json.loads(wez("list-clients", "--format", "json"))
    if not clients:
        sys.exit("no WezTerm GUI client attached; ask the operator to launch WezTerm")
    return clients[0]["pid"]


def registry() -> Path:
    """Per-GUI-process registry: pane ids restart when WezTerm restarts, so old entries must not carry over."""
    return REGISTRY.with_name(f"{REGISTRY.name}.{gui_pid()}")


def owned(pane: str) -> bool:
    return registry().exists() and pane in registry().read_text().split()


def register(pane: str) -> None:
    if owned(pane):
        return
    registry().parent.mkdir(parents=True, exist_ok=True)
    with registry().open("a") as f:
        f.write(pane + "\n")


def unregister(pane: str) -> None:
    if registry().exists():
        registry().write_text("".join(p + "\n" for p in registry().read_text().split() if p != pane))


def send(pane: str, text: str) -> None:
    wez("send-text", "--pane-id", pane, "--no-paste", text)


def wait_for(pane: str, before: list[str], pattern: str, timeout: float) -> list[str]:
    rx, pager = re.compile(pattern, re.M), re.compile(PAGER_RE)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        new = delta(before, get_lines(pane))
        if len(new) > 1 and pager.search(new[-1]):
            send(pane, " ")
        elif rx.search("\n".join(new[1:])):
            return new
        time.sleep(0.4)
    raise TimeoutError(f"timed out waiting for {pattern!r} on pane {pane}; human takeover may be needed")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--announce", action="store_true", help="testing: print a marker line in the pane for status/ensure")
    sub = ap.add_subparsers(dest="op", required=True)
    sp = sub.add_parser("spawn"); sp.add_argument("--cwd"); sp.add_argument("--anchor", help="pane id in the operator's visible window")
    sp.add_argument("--tab", action="store_true", help="new tab instead of a split beside the anchor"); sp.add_argument("cmd", nargs="*")
    sub.add_parser("where")
    en = sub.add_parser("ensure"); en.add_argument("--cwd"); en.add_argument("--anchor")
    en.add_argument("--spawn-if-missing", action="store_true", help="create the agent pane if the layout didn't")
    st = sub.add_parser("status"); st.add_argument("--anchor")
    se = sub.add_parser("send"); se.add_argument("pane"); se.add_argument("command")
    se.add_argument("--expect", default=PROMPT_RE); se.add_argument("--timeout", type=float, default=15)
    se.add_argument("--confirmed", action="store_true", help="operator approved a destructive command")
    se.add_argument("--no-enter", action="store_true", help="send the text as-is, without the trailing CR (e.g. $'\\x1d' for telnet's escape)")
    rd = sub.add_parser("read"); rd.add_argument("pane"); rd.add_argument("--lines", type=int, default=50)
    cl = sub.add_parser("close"); cl.add_argument("pane")
    a = ap.parse_args(argv)
    global ANNOUNCE
    ANNOUNCE = ANNOUNCE or a.announce

    if a.op == "spawn":
        anchor = resolve_anchor(a.anchor)
        pane = spawn_pane(anchor, a.cwd, a.cmd, a.tab)
        print(pane)
        return 0
    if a.op == "ensure":
        anchor = resolve_anchor(a.anchor)
        pane = find_agent_pane(anchor)
        if pane is None and not a.spawn_if_missing:
            sys.exit("no agent pane in the operator's window; start WezTerm with the agent layout (see AGENTS.md), "
                     "or pass --spawn-if-missing")
        if pane is None:
            pane = spawn_pane(anchor, a.cwd, [], False)
        else:
            reset_pane(pane, a.cwd)
        print(pane)
        return 0
    if a.op == "status":
        anchor = resolve_anchor(a.anchor)
        pane = find_agent_pane(anchor)
        if pane is None:
            sys.exit("no agent pane in the operator's window")
        announce(pane, "status")
        info = next(p for p in panes() if str(p["pane_id"]) == pane)
        print(f"agent pane={pane} window={info['window_id']} title={info['title']} tty={info['tty_name']}")
        print(subprocess.run(["ps", "-t", info["tty_name"].removeprefix("/dev/"), "-o", "pid,command"],
                             capture_output=True, text=True).stdout.rstrip())
        return 0
    if a.op == "where":
        o = operator_pane()
        print(f"focused pane={o['pane_id']} window={o['window_id']} workspace={o['workspace']} title={o['title']}")
        return 0
    if not owned(a.pane):
        sys.exit(f"refusing: pane {a.pane} was not spawned by this tool")
    if a.op == "read":
        print("\n".join(get_lines(a.pane, a.lines)))
    elif a.op == "close":
        wez("kill-pane", "--pane-id", a.pane); unregister(a.pane)
    else:
        if is_destructive(a.command) and not a.confirmed:
            sys.exit("refusing: destructive command; ask the operator, then re-run with --confirmed")
        before = get_lines(a.pane)
        send(a.pane, a.command + ("" if a.no_enter else "\r"))
        print("\n".join(wait_for(a.pane, before, a.expect, a.timeout)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
