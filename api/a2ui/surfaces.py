"""A2UI v1.0 surfaces for the Stabilization Navigator.

Each surface is a fixed component tree (adjacency list) plus a data model built by view.py.
The server sends `createSurface` (components + dataModel) once per connection, then only
`updateDataModel` as the case changes. The agent never writes components, so it cannot put
an unverified record on screen: every value bound here comes from a tool result.

Components come from one catalog, NAVIGATOR_CATALOG_ID: the A2UI v1.0 basic catalog
(Column, Row, Text, Button, TextField, ...) plus the navigator's own components (Badge,
RecordCard, ExcludedCard, ...). Its definition is api/a2ui/navigator_catalog.json, served at
GET /api/a2ui/catalog; the React renderer implements it in ui/src/a2ui/catalog.tsx.
"""

from __future__ import annotations

from typing import Any

A2UI_VERSION = "1.0"
NAVIGATOR_CATALOG_ID = "https://a4i-housing-navigator.dev/a2ui/v1/navigator_catalog.json"
BASIC_CATALOG_ID = "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"

# Surface ids (unique among the surfaces of one connection).
QUEUE = "intake_queue"
HEADER = "case_header"
DOCUMENTS = "case_documents"
SUGGESTIONS = "suggested_questions"
BRIEF = "stabilization_brief"
INTAKE_FORM = "new_intake_form"
MAP = "case_map"

SURFACES = (QUEUE, HEADER, MAP, SUGGESTIONS, DOCUMENTS, BRIEF, INTAKE_FORM)


def P(path: str) -> dict:
    """A data binding. Absolute when it starts with '/', else relative to a template item."""
    return {"@path": path}


def event(name: str, **context: Any) -> dict:
    return {"event": {"name": name, "context": context}} if context else {"event": {"name": name}}


def open_url(path: str) -> dict:
    return {"functionCall": {"@call": "openUrl", "args": {"url": P(path)}}}


def text(cid: str, value: Any, variant: str = "body") -> dict:
    return {"id": cid, "component": "Text", "text": value, "variant": variant}


def button(cid: str, label: Any, action: dict, variant: str = "default", **extra: Any) -> list[dict]:
    return [
        {"id": cid, "component": "Button", "child": f"{cid}_label", "variant": variant, "action": action, **extra},
        text(f"{cid}_label", label),
    ]


def icon_button(cid: str, icon: str, label: Any, action: dict, variant: str = "default", **extra: Any) -> dict:
    """Navigator IconButton: a lucide icon + label (icons named in ui/src/a2ui/catalog.tsx ICONS)."""
    return {"id": cid, "component": "IconButton", "icon": icon, "label": label, "variant": variant, "action": action, **extra}


def column(cid: str, children: Any, **extra: Any) -> dict:
    return {"id": cid, "component": "Column", "children": children, "align": "stretch", **extra}


def template(component_id: str, path: str) -> dict:
    return {"componentId": component_id, "path": path}


# --------------------------------------------------------------------------- component trees


def queue_components() -> list[dict]:
    return [
        column("root", ["q_new", "q_title", "q_list", "q_foot"]),
        icon_button("q_new", "userPlus", "New intake", event("open_intake_form"), "primary", block=True),
        {"id": "q_title", "component": "SectionTitle", "icon": "users", "text": P("/title"), "meta": P("/meta")},
        column("q_list", template("q_item", "/cases")),
        {"id": "q_item", "component": "QueueItem", "caseId": P("case_id"), "badge": P("badge"),
         "badgeTone": P("badge_tone"), "title": P("title"), "subtitle": P("subtitle"),
         "status": P("status"), "statusTone": P("status_tone"), "selected": P("selected"),
         "action": event("open_case", case_id=P("case_id"))},
        text("q_foot", P("/footnote"), "caption"),
    ]


def header_components() -> list[dict]:
    return [
        column("root", ["hdr_row", "hdr_steps", "hdr_stub"]),
        {"id": "hdr_row", "component": "Wrap", "children": ["hdr_case", "hdr_deadline"], "justify": "spaceBetween"},
        {"id": "hdr_case", "component": "CaseHeader", "eyebrow": P("/eyebrow"), "title": P("/title"),
         "subtitle": P("/subtitle")},
        {"id": "hdr_deadline", "component": "DeadlineCard", "label": P("/deadline/label"),
         "value": P("/deadline/value"), "detail": P("/deadline/detail"), "tone": P("/deadline/tone")},
        {"id": "hdr_steps", "component": "StepTracker", "steps": P("/steps")},
        {"id": "hdr_stub", "component": "Callout", "text": P("/stub_note"), "tone": "excluded"},
    ]


