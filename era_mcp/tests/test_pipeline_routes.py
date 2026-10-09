from datetime import datetime, timedelta

from era_mcp import pipeline_routes as pr


def _run(**kw):
    base = {"run_id": "weekly-1", "kind": "weekly", "status": "finished", "stage": "finalize",
            "started_at": datetime(2026, 10, 10, 1, 0), "finished_at": datetime(2026, 10, 10, 9, 0),
            "heartbeat_at": datetime(2026, 10, 10, 9, 0), "counts": {"docs_extracted": 40}, "errors": []}
    base.update(kw)
    return base


def test_no_runs_yet():
    out = pr.summarize([], None)
    assert out["latest_run"] is None and out["knowledge_as_of"] is None
    assert "No pipeline run" in out["note"]


def test_completed_run_sets_knowledge_as_of():
    out = pr.summarize([_run()], 3)
    assert out["knowledge_as_of"] == datetime(2026, 10, 10, 9, 0)
    assert out["backlog_documents"] == 3 and out["stale"] is False


def test_running_with_recent_heartbeat_is_not_stale():
    now = datetime(2026, 10, 11, 3, 0)
    runs = [_run(run_id="weekly-2", status="running", finished_at=None,
                 heartbeat_at=now - timedelta(minutes=20)), _run()]
    out = pr.summarize(runs, 500, now=now, stale_hours=3)
    assert out["stale"] is False
    assert out["last_completed_run"]["run_id"] == "weekly-1"  # previous finished run still the "as of"


def test_running_without_heartbeat_is_stale():
    now = datetime(2026, 10, 11, 3, 0)
    runs = [_run(run_id="weekly-2", status="running", finished_at=None,
                 heartbeat_at=(now - timedelta(hours=5)).isoformat())]
    out = pr.summarize(runs, 500, now=now, stale_hours=3)
    assert out["stale"] is True and "weekly-2" in out["stale_reason"]
    assert out["knowledge_as_of"] is None
