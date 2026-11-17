#!/usr/bin/env python3
"""Drive a pane in a running WezTerm GUI via `wezterm cli`. Stdlib only.

Usage:
  wez_expect.py spawn [--anchor PANE] [--tab] [--cwd DIR] [-- CMD...]   # default CMD: bash (prompt '[wez]$ ')
  wez_expect.py ensure [--anchor PANE] [--cwd DIR]   # reuse the agent pane, or spawn it; prints pane id
  wez_expect.py where                           # show the operator's visible pane/workspace
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


def wez(*args: str) -> str:
    return subprocess.run(["wezterm", "cli", *args], check=True, capture_output=True, text=True).stdout


def panes() -> list[dict]:
    return json.loads(wez("list", "--format", "json"))


def operator_pane() -> dict:
    """The pane the operator's GUI client is focused on (their visible window), not just any pane."""
    clients = json.loads(wez("list-clients", "--format", "json"))
    if not clients:
        sys.exit("no WezTerm GUI client attached; ask the operator to launch WezTerm")
    focused = max(clients, key=lambda c: -c["idle_time"]["secs"])["focused_pane_id"]
    return next(p for p in panes() if p["pane_id"] == focused)


AGENT_TITLE = "agent"
DEFAULT_CMD = [
    "bash", "-c",
    f"printf '\\033]2;{AGENT_TITLE}\\007'; exec env 'PS1=[wez]$ ' bash --norc --noprofile",
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
    """A registered, still-alive agent pane in the operator's window; prunes dead registry entries."""
    live = {str(p["pane_id"]): p for p in panes()}
    reg = REGISTRY.read_text().split() if REGISTRY.exists() else []
    alive = [p for p in reg if p in live]
    if alive != reg:
        REGISTRY.write_text("".join(p + "\n" for p in alive))
    return next((p for p in alive if live[p]["window_id"] == anchor["window_id"]
                 and live[p]["workspace"] == anchor["workspace"]), None)


def is_clean_prompt(lines: list[str]) -> bool:
    return bool(lines) and re.fullmatch(r"\[wez\]\$", lines[-1]) is not None


def reset_pane(pane: str, cwd: str | None) -> None:
    """Between tasks: require a clean prompt (else the human is mid-command), then cd + clear."""
    if not is_clean_prompt(get_lines(pane)):
        sys.exit(f"pane {pane} is not at a clean '[wez]$' prompt; human takeover needed")
    send(pane, f"cd {shlex.quote(cwd or os.getcwd())} && clear\r")
    # `clear` wipes the screen, so the usual before/after delta doesn't apply: wait for a bare prompt instead.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        time.sleep(0.5)
        lines = get_lines(pane)
        if is_clean_prompt(lines) and not any("&& clear" in l for l in lines):
            return
    sys.exit(f"pane {pane} did not return to a clean prompt after reset; human takeover needed")


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


def owned(pane: str) -> bool:
    return REGISTRY.exists() and pane in REGISTRY.read_text().split()


def register(pane: str) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY.open("a") as f:
        f.write(pane + "\n")


def unregister(pane: str) -> None:
    if REGISTRY.exists():
        REGISTRY.write_text("".join(p + "\n" for p in REGISTRY.read_text().split() if p != pane))


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
    sub = ap.add_subparsers(dest="op", required=True)
    sp = sub.add_parser("spawn"); sp.add_argument("--cwd"); sp.add_argument("--anchor", help="pane id in the operator's visible window")
    sp.add_argument("--tab", action="store_true", help="new tab instead of a split beside the anchor"); sp.add_argument("cmd", nargs="*")
    sub.add_parser("where")
    en = sub.add_parser("ensure"); en.add_argument("--cwd"); en.add_argument("--anchor")
    se = sub.add_parser("send"); se.add_argument("pane"); se.add_argument("command")
    se.add_argument("--expect", default=PROMPT_RE); se.add_argument("--timeout", type=float, default=15)
    se.add_argument("--confirmed", action="store_true", help="operator approved a destructive command")
    se.add_argument("--no-enter", action="store_true", help="send the text as-is, without the trailing CR (e.g. $'\\x1d' for telnet's escape)")
    rd = sub.add_parser("read"); rd.add_argument("pane"); rd.add_argument("--lines", type=int, default=50)
    cl = sub.add_parser("close"); cl.add_argument("pane")
    a = ap.parse_args(argv)

    if a.op == "spawn":
        anchor = resolve_anchor(a.anchor)
        pane = spawn_pane(anchor, a.cwd, a.cmd, a.tab)
        print(pane)
        return 0
    if a.op == "ensure":
        anchor = resolve_anchor(a.anchor)
        pane = find_agent_pane(anchor)
        if pane is None:
            pane = spawn_pane(anchor, a.cwd, [], False)
        else:
            reset_pane(pane, a.cwd)
        print(pane)
        return 0
    if a.op == "where":
        o = operator_pane()
        print(f"operator pane={o['pane_id']} window={o['window_id']} workspace={o['workspace']} title={o['title']}")
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
