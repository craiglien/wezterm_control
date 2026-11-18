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
    name = f"test{os.getpid()}"
    env = {**os.environ, "WEZ_STATE_DIR": str(tmp_path_factory.mktemp("wez_state"))}
    env.pop("WEZTERM_PANE", None)
    script = str(ROOT / "scripts" / "start_wezterm.sh")
    out = subprocess.run([script, name], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert f'WEZ_INSTANCE={name}' in out.stdout  # the pasteable prompt names the instance
    dup = subprocess.run([script, name], env=env, capture_output=True, text=True)
    assert dup.returncode != 0 and "already running" in dup.stderr  # unique names or fail loudly
    os.environ["WEZ_INSTANCE"] = w.INSTANCE = name
    pid = w.gui_pid()
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


def test_ensure_keeps_history_and_banner(instance):
    p = helper("ensure", "--cwd", str(ROOT)).stdout.strip()
    helper("send", p, "echo marker-one")
    helper("ensure", "--cwd", str(ROOT))
    text = w.wez("get-text", "--pane-id", p, "--start-line", "-200")
    assert "== AGENT PANE (bash) ==" in text and "marker-one" in text  # not cleared
    assert "== agent:" not in text  # quiet by default


def test_announce_markers_only_when_asked(instance):
    p = helper("ensure", "--cwd", str(ROOT)).stdout.strip()
    helper("--announce", "status")
    assert "# == agent: status ==" in w.wez("get-text", "--pane-id", p, "--start-line", "-200")


def test_dirty_prompt_refuses_reset(instance):
    p = helper("ensure", "--cwd", str(ROOT)).stdout.strip()
    w.wez("send-text", "--pane-id", p, "--no-paste", "half typed")
    r = helper("ensure", check=False)
    assert r.returncode != 0 and "human takeover" in r.stderr
    w.wez("send-text", "--pane-id", p, "--no-paste", "\x15")  # Ctrl-U


def test_hello_world_end_to_end(instance):
    p = helper("ensure", "--cwd", str(ROOT)).stdout.strip()
    helper("send", p, "rm -f hello.py", "--confirmed")
    helper("send", p, "printf 'import sys\\nsys.stdout.write(\"hello, world\\\\n\")\\n' > hello.py")
    assert "hello, world" in helper("send", p, "python3 hello.py").stdout


def test_helper_refuses_without_instance_name():
    env = {k: v for k, v in os.environ.items() if k != "WEZ_INSTANCE"}
    r = subprocess.run([sys.executable, "-I", S, "where"], capture_output=True, text=True, env=env)
    assert r.returncode != 0 and "--instance" in r.stderr


def test_helper_refuses_unknown_instance():
    env = {**os.environ, "WEZ_INSTANCE": "nosuchinstance"}
    r = subprocess.run([sys.executable, "-I", S, "where"], capture_output=True, text=True, env=env)
    assert r.returncode != 0 and "not running" in r.stderr
