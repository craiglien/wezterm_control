"""Live retest against a real WezTerm GUI. Run: WEZ_LIVE=1 uv run --no-project --with pytest pytest tests/test_live.py -v -s
Run from a terminal outside WezTerm. Starts its OWN throwaway dedicated instance (separate WEZ_STATE_DIR) and quits it
afterward, so a dedicated instance you are using is never touched. Add WEZ_PACE=2 to slow it down for watching."""
import json, os, signal, subprocess, sys, time
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import wez_expect as w

pytestmark = pytest.mark.skipif(not os.environ.get("WEZ_LIVE"), reason="set WEZ_LIVE=1 (needs a GUI; run outside WezTerm)")
S = str(ROOT / "scripts" / "wez_expect.py")
PACE = float(os.environ.get("WEZ_PACE", 0))


@pytest.fixture(scope="module")
def instance(tmp_path_factory):
    state_dir = tmp_path_factory.mktemp("wez_state")
    env = {**os.environ, "WEZ_STATE_DIR": str(state_dir)}
    env.pop("WEZTERM_PANE", None)
    out = subprocess.run([str(ROOT / "scripts" / "start_wezterm.sh")], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    pid = int((state_dir / "instance").read_text().split()[0])
    w.STATE = state_dir / "instance"
    os.environ["WEZ_STATE_DIR"] = str(state_dir)
    yield pid
    os.kill(pid, signal.SIGTERM)


def helper(*args, check=True):
    r = subprocess.run([sys.executable, "-I", S, *args], capture_output=True, text=True)
    time.sleep(PACE)
    if check and r.returncode:
        raise AssertionError(r.stderr or r.stdout)
    return r


def panes():
    return {str(p["pane_id"]): p for p in json.loads(w.wez("list", "--format", "json"))}


def test_startup_layout_is_one_agent_pane(instance):
    ps = panes()
    assert len(ps) == 1
    (p,) = ps.values()
    assert p["title"] == "agent"
    assert "== AGENT PANE (bash) ==" in w.wez("get-text", "--pane-id", str(p["pane_id"]))


def test_status_proves_bash(instance):
    assert "bash --norc --noprofile" in helper("status").stdout


def test_ensure_reuses_without_new_panes_and_resets_cwd(instance):
    p1 = helper("ensure", "--cwd", str(ROOT)).stdout.strip()
    helper("send", p1, "cd /")
    p2 = helper("ensure", "--cwd", str(ROOT)).stdout.strip()
    assert p2 == p1 and len(panes()) == 1
    assert str(ROOT) in helper("send", p2, "pwd").stdout


def test_dirty_prompt_refuses_reset(instance):
    p = helper("ensure", "--cwd", str(ROOT)).stdout.strip()
    subprocess.run(["wezterm", "cli", "send-text", "--pane-id", p, "--no-paste", "half typed"], check=True,
                   env={**os.environ, "WEZTERM_UNIX_SOCKET": w.instance_socket()})
    r = helper("ensure", check=False)
    assert r.returncode != 0 and "human takeover" in r.stderr
    subprocess.run(["wezterm", "cli", "send-text", "--pane-id", p, "--no-paste", "\x15"], check=True,  # Ctrl-U
                   env={**os.environ, "WEZTERM_UNIX_SOCKET": w.instance_socket()})


def test_hello_world_end_to_end(instance):
    p = helper("ensure", "--cwd", str(ROOT)).stdout.strip()
    helper("send", p, "rm -f hello.py", "--confirmed")
    helper("send", p, "printf 'import sys\\nsys.stdout.write(\"hello, world\\\\n\")\\n' > hello.py")
    assert "hello, world" in helper("send", p, "python3 hello.py").stdout


def test_helper_refuses_without_instance(tmp_path):
    env = {**os.environ, "WEZ_STATE_DIR": str(tmp_path)}  # no state file here
    r = subprocess.run([sys.executable, "-I", S, "where"], capture_output=True, text=True, env=env)
    assert r.returncode != 0 and "start_wezterm.sh" in r.stderr
