"""AGS-to-NUTS mapping.

Kreis- and Gemeinde-level exact lookup against a :class:`NutsCrosswalk`. Land (2-digit) and
ARS (12-digit) keys are out of scope for now and are reported unmatched, not rejected: string
keys keep the door open.
"""

from __future__ import annotations

import warnings
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .crosswalk import NutsCrosswalk
from .keys import AgsLevel, detect_level
from .reference.eurostat import LauNutsRow
from .reference.gv_isys import GvIsysChange


@dataclass(frozen=True)
class MatchedMapping:
    key: str
    nuts1: str
    nuts2: str
    nuts3: str
    nuts_version: str


@dataclass(frozen=True)
class UnmatchedKey:
    key: str
    reason: str


@dataclass(frozen=True)
class MappingResult:
    matched: tuple[MatchedMapping, ...]
    unmatched: tuple[UnmatchedKey, ...]
    crosswalk: NutsCrosswalk
    data_year_checked: bool


class UnmatchedKeysError(ValueError):
    def __init__(self, unmatched: tuple[UnmatchedKey, ...]) -> None:
        self.unmatched = unmatched
        detail = "; ".join(f"{u.key} ({u.reason})" for u in unmatched)
        super().__init__(f"{len(unmatched)} key(s) did not map to a NUTS-3 code: {detail}")


def _kreis_index(lau_rows: Sequence[LauNutsRow]) -> dict[str, str]:
    """Groups LAU rows by their 5-digit Kreis prefix; each group's NUTS-3 must be unique.

    A Kreis spanning two NUTS-3 codes means it sits mid a boundary-reform lag window
    (a Kreis merger that predates the next NUTS version picking it up, see the
    Eisenach/Wartburgkreis case): raise rather than silently pick either one.
    """
    grouped: dict[str, set[str]] = defaultdict(set)
    for row in lau_rows:
        grouped[row.lau_code[:5]].add(row.nuts3)
    index: dict[str, str] = {}
    for kreis, nuts3_values in grouped.items():
        if len(nuts3_values) > 1:
            raise ValueError(
                f"Kreis {kreis} maps to multiple NUTS-3 codes in the crosswalk: {sorted(nuts3_values)}; "
                "likely a boundary-reform lag window, not resolvable within one NUTS version"
            )
        index[kreis] = next(iter(nuts3_values))
    return index


def _kreis_redirect_candidates(key: str, changes: Sequence[GvIsysChange]) -> set[str]:
    return {
        change.to_ags
        for change in changes
        if change.level == "Kreis" and change.from_ags == key and change.to_ags is not None
    }


def _resolve_one(
    key: str, crosswalk: NutsCrosswalk, kreis_index: dict[str, str], gemeinde_index: dict[str, str]
) -> tuple[str | None, str | None]:
    """Returns ``(nuts3, None)`` on a match, or ``(None, reason)`` when unmatched."""
    try:
        level = detect_level(key)
    except ValueError as exc:
        return None, str(exc)

    if level == AgsLevel.KREIS:
        nuts3 = kreis_index.get(key)
        if nuts3 is None:
            candidates = _kreis_redirect_candidates(key, crosswalk.gv_isys_changes)
            if len(candidates) > 1:
                return None, (
                    f"Kreis {key} has {len(candidates)} ambiguous GV-ISys successors "
                    f"{sorted(candidates)} (e.g. a split); not resolved to a single redirect"
                )
            if len(candidates) == 1:
                nuts3 = kreis_index.get(next(iter(candidates)))
        if nuts3 is not None:
            return nuts3, None
        return None, f"Kreis {key} not found in the LAU-to-NUTS crosswalk (no GV-ISys redirect resolved it)"

    if level == AgsLevel.GEMEINDE:
        nuts3 = gemeinde_index.get(key)
        if nuts3 is not None:
            return nuts3, None
        return None, f"Gemeinde/Gemeindefreies Gebiet {key} not found in the LAU-to-NUTS crosswalk"

    if level == AgsLevel.LAND:
        return None, f"Land-level key {key}: Land mapping is out of scope for now"

    return None, f"ARS key {key}: Gemeinde/ARS mapping is out of scope for now"