def suggestions_components() -> list[dict]:
    return [
        {"id": "root", "component": "Wrap", "children": template("sg_item", "/items")},
        icon_button("sg_item", "sparkles", P("text"), event("ask", text=P("text")), "chip"),
    ]


def documents_components() -> list[dict]:
    return [
        column("root", ["d_tabs", "d_cta"]),
        {"id": "d_tabs", "component": "PanelTabs", "active": P("/active_tab"), "focusSeq": P("/focus_seq"),
         "tabs": [
             {"key": "evidence", "title": P("/tabs/evidence"), "child": "tab_ev"},
             {"key": "statutes", "title": P("/tabs/statutes"), "child": "tab_st"},
             {"key": "funds", "title": P("/tabs/funds"), "child": "tab_fu"},
             {"key": "tract", "title": P("/tabs/tract"), "child": "tab_tr"},
             {"key": "memo", "title": P("/tabs/memo"), "child": "tab_memo"},
         ]},
        # Evidence
        column("tab_ev", ["ev_photos", "ev_title", "ev_empty", "ev_none", "ev_list", "ex_box", "ev_boundary"]),
        {"id": "ev_photos", "component": "PhotoGallery", "title": P("/photos_title"), "note": P("/photos_note"),
         "photos": P("/photos")},
        {"id": "ev_title", "component": "SectionTitle", "text": "Corroborating 311 records",
         "meta": "Residential · open · ranked by meaning"},
        {"id": "ev_empty", "component": "Callout", "text": P("/evidence_empty"), "tone": "neutral"},
        {"id": "ev_none", "component": "Callout", "text": P("/evidence_none_found"), "tone": "excluded"},
        column("ev_list", template("ev_item", "/evidence")),
        {"id": "ev_item", "component": "RecordCard", "recordId": P("request_id"), "badge": P("badge"),
         "badgeTone": P("badge_tone"), "title": P("title"), "meta": P("meta"), "quote": P("quote"),
         "similarity": P("similarity"), "weak": P("weak"), "focused": P("focused"), "updated": P("updated")},
        {"id": "ex_box", "component": "Collapsible", "title": P("/excluded_title"), "tone": "excluded",
         "open": P("/excluded_open"), "child": "ex_list"},
        column("ex_list", template("ex_item", "/excluded")),
        {"id": "ex_item", "component": "ExcludedCard", "heading": P("heading"), "label": P("label"),
         "summary": P("summary"), "detail": P("detail"), "focused": P("focused"), "actionLabel": "Ask why",
         "action": event("explain_exclusion", request_id=P("request_id"))},
        {"id": "ev_boundary", "component": "Callout", "text": P("/boundary_note"), "tone": "neutral"},
        # Statutes
        column("tab_st", ["st_title", "st_empty", "st_list"]),
        {"id": "st_title", "component": "SectionTitle", "text": "Matched statutes · California / San Francisco"},
        {"id": "st_empty", "component": "Callout", "text": P("/statutes_empty"), "tone": "neutral"},
        column("st_list", template("st_item", "/statutes")),
        {"id": "st_item", "component": "StatuteCard", "citation": P("citation"), "statuteId": P("statute_id"),
         "title": P("title"), "protection": P("protection"), "appliesBecause": P("applies_because"),
         "needs": P("needs"), "primary": P("primary"), "updated": P("updated")},
        # Funds
        column("tab_fu", ["fu_title", "fu_empty", "fu_list"]),
        {"id": "fu_title", "component": "SectionTitle", "text": "Relief fund fit", "meta": P("/funds_meta")},
        {"id": "fu_empty", "component": "Callout", "text": P("/funds_empty"), "tone": "neutral"},
        column("fu_list", template("fu_item", "/funds")),
        {"id": "fu_item", "component": "FundCard", "name": P("name"), "agency": P("agency"),
         "fitLabel": P("fit_label"), "fitTone": P("fit_tone"), "why": P("why"), "checklist": P("checklist"),
         "intakeLabel": P("intake_label"), "action": open_url("intake_url")},
        # Tract
        column("tab_tr", ["tr_title", "tr_grid", "tr_note"]),
        {"id": "tr_title", "component": "SectionTitle", "text": P("/tract_title")},
        {"id": "tr_grid", "component": "Grid", "columns": 2, "children": template("tr_item", "/tract_tiles")},
        {"id": "tr_item", "component": "StatTile", "label": P("label"), "value": P("value"), "note": P("note"),
         "modeled": P("modeled")},
        {"id": "tr_note", "component": "Callout", "text": P("/tract_note"), "tone": "modeled"},
        # Memo
        column("tab_memo", ["memo_title", "memo_view", "memo_actions"]),
        {"id": "memo_title", "component": "SectionTitle", "text": "Intake memo", "meta": "Draft for the supervising attorney"},
        {"id": "memo_view", "component": "MemoView", "markdown": P("/memo/markdown"),
         "statusLabel": P("/memo/status_label"), "statusTone": P("/memo/status_tone")},
        {"id": "memo_actions", "component": "Wrap", "children": ["memo_copy", "memo_download", "memo_regen", "memo_review"]},
        icon_button("memo_copy", "copy", "Copy", event("copy_memo")),
        icon_button("memo_download", "download", "Download .md", open_url("/memo_url")),
        icon_button("memo_regen", "refresh", "Regenerate", event("ask", text="Regenerate the intake memo with everything we know now.")),
        icon_button("memo_review", "checkCircle", "Mark reviewed", event("mark_memo_reviewed"), "primary"),
        # Footer CTA
        icon_button("d_cta", "fileText", P("/brief_cta"), event("open_brief"), "primary", enabled=P("/brief_ready"), block=True),
    ]


