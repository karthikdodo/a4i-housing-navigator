"""Tool registry. Real tools win; stubs fill in until Prachi's files are merged.

Prachi: add match_fund.py / tract_context.py / equity_audit.py with a function of the
same name and signature as in _stubs.py. No edit to this file is needed.
"""

import importlib
import logging

from .resolve_date import resolve_date
from .semantic_search import semantic_search

log = logging.getLogger(__name__)


def _load(name: str):
    try:
        module = importlib.import_module(f".{name}", __name__)
    except ModuleNotFoundError as e:
        if e.name != f"{__name__}.{name}":
            raise  # the real file exists but is broken: fail loudly, don't hide it behind a stub
        log.warning("tools/%s.py not found, using STUB", name)
        module = importlib.import_module("._stubs", __name__)
    return getattr(module, name)


match_fund = _load("match_fund")
tract_context = _load("tract_context")
equity_audit = _load("equity_audit")

__all__ = ["resolve_date", "semantic_search","match_fund", "tract_context", "equity_audit"]
