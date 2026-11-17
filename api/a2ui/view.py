"""CaseState -> A2UI data models (one plain JSON object per surface).

The component trees in surfaces.py never change; only these data models do. Keeping the
formatting here (dates, tones, labels) means the agent never writes UI, and the renderer
never interprets raw tool output.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from urllib.parse import quote_plus
from typing import Any, Optional

from ..cases import TZ, CaseState, now

# --------------------------------------------------------------------------- formatting




DRAFT_STAMP = ("> **DRAFT – not reviewed by staff.** Written by the navigator agent; a paralegal must review it "
               "(Mark reviewed) before anyone relies on it.\n\n")

def _photo_hazards(photos: list[dict]) -> str:
    """'mold (severe), water damage (moderate)': the worst severity per hazard across the tenant's photos."""
    rank = {"low": 0, "moderate": 1, "severe": 2}
    worst: dict[str, str] = {}
    for ph in photos:
        for h in ph.get("hazards") or []:
            t, sv = (h.get("type") or "other").replace("_", " "), h.get("severity") or "low"
            if rank.get(sv, 0) >= rank.get(worst.get(t, "low"), 0):
                worst[t] = sv
    return ", ".join(f"{t} ({sv})" for t, sv in sorted(worst.items(), key=lambda x: -rank.get(x[1], 0)))

def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        if len(value) <= 10:
            d = date.fromisoformat(value)
            return datetime(d.year, d.month, d.day, tzinfo=TZ)
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=TZ)
    except ValueError:
        return None


def fmt_hearing(value: Optional[str]) -> str:
    dt = _parse_dt(value)
    if not dt:
        return "No hearing set"
    day = dt.strftime("%a %b ") + str(dt.day)
    if value and len(value) > 10:
        return f"{day} · {dt.strftime('%I:%M %p').lstrip('0')}"
    return day


def fmt_short_date(value: Any) -> str:
    if not value:
        return ""
    try:
        d = date.fromisoformat(str(value)[:10])
        return d.strftime("%b ") + str(d.day) + d.strftime(", %Y")
    except ValueError:
        return str(value)


def countdown(value: Optional[str]) -> tuple[str, Optional[float]]:
    dt = _parse_dt(value)
    if not dt:
        return "", None
    hours = (dt - now()).total_seconds() / 3600
    if hours < 0:
        return "Hearing date has passed: confirm it", hours
    days, rem = divmod(int(hours), 24)
    left = f"{days} day{'s' if days != 1 else ''} {rem} h left" if days else f"{rem} h left"
    return left, hours


def pct(v: Any) -> str:
    return "—" if v is None else f"{float(v):.1f}%"


def short_block(addr: str) -> str:
    return (addr or "").split(",")[0]


def title_case_status(s: str) -> str:
    return (s or "").replace(" - ", " – ")


# --------------------------------------------------------------------------- tones & labels

TONES = ("evidence", "excluded", "deadline", "eligible", "modeled", "neutral")

FIT = {
    "likely": ("Likely fit", "eligible"),
    "eligible": ("Eligible", "eligible"),
    "conditional": ("Conditional", "excluded"),
    "needs_info": ("Needs info", "neutral"),
    "not_eligible": ("Not eligible", "neutral"),
}

# Preconditions a statute needs before it helps THIS tenant. Shown as the "Needs:" line.
# The agent should send `needs` per statute (docs/AGENT_REQUIREMENTS.md R6); this map is
# the fallback, written from the statute text in municipal_housing_ordinance_statutes.
STATUTE_NEEDS = {
    "STAT-CA-01": "Needs: an official citation on her unit left unabated more than 35 days.",
    "STAT-CA-03": "Needs: a complaint to building inspection by or for the tenant within the last 180 days.",
    "STAT-CA-02": "Needs: the unlawful detainer service date (counsel within 30 days).",
}


def fund_fit(f: dict, case: CaseState) -> tuple[str, str, list[str]]:
    """(label, tone, missing_inputs). Uses the agent's `fit` when sent; else derives it."""
    fit = f.get("fit")
    missing = list(f.get("missing_inputs") or [])
    if not fit:
        why = (f.get("why") or "").lower()
        if f.get("eligible"):
            fit = "likely"
        elif case.income_pct_ami is None and "ami" in why:
            fit, missing = "needs_info", missing or ["income_pct_ami"]
        elif f.get("requires_open_habitability_case") and case.matches:
            fit, missing = "conditional", missing or ["unit_dbi_complaint"]
        else:
            fit = "not_eligible"
    label, tone = FIT.get(fit, ("Check", "neutral"))
    if fit == "needs_info" and missing == ["income_pct_ami"]:
        label = "Needs income"
    return label, tone, missing