def brief_components() -> list[dict]:
    return [
        column("root", ["b_head", "b_stub", "s1_title", "s1_table", "s1_excl", "s2_title", "s2_grid",
                        "s3_title", "s3_table", "s4_grid", "s5_box", "s5_photos", "s6_title", "s6_memo", "b_foot", "b_actions"]),
        {"id": "b_head", "component": "DocHeader", "eyebrow": P("/eyebrow"), "title": P("/title"),
         "subtitle": P("/subtitle"), "rightLabel": P("/hearing_label"), "rightValue": P("/hearing"),
         "rightNote": P("/prepared")},
        {"id": "b_stub", "component": "Callout", "text": P("/stub_note"), "tone": "excluded"},
        {"id": "s1_title", "component": "SectionTitle", "text": "1 · Corroborating 100-block 311 records"},
        {"id": "s1_table", "component": "DataTable", "columns": P("/evidence_columns"), "rows": P("/evidence_rows"),
         "monoFirstColumn": True},
        {"id": "s1_excl", "component": "Callout", "text": P("/excluded_line"), "tone": "excluded"},
        {"id": "s2_title", "component": "SectionTitle", "text": "2 · Applicable statutes"},
        {"id": "s2_grid", "component": "Grid", "columns": 3, "children": template("s2_item", "/statutes")},
        {"id": "s2_item", "component": "StatuteCard", "citation": P("citation"), "statuteId": P("statute_id"),
         "title": P("title"), "protection": P("protection"), "needs": P("needs"), "primary": P("primary"),
         "compact": True},
        {"id": "s3_title", "component": "SectionTitle", "text": "3 · Relief referral"},
        {"id": "s3_table", "component": "DataTable", "columns": P("/fund_columns"), "rows": P("/fund_rows")},
        {"id": "s4_grid", "component": "Grid", "columns": 2, "children": ["s4_tract", "s4_equity"]},
        column("s4_tract", ["s4_title", "s4_table"]),
        {"id": "s4_title", "component": "SectionTitle", "text": "4 · Tract context"},
        {"id": "s4_table", "component": "DataTable", "rows": P("/tract_rows")},
        column("s4_equity", ["s4e_title", "s4e_table", "s4e_note"]),
        {"id": "s4e_title", "component": "SectionTitle", "text": "Equity audit",
         "meta": "post-output, not used in ranking"},
        {"id": "s4e_table", "component": "DataTable", "rows": P("/equity_rows")},
        text("s4e_note", P("/equity_note"), "caption"),
        {"id": "s5_box", "component": "Callout", "title": "5 · What the public record cannot prove",
         "text": P("/cannot_prove"), "tone": "neutral"},
        {"id": "s5_photos", "component": "Callout", "text": P("/photos_line"), "tone": "neutral"},
        {"id": "s6_title", "component": "SectionTitle", "text": "6 · Legal-aid intake memo", "meta": P("/memo_status")},
        {"id": "s6_memo", "component": "MemoView", "markdown": P("/memo"), "variant": "quote"},
        {"id": "b_foot", "component": "Row", "children": ["b_sources", "b_signoff"], "justify": "spaceBetween"},
        text("b_sources", P("/sources"), "caption"),
        text("b_signoff", P("/signoff"), "caption"),
        {"id": "b_actions", "component": "Wrap", "children": ["b_print", "b_close"]},
        icon_button("b_print", "printer", "Print / save as PDF", event("print_brief"), "primary"),
        icon_button("b_close", "arrowLeft", "Back to case", event("close_brief")),
    ]


