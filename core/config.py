"""Assumptions config. Single source of truth = the YAML block in ASSUMED_ANSWERS.md (parsed, not copied).

    from core.config import cfg, assumptions
    cfg()["risk"]["lambda"]                  -> 0.5
    cfg({"risk.lambda": 1.0})["risk"]["lambda"] -> 1.0  (UI slider overrides)

Every value is an Assumption tagged with its source and the ASSUMED_ANSWERS.md section it comes from.
"""
from __future__ import annotations

import copy
import re
from functools import lru_cache
from typing import Any

import yaml
from pydantic import BaseModel

from core.fork import ROOT

ANSWERS = ROOT / "ASSUMED_ANSWERS.md"
SOURCE = "ASSUMED_ANSWERS.md (pending Belem confirmation)"
PLACEHOLDER = "placeholder_prior"

# top-level key -> section of ASSUMED_ANSWERS.md it implements
SECTION = {"mandate": "1. Reference portfolio", "loop": "1. Reference portfolio", "kpi_rules": "2. Incident families",
           "risk": "3. Risk aversion", "sizing": "4. Position sizes", "exit": "5. Exit-cost assumptions",
           "monitoring": "6. Scorecard and monitoring", "fallback_priors": "7. Data access and base rates"}

# explicit slider ranges where the generic rule (0 .. 3x value) is wrong
SLIDER = {
    "risk.lambda": (0.0, 1.0, 0.05),
    "loop.target_ltv_over_lltv": (0.5, 0.99, 0.01),
    "loop.deleverage_trigger_over_lltv": (0.5, 0.99, 0.01),
    "loop.emergency_unwind_over_lltv": (0.5, 1.0, 0.01),
    "mandate.pockets": (1, 20, 1),
    "mandate.pocket_weight": (0.01, 1.0, 0.01),
    "monitoring.loop_hf_warn": (1.0, 2.0, 0.01),
    "monitoring.loop_hf_act": (1.0, 2.0, 0.01),
    "monitoring.utilization_warn": (0.5, 1.0, 0.01),
    "monitoring.utilization_act": (0.5, 1.0, 0.01),
}


class Assumption(BaseModel):
    key: str                      # dotted path, e.g. "risk.lambda"
    value: Any
    default: Any
    source: str = SOURCE
    section: str
    numeric: bool
    slider: tuple[float, float, float] | None = None
    placeholder_prior: bool = False


@lru_cache(maxsize=1)
def _raw() -> dict:
    text = ANSWERS.read_text()
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.S)
    data = next((yaml.safe_load(b) for b in blocks if "assumed_answers:" in b), None)
    if data is None:
        raise RuntimeError("no `assumed_answers:` YAML block in ASSUMED_ANSWERS.md")
    return data["assumed_answers"]


def _flatten(d: dict, prefix: str = "") -> dict[str, Any]:
    out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out |= _flatten(v, key)
        else:
            out[key] = v
    return out


def _slider(key: str, v) -> tuple[float, float, float] | None:
    if key in SLIDER:
        return SLIDER[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if isinstance(v, int) and v >= 1000:
        return (0, 3 * v, max(1, v // 100))
    if isinstance(v, int):
        return (0, max(3 * v, 10), 1)
    hi = 1.0 if v <= 1 else 3 * v
    return (0.0, hi, round(hi / 200, 6))


def assumptions(overrides: dict[str, Any] | None = None) -> list[Assumption]:
    overrides = overrides or {}
    raw = _raw()
    out = []
    for key, v in _flatten({k: v for k, v in raw.items() if k != "source"}).items():
        numeric = isinstance(v, (int, float)) and not isinstance(v, bool)
        out.append(Assumption(key=key, value=overrides.get(key, v), default=v, source=raw.get("source", SOURCE),
                              section=SECTION.get(key.split(".")[0], "?"), numeric=numeric,
                              slider=_slider(key, v) if numeric else None,
                              placeholder_prior=key.startswith("fallback_priors.")))
    return out


def cfg(overrides: dict[str, Any] | None = None) -> dict:
    """Nested config with overrides applied ({"risk.lambda": 0.8})."""
    d = copy.deepcopy({k: v for k, v in _raw().items() if k != "source"})
    for key, v in (overrides or {}).items():
        node = d
        *path, leaf = key.split(".")
        for p in path:
            node = node[p]
        if leaf not in node:
            raise KeyError(f"unknown assumption {key}")
        node[leaf] = v
    return d