MISSING_LABELS = {
    "income_pct_ami": "household income (% AMI)",
    "unit_dbi_complaint": "a DBI complaint on her unit",
    "wage_loss_or_medical_leave": "wage loss or medical leave",
    "household_size": "household size",
}


def exclusion_parts(row: dict) -> tuple[str, str]:
    """(short label, 'field = value → consequence')."""
    reason = row.get("reason") or ""
    status = row.get("inspection_status") or ""
    m = re.match(r"Case closed \((.+?), (\d{4}-\d{2}-\d{2})\)", reason)
    if reason.startswith("Commercial") or row.get("property_type") == "Commercial":
        return "Commercial", "property_type = Commercial → no residential tenant"
    if "no violation" in reason.lower() or status == "Closed - No Violation":
        return "No violation found", "inspection_status = Closed – No Violation → contradicts, doesn't corroborate"
    if m or row.get("closed_date"):
        st = title_case_status(m.group(1) if m else status) or "Closed"
        closed = m.group(2) if m else row.get("closed_date")
        return st, f"closed_date = {closed} → not an active hazard"
    return reason or "Excluded", reason


# --------------------------------------------------------------------------- per surface


def queue_model(cases: dict[str, CaseState], active_id: Optional[str]) -> dict:
    items = []
    for c in sorted(cases.values(), key=lambda c: (_parse_dt(c.hearing_datetime) or datetime.max.replace(tzinfo=TZ))):
        left, hours = countdown(c.hearing_datetime)
        if c.flag == "3-day notice" and not c.hearing_datetime:
            badge, tone = "3-day notice", "deadline"
        elif hours is None:
            badge, tone = "No hearing set", "neutral"
        elif hours <= 7 * 24:
            badge, tone = "Hearing " + fmt_hearing(c.hearing_datetime).replace(" · ", " "), "deadline"
        else:
            badge, tone = f"Hearing in {int(hours // 24)}d", "excluded"
        hh = f"household of {c.household_size}" if c.household_size and c.household_size > 1 else "single adult"
        items.append({
            "case_id": c.case_id,
            "badge": badge,
            "badge_tone": tone,
            "title": f"{c.client_initials} · {hh}",
            "subtitle": f"{short_block(c.block_address)} · {', '.join(c.hazards)}",
            "status": c.queue_status,
            "status_tone": c.queue_status_tone,
            "selected": c.case_id == active_id,
        })
    return {
        "title": "Today's intake",
        "meta": f"{len(items)} open · sorted by hearing",
        "cases": items,
        "footnote": "Intakes are sample cases. 311 rows, statutes, funds and tract figures come from the challenge dataset.",
    }


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _stages(c: CaseState) -> list[dict]:
    """Every stage of the case with what it actually found. state: done | current | todo | skipped | warn."""
    out: list[dict] = []

    # 1 · Intake
    facts = [x for x in (
        c.client_initials or None,
        f"household {c.household_size}" if c.household_size else None,
        f"{c.income_pct_ami:g}% AMI" if c.income_pct_ami is not None else None,
        (c.notice_type.split(" (")[0] + " served") if c.notice_type else None,
    ) if x]
    missing = [x for x, ok in (("income", c.income_pct_ami is not None), ("household", bool(c.household_size))) if not ok]
    out.append({"key": "intake", "label": "Intake", "state": "done" if c.block_address else "current",
                "detail": " · ".join(facts) or "Block and problems needed",
                "note": ("Missing: " + ", ".join(missing)) if c.block_address and missing else ""})

    # 2 · Tenant photos (optional)
    if not c.photos:
        out.append({"key": "photos", "label": "Tenant photos", "state": "skipped", "detail": "None attached (optional)"})
    else:
        analyzed = [p for p in c.photos if p.get("analyzed")]
        found = _photo_hazards(c.photos)
        out.append({"key": "photos", "label": "Tenant photos", "state": "done" if analyzed else "current",
                    "detail": f"{_plural(len(c.photos), 'photo')} · " + (found or "no visible hazard") if analyzed
                    else f"{_plural(len(c.photos), 'photo')} · not analyzed yet",
                    "note": "Tenant-provided, not 311 evidence"})

    # 3 · 311 evidence
    if not (c.matches or c.excluded):
        out.append({"key": "evidence", "label": "311 evidence", "state": "todo", "detail": "Vector search not run yet"})
    else:
        on_block = sum(1 for m in c.matches.values() if m.get("on_tenant_block"))
        nearby = len(c.matches) - on_block
        decoys = sum(1 for e in c.excluded.values() if e.get("planted_decoy") or str(e.get("request_id", "")).startswith("DECOY-"))
        out.append({"key": "evidence", "label": "311 evidence", "state": "done" if on_block else "warn",
                    "detail": f"{on_block} on block · {nearby} nearby · {len(c.excluded)} excluded ({decoys} decoys)",
                    "note": "" if on_block else "No open case on the tenant's block"})

    # 4 · Statutes
    if c.statutes:
        first = next(iter(c.statutes.values()))
        cite = (first.get("code_citation") or "").split(" & ")[0]
        out.append({"key": "statutes", "label": "Statutes", "state": "done",
                    "detail": f"{len(c.statutes)} matched · {cite}" if cite else f"{len(c.statutes)} matched"})
    else:
        out.append({"key": "statutes", "label": "Statutes", "state": "todo", "detail": "Not matched yet"})

    # 5 · Funds
    if c.funds:
        fits: dict[str, int] = {}
        for f in c.funds:
            k = f.get("fit") or ("likely" if f.get("eligible") else "not_eligible")
            fits[k] = fits.get(k, 0) + 1
        order = ["likely", "eligible", "conditional", "needs_info", "not_eligible"]
        detail = " · ".join(f"{fits[k]} {k.replace('_', ' ')}" for k in order if k in fits)
        good = fits.get("likely", 0) + fits.get("eligible", 0)
        out.append({"key": "funds", "label": "Funds", "state": "done" if good else "warn", "detail": detail,
                    "note": "" if good else "No program fits yet"})
    else:
        out.append({"key": "funds", "label": "Funds", "state": "todo",
                    "detail": "Needs income % AMI" if c.income_pct_ami is None else "Not checked yet"})

    # 6 · Neighborhood (tract)
    t = c.tract or {}
    if t.get("severe_rent_burden_pct") is not None:
        tp, mp = t.get("severe_rent_burden_pct"), t.get("metro_severe_rent_burden_pct")
        side = "" if mp is None else (" (higher)" if tp > mp else " (lower)")
        filings = t.get("annual_filings_modeled")
        out.append({"key": "tract", "label": "Neighborhood", "state": "done",
                    "detail": f"{tp}% rent-burdened vs {mp}% metro{side}"
                    + (f" · {filings} filings/yr" if filings is not None else ""),
                    "note": "Filings are modeled" if filings is not None else ""})
    else:
        out.append({"key": "tract", "label": "Neighborhood",
                    "state": "todo", "detail": f"Tract {c.census_tract_geoid}" if c.census_tract_geoid else "Tract not located yet"})

    # 7 · Equity audit (post-brief only)
    if c.equity:
        out.append({"key": "equity", "label": "Equity audit", "state": "done",
                    "detail": f"{c.equity.get('selected_tract_count', 1)} tract vs {c.equity.get('metro_tract_count', '?')} metro tracts",
                    "note": "Run after the brief; never used for ranking"})
    else:
        out.append({"key": "equity", "label": "Equity audit", "state": "todo",
                    "detail": "Runs after the brief" if not c.brief else "Not run"})

    # 8 · Memo & staff review
    if not c.memo_markdown:
        out.append({"key": "memo", "label": "Memo & review", "state": "todo", "detail": "Not drafted"})
    elif c.memo_status == "reviewed":
        out.append({"key": "memo", "label": "Memo & review", "state": "done", "detail": "Reviewed · ready for attorney"})
    else:
        out.append({"key": "memo", "label": "Memo & review", "state": "warn", "detail": "Draft · needs staff review",
                    "note": "Exports carry a DRAFT line"})

    # The first unfinished, non-optional stage is "current".
    if not any(s["state"] == "current" for s in out):
        for s in out:
            if s["state"] == "todo":
                s["state"] = "current"
                break
    for i, s in enumerate(out, 1):
        s["n"] = i
    return out


