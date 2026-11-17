import sys
from pathlib import Path

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
    assert not w.owned("5")
    w.register("5"); assert w.owned("5")
    w.unregister("5"); assert not w.owned("5")
