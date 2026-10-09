from era_mcp import career_deliverables as cd

PROJECT = {"id": 1, "name": "Acme Credit", "client": "Acme Bank", "project_type": "ai", "status": "ACTIVE"}
STATE = {"state": {"business_problem": {"value": "Manual credit triage took days"}, "stage": {"value": "delivery"},
                   "technologies": {"value": [{"name": "Appian"}, {"name": "Gemini"}]},
                   "timeline": {"value": [{"date": "2026-01-10"}, {"date": "2026-06-30"}]}},
         "health": {"level": "green", "overall": 82}}
ROLE = {"role": "solution_architect", "status": "confirmed", "confidence": 0.9, "project_id": 1, "project": "Acme Credit"}
FACTS = [
    {"id": 1, "kind": "requirement", "statement": "Triage 500 applications/day", "file_name": "req.docx"},
    {"id": 2, "kind": "contribution", "statement": "Designed the target architecture", "attributes": {"activity": "designed"}, "file_name": "arch.docx"},
    {"id": 3, "kind": "contribution", "statement": "Led the vendor workshops", "attributes": {}, "file_name": "notes.md"},
    {"id": 4, "kind": "outcome", "statement": "Cut triage time by 60%", "file_name": "closeout.pptx", "from_latest_version": False},
    {"id": 5, "kind": "milestone", "statement": "Go-live", "status": "done", "file_name": "plan.xlsx"},
    {"id": 6, "kind": "lesson", "statement": "Start UAT two weeks earlier", "file_name": "retro.md"},
    {"id": 7, "kind": "decision", "statement": "Use Appian for workflow", "file_name": "arch.docx"},
]
ACHS = [{"id": 9, "statement": "Went live on schedule", "metric": {"raw": "60%"}, "evidence_fact_ids": [4, 5],
         "file": {"file_name": "closeout.pptx"}, "project": "Acme Credit", "project_id": 1, "confidence": 0.8}]


def test_render_star_sections_and_citations():
    md = cd.render_star(PROJECT, STATE, ROLE, FACTS, ACHS)
    for h in ("## STAR — Acme Credit", "### Situation", "### Task", "### Action (what I did)", "### Result", "### Lessons"):
        assert h in md
    assert "Manual credit triage took days" in md
    assert "Designed the target architecture [F2, arch.docx]" in md
    assert "Led the vendor workshops [F3, notes.md]" in md
    assert "Went live on schedule — **60%** [F4, F5, closeout.pptx]" in md
    assert "Cut triage time by 60% [F4, closeout.pptx] (older version)" in md
    assert "solution architect (confirmed, confidence 0.90)" in md


def test_render_star_marks_unknowns():
    md = cd.render_star(PROJECT, None, None, [], [])
    assert "UNKNOWN (no role inferred yet" in md and "Business problem not stated" in md
    assert "No contribution facts attributed to me yet" in md and "No outcome recorded" in md


def test_pick_star_projects_ranks_by_evidence_then_roles():
    skills = [{"project_id": 2, "strength": 1.5}, {"project_id": 1, "strength": 0.4}]
    facts = [{"project_id": 1, "confidence": 0.9}, {"project_id": 1, "confidence": 0.9}, {"project_id": 3, "confidence": 0.5}]
    assert cd.pick_star_projects("ai", skills, facts, [], limit=2) == [1, 2]
    roles = [{"project_id": 7, "confidence": 0.3}, {"project_id": 8, "confidence": 0.7}]
    assert cd.pick_star_projects(None, [], [], roles, limit=5) == [8, 7]


def test_render_compare_table():
    a = {"project": PROJECT, "state": STATE, "role": ROLE, "achievements": ACHS, "facts": FACTS}
    b = {"project": {"id": 2, "name": "Orion Portal", "client": "Orion", "project_type": "web", "status": "CLOSED"},
         "state": None, "role": None, "achievements": [], "facts": []}
    md = cd.render_compare(a, b)
    assert "| My role | solution_architect (0.90) | UNKNOWN |" in md
    assert "| Technologies | Appian, Gemini | — |" in md
    assert "| Timeline | 2026-01-10 → 2026-06-30 | — |" in md
    assert "Went live on schedule [F4,F5]" in md
    assert "Facts considered: 7 vs 0" in md


def test_capability_evidence_buckets():
    facts = [{**f, "project": "Acme Credit"} for f in FACTS if f["kind"] in ("contribution", "outcome")]
    skills = [{"skill": "Appian", "project": "Acme Credit", "role": "solution_architect", "strength": 1.2,
               "mention_count": 7, "evidence_fact_ids": [2]}]
    md = cd.render_capability_evidence("architecture", skills, facts, ACHS)
    assert "### Architecture" in md and "Designed the target architecture" in md
    assert "### Leadership" in md and "Led the vendor workshops" in md
    assert "### Outcomes" in md and "### Achievements" in md
    assert "Appian on Acme Credit as solution_architect — strength 1.20, 7 mention(s) [F2]" in md
    assert "No evidence recorded" in cd.render_capability_evidence("x", [], [], [])


def test_career_timeline_sorted():
    roles = [{"role": "project_manager", "project": "B", "client": "c", "status": "proposed", "confidence": 0.5,
              "period_start": "2025-03-01", "period_end": None, "project_id": 2},
             {"role": "solution_architect", "project": "A", "client": "c", "status": "confirmed", "confidence": 0.9,
              "first_activity": "2024-01-15", "last_activity": "2024-12-01", "project_id": 1}]
    md = cd.render_career_timeline(roles, [{"statement": "Won deal", "period_end": "2024-06-01", "project": "A", "evidence_fact_ids": [3]}])
    lines = [l for l in md.splitlines() if l.startswith("- ")]
    assert lines[0].startswith("- 2024-01-15 → 2024-12-01: **solution architect** on A")
    assert lines[1].startswith("- 2024-06-01: Won deal — A [F3]")
    assert lines[2].startswith("- 2025-03-01 → now: **project manager** on B")


def test_activity_detection():
    assert cd.activity_of({"attributes": {"activity": "Negotiated"}}) == "negotiated"
    assert cd.activity_of({"statement": "I presented the roadmap to the board"}) == "presented"
    assert cd.capability_bucket("presented") == "presales" and cd.capability_bucket("zzz") == "other"