def header_model(c: CaseState) -> dict:
    left, hours = countdown(c.hearing_datetime)
    steps = _stages(c)
    if hours is None:
        detail = "Confirm the hearing date with the client"
    elif hours <= 72:
        detail = f"{left} · under 72 h: same-day steps and defenses first"
    else:
        detail = f"{left} · strategy: defense first"
    hazards = ", ".join(c.hazards) if c.hazards else "conditions not logged yet"
    notice = c.notice_type.split(" (")[0] if c.notice_type else ""
    sub = [short_block(c.block_address) or "Block not logged"]
    if c.census_tract_geoid:
        sub.append(f"Tract {c.census_tract_geoid}")
    sub.append("Residential")
    if notice:
        sub.append(f"{notice} served")
    return {
        "eyebrow": f"{c.case_id} · opened {c.opened_at.strftime('%a %b')} {c.opened_at.day}, {c.opened_at.strftime('%I:%M %p').lstrip('0')}",
        "title": f"{c.client_initials} — nonpayment, {hazards}",
        "subtitle": " · ".join(sub),
        "deadline": {
            "label": "Nonpayment hearing" if c.hearing_datetime else "Hearing",
            "value": fmt_hearing(c.hearing_datetime),
            "detail": detail,
            "tone": "deadline" if hours is not None and hours <= 7 * 24 else "neutral",
        },
        "steps": steps,
        "stub_note": ("Placeholder data from: " + ", ".join(sorted(c.stub_tools))) if c.stub_tools else "",
    }


