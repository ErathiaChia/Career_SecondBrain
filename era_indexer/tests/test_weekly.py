from datetime import datetime, timedelta

import pytest

from career_history import weekly


def test_parse_deadline_weekday_next_occurrence():
    now = datetime(2026, 10, 10, 1, 0)  # Saturday
    assert weekly.parse_deadline("Mon 05:00", now) == datetime(2026, 10, 12, 5, 0)
    # already past this Monday 05:00 -> next week
    assert weekly.parse_deadline("Mon 05:00", datetime(2026, 10, 12, 6, 0)) == datetime(2026, 10, 19, 5, 0)


def test_parse_deadline_relative_and_clock():
    now = datetime(2026, 10, 10, 1, 0)
    assert weekly.parse_deadline("+12h", now) == now + timedelta(hours=12)
    assert weekly.parse_deadline("+90m", now) == now + timedelta(minutes=90)
    assert weekly.parse_deadline("06:00", now) == datetime(2026, 10, 10, 6, 0)
    assert weekly.parse_deadline("00:30", now) == datetime(2026, 10, 11, 0, 30)
    assert weekly.parse_deadline(None, now) is None
    assert weekly.parse_deadline("2026-10-13T05:00", now) == datetime(2026, 10, 13, 5, 0)


def test_interactive_hours():
    assert weekly.is_interactive_hours(datetime(2026, 10, 12, 9, 0))      # Monday 09:00
    assert not weekly.is_interactive_hours(datetime(2026, 10, 12, 23, 30))
    assert not weekly.is_interactive_hours(datetime(2026, 10, 10, 12, 0))  # Saturday


def test_should_catchup():
    now = datetime(2026, 10, 12, 23, 0)
    assert weekly.should_catchup(None, 10, now)
    assert not weekly.should_catchup(None, 0, now)
    assert weekly.should_catchup({"status": "partial", "started_at": now - timedelta(days=1)}, 5, now)
    assert not weekly.should_catchup({"status": "finished", "started_at": now - timedelta(days=1)}, 5, now)
    assert weekly.should_catchup({"status": "finished", "started_at": (now - timedelta(days=8)).isoformat()}, 5, now)


