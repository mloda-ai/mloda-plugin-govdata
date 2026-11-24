"""Pinned reference-table sources for the harmonization mapper.

All four sources are redistributable: BBSR and Destatis under
Datenlizenz Deutschland - Namensnennung - Version 2.0 (DL-DE-BY-2.0), Eurostat under
CC BY 4.0 (CC-BY-4.0). Hashes below are the *original* published file's sha256, fetched and pinned
2026-08-17 (see the fixtures' own ``NOTICE`` for the matching extract hashes); BBSR re-pinned
2026-09-24 after the 2024-2025 sheet was added, the earlier sheets unchanged; Eurostat LAU-to-NUTS re-pinned
2026-10-21 and 2026-11-24, each after a re-publication that left the DE sheet unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from mloda_plugin_govdata.feature_groups.govdata.core.discovery import CC_BY_4_0, DL_DE_BY_2_0


@dataclass(frozen=True)
class ReferenceSource:
    name: str
    url: str
    sha256: str | None  # None when the URL varies per call (GV-ISys per year) and no single hash applies
    license: str
    attribution: str


@dataclass(frozen=True)
class ReferenceCopy:
    """A source and its cached copy; ``sha256`` and ``retrieved_at`` are None when no pinned copy is cached."""

    source: ReferenceSource
    sha256: str | None
    retrieved_at: datetime | None


BBSR_KREISE = ReferenceSource(
    name="BBSR Umsteigeschluessel Kreise",
    url="https://www.bbsr.bund.de/BBSR/DE/forschung/raumbeobachtung/Raumabgrenzungen/umstiegsschluessel/ref-kreise-1990-2024.xlsx?__blob=publicationFile&v=2",
    sha256="b7250207cae01268667426ba416312577ba207f0acd8df8048d80db8206a01af",
    license=DL_DE_BY_2_0,
    attribution="Laufende Raumbeobachtung des BBSR",
)

EUROSTAT_NUTS_CORRESPONDENCE = ReferenceSource(
    name="Eurostat NUTS-to-national-administrative-units correspondence table",
    url="https://ec.europa.eu/eurostat/documents/345175/6742814/Correspondence-table-2024-NUTS-SR-EN-DE-FR.xlsx/4576becd-b6b9-c3e5-cb83-e4200aa43c3a",
    sha256="01ef6cd3a49374c94f5401b9cb2116bd735c02fa0469ed717708a2c0938519a5",
    license=CC_BY_4_0,
    attribution="Source: Eurostat.",
)

EUROSTAT_LAU_NUTS = ReferenceSource(
    name="Eurostat LAU-to-NUTS correspondence (EU-27-LAU-2025-NUTS-2024)",
    url="https://ec.europa.eu/eurostat/documents/345175/501971/EU-27-LAU-2025-NUTS-2024.xlsx/574c9e4a-2dae-99fe-5510-3fd18d8e90c2",
    sha256="5cfb4dc995746a4b5b8a60994e91e9bdc82bfdf68769c05b171d475d16a9c799",
    license=CC_BY_4_0,
    attribution="Source: Eurostat.",
)

# GV-ISys ("Namens-Grenz-Aenderung") is published as one file per year; only the 2016
# file has a pinned hash here (matches the fixture extract). Other years fetch without
# a pin check unless the caller supplies one.
GV_ISYS_URL_TEMPLATE = (
    "https://www.destatis.de/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis/"
    "Namens-Grenz-Aenderung/{year}.xlsx?__blob=publicationFile&v=5"
)
GV_ISYS_2016_SHA256 = "301a0b72381d78ece5b3fe811fd29e7739258da55ebda9dacb1a0d2651f2b0b7"
_KNOWN_GV_ISYS_SHA256: dict[int, str] = {2016: GV_ISYS_2016_SHA256}


def gv_isys_source(year: int, *, sha256: str | None = None) -> ReferenceSource:
    """The :class:`ReferenceSource` for one year of Destatis' GV-ISys change file; ``sha256`` defaults to the pin."""
    return ReferenceSource(
        name=f"Destatis GV-ISys Namens-Grenz-Aenderung {year}",
        url=GV_ISYS_URL_TEMPLATE.format(year=year),
        sha256=sha256 or _KNOWN_GV_ISYS_SHA256.get(year),
        license=DL_DE_BY_2_0,
        attribution="(c) Statistisches Bundesamt (Destatis)",
    )