def _evidence_item(c: CaseState, r: dict, focus: Optional[str]) -> dict:
    sim = float(r.get("similarity") or 0)
    weak = sim < 0.7
    if r.get("on_tenant_block"):
        badge, tone = "Same block", "evidence"
    elif c.census_tract_geoid and str(r.get("census_tract_geoid")) == c.census_tract_geoid:
        badge, tone = "Same tract", "neutral"
    else:
        badge, tone = "Adjacent tract", "neutral"
    if weak:
        badge, tone = f"Weak · {badge.lower()}", "neutral"
    narrative = (r.get("narrative") or "").strip()
    if len(narrative) > 220:
        narrative = narrative[:217].rstrip() + "…"
    meta = " · ".join(x for x in [
        r.get("raw_complaint_type"), title_case_status(r.get("inspection_status") or ""),
        ("filed " + fmt_short_date(r.get("created_date"))) if r.get("created_date") else "",
    ] if x)
    return {
        "request_id": r["request_id"],
        "badge": badge,
        "badge_tone": tone,
        "title": short_block(r.get("block_address", "")),
        "meta": meta,
        "quote": f"“{narrative}”" if narrative else "",
        "similarity": round(sim, 2),
        "weak": weak,
        "focused": r["request_id"] == focus,
        "updated": r["request_id"] in c.changed_this_turn,
        "provenance": "public record",
    }


def _excluded_item(c: CaseState, r: dict, focus: Optional[str]) -> dict:
    label, detail = exclusion_parts(r)
    rank = c.raw_rank(r["request_id"])
    sim = float(r.get("similarity") or 0)
    head = f"{r['request_id']} · raw #{rank} · {sim:.2f}" if rank else f"{r['request_id']} · {sim:.2f}"
    narrative = (r.get("narrative") or r.get("raw_complaint_type") or "").strip()
    if len(narrative) > 140:
        narrative = narrative[:137].rstrip() + "…"
    return {
        "request_id": r["request_id"],
        "heading": head,
        "label": label,
        "summary": narrative,
        "detail": detail,
        "focused": r["request_id"] == focus,
        "ask": f"Why did you exclude {r['request_id']}?",
    }


def _statute_item(c: CaseState, s: dict, primary: bool) -> dict:
    sid = s.get("statute_section_id", "")
    needs = s.get("needs") or STATUTE_NEEDS.get(sid, "")
    if sid == "STAT-CA-01" and not s.get("needs"):
        on_block = [r for r in c.matches.values() if r.get("on_tenant_block") and r.get("created_date")]
        if on_block:
            opened = min(date.fromisoformat(str(r["created_date"])[:10]) for r in on_block)
            days = (now().date() - opened).days
            needs += f" Block case opened {opened.strftime('%b')} {opened.day} = {days} days → {'over' if days > 35 else 'under'} 35."
    return {
        "statute_id": sid,
        "citation": s.get("code_citation", ""),
        "title": s.get("ordinance_title", ""),
        "protection": s.get("protection") or s.get("text") or "",
        "applies_because": s.get("applies_because") or "",
        "needs": needs,
        "primary": primary,
        "updated": sid in c.changed_this_turn,
    }


