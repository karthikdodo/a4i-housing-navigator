"""Voice, photo and map APIs in demo mode (no GCP).  python -m pytest api/tests -q"""

import base64
import json
import os
import tempfile

os.environ["A4I_AGENT_MODE"] = "mock"
os.environ["A4I_MOCK_DELAY"] = "0"
os.environ.setdefault("A4I_UPLOAD_DIR", tempfile.mkdtemp(prefix="a4i-uploads-"))

from fastapi.testclient import TestClient  # noqa: E402

from api.a2ui import surfaces as S  # noqa: E402
from api.main import app  # noqa: E402
from api.media import rule_parse_intake  # noqa: E402
from api.tests.test_api import ALL_A2UI, _collect, _last_model  # noqa: E402

client = TestClient(app)
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _sse(path, body):
    with client.stream("POST", path, json=body) as r:
        assert r.status_code == 200, r.text
        return _collect([json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")])


def test_photo_upload_and_chat():
    sid = client.post("/api/sessions", json={"session_id": "m1"}).json()["session_id"]
    up = client.post(f"/api/sessions/{sid}/uploads", files={"file": ("mold.png", PNG, "image/png")}).json()
    assert up["kind"] == "image" and up["url"].startswith("/api/uploads/")
    got = client.get(up["url"])
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    assert got.headers["x-content-type-options"] == "nosniff"

    events = _sse(f"/api/sessions/{sid}/messages", {"text": "", "attachments": [up["id"]]})
    turn = [e for e in events if e["type"] == "user_turn"][0]["turn"]
    assert turn["attachments"][0]["url"] == up["url"]
    docs = _last_model(events, S.DOCUMENTS)
    assert docs["photos_title"] == "Tenant-provided photos (1)"
    assert "not a public record" in docs["photos_note"]
    assert _last_model(events, S.BRIEF)["photos_line"]


def test_rejects_bad_uploads():
    sid = client.post("/api/sessions", json={"session_id": "m2"}).json()["session_id"]
    r = client.post(f"/api/sessions/{sid}/uploads", files={"file": ("x.svg", b"<svg/>", "image/svg+xml")})
    assert r.status_code == 415
    r = client.post(f"/api/sessions/{sid}/uploads", files={"file": ("x.png", b"", "image/png")})
    assert r.status_code == 413
    r = client.get("/api/uploads/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code == 404 or "root:" not in r.text
    r = client.get("/..%2F..%2Fapi%2Fmain.py")  # SPA fallback must not escape ui/dist
    assert "FastAPI" not in r.text
    assert client.get("/api/uploads/notanid").status_code == 404


def test_voice_message_shows_transcript():
    sid = client.post("/api/sessions", json={"session_id": "m3"}).json()["session_id"]
    said = "Any open residential complaints on her block?"
    tr = client.post(f"/api/sessions/{sid}/transcribe",
                     files={"audio": ("clip.webm", b"\x1aE\xdf\xa3fake-webm", "audio/webm")},
                     data={"browser_text": said, "duration": "3.2"}).json()
    assert tr["text"] == said and tr["source"] == "browser"
    events = _sse(f"/api/sessions/{sid}/messages",
                  {"text": tr["text"], "voice": {"id": tr["audio"]["id"], "duration": 3.2, "source": tr["source"]}})
    turn = [e for e in events if e["type"] == "user_turn"][0]["turn"]
    assert turn["voice"]["url"] == tr["audio"]["url"] and turn["voice"]["duration"] == 3.2
    assert turn["text"] == said
    case = client.get(f"/api/sessions/{sid}/cases/INT-1142").json()
    assert case["transcript"][0]["voice"]["id"] == tr["audio"]["id"], "voice clip kept in chat history"
    m = _last_model(events, S.MAP)
    assert m["address"] == "600 John Muir Dr, San Francisco, CA"
    assert m["center"] and any(p["kind"] == "same_block" for p in m["markers"])


def test_voice_intake_fills_form():
    sid = client.post("/api/sessions", json={"session_id": "m4"}).json()["session_id"]
    text = ("Tenant Maria Rodriguez, 600 block of John Muir Drive. Water under the floorboards and black mold. "
            "Hearing Monday at 9 am. Household of three, 45 percent AMI. 3-day pay or quit notice.")
    r = client.post(f"/api/sessions/{sid}/intake/voice", json={"text": text}).json()
    f = r["fields"]
    assert f["client"] == "M.R." and "Maria" not in json.dumps(r)
    assert f["block"] == "600 block of John Muir Drive"
    assert f["household"] == "3" and f["ami"] == "45" and f["notice"] == "nonpayment"
    assert f["hearing"].endswith("T09:00")
    paths = {m["updateDataModel"]["path"] for m in r["a2ui"]}
    assert {"/form/client", "/form/block", "/form/notice"} <= paths
    ALL_A2UI.extend(r["a2ui"])


def test_rule_parser_variants():
    f = rule_parse_intake("Client J T at 450 Eddy Street, no heat, unlawful detainer served, hearing Nov 30 at 1:30 pm")
    assert f["client"] == "J.T." and f["block"] == "400 block of Eddy Street"
    assert f["notice"] == "unlawful_detainer" and f["hearing"].endswith("T13:30")
