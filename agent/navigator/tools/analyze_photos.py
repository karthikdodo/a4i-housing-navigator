"""analyze_photos: Gemini vision on tenant-provided photos -> structured habitability findings.

Owner: Karthik.

The API saves uploads to A4I_UPLOAD_DIR as <id>.<ext> plus <id>.json metadata (api/media.py).
This tool reads them by id (no import of the api package) and asks Gemini for a fixed JSON
shape: hazards per photo, where, how severe, how confident, and a 311-style search query the
evidence search can use.

Rules baked in: photos are tenant-provided, never a public record or inspection finding, and
cannot establish date or location. People and personal documents are never described.
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from .. import config

_ID = re.compile(r"^[a-f0-9]{32}$")
_REPO = Path(__file__).resolve().parents[3]
_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
        "image/heic": ".heic", "image/heif": ".heif"}
MAX_PHOTOS = 6
PHOTO_MODEL = os.getenv("A4I_PHOTO_MODEL", config.MODEL)

HAZARD_TYPES = ["mold", "water_leak", "water_damage", "heating_problem", "pests", "electrical",
                "sewage", "structural", "broken_fixture", "fire_damage", "other"]

_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "photos": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "index": {"type": "INTEGER", "description": "0-based position of the photo in the request"},
                    "shows_housing_condition": {"type": "BOOLEAN"},
                    "summary": {"type": "STRING", "description": "One sentence: what the photo shows."},
                    "hazards": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "type": {"type": "STRING", "enum": HAZARD_TYPES},
                                "where": {"type": "STRING", "description": "Where in the image, e.g. 'ceiling corner above the shower'"},
                                "severity": {"type": "STRING", "enum": ["low", "moderate", "severe"]},
                                "confidence": {"type": "NUMBER", "description": "0 to 1"},
                                "visible_evidence": {"type": "STRING", "description": "What is visible that supports this"},
                            },
                            "required": ["type", "where", "severity", "confidence", "visible_evidence"],
                        },
                    },
                    "people_or_personal_info_visible": {"type": "BOOLEAN"},
                },
                "required": ["index", "shows_housing_condition", "summary", "hazards", "people_or_personal_info_visible"],
            },
        },
        "suggested_311_query": {
            "type": "STRING",
            "description": "A short 311 / building-inspection style description of the visible conditions, for a semantic search.",
        },
    },
    "required": ["photos", "suggested_311_query"],
}

_PROMPT = """You are assisting a San Francisco legal-aid paralegal. These photos were taken by a tenant.
For each photo, report only habitability conditions that are clearly VISIBLE: mold, water leaks or
damage, signs of heating failure (e.g. space heaters, frost, a broken radiator or thermostat), pests,
exposed wiring, sewage, structural damage, broken fixtures, fire damage.
- Do not guess what is not visible, and do not infer when or where the photo was taken.
- Never describe or identify people, and never read personal documents, screens or mail. Only set
  people_or_personal_info_visible = true if any are visible.
- If a photo does not show a housing condition, set shows_housing_condition = false and list no hazards.
- Severity: low = cosmetic, moderate = needs repair, severe = health or safety risk.
- suggested_311_query: describe the visible conditions the way a 311 or building-inspection complaint
  would (e.g. "black mold on bathroom ceiling, water leak under sink"). Empty string if none."""

CAVEATS = [
    "Tenant-provided photos: not a public record or an inspection finding.",
    "A photo cannot establish when or where it was taken; confirm with the tenant and the landlord record.",
]

_client: Any = None


def _gemini():
    global _client
    if _client is None:
        from google import genai  # installed with google-adk

        _client = genai.Client(vertexai=True, project=config.PROJECT,
                               location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    return _client


def _upload_dir() -> Path:
    return Path(os.getenv("A4I_UPLOAD_DIR", _REPO / ".run" / "uploads"))


def _load(photo_id: str) -> tuple[bytes, str]:
    if not _ID.match(photo_id or ""):
        raise ValueError("not a valid photo id")
    meta_path = _upload_dir() / f"{photo_id}.json"
    meta = json.loads(meta_path.read_text())
    mime = meta.get("mime", "")
    if meta.get("kind") != "image" or mime not in _EXT:
        raise ValueError("not an image upload")
    return (_upload_dir() / f"{photo_id}{_EXT[mime]}").read_bytes(), mime


def analyze_photos(photo_ids: list[str], focus: Optional[str] = None) -> dict:
    """Analyze tenant-provided photos for visible habitability hazards (Gemini vision).

    Call this first whenever the paralegal's message lists attached photo ids. Use the returned
    `suggested_311_query` and hazards to describe the problems when searching 311 evidence.
    Photos are tenant-provided: never cite them as 311 evidence or as proof of date or location.

    Args:
        photo_ids: The photo ids listed in the paralegal's message (32-character hex strings).
        focus: Optional problems the tenant reported, e.g. "mold and no heat", to look for first.

    Returns:
        `photos` (per photo: summary, hazards with type / where / severity / confidence /
        visible_evidence), `hazard_types` across all photos, `suggested_311_query`, `caveats`,
        and `skipped` ids that could not be read.
    """
    from google.genai import types

    parts, used, skipped = [], [], []
    for pid in list(photo_ids or [])[:MAX_PHOTOS]:
        try:
            data, mime = _load(str(pid))
        except Exception as e:
            skipped.append({"photo_id": pid, "reason": str(e)[:80]})
            continue
        parts.append(types.Part.from_bytes(data=data, mime_type=mime))
        used.append(pid)
    if not used:
        return {"error": "No readable photos for these ids.", "skipped": skipped}

    prompt = _PROMPT + (f"\nThe tenant reported: {focus}. Check for these first." if focus else "")
    try:
        resp = _gemini().models.generate_content(
            model=PHOTO_MODEL,
            contents=[*parts, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=_SCHEMA, temperature=0.1),
        )
        result = json.loads(resp.text)
    except Exception as e:
        return {"error": f"Photo analysis failed: {str(e)[:200]}", "skipped": skipped}

    photos = []
    for p in result.get("photos") or []:
        i = p.get("index")
        if isinstance(i, int) and 0 <= i < len(used):
            photos.append({"photo_id": used[i], **{k: v for k, v in p.items() if k != "index"}})
    hazard_types = sorted({h["type"] for p in photos for h in p.get("hazards") or []})
    severe = sorted({h["type"] for p in photos for h in p.get("hazards") or [] if h.get("severity") == "severe"})
    return {
        "photo_count": len(used),
        "photos": photos,
        "hazard_types": hazard_types,
        "severe_hazards": severe,
        "suggested_311_query": result.get("suggested_311_query", ""),
        "people_or_personal_info_visible": any(p.get("people_or_personal_info_visible") for p in photos),
        "caveats": CAVEATS,
        "skipped": skipped,
        "source": "tenant-provided photos, analyzed by Gemini vision",
    }
