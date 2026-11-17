"""API tests in demo mode (no GCP). Run from the repo root:  python -m pytest api/tests -q

Also writes every A2UI message the run produced to api/tests/out/a2ui_messages.json, which
`npm run validate:a2ui` (ui/) feeds through the real A2UI renderer core to check them
against the navigator catalog.
"""

import json
import os
from pathlib import Path

os.environ["A4I_AGENT_MODE"] = "mock"
os.environ["A4I_MOCK_DELAY"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from api.a2ui import surfaces as S  # noqa: E402
from api.main import app  # noqa: E402

OUT = Path(__file__).with_name("out")
client = TestClient(app)
ALL_A2UI: list[dict] = []


def _collect(events):
    for e in events:
        if e.get("type") == "a2ui":
            ALL_A2UI.extend(e["messages"])
    return events


def _ws_turn(ws, frame):
    ws.send_json(frame)
    events = []
    while True:
        e = ws.receive_json()
        events.append(e)
        if e["type"] in ("turn_end",) or (frame["type"] == "a2ui_action" and e["type"] in ("case",)):
            break
        if frame["type"] == "a2ui_action" and frame["message"]["action"]["name"] in ("mark_memo_reviewed", "focus_record") \
                and e["type"] == "a2ui":
            break
    return _collect(events)


def _action(name, surface, **context):
    return {"version": "1.0", "action": {"name": name, "surfaceId": surface, "sourceComponentId": "test",
                                         "timestamp": "2026-11-17T20:00:00Z", "context": context}}


def test_health_and_config():
    assert client.get("/health").json()["agent_mode"] == "mock"
    cfg = client.get("/api/config").json()
    assert cfg["a2ui"]["version"] == "1.0"
    assert cfg["a2ui"]["catalogId"] == S.NAVIGATOR_CATALOG_ID


def test_catalog_served():
    cat = client.get("/api/a2ui/catalog").json()
    assert cat["catalogId"] == S.NAVIGATOR_CATALOG_ID
    for name in ("RecordCard", "ExcludedCard", "FundCard", "PanelTabs", "Column", "Button"):
        assert name in cat["components"], name


def test_full_intake_over_websocket():
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "session_id": "t1"})
        snap = ws.receive_json()
        assert snap["type"] == "a2ui"
        created = [m["createSurface"]["surfaceId"] for m in snap["messages"]]
        assert set(created) == set(S.SURFACES)
        ALL_A2UI.extend(snap["messages"])
        assert ws.receive_json()["type"] == "case"

        ev = _ws_turn(ws, {"type": "user_message", "session_id": "t1",
                           "text": "Any open residential complaints on her block?"})
        kinds = [e["type"] for e in ev]
        assert "status" in kinds and "message" in kinds and kinds[-1] == "turn_end"
        docs = _last_model(ev, S.DOCUMENTS)
        ids = [e["request_id"] for e in docs["evidence"]]
        assert ids[0] == "SF-202665044"
        assert all(not i.startswith("DECOY") for i in ids), "a decoy reached the evidence list"
        ex = {e["request_id"]: e for e in docs["excluded"]}
        assert ex["DECOY-SANF-05"]["heading"].startswith("DECOY-SANF-05 · raw #1")
        assert ex["DECOY-SANF-02"]["label"] == "Commercial"
        hdr = _last_model(ev, S.HEADER)
        assert "06075033204" in hdr["subtitle"]  # tract stays a string with its leading 0

        # A2UI action from the ExcludedCard button
        ev = _ws_turn(ws, {"type": "a2ui_action", "session_id": "t1",
                           "message": _action("explain_exclusion", S.DOCUMENTS, request_id="DECOY-SANF-02")})
        while ev[-1]["type"] != "turn_end":
            ev += _collect([ws.receive_json()])
        reply = [e for e in ev if e["type"] == "message" and e["final"]][-1]["text"]
        assert "Commercial" in reply

        for q in ("Which statute bars the rent demand?", "Which fund fits before Monday?",
                  "How bad is eviction pressure here?", "Draft the intake memo"):
            ev = _ws_turn(ws, {"type": "user_message", "session_id": "t1", "text": q})

        assert any(e["type"] == "brief" for e in ev)
        docs = _last_model(ev, S.DOCUMENTS)
        assert docs["brief_ready"] is True
        assert [f["fit_label"] for f in docs["funds"]][0] == "Likely fit"
        assert docs["tract_tiles"][0]["value"] == "30.3%"
        brief = _last_model(ev, S.BRIEF)
        assert brief["equity_rows"], "equity audit belongs in the brief"
        assert "audit" not in json.dumps(docs).lower(), "audit_* data must not reach the case panel"

        ev = _ws_turn(ws, {"type": "a2ui_action", "session_id": "t1",
                           "message": _action("mark_memo_reviewed", S.DOCUMENTS)})
        assert _last_model(ev, S.DOCUMENTS)["memo"]["status_label"] == "Reviewed"

        ev = _ws_turn(ws, {"type": "a2ui_action", "session_id": "t1",
                           "message": _action("open_case", S.QUEUE, case_id="INT-1139")})
        assert ev[-1] == {**ev[-1], "type": "case", "case_id": "INT-1139"}

    memo = client.get("/api/sessions/t1/cases/INT-1142/memo.md")
    assert memo.status_code == 200 and "SF-202665044" in memo.text
    brief = client.get("/api/sessions/t1/cases/INT-1142/brief").json()
    assert {e["request_id"] for e in brief["evidence"]} == {"SF-202665044", "SF-202665131", "SF-202665071"}
    assert brief["excluded"], "excluded is always included"


def test_sse_message_and_intake_form():
    sid = client.post("/api/sessions", json={"session_id": "t2"}).json()["session_id"]
    snap = client.get(f"/api/sessions/{sid}/a2ui").json()["messages"]
    assert len(snap) == len(S.SURFACES)

    body = _action("submit_intake", S.INTAKE_FORM, client="Jane Q Public", block="400 block of Eddy St",
                   issue="No heat for two weeks and black mold", hearing="2026-11-30T09:00",
                   notice=["nonpayment"], household="3", ami="45")
    with client.stream("POST", f"/api/sessions/{sid}/actions", json=body) as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    _collect(events)
    case_ev = [e for e in events if e["type"] == "case"][0]
    assert case_ev["case_id"].startswith("INT-")
    queue = _last_model(events, S.QUEUE)
    new = [c for c in queue["cases"] if c["case_id"] == case_ev["case_id"]][0]
    assert new["title"].startswith("J.Q.P."), "full names never reach the queue"
    assert events[-1]["type"] == "turn_end"

    with client.stream("POST", f"/api/sessions/{sid}/messages", json={"text": "hello"}) as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    assert events[-1]["type"] == "turn_end"


def test_dump_a2ui_messages():
    OUT.mkdir(exist_ok=True)
    (OUT / "a2ui_messages.json").write_text(json.dumps(ALL_A2UI, indent=1, ensure_ascii=False))
    assert ALL_A2UI


def _last_model(events, surface_id):
    for e in reversed(events):
        if e.get("type") == "a2ui":
            for m in reversed(e["messages"]):
                upd = m.get("updateDataModel") or m.get("createSurface")
                if upd and upd["surfaceId"] == surface_id:
                    return upd.get("value", upd.get("dataModel"))
    raise AssertionError(f"no data model for {surface_id}")
