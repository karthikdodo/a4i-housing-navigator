"""Uploads (tenant photos, voice clips), speech-to-text, and voice intake parsing.

Transcription
  * Gemini on Vertex AI (same project and credentials as the agent) when it is reachable:
    the audio clip goes to `A4I_TRANSCRIBE_MODEL` (default gemini-2.5-flash) for a verbatim transcript.
  * Otherwise the browser's own live transcript (Web Speech API), sent with the clip.
  A4I_TRANSCRIBE = auto (default: Gemini in live mode, browser in demo mode) | gemini | browser.

Voice intake
  The paralegal speaks the intake ("Tenant M R, 600 block of John Muir Drive, mold and no heat,
  hearing Monday 9 AM, household of three"). `parse_intake` turns the transcript into the New
  intake form's fields: Gemini structured output when available, else the rule-based parser here.
  Names never survive: they become initials before anything is stored or shown.

Uploads are kept on local disk (A4I_UPLOAD_DIR, default .run/uploads). Cloud Run's disk is
per-instance and temporary, which matches the in-memory sessions (max-instances=1).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .cases import TZ, now

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
UPLOAD_DIR = Path(os.getenv("A4I_UPLOAD_DIR", ROOT / ".run" / "uploads"))

IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
               "image/heic": ".heic", "image/heif": ".heif"}
AUDIO_TYPES = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/mpeg": ".mp3",
               "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/x-m4a": ".m4a", "audio/aac": ".aac"}
MAX_BYTES = {"image": 10 * 1024 * 1024, "audio": 15 * 1024 * 1024}
_ID = re.compile(r"^[a-f0-9]{32}$")


@dataclass
class Upload:
    id: str
    kind: str  # image | audio
    mime: str
    name: str
    size: int
    created_at: str

    @property
    def url(self) -> str:
        return f"/api/uploads/{self.id}"

    def to_json(self) -> dict:
        return {**asdict(self), "url": self.url}


class UploadError(ValueError):
    pass


def save_upload(data: bytes, mime: str, name: str) -> Upload:
    mime = (mime or "").split(";")[0].strip().lower()
    if mime in IMAGE_TYPES:
        kind, ext = "image", IMAGE_TYPES[mime]
    elif mime in AUDIO_TYPES:
        kind, ext = "audio", AUDIO_TYPES[mime]
    else:
        raise UploadError(f"Unsupported file type {mime or 'unknown'}. Photos: JPEG, PNG, WebP, GIF, HEIC. Audio: WebM, Ogg, M4A, MP3, WAV.")
    if not data:
        raise UploadError("The file is empty.")
    if len(data) > MAX_BYTES[kind]:
        raise UploadError(f"File too large ({len(data) // 1024} KB). Limit for {kind}: {MAX_BYTES[kind] // (1024 * 1024)} MB.")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    up = Upload(id=uuid.uuid4().hex, kind=kind, mime=mime, size=len(data), created_at=now().isoformat(),
                name=re.sub(r"[^\w.\- ]", "_", Path(name or f"upload{ext}").name)[:80] or f"upload{ext}")
    (UPLOAD_DIR / f"{up.id}{ext}").write_bytes(data)
    (UPLOAD_DIR / f"{up.id}.json").write_text(json.dumps(asdict(up)))
    return up


def get_upload(upload_id: str) -> tuple[Upload, Path]:
    if not _ID.match(upload_id or ""):
        raise FileNotFoundError(upload_id)
    meta = UPLOAD_DIR / f"{upload_id}.json"
    if not meta.exists():
        raise FileNotFoundError(upload_id)
    up = Upload(**json.loads(meta.read_text()))
    ext = IMAGE_TYPES.get(up.mime) or AUDIO_TYPES.get(up.mime) or ""
    return up, UPLOAD_DIR / f"{up.id}{ext}"


# ------------------------------------------------------------------ Gemini (optional)

_client: Any = None
_client_failed = False


def _gemini() -> Any:
    """A google-genai client on Vertex AI, or None when unavailable (no package / no credentials)."""
    global _client, _client_failed
    if _client is not None or _client_failed:
        return _client
    try:
        from google import genai  # installed with google-adk (agent/requirements.txt)

        _client = genai.Client(
            vertexai=True,
            project=os.getenv("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-04-3b4b41069fc3"),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )
    except Exception as e:  # ImportError, DefaultCredentialsError, ...
        log.info("Gemini unavailable for transcription (%s); using the browser transcript.", e)
        _client_failed = True
    return _client


def use_gemini(agent_mode: str) -> bool:
    pref = os.getenv("A4I_TRANSCRIBE", "auto").lower()
    if pref == "browser":
        return False
    if pref == "gemini" or agent_mode == "live":
        return _gemini() is not None
    return False


MODEL = os.getenv("A4I_TRANSCRIBE_MODEL", "gemini-2.5-flash")

_TRANSCRIBE_PROMPT = (
    "Transcribe this audio verbatim in the language spoken. It is a legal-aid paralegal talking about a "
    "tenant's housing case in San Francisco. Keep numbers, street names and dates exactly as said. "
    "Return only the transcript text, no commentary."
)


async def transcribe(audio: bytes, mime: str, browser_text: str, agent_mode: str) -> dict:
    browser_text = (browser_text or "").strip()
    if use_gemini(agent_mode):
        try:
            from google.genai import types

            resp = await asyncio.to_thread(
                _gemini().models.generate_content,
                model=MODEL,
                contents=[types.Part.from_bytes(data=audio, mime_type=mime.split(";")[0]), _TRANSCRIBE_PROMPT],
            )
            text = (resp.text or "").strip()
            if text:
                return {"text": text, "source": "gemini"}
        except Exception as e:
            log.warning("Gemini transcription failed: %s", e)
    if browser_text:
        return {"text": browser_text, "source": "browser"}
    return {"text": "", "source": "none"}


# ------------------------------------------------------------------ voice intake

INTAKE_FIELDS = ("client", "block", "issue", "hearing", "notice", "household", "ami")

_INTAKE_PROMPT = """Extract intake fields from this transcript of a legal-aid paralegal describing a tenant.
Today is {today} (America/Los_Angeles). Return JSON with these keys, empty string when not said:
- client: the tenant's INITIALS only, like "M.R." (never a full name)
- block: the block or street address, like "600 block of John Muir Dr"
- issue: the housing conditions, in the tenant's words
- hearing: hearing date and time as YYYY-MM-DDTHH:MM (or YYYY-MM-DD if no time)
- notice: one of nonpayment | unlawful_detainer | holdover | none
- household: number of people, digits only
- ami: household income as percent of Area Median Income, digits only
Transcript:
{text}"""


_NAME = re.compile(r"\b(?i:tenant|client)(?:'s name)?\s+(?:is\s+|named\s+)?((?:[A-Z][a-z'-]+\s?){2,3})")


def redact_names(text: str) -> str:
    """'Tenant Maria Rodriguez' -> 'Tenant M.R.' everywhere in the text. Intake keeps initials only."""
    for m in list(_NAME.finditer(text or "")):
        name = m.group(1).strip()
        initials = "".join(w[0] + "." for w in name.split())
        text = re.sub(rf"\b{re.escape(name)}\b", initials, text)
        for w in name.split():  # a later "Maria" or "Ms. Rodriguez" on its own
            text = re.sub(rf"\b{re.escape(w)}\b", w[0] + ".", text)
    return text


async def parse_intake(text: str, agent_mode: str) -> dict:
    text = redact_names(text)
    if use_gemini(agent_mode):
        try:
            from google.genai import types

            schema = {"type": "OBJECT", "properties": {k: {"type": "STRING"} for k in INTAKE_FIELDS}}
            resp = await asyncio.to_thread(
                _gemini().models.generate_content,
                model=MODEL,
                contents=_INTAKE_PROMPT.format(today=now().strftime("%A %Y-%m-%d"), text=text),
                config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema),
            )
            fields = {k: str(v).strip() for k, v in json.loads(resp.text or "{}").items() if k in INTAKE_FIELDS and v}
            return {**_normalize(fields), "_source": "gemini"}
        except Exception as e:
            log.warning("Gemini intake parsing failed, using rules: %s", e)
    return {**rule_parse_intake(text), "_source": "rules"}


_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
              "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_SUFFIX = r"(?:street|st|avenue|ave|av|drive|dr|boulevard|blvd|road|rd|way|court|ct|place|pl|terrace|ter|lane|ln|alley|aly)"
_HAZ = ("mold", "heat", "leak", "water", "sewage", "wiring", "pest", "roach", "rodent", "mice", "rat", "fire",
        "power", "sink", "toilet", "ceiling", "plumbing", "gas", "lead", "smoke", "broken", "door", "window", "lock")


def _num(tok: str) -> Optional[int]:
    tok = tok.lower()
    return int(tok) if tok.isdigit() else _NUM_WORDS.get(tok)


def rule_parse_intake(text: str) -> dict:
    text = redact_names(text or "")
    t = " " + text.strip() + " "
    low = t.lower()
    out: dict[str, str] = {}

    # Initials: "tenant M R", "client M.R.", "initials M R", or a name after tenant/client -> initials.
    m = re.search(r"\b(?i:initials?|tenant|client)\s+(?:is\s+)?((?:[A-Z]\.?\s?){1,3})(?=[\s,.]|$)", t)
    if m and re.fullmatch(r"(?:[A-Z]\.?\s?){1,3}", m.group(1).strip()):
        out["client"] = ".".join(re.findall(r"[A-Z]", m.group(1))) + "."
    else:
        m = re.search(r"\b(?i:tenant|client)(?:'s name)?\s+(?:is\s+)?((?:[A-Z][a-z]+\s?){1,3})", t)
        if m:
            out["client"] = "".join(w[0] + "." for w in m.group(1).split()[:3])

    # Block / address
    m = re.search(rf"\b(\d{{2,5}})\s+(?:block\s+(?:of\s+)?)?((?:[A-Za-z0-9]+\s){{0,3}}?[A-Za-z0-9]+\s{_SUFFIX})\b", t, re.I)
    if m:
        hundred = int(m.group(1)) // 100 * 100
        out["block"] = f"{hundred} block of {m.group(2).strip()}"

    # Issue: sentences that mention a condition, else the whole text.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    haz = re.compile(r"\b(?:" + "|".join(_HAZ) + r")s?\b", re.I)
    hits = [s for s in sentences if haz.search(s)]
    out["issue"] = " ".join(hits) if hits else text.strip()

    # Hearing date + time
    today = now().date()
    date = None
    if "tomorrow" in low:
        date = today + timedelta(days=1)
    elif re.search(r"\btoday\b", low):
        date = today
    else:
        m = re.search(r"\b(20\d\d)-(\d\d)-(\d\d)\b", low)
        if m:
            date = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        else:
            m = re.search(r"\b(" + "|".join(_MONTHS) + r")[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", low)
            if m:
                mon = _MONTHS.index(m.group(1)) + 1
                year = today.year + (1 if (mon, int(m.group(2))) < (today.month, today.day) else 0)
                date = datetime(year, mon, int(m.group(2))).date()
            else:
                m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", low)
                if m:
                    mon, day = int(m.group(1)), int(m.group(2))
                    year = today.year + (1 if (mon, day) < (today.month, today.day) else 0)
                    date = datetime(year, mon, day).date()
                else:
                    m = re.search(r"\b(next\s+)?(" + "|".join(_DAYS) + r")\b", low)
                    if m:
                        ahead = (_DAYS.index(m.group(2)) - today.weekday()) % 7 or 7
                        date = today + timedelta(days=ahead + (7 if m.group(1) and ahead < 7 else 0))
    if date:
        hearing = date.isoformat()
        m = re.search(r"\b(\d{1,2})(?::(\d\d))?\s*(a\.?m\.?|p\.?m\.?)", low)
        if m:
            hour = int(m.group(1)) % 12 + (12 if m.group(3).startswith("p") else 0)
            hearing += f"T{hour:02d}:{int(m.group(2) or 0):02d}"
        out["hearing"] = hearing

    # Notice
    if re.search(r"unlawful detainer|\bud\b|summons", low):
        out["notice"] = "unlawful_detainer"
    elif re.search(r"holdover|no.fault|owner move", low):
        out["notice"] = "holdover"
    elif re.search(r"3.day|three.day|pay or quit|pay-or-quit|nonpayment|unpaid rent|behind on rent", low):
        out["notice"] = "nonpayment"

    # Household size
    m = re.search(r"household of (\w+)|(\w+) (?:people|persons|person household|in the household|family members)", low)
    if m:
        n = _num(m.group(1) or m.group(2))
        if n:
            out["household"] = str(n)

    # Income as % AMI
    m = re.search(r"(\d{1,3})\s*(?:%|percent)\s*(?:of\s+)?(?:the\s+)?(?:ami|a\.m\.i\.|area median)", low)
    if m:
        out["ami"] = m.group(1)
    return _normalize(out)


def _normalize(fields: dict) -> dict:
    out = {k: v for k, v in fields.items() if k in INTAKE_FIELDS and v not in (None, "")}
    if out.get("client") and not re.fullmatch(r"(?:[A-Z]\.){1,3}", out["client"]):
        letters = [w[0].upper() for w in re.findall(r"[A-Za-z]+", out["client"])][:3]
        out["client"] = "".join(f"{x}." for x in letters)
    if out.get("notice") not in (None, "nonpayment", "unlawful_detainer", "holdover", "none"):
        out.pop("notice", None)
    for k in ("household", "ami"):
        if k in out and not str(out[k]).isdigit():
            digits = re.findall(r"\d+", str(out[k]))
            out[k] = digits[0] if digits else ""
            if not out[k]:
                out.pop(k)
    return out


def tz_today() -> str:
    return datetime.now(TZ).date().isoformat()
