"""Writes every A2UI message the tests produced to api/tests/out/a2ui_messages.json, which
`npm run validate:a2ui` (ui/) runs through the real A2UI renderer core."""

import json
from pathlib import Path


def pytest_sessionfinish(session, exitstatus):
    from api.tests.test_api import ALL_A2UI

    out = Path(__file__).with_name("out")
    out.mkdir(exist_ok=True)
    (out / "a2ui_messages.json").write_text(json.dumps(ALL_A2UI, indent=1, ensure_ascii=False))