def _fund_item(c: CaseState, f: dict) -> dict:
    label, tone, missing = fund_fit(f, c)
    checks = []
    if f.get("residential_tenants_only", True):
        checks.append("✓ Residential")
    if f.get("requires_open_habitability_case"):
        checks.append("✓ Open habitability case on block" if c.matches else "✗ Open habitability case")
    else:
        checks.append("✓ No open case required")
    checks += [f"? {MISSING_LABELS.get(m, m.replace('_', ' '))}" for m in missing]
    return {
        "name": f.get("program_name", ""),
        "agency": f.get("administering_agency", ""),
        "fit_label": label,
        "fit_tone": tone,
        "why": f.get("why", ""),
        "checklist": " · ".join(checks),
        "intake_url": f.get("intake_url") or "",
        "intake_label": (f.get("intake_url") or "").replace("https://", "").rstrip("/"),
    }


def _tract_tiles(c: CaseState) -> list[dict]:
    t = c.tract or {}
    tiles = [
        {"label": "Severe rent burden (50%+)", "value": pct(t.get("severe_rent_burden_pct")),
         "note": f"metro {pct(t.get('metro_severe_rent_burden_pct'))}", "modeled": False},
        {"label": "Nonpayment filings / yr", "value": "—" if t.get("annual_filings_modeled") is None else str(t["annual_filings_modeled"]),
         "note": (f"{t['annual_filings_percentile']}th pct of SF tracts" if t.get("annual_filings_percentile") is not None else "sum of 4 quarters"),
         "modeled": True},
    ]
    if t.get("median_claimed_arrears_usd") is not None:
        tiles.append({"label": "Median claimed arrears", "value": f"${int(t['median_claimed_arrears_usd']):,}",
                      "note": t.get("arrears_quarter", ""), "modeled": True})
    if t.get("poverty_rate_pct") is not None:
        tiles.append({"label": "Poverty rate", "value": pct(t["poverty_rate_pct"]),
                      "note": f"metro tract avg {pct(t.get('metro_poverty_rate_pct'))}", "modeled": False})
    return tiles


def documents_model(c: CaseState) -> dict:
    ev = [_evidence_item(c, r, c.focus_id) for r in c.evidence_rows]
    ex = [_excluded_item(c, r, c.focus_id) for r in c.excluded_rows]
    statute_rows = list(c.statutes.values())
    if c.brief and c.brief.get("statutes"):
        cited = [s["statute_section_id"] for s in c.brief["statutes"]]
        statute_rows = [c.statutes.get(sid, s) | s for sid, s in zip(cited, c.brief["statutes"])]
    statute_rows.sort(key=lambda s: -float(s.get("similarity") or 0))
    st = [_statute_item(c, s, i == 0) for i, s in enumerate(statute_rows)]
    fu = [_fund_item(c, f) for f in c.funds]
    order = {"eligible": 0, "excluded": 1, "neutral": 2}
    fu.sort(key=lambda f: order.get(f["fit_tone"], 3))
    t = c.tract or {}
    searched = "corroborate" if (c.matches or c.excluded) else ""
    return {
        "active_tab": c.active_tab,
        "tabs": {
            "evidence": f"Evidence ({len(ev)})" if searched else "Evidence",
            "statutes": f"Statutes ({len(st)})" if st else "Statutes",
            "funds": f"Funds ({len(fu)})" if fu else "Funds",
            "tract": "Tract",
            "memo": "Memo",
        },
        "evidence": ev,
        "evidence_empty": "" if searched else "No search yet. Describe the tenant's block and conditions in the chat and the navigator will run BigQuery vector search over 311 records.",
        "evidence_none_found": "Vector search found no open residential record that matches. Excluded look-alikes are listed below." if searched and not ev else "",
        "excluded": ex,
        "excluded_title": f"Excluded by filter ({len(ex)}): why they can't be used" if searched else "",
        "excluded_open": bool(ex),
        "photos": [{"url": ph["url"], "name": ph.get("name", "photo"), "caption": ph.get("caption", ""),
                    "hazards": ph.get("hazards") or [], "analyzed": bool(ph.get("analyzed")),
                    "people_visible": bool(ph.get("people_visible"))} for ph in c.photos],
        "photos_title": (f"Tenant-provided photos ({len(c.photos)})"
                         + (" · analyzed by Gemini vision" if any(ph.get("analyzed") for ph in c.photos) else "")) if c.photos else "",
        "photos_note": ("From the tenant, not a public record or an inspection finding, and no proof of when or where they "
                        "were taken. Attach them to the DBI complaint and the attorney packet.") if c.photos else "",
        "boundary_note": ("**What the public record cannot prove:** 311 rows are redacted to the 100-block. They show the building has "
                          "open hazards, not that *her unit* is cited. Ask for photos, texts to the landlord, and her own DBI complaint number."),
        "statutes": st,
        "statutes_empty": "" if st else "No statute matched yet. Ask which statute covers a habitability defense.",
        "funds": fu,
        "funds_meta": f"AMI: {c.income_pct_ami:g}%" if c.income_pct_ami is not None else "AMI: not given yet",
        "funds_empty": "" if fu else "Fund fit not checked yet. Ask which fund fits before the hearing.",
        "tract_title": f"Tract {c.census_tract_geoid} vs. San Francisco" if c.census_tract_geoid else "Tract not located yet",
        "tract_tiles": _tract_tiles(c) if t else [],
        "tract_note": ("Filings are summed over 4 quarters before joining, so nothing is counted 4×. "
                       "Modeled baselines, not a court docket.") if t else "Ask how severe eviction pressure is in this tract.",
        "memo": {
            "markdown": c.memo_markdown or "_No memo yet. Ask the navigator to draft the intake memo for the attorney._",
            "status_label": "Reviewed" if c.memo_status == "reviewed" else ("Unreviewed draft" if c.memo_markdown else "Not drafted"),
            "status_tone": "eligible" if c.memo_status == "reviewed" else "excluded",
            "has_memo": bool(c.memo_markdown),
        },
        "brief_ready": c.brief is not None,
        "brief_cta": "Open Tenant Stabilization Brief →" if c.brief else "Brief appears once the navigator submits it",
    }


