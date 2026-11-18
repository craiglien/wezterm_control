import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import wez_expect as w


def test_delta_includes_echo_line_and_new_output():
    before = ["[wez]$"]
    after = ["[wez]$ echo hi", "hi", "[wez]$"]
    assert w.delta(before, after) == after


def test_delta_after_scroll_keeps_only_new():
    before = ["a", "b", "[wez]$"]
    after = ["a", "b", "[wez]$ ls", "x", "[wez]$"]
    assert w.delta(before, after) == ["[wez]$ ls", "x", "[wez]$"]


def test_destructive():
    for c in ["reload", "write erase", "rm -rf x", "erase flash:"]:
        assert w.is_destructive(c)
    for c in ["ls", "echo hi", "python3 hello.py"]:
        assert not w.is_destructive(c)


def test_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "REGISTRY", tmp_path / "panes")
    monkeypatch.setattr(w, "gui_pid", lambda: 111)
    assert not w.owned("5")
    w.register("5"); assert w.owned("5")
    w.unregister("5"); assert not w.owned("5")


def test_registry_is_per_gui_process(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "REGISTRY", tmp_path / "panes")
    monkeypatch.setattr(w, "gui_pid", lambda: 111)
    w.register("5")
    monkeypatch.setattr(w, "gui_pid", lambda: 222)  # WezTerm restarted; pane ids start over
    assert not w.owned("5")


def test_lua_layout_matches_helper():
    lua = (Path(__file__).parent.parent / "wezterm" / "agent_layout.lua").read_text()
    assert w.AGENT_TITLE in lua and "PS1=[wez]$ " in lua and "--norc --noprofile" in lua


def test_no_instance_means_refuse(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "STATE", tmp_path / "missing")
    with pytest.raises(SystemExit):
        w.instance_socket()


def test_dead_instance_means_refuse(tmp_path, monkeypatch):
    state = tmp_path / "instance"
    state.write_text("999999\n/tmp/sock\n")  # pid that does not exist
    monkeypatch.setattr(w, "STATE", state)
    with pytest.raises(SystemExit):
        w.instance_socket()


def test_live_instance_returns_socket(tmp_path, monkeypatch):
    state = tmp_path / "instance"
    state.write_text(f"{os.getpid()}\n/tmp/sock\n")
    monkeypatch.setattr(w, "STATE", state)
    assert w.instance_socket() == "/tmp/sock"