def _wire(monkeypatch, extract_result):
    """Monkeypatch every stage so run() is a pure orchestration test."""
    calls = []
    import career_history.weekly as w
    monkeypatch.setattr(w, "preflight", lambda use_llm: {"ok": True, "checks": {"database": "ok"}})
    monkeypatch.setattr(w.db, "migrate", lambda: [])
    monkeypatch.setattr(w.db, "extraction_backlog", lambda folder=None: 7)
    monkeypatch.setattr(w.intel_db, "latest_pipeline_run", lambda kinds=None: None)
    monkeypatch.setattr(w.intel_db, "start_pipeline_run", lambda *a, **k: calls.append("start"))
    monkeypatch.setattr(w.intel_db, "heartbeat_pipeline_run", lambda *a, **k: None)
    finished = {}
    monkeypatch.setattr(w.intel_db, "finish_pipeline_run",
                        lambda run_id, status, stages, counts, errors, digest_id=None, notes=None:
                        finished.update(status=status, counts=counts, errors=errors))
    monkeypatch.setattr(w, "_model_config", lambda: {})
    monkeypatch.setattr(w, "_git_sha", lambda: "abc")
    monkeypatch.setattr(w.config, "get", lambda: {"models": {}})

    class M:  # stand-in for the intelligence modules
        @staticmethod
        def discover_projects(): calls.append("projects")
        @staticmethod
        def link_versions(): calls.append("versions")
        @staticmethod
        def resolve_entities(apply, use_embeddings): calls.append("resolve")
        @staticmethod
        def detect_changes(use_llm): calls.append(f"changes:{use_llm}")
        @staticmethod
        def detect_conflicts(use_llm, max_pairs): calls.append("conflicts")
        @staticmethod
        def detect_stale(): calls.append("stale")
        @staticmethod
        def refresh_similarity(): calls.append("similarity")
        @staticmethod
        def refresh_states(use_llm): calls.append(f"state:{use_llm}")
    import sys, types
    import career_history as pkg
    # `from career_history import x` resolves the package ATTRIBUTE first (set by
    # earlier real imports), so patch both the attribute and sys.modules.
    for name in ("changes", "conflicts", "project_state", "projects", "resolve", "similarity", "versions"):
        monkeypatch.setitem(sys.modules, f"career_history.{name}", M)
        monkeypatch.setattr(pkg, name, M, raising=False)
    graph = types.SimpleNamespace(refresh_documents=lambda **kw: (calls.append("extract"), extract_result)[1])
    monkeypatch.setitem(sys.modules, "career_history.graph", graph)
    monkeypatch.setattr(pkg, "graph", graph, raising=False)
    import career_history.cards as cards_mod, career_history.career as career_mod
    monkeypatch.setattr(cards_mod, "refresh_cards", lambda **kw: calls.append(f"cards:{kw.get('use_llm')}"))
    monkeypatch.setattr(career_mod, "refresh_career", lambda **kw: calls.append(f"career:{kw.get('use_llm')}"))
    monkeypatch.setattr(w.monitor, "build_digest", lambda threshold: (calls.append("digest"), {"digest_id": 9, "markdown": ""})[1])
    monkeypatch.setattr(w.monitor, "build_weekly_report",
                        lambda run_id, threshold: (calls.append("digest"), {"digest_id": 9, "markdown": ""})[1])
    import career_history.evalrun as evalrun_mod
    monkeypatch.setattr(evalrun_mod, "run_weekly_eval", lambda run_id=None, **kw: (calls.append("eval"), {"scores": {"career": 0.8}, "hard_gates_passed": True})[1])
    import career_history.evalprobe as probe_mod
    monkeypatch.setattr(probe_mod, "arm", lambda run_id: None)
    return calls, finished


def test_run_stage_order_and_finished(monkeypatch):
    calls, finished = _wire(monkeypatch, {"processed_documents": 3, "failed_documents": 0, "stopped_early": False})
    out = weekly.run(kind="manual", deadline="+2h", skip_sync=True, force_hours=True)
    assert out["status"] == "finished" and finished["status"] == "finished"
    assert calls == ["start", "extract", "cards:True", "projects", "versions", "resolve", "changes:True",
                     "conflicts", "stale", "similarity", "career:True", "state:True", "eval", "digest"]
    assert finished["counts"]["docs_extracted"] == 3 and finished["counts"]["docs_remaining"] == 7
    assert finished["counts"]["eval"] == {"scores": {"career": 0.8}, "hard_gates_passed": True}


def test_run_partial_when_deadline_hit_and_post_stages_go_no_llm(monkeypatch):
    calls, finished = _wire(monkeypatch, {"processed_documents": 1, "failed_documents": 0, "stopped_early": True})
    out = weekly.run(kind="manual", deadline="+2h", skip_sync=True, force_hours=True)
    assert out["status"] == "partial"
    assert "changes:True" in calls  # deadline not actually past in wall-clock terms -> LLM stages still allowed


def test_catchup_skips_when_not_needed(monkeypatch):
    calls, _ = _wire(monkeypatch, {})
    import career_history.weekly as w
    monkeypatch.setattr(w.intel_db, "latest_pipeline_run",
                        lambda kinds=None: {"status": "finished", "started_at": datetime.now()})
    out = weekly.run(catchup=True, deadline="+1h")
    assert out.get("skipped") is True and "extract" not in calls and "eval" not in calls


def test_interactive_hours_guard(monkeypatch):
    _wire(monkeypatch, {})
    import career_history.weekly as w
    monkeypatch.setattr(w, "is_interactive_hours", lambda now=None: True)
    with pytest.raises(RuntimeError):
        weekly.run(kind="manual", deadline="+1h")
