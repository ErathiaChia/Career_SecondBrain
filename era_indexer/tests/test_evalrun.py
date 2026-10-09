from pathlib import Path

from career_history import evalrun


def test_available_suites_and_paths(tmp_path, monkeypatch):
    sets = tmp_path / "eval"
    sets.mkdir()
    (sets / "career.json").write_text("{}")
    (sets / "agent.json").write_text("{}")
    assert evalrun.available_suites(sets) == ["career", "agent"]
    monkeypatch.setattr(evalrun.config, "get", lambda: {"eval": {"sets_dir": str(sets)}})
    p = evalrun.paths()
    assert p["sets"] == sets and p["runs"] == sets / "runs" and p["scorecard"].name == "era_mcp"


def test_run_skips_without_sets(tmp_path, monkeypatch):
    monkeypatch.setattr(evalrun.config, "get", lambda: {"eval": {"sets_dir": str(tmp_path)}})
    out = evalrun.run_weekly_eval("r1")
    assert out["skipped"].startswith("no question sets")


def test_run_invokes_scorecard_and_reads_result(tmp_path, monkeypatch):
    sets = tmp_path / "eval"; sets.mkdir()
    (sets / "career.json").write_text("{}")
    monkeypatch.setattr(evalrun.config, "get", lambda: {"eval": {"sets_dir": str(sets), "base_url": "http://nas:8808"}})
    seen = {}

    class P:
        returncode = 1
        stdout = "x"
        stderr = ""

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        out = Path(cmd[cmd.index("--out") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text('{"suites": {"career": {"score": 0.8, "hard_gate_passed": false}}}')
        return P()
    monkeypatch.setattr(evalrun.subprocess, "run", fake_run)
    out = evalrun.run_weekly_eval("weekly-1")
    assert "--run-id" in seen["cmd"] and "http://nas:8808" in seen["cmd"] and "career" in seen["cmd"]
    assert out["scores"] == {"career": 0.8} and out["hard_gates_passed"] is False