def suggestions_model(c: CaseState) -> dict:
    return {"items": [{"text": s} for s in c.suggestions]}


def default_suggestions(c: CaseState) -> list[str]:
    done = {
        "corroborate": bool(c.matches or c.excluded),
        "tract": bool(c.tract and c.tract.get("severe_rent_burden_pct") is not None),
    }
    if not done["corroborate"]:
        return ["Any open residential complaints on her block?"]
    out = []
    asked = " ".join(t.text.lower() for t in c.transcript if t.role == "user")
    if c.excluded and "exclude" not in asked:
        out.append("Why did you exclude the top raw match?")
    if not c.statutes:
        out.append("Which statute bars the rent demand?")
    if not c.funds:
        out.append("Which fund fits before the hearing?")
    if not done["tract"]:
        out.append("How bad is eviction pressure here?")
    if not c.memo_markdown:
        out.append("Draft the intake memo")
    return out[:4] or ["What should she bring to the hearing?"]


def brief_model(c: CaseState) -> dict:
    """The printable Tenant Stabilization Brief. Only rendered from a submitted brief."""
    b = c.brief or {}
    doc = documents_model(c)
    ev_rows = [[e["request_id"], e["title"] + (" (same block)" if e["badge"] == "Same block" else ""),
                e["quote"].strip("“”")[:110], e["meta"].split(" · ")[1] if " · " in e["meta"] else e["meta"], f"{e['similarity']:.2f}"]
               for e in doc["evidence"]]
    ex = doc["excluded"]
    excluded_line = (f"**Excluded after vector search ({len(ex)}):** " + " · ".join(f"{x['request_id']} {x['label']}" for x in ex)
                     + ". Filter: property_type = Residential AND closed_date IS NULL AND status ≠ No Violation.") if ex else \
        "**Excluded after vector search:** none."
    fund_rows = [[f["name"] + "\n" + f["agency"], f["fit_label"], f["why"], f["intake_label"]] for f in doc["funds"]]
    tiles = doc["tract_tiles"]
    tract_rows = [[t["label"] + (" (modeled)" if t["modeled"] else ""), f"{t['value']}  {t['note']}"] for t in tiles]
    eq = c.equity or {}
    equity_rows = [[r["group"] + " share", f"{r['tract_pct']:.1f}% vs {r['metro_pct']:.1f}%"] for r in eq.get("rows", [])]
    cannot = b.get("cannot_prove") or []
    left, _ = countdown(c.hearing_datetime)
    prepared = c.brief_prepared_at or now()
    return {
        "eyebrow": f"TENANT STABILIZATION BRIEF · {c.case_id} · DRAFT FOR ATTORNEY REVIEW",
        "title": f"{c.client_initials} — {short_block(c.block_address)}, San Francisco",
        "subtitle": " · ".join(x for x in ["Nonpayment", (c.notice_type.split(' (')[0] + ' served') if c.notice_type else "",
                                            "Residential", f"Tract {c.census_tract_geoid}" if c.census_tract_geoid else ""] if x),
        "hearing_label": "Hearing",
        "hearing": fmt_hearing(c.hearing_datetime),
        "prepared": f"Prepared {prepared.strftime('%a %b')} {prepared.day}, {prepared.strftime('%I:%M %p').lstrip('0')}",
        "evidence_columns": ["Request ID", "Block", "Condition", "Status", "Sim."],
        "evidence_rows": ev_rows,
        "excluded_line": excluded_line,
        "statutes": doc["statutes"],
        "fund_columns": ["Program", "Fit", "Why", "Intake"],
        "fund_rows": fund_rows,
        "tract_rows": tract_rows,
        "equity_rows": equity_rows,
        "equity_note": b.get("equity_note") or ("Equity audit not run yet." if not eq else eq.get("baseline", "")),
        "photos_line": (f"**Tenant-provided photos:** {len(c.photos)} attached in the case file"
                        + (f", showing {_photo_hazards(c.photos)}" if _photo_hazards(c.photos) else "")
                        + ". They show what the tenant photographed; they are not a public record or an inspection finding.") if c.photos else "",
        "cannot_prove": "\n".join(f"- {x}" for x in cannot) or "- 311 records show conditions on the block, not inside this tenant's unit",
        # Unreviewed memos are never blocked from printing, but always carry the draft line.
        "memo": (DRAFT_STAMP + c.memo_markdown) if c.memo_markdown and c.memo_status != "reviewed" else c.memo_markdown,
        "memo_status": doc["memo"]["status_label"],
        "sources": "Sources: SF 311 (public, 100-block) · ACS 5-Year · statute & bulletin text (public) · court filings (modeled)",
        "signoff": "Reviewed by: ____________ · Date: ______",
        "stub_note": ("Some sections use placeholder tool output: " + ", ".join(sorted(c.stub_tools))) if c.stub_tools else "",
        "countdown": left,
    }