NOTICE_OPTIONS = [
    {"label": "3-day pay-or-quit (nonpayment)", "value": "nonpayment"},
    {"label": "Unlawful detainer served", "value": "unlawful_detainer"},
    {"label": "No-fault / holdover", "value": "holdover"},
    {"label": "None served yet", "value": "none"},
]


def intake_form_components() -> list[dict]:
    required = lambda path, msg: [{"condition": {"@call": "required", "args": {"value": P(path)}}, "message": msg}]  # noqa: E731
    return [
        column("root", ["f_title", "f_client", "f_block", "f_issue", "f_hearing", "f_notice", "f_row", "f_note", "f_actions"]),
        {"id": "f_title", "component": "SectionTitle", "icon": "userPlus", "text": "New intake",
         "meta": "Initials and block only: no names or unit numbers"},
        {"id": "f_client", "component": "TextField", "label": "Client initials", "value": P("/form/client"),
         "placeholder": "e.g. M.R."},
        {"id": "f_block", "component": "TextField", "label": "Block or street address", "value": P("/form/block"),
         "placeholder": "e.g. 600 block of John Muir Dr", "checks": required("/form/block", "Block is required.")},
        {"id": "f_issue", "component": "TextField", "label": "Issue, in the tenant's words", "value": P("/form/issue"),
         "variant": "longText", "checks": required("/form/issue", "Describe the conditions.")},
        {"id": "f_hearing", "component": "DateTimeInput", "label": "Hearing date and time", "value": P("/form/hearing"),
         "enableDate": True, "enableTime": True},
        {"id": "f_notice", "component": "ChoicePicker", "label": "Notice served", "options": NOTICE_OPTIONS,
         "value": P("/form/notice"), "variant": "mutuallyExclusive", "displayStyle": "chips"},
        {"id": "f_row", "component": "Row", "children": ["f_house", "f_ami"]},
        {"id": "f_house", "component": "TextField", "label": "Household size", "value": P("/form/household"),
         "variant": "number", "weight": 1},
        {"id": "f_ami", "component": "TextField", "label": "Income (% of AMI), if known", "value": P("/form/ami"),
         "variant": "number", "weight": 1},
        text("f_note", "Tip: use Speak the intake above to fill this form by voice. Submitting opens the case and searches 311 records for this block.", "caption"),
        {"id": "f_actions", "component": "Row", "children": ["f_cancel", "f_submit"], "justify": "end"},
        *button("f_cancel", "Cancel", event("close_intake_form")),
        *button("f_submit", "Open case & search", event(
            "submit_intake", client=P("/form/client"), block=P("/form/block"), issue=P("/form/issue"),
            hearing=P("/form/hearing"), notice=P("/form/notice"), household=P("/form/household"), ami=P("/form/ami"),
        ), "primary", checks=required("/form/block", "Block is required.") + required("/form/issue", "Describe the conditions.")),
    ]


def map_components() -> list[dict]:
    return [
        column("root", ["map_title", "map_view", "map_note"]),
        {"id": "map_title", "component": "SectionTitle", "icon": "mapPin", "text": P("/title"), "meta": P("/meta")},
        {"id": "map_view", "component": "MapView", "address": P("/address"), "center": P("/center"),
         "markers": P("/markers"), "apiKey": P("/maps_key"), "openUrl": P("/open_url")},
        text("map_note", P("/note"), "caption"),
    ]


COMPONENTS = {
    MAP: map_components,
    QUEUE: queue_components,
    HEADER: header_components,
    SUGGESTIONS: suggestions_components,
    DOCUMENTS: documents_components,
    BRIEF: brief_components,
    INTAKE_FORM: intake_form_components,
}


# --------------------------------------------------------------------------- messages


def create_surface(surface_id: str, data_model: dict) -> dict:
    return {
        "version": A2UI_VERSION,
        "createSurface": {
            "surfaceId": surface_id,
            "catalogId": NAVIGATOR_CATALOG_ID,
            "sendDataModel": surface_id == INTAKE_FORM,
            "components": COMPONENTS[surface_id](),
            "dataModel": data_model,
        },
    }


def update_data_model(surface_id: str, value: Any, path: str = "/") -> dict:
    return {"version": A2UI_VERSION, "updateDataModel": {"surfaceId": surface_id, "path": path, "value": value}}


def delete_surface(surface_id: str) -> dict:
    return {"version": A2UI_VERSION, "deleteSurface": {"surfaceId": surface_id}}
