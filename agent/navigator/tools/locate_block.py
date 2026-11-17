"""locate_block: tenant's street address -> census tract GEOID, without needing an open 311 match.

Owner: Sid.

semantic_search only yields a tract when an OPEN residential case sits on the tenant's block.
When there isn't one, tract_context and equity_audit get skipped. This tool looks at every
311 record on the tenant's street (open or closed, any property type, since only the address
is used here, never the complaint) and picks the tract of the nearest block number.

Location only: a record found here is never evidence of a habitability condition.
"""

import re
from typing import Optional

from google.cloud import bigquery

from .. import config
from .semantic_search import _bq

_SUFFIXES = (
    r"st|street|av|ave|avenue|blvd|boulevard|rd|road|way|dr|drive|ct|court|pl|place|"
    r"ter|terrace|ln|lane|hwy|highway|aly|alley"
)


def parse_address(address: str) -> tuple[Optional[int], Optional[str]]:
    """'450 Eddy Street' / '400 block of Eddy St' -> (400, 'eddy'). Hundred-block may be None."""
    text = address.lower().split(",")[0]
    m = re.search(r"\b(\d+)\b(?!\s*(?:st|nd|rd|th)\b)", text)
    hundred = int(m.group(1)) // 100 * 100 if m else None
    if m:
        text = text[: m.start()] + " " + text[m.end():]
    text = re.sub(r"\bblock\b|\bof\b|\bthe\b", " ", text)
    text = re.sub(rf"\b({_SUFFIXES})\b\.?", " ", text)
    words = re.findall(r"[a-z0-9']+", text)
    street = " ".join(words) if words else None
    return hundred, street


def locate_block(block_address: str) -> dict:
    """Find the census tract for a tenant's street address using San Francisco 311 block addresses.

    Use when the tenant's tract is unknown because semantic_search found no on-block match.
    Only the address is used: records returned here are NOT habitability evidence.

    Args:
        block_address: Tenant's address or block, e.g. "450 Eddy St" or "400 block of Eddy Street".

    Returns:
        `census_tract_geoid` (11-character string) of the closest block on that street,
        `match` ("exact_block", "nearest_block_same_street", or "street_only"),
        `blocks_away` (hundreds between the tenant's block and the matched block), and
        `candidates` (other tracts on the street), or `error` if the street isn't found.
    """
    hundred, street = parse_address(block_address)
    if not street:
        return {"error": f"Could not read a street name from {block_address!r}."}

    sql = f"""
    SELECT census_tract_geoid,
           SAFE_CAST(REGEXP_EXTRACT(block_address, r'^(\\d+) Block') AS INT64) AS block_number,
           ANY_VALUE(block_address) AS example_block,
           COUNT(*) AS records
    FROM {config.table('municipal_311_housing_complaints')}
    WHERE metro_area = @metro
      AND NOT STARTS_WITH(request_id, 'DECOY-')
      AND REGEXP_CONTAINS(LOWER(block_address), CONCAT(r'^\\d+ block ', @street, r'\\b'))
    GROUP BY census_tract_geoid, block_number
    """
    try:
        rows = [
            dict(r)
            for r in _bq().query(
                sql,
                job_config=bigquery.QueryJobConfig(query_parameters=[
                    bigquery.ScalarQueryParameter("metro", "STRING", config.METRO),
                    bigquery.ScalarQueryParameter("street", "STRING", re.escape(street)),
                ]),
            ).result()
        ]
    except Exception as e:  # surface to the model instead of crashing the run
        return {"error": f"BigQuery lookup failed: {e}"}

    if not rows:
        return {
            "error": f"No 311 records on a street matching {street!r} in {config.METRO}. "
                     "Ask the paralegal for the tract or a cross street.",
            "street_parsed": street,
        }

    if hundred is not None:
        for r in rows:
            r["blocks_away"] = abs((r["block_number"] or 0) - hundred) // 100
        rows.sort(key=lambda r: (r["blocks_away"], -r["records"]))
        best = rows[0]
        match = "exact_block" if best["blocks_away"] == 0 else "nearest_block_same_street"
    else:
        rows.sort(key=lambda r: -r["records"])
        best = rows[0]
        match = "street_only"

    others = []
    for r in rows[1:]:
        if r["census_tract_geoid"] != best["census_tract_geoid"] and \
                r["census_tract_geoid"] not in {o["census_tract_geoid"] for o in others}:
            others.append({k: r.get(k) for k in ("census_tract_geoid", "example_block", "blocks_away")})

    return {
        "census_tract_geoid": best["census_tract_geoid"],
        "match": match,
        "matched_block": best["example_block"],
        "blocks_away": best.get("blocks_away"),
        "street_parsed": street,
        "hundred_block_parsed": hundred,
        "candidates": others[:5],
        "note": "Location lookup only. These records are not evidence of conditions. "
                "Streets can cross tract lines, so a non-exact match is approximate.",
    }