def intake_form_model() -> dict:
    return {
        "form": {"client": "", "block": "", "issue": "", "hearing": "", "notice": ["nonpayment"],
                 "household": "", "ami": ""},
    }


def street_address(block_address: str) -> str:
    """'600 Block John Muir Dr, San Francisco, CA' / '400 block of Eddy St' -> '600 John Muir Dr, San Francisco, CA'."""
    addr = re.sub(r"\b(\d+)\s+block\s+(?:of\s+)?", r"\1 ", block_address or "", flags=re.I).strip()
    if addr and "san francisco" not in addr.lower():
        addr += ", San Francisco, CA"
    return addr


def map_model(c: CaseState) -> dict:
    """Where the tenant's block is, with the corroborating 311 records that carry coordinates."""
    markers, center = [], None
    for r in c.evidence_rows:
        lat, lng = r.get("latitude"), r.get("longitude")
        if lat is None or lng is None:
            continue
        on_block = bool(r.get("on_tenant_block"))
        markers.append({"id": r["request_id"], "lat": float(lat), "lng": float(lng),
                        "label": f"{r['request_id']} · {short_block(r.get('block_address', ''))}",
                        "kind": "same_block" if on_block else "nearby"})
        if on_block and center is None:
            center = {"lat": float(lat), "lng": float(lng)}
    addr = street_address(c.block_address)
    return {
        "title": short_block(c.block_address) or "No block logged",
        "meta": "Block level only",
        "address": addr,
        "center": center,
        "markers": markers,
        "maps_key": os.getenv("GOOGLE_MAPS_API_KEY", ""),
        "open_url": f"https://www.google.com/maps/search/?api=1&query={quote_plus(addr)}" if addr else "",
        "note": (f"Red pin: the tenant's block. Blue pins: {len(markers)} open 311 record{'s' if len(markers) != 1 else ''} "
                 "cited as evidence. 311 data is redacted to the 100-block, so pins mark blocks, not units.")
                if markers else "Pins for cited 311 records appear after the first search. Addresses are block level only.",
    }