def map_ags_to_nuts(
    keys: Sequence[str],
    *,
    crosswalk: NutsCrosswalk,
    data_year: int | None = None,
    on_unmatched: Literal["raise", "drop", "flag"] = "raise",
) -> MappingResult:
    """Maps AGS keys to NUTS-1/2/3 codes via the LAU-to-NUTS ``crosswalk``.

    Kreis (5-digit) keys resolve by grouping every Gemeinde under that Kreis and
    requiring one shared NUTS-3 code; a Kreis missing from the crosswalk is retried
    once through ``crosswalk.gv_isys_changes`` (its historical successor key). Gemeinde-
    level (8-digit) keys resolve by direct lookup. Land (2-digit) and ARS (12-digit)
    keys always come back unmatched, never raised.

    ``data_year``, when given, warns if it diverges from the crosswalk's own Gebietsstand
    year and raises if it falls outside the crosswalk's covered range; without it neither
    check runs (``MappingResult.data_year_checked`` records which happened).

    ``on_unmatched``: ``"raise"`` (default) raises :class:`UnmatchedKeysError` if anything
    is unmatched; ``"flag"`` returns matched and unmatched together; ``"drop"`` returns
    matched only. Any other value raises immediately: the type hint is not runtime-enforced,
    so a typo would otherwise silently fall through to ``"flag"`` behavior.
    """
    if on_unmatched not in ("raise", "drop", "flag"):
        raise ValueError(f"on_unmatched must be 'raise', 'drop', or 'flag', got {on_unmatched!r}")

    data_year_checked = data_year is not None
    if data_year is not None:
        low, high = crosswalk.year_range
        if data_year < low or data_year > high:
            raise ValueError(f"data_year {data_year} is outside the crosswalk's covered range {crosswalk.year_range}")
        crosswalk_year = int(crosswalk.gebietsstand)
        if data_year != crosswalk_year:
            warnings.warn(
                f"data_year {data_year} diverges from the crosswalk's Gebietsstand year {crosswalk_year}; "
                "results reflect the crosswalk's own Gebietsstand, not data_year",
                stacklevel=2,
            )

    kreis_index = _kreis_index(crosswalk.lau_rows)
    gemeinde_index = {row.lau_code: row.nuts3 for row in crosswalk.lau_rows}

    matched: list[MatchedMapping] = []
    unmatched: list[UnmatchedKey] = []
    for key in keys:
        nuts3, reason = _resolve_one(key, crosswalk, kreis_index, gemeinde_index)
        if nuts3 is not None:
            matched.append(
                MatchedMapping(
                    key=key, nuts1=nuts3[:3], nuts2=nuts3[:4], nuts3=nuts3, nuts_version=crosswalk.nuts_version
                )
            )
        elif reason is not None:
            unmatched.append(UnmatchedKey(key=key, reason=reason))

    if on_unmatched == "raise" and unmatched:
        raise UnmatchedKeysError(tuple(unmatched))
    if on_unmatched == "drop":
        unmatched = []

    return MappingResult(
        matched=tuple(matched), unmatched=tuple(unmatched), crosswalk=crosswalk, data_year_checked=data_year_checked
    )


def combine_mapping_results(results: Sequence[MappingResult]) -> MappingResult:
    """Concatenates results built from the same NUTS version; raises on a mismatch.

    Joining results across NUTS versions is not a valid operation: a NUTS-3
    code is only comparable within one NUTS version.
    """
    if not results:
        raise ValueError("no results to combine")
    versions = {r.crosswalk.nuts_version for r in results}
    if len(versions) > 1:
        raise ValueError(f"cannot combine MappingResults across different NUTS versions: {sorted(versions)}")
    matched = tuple(m for r in results for m in r.matched)
    unmatched = tuple(u for r in results for u in r.unmatched)
    checked = any(r.data_year_checked for r in results)
    return MappingResult(
        matched=matched, unmatched=unmatched, crosswalk=results[0].crosswalk, data_year_checked=checked
    )
