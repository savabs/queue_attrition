"""Normalise the ISOs' generation-type vocabularies onto one set.

Without this the segment table reports "Solar 32.1%" next to "Photovoltaic
13.0%" as if they were different technologies. They are the same technology
labelled differently by different ISOs, so the gap is measuring ISO mix, not
fuel. Any conclusion drawn from the raw labels is an artifact.
"""
import re

CANON = {
    "solar": ["solar", "photovoltaic", "sun", "pv", "solar pv"],
    "wind": ["wind", "wnd", "wind turbine", "windturbine"],
    "offshore_wind": ["offshore wind", "osw", "wind offshore"],
    "storage": ["storage", "energy storage", "bat", "battery", "battery storage", "es"],
    "solar_storage": ["photovoltaic + storage", "solar + storage", "hybrid", "solar/storage"],
    "gas": ["ng", "natural gas", "gas", "combined cycle", "combustion turbine",
            "gas turbine", "ct", "cc", "methane"],
    "steam": ["steam turbine", "steam", "st"],
    "nuclear": ["nuclear", "nu"],
    "hydro": ["hydro", "hydroelectric", "water", "wat", "pumped storage"],
    "coal": ["coal", "bituminous"],
    "biomass": ["biomass", "wood", "landfill gas", "lfg", "biogas"],
    "transmission": ["ac transmission", "dc transmission", "transmission", "hvdc"],
    "other": ["other", "oil", "diesel", "fuel cell", "geothermal", "waste heat"],
}
_LOOKUP = {alias: canon for canon, aliases in CANON.items() for alias in aliases}


def normalise(raw) -> str:
    if raw is None:
        return "unknown"
    s = re.sub(r"\s+", " ", str(raw)).strip().lower()
    if not s or s in ("nan", "none", "n/a", "-"):
        return "unknown"
    if s in _LOOKUP:
        return _LOOKUP[s]
    # Compound labels ("Solar; Battery Storage") resolve to the hybrid class
    # rather than to whichever component happens to be matched first.
    hits = {c for alias, c in _LOOKUP.items() if re.search(rf"\b{re.escape(alias)}\b", s)}
    if hits == {"solar", "storage"} or hits == {"solar_storage"}:
        return "solar_storage"
    if len(hits) == 1:
        return hits.pop()
    if hits:
        return "hybrid_multi"
    return "unmapped"
