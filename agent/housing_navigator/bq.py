"""Thin BigQuery helper: parameterized queries returning JSON-safe dicts."""

from __future__ import annotations

import datetime as _dt
import decimal
from functools import lru_cache
from typing import Any

from google.cloud import bigquery

from . import config


@lru_cache(maxsize=1)
def client() -> bigquery.Client:
    return bigquery.Client(project=config.PROJECT or None, location=config.BQ_LOCATION)


def _param(name: str, value: Any) -> bigquery.query._AbstractQueryParameter:
    if isinstance(value, (list, tuple)):
        return bigquery.ArrayQueryParameter(name, "STRING", [str(v) for v in value])
    if isinstance(value, bool):
        return bigquery.ScalarQueryParameter(name, "BOOL", value)
    if isinstance(value, int):
        return bigquery.ScalarQueryParameter(name, "INT64", value)
    if isinstance(value, float):
        return bigquery.ScalarQueryParameter(name, "FLOAT64", value)
    return bigquery.ScalarQueryParameter(name, "STRING", value)


def _jsonable(v: Any) -> Any:
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, float):
        return round(v, 4)
    return v


def query(sql: str, **params: Any) -> list[dict[str, Any]]:
    job_config = bigquery.QueryJobConfig(
        query_parameters=[_param(k, v) for k, v in params.items()]
    )
    rows = client().query(sql, job_config=job_config).result()
    return [{k: _jsonable(v) for k, v in dict(r).items()} for r in rows]
