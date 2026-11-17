"""Live retest against the real WezTerm GUI. Run: WEZ_LIVE=1 uv run --no-project --with pytest pytest tests/test_live.py -v -s
Watch the operator window: one agent pane should appear once and be reused. Add WEZ_PACE=2 to slow it down.
The agent pane is left open afterward; each test run starts by closing panes from the previous run."""
import json, os, subprocess, sys, time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("WEZ_LIVE"), reason="set WEZ_LIVE=1 (needs a running WezTerm GUI)")
S = str(Path(__file__).parent.parent / "scripts" / "wez_expect.py")
ROOT = str(Path(__file__).parent.parent)


PACE = float(os.environ.get("WEZ_PACE", 0))  # seconds to pause after each step so the operator can watch


def helper(*args, check=True):
    r = subprocess.run([sys.executable, "-I", S, *args], capture_output=True, text=True)
    time.sleep(PACE)
    if check and r.returncode:
        raise AssertionError(r.stderr or r.stdout)
    return r


def panes():
    out = subprocess.check_output(["wezterm", "cli", "list", "--format", "json"], text=True)
    return {str(p["pane_id"]): p for p in json.loads(out)}


def operator_window():
    where = helper("where").stdout
    return int(where.split("window=")[1].split()[0])


@pytest.fixture(autouse=True)
def clean_slate():
    """Close any agent panes left by earlier runs so each test starts from none."""
    reg = Path.home() / ".cache/wez_expect/panes"
    for p in (reg.read_text().split() if reg.exists() else []):
        if p in panes():
            helper("close", p)
    yield


def test_ensure_spawns_in_operator_window_with_title():
    win = operator_window()
    before = set(panes())
    pane = helper("ensure", "--cwd", ROOT).stdout.strip()
    after = panes()
    assert set(after) - before == {pane}
    assert after[pane]["window_id"] == win
    assert after[pane]["title"] == "agent"


def test_ensure_reuses_and_resets_cwd():
    p1 = helper("ensure", "--cwd", ROOT).stdout.strip()
    helper("send", p1, "cd /")
    count = len(panes())
    p2 = helper("ensure", "--cwd", ROOT).stdout.strip()
    assert p2 == p1 and len(panes()) == count  # no new pane
    assert ROOT in helper("send", p2, "pwd").stdout


def test_dirty_prompt_refuses_reset():
    p = helper("ensure", "--cwd", ROOT).stdout.strip()
    subprocess.run(["wezterm", "cli", "send-text", "--pane-id", p, "--no-paste", "half typed"], check=True)
    r = helper("ensure", check=False)
    assert r.returncode != 0 and "human takeover" in r.stderr


def test_dead_pane_is_respawned():
    p1 = helper("ensure", "--cwd", ROOT).stdout.strip()
    subprocess.run(["wezterm", "cli", "kill-pane", "--pane-id", p1], check=True)  # simulate operator closing it
    p2 = helper("ensure", "--cwd", ROOT).stdout.strip()
    assert p2 != p1 and p2 in panes()


def test_hello_world_end_to_end():
    p = helper("ensure", "--cwd", ROOT).stdout.strip()
    helper("send", p, "rm -f hello.py", "--confirmed")
    helper("send", p, "printf 'import sys\\nsys.stdout.write(\"hello, world\\\\n\")\\n' > hello.py")
    assert "hello, world" in helper("send", p, "python3 hello.py").stdout
