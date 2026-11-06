"""Reading and checking of the five source files (#415).

Single entry: :func:`check_sources` (does not raise, returns the report) and
:func:`read_sources` (raises :class:`SourceValidationError` if there are errors).
They take the bytes of the uploaded files (:class:`UploadedFiles`) and the OWL
vocabulary (:class:`OntologyVocabulary`); they produce a :class:`ParsedSources` with the
data already in the project types (``IstatData`` and ``HazardMapping`` of the same
models that ISTAT uses today), ready to be packaged into a source set. The module does
not know the active set, the sessions or the request context: it is pure.

The five files:

* **ontology** (Turtle or OWL/RDF-XML): :mod:`.ontology_reader`;
* **OSM -> class table** (``osm_table``): ``osm_tag,classe``;
* **statistical data** (``data``): ``luogo,voce,voce_etichetta,anno,delitti,tasso``
  and, optional, ``tasso_sotto_soglia`` (``si``/``no``). The most recent year of the
  file is the current year, the comparison one is ``anno - 10``; ``IT`` is the
  national row and ``TOT`` the total item (like ``delitti.json``); version =
  first 12 characters of the file's SHA-256;
* **hazard -> item table** (``hazard_table``): ``hazard,voce,corrispondenza``
  and, optional, ``serie_non_confrontabile`` (``si``/``no``) and ``nota``;
* **boundaries** (``boundaries``, optional): GeoJSON ``FeatureCollection`` with in
  ``properties`` ``codice``, ``tipo`` (``comune``/``provincia``), ``nome``,
  ``nome_breve`` and, optional, ``provincia``. Without the file only the
  boundaries passed in ``fallback_places`` (our own) apply.

The check runs before activating anything and collects ALL the problems.
The cross checks (classes and hazards in the ontology, items in the data) are
skipped only when the file they depend on is not readable.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from rdflib import Graph

from crime_risk_analyzer.istat.data import (
    ITALY_CODE,
    TOTAL_ITEM,
    IstatData,
    OffencesFile,
    Place,
    PlaceType,
    YearValue,
)
from crime_risk_analyzer.istat.mapping import HazardMapping, MatchKind
from crime_risk_analyzer.models.geo import (
    CityBoundary,
    Polygon,
    Ring,
    boundary_from_geojson,
    point_in_polygon,
)
from crime_risk_analyzer.sources.csv_reader import CsvRow, read_csv
from crime_risk_analyzer.sources.limits import (
    MAX_BYTES_CSV,
    MAX_BYTES_GEOJSON,
    MAX_BYTES_ONTOLOGY,
    MAX_OSM_SELECTORS,
    check_note,
    check_text,
)
from crime_risk_analyzer.sources.ontology_reader import (
    OntologyReading,
    read_ontology,
)
from crime_risk_analyzer.sources.report import (
    FileName,
    SourceValidationError,
    ValidationReport,
)
from crime_risk_analyzer.sources.vocabulary import (
    TERMINUS_VOCABULARY,
    OntologyVocabulary,
)

__all__ = [
    "DATA_COLUMNS",
    "DATA_OPTIONAL_COLUMNS",
    "HAZARD_COLUMNS",
    "HAZARD_OPTIONAL_COLUMNS",
    "OSM_COLUMNS",
    "ParsedSources",
    "UploadedFiles",
    "check_sources",
    "read_sources",
]

OSM_COLUMNS = ("osm_tag", "classe")
DATA_COLUMNS = (
    "luogo",
    "voce",
    "voce_etichetta",
    "anno",
    "delitti",
    "tasso",
)
DATA_OPTIONAL_COLUMNS = ("tasso_sotto_soglia",)
HAZARD_COLUMNS = ("hazard", "voce", "corrispondenza")
HAZARD_OPTIONAL_COLUMNS = ("serie_non_confrontabile", "nota")

_MATCHES: tuple[MatchKind, ...] = ("esatta", "piu_larga", "piu_stretta")
_PLACE_TYPES: tuple[PlaceType, ...] = ("comune", "provincia")
_OSM_TAG = re.compile(r"[A-Za-z0-9_:\-]+=[A-Za-z0-9_:.\-]+")
_PLACE_CODE = re.compile(r"[A-Za-z0-9_\-]{1,20}")
_ITEM_CODE = re.compile(r"[A-Za-z0-9_]{1,40}")
_YEAR = re.compile(r"[0-9]{4}")
_INTEGER = re.compile(r"[0-9]{1,12}")
_DECIMAL = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,6})?")
_COMPARISON_YEARS = 10


@dataclass(frozen=True)
class UploadedFiles:
    """Bytes of the uploaded files; ``boundaries`` is the only optional one."""

    ontology: bytes
    #: Name of the ontology file: the extension chooses the format.
    ontology_name: str
    osm_table: bytes
    data: bytes
    hazard_table: bytes
    boundaries: bytes | None = None


@dataclass(frozen=True)
class ParsedSources:
    """Sources read and checked, in the project types."""

    graph: Graph
    vocabulary: OntologyVocabulary
    #: Local names of all the classes of the ontology in the namespace.
    classes: frozenset[str]
    #: Class -> (IT label, EN label); fallback: name with ``_`` -> space.
    labels: dict[str, tuple[str, str]]
    #: OSM ``key=value`` -> class name (same shape as ``OSM_TO_TERMINUS``).
    osm_to_class: dict[str, str]
    #: Families of OSM keys in order of first appearance in the table.
    family_order: tuple[str, ...]
    #: Data and places with boundaries (only places that have data), like ``load_data``.
    istat: IstatData
    #: Hazard -> item (same shape as ``istat.mapping.HAZARD_MAPPING``).
    mappatura: dict[str, HazardMapping]
    #: Items with a non-comparable series (equivalent of ``BREAK_ITEMS_2016``).
    voci_rottura: frozenset[str]
    #: First 12 characters of the SHA-256 of the data file.
    versione: str


def read_sources(
    files: UploadedFiles,
    vocabulary: OntologyVocabulary = TERMINUS_VOCABULARY,
    *,
    fallback_places: Sequence[Place] = (),
) -> tuple[ParsedSources, ValidationReport]:
    """Like :func:`check_sources`, but raises if the upload is not valid.

    Raises:
        SourceValidationError: ``report`` has all the blocking problems.
    """
    parsed, report = check_sources(files, vocabulary, fallback_places=fallback_places)
    if parsed is None:
        raise SourceValidationError(report)
    return parsed, report


def check_sources(
    files: UploadedFiles,
    vocabulary: OntologyVocabulary = TERMINUS_VOCABULARY,
    *,
    fallback_places: Sequence[Place] = (),
) -> tuple[ParsedSources | None, ValidationReport]:
    """Reads and checks the files; ``ParsedSources`` is ``None`` if there are errors.

    The warnings (``report.warnings``) do not block and are reported also on a
    positive outcome. ``fallback_places`` are our own boundaries, used for the places of
    the data that the boundaries file does not cover.
    """
    report = ValidationReport()
    allowed = _check_sizes(files, report)

    ontology_reading = (
        read_ontology(files.ontology, files.ontology_name, vocabulary, report)
        if "ontology" in allowed
        else None
    )
    osm = (
        _read_osm(files.osm_table, ontology_reading, report)
        if "osm_table" in allowed
        else None
    )
    parsed_data = _read_data(files.data, report) if "data" in allowed else None
    mappatura = (
        _read_hazard(files.hazard_table, ontology_reading, parsed_data, report)
        if "hazard_table" in allowed
        else None
    )
    boundary_places = (
        _read_boundaries(files.boundaries, report)
        if files.boundaries is not None and "boundaries" in allowed
        else {}
    )
    luoghi = (
        _choose_places(parsed_data, boundary_places, fallback_places, report)
        if parsed_data is not None
        and (files.boundaries is None or "boundaries" in allowed)
        else None
    )

    if (
        not report.ok
        or ontology_reading is None
        or osm is None
        or parsed_data is None
        or mappatura is None
        or luoghi is None
    ):
        return None, report

    delitti = _offences_file(parsed_data, files.data)
    versione = delitti.estratto_il
    voci_rottura, per_hazard = mappatura
    return (
        ParsedSources(
            graph=ontology_reading.graph,
            vocabulary=vocabulary,
            classes=ontology_reading.classes,
            labels=ontology_reading.labels,
            osm_to_class=dict(osm.tag_to_class),
            family_order=osm.families,
            istat=IstatData(delitti=delitti, luoghi=luoghi),
            mappatura=per_hazard,
            voci_rottura=voci_rottura,
            versione=versione,
        ),
        report,
    )


# --- sizes ---


def _check_sizes(files: UploadedFiles, report: ValidationReport) -> set[FileName]:
    """Reports the files over the limit and returns the ones to read."""
    limits: list[tuple[FileName, bytes | None, int]] = [
        ("ontology", files.ontology, MAX_BYTES_ONTOLOGY),
        ("osm_table", files.osm_table, MAX_BYTES_CSV),
        ("data", files.data, MAX_BYTES_CSV),
        ("hazard_table", files.hazard_table, MAX_BYTES_CSV),
        ("boundaries", files.boundaries, MAX_BYTES_GEOJSON),
    ]
    allowed: set[FileName] = set()
    for nome, content, limit in limits:
        if content is not None and len(content) > limit:
            report.error(
                "file_troppo_grande",
                nome,
                f"il file pesa {len(content) / (1024 * 1024):.1f} MB, "
                f"il massimo e' {limit // (1024 * 1024)} MB",
            )
        else:
            allowed.add(nome)
    return allowed


# --- OSM table ---


@dataclass(frozen=True)
class _Osm:
    tag_to_class: dict[str, str]
    families: tuple[str, ...]


def _read_osm(
    content: bytes, ontology_reading: OntologyReading | None, report: ValidationReport
) -> _Osm | None:
    rows = read_csv(
        content,
        "osm_table",
        required=OSM_COLUMNS,
        report=report,
        max_rows=MAX_OSM_SELECTORS,
    )
    if rows is None:
        return None
    tag_to_class: dict[str, str] = {}
    seen: set[str] = set()
    for row in rows:
        tag, class_name = row.cells["osm_tag"], row.cells["classe"]
        if _OSM_TAG.fullmatch(tag) is None:
            report.error(
                "osm_tag_non_valido",
                "osm_table",
                f"selettore OSM {tag[:40]!r} non valido: serve la forma "
                "chiave=valore, solo lettere, cifre e _ : . -",
                line=row.line,
            )
            continue
        if tag in seen:
            report.error(
                "chiave_duplicata",
                "osm_table",
                f"il selettore {tag!r} compare piu' volte",
                line=row.line,
            )
            continue
        seen.add(tag)
        if ontology_reading is not None and class_name not in ontology_reading.classes:
            report.error(
                "classe_assente_dall_ontologia",
                "osm_table",
                f"la classe {class_name[:40]!r} non esiste nell'ontologia caricata",
                line=row.line,
            )
            continue
        tag_to_class[tag] = class_name
    families = tuple(dict.fromkeys(t.partition("=")[0] for t in tag_to_class))
    return _Osm(tag_to_class=tag_to_class, families=families)


# --- statistical data ---


@dataclass(frozen=True)
class _Data:
    anno: int
    voci: dict[str, str]
    valori: dict[str, dict[str, dict[str, YearValue | None]]]


def _yes_no(value: str) -> bool | None:
    """``True``/``False`` for ``si``/``no`` (empty = ``no``); ``None`` if not valid."""
    cleaned = value.strip().lower()
    if cleaned in ("", "no"):
        return False
    if cleaned in ("si", "sì"):
        return True
    return None


def _read_data(content: bytes, report: ValidationReport) -> _Data | None:
    rows = read_csv(
        content,
        "data",
        required=DATA_COLUMNS,
        optional=DATA_OPTIONAL_COLUMNS,
        report=report,
    )
    if rows is None:
        return None
    voci: dict[str, str] = {}
    valori: dict[str, dict[str, dict[str, YearValue | None]]] = {}
    for row in rows:
        _data_row(row, voci, valori, report)
    if not valori:
        return None
    if ITALY_CODE not in valori:
        report.error(
            "riga_nazionale_mancante",
            "data",
            f"manca la riga nazionale (luogo={ITALY_CODE}), serve per il "
            "confronto con il tasso nazionale",
        )
    years = [
        int(a) for per_item in valori.values() for v in per_item.values() for a in v
    ]
    anno = max(years)
    if not any(
        str(anno - _COMPARISON_YEARS) in per_year
        for per_item in valori.values()
        for per_year in per_item.values()
    ):
        report.warning(
            "anno_confronto_assente",
            "data",
            f"nessun dato per l'anno di confronto {anno - _COMPARISON_YEARS}: "
            "la tendenza non si calcola",
        )
    without_total = sorted(
        place for place, per_item in valori.items() if TOTAL_ITEM not in per_item
    )
    if without_total:
        report.warning(
            "totale_mancante",
            "data",
            f"nessuna riga della voce {TOTAL_ITEM} (totale) per: "
            f"{', '.join(without_total)}",
        )
    return _Data(anno=anno, voci=voci, valori=valori)


def _data_row(
    row: CsvRow,
    voci: dict[str, str],
    valori: dict[str, dict[str, dict[str, YearValue | None]]],
    report: ValidationReport,
) -> None:
    c = row.cells
    ok = True

    def add_error(codice: str, message: str) -> None:
        nonlocal ok
        ok = False
        report.error(codice, "data", message, line=row.line)

    place, voce, label = c["luogo"], c["voce"], c["voce_etichetta"]
    if _PLACE_CODE.fullmatch(place) is None:
        add_error(
            "codice_non_valido",
            f"codice luogo {place[:40]!r} non valido: massimo 20 tra lettere, "
            "cifre, _ e -",
        )
    if _ITEM_CODE.fullmatch(voce) is None:
        add_error(
            "codice_non_valido",
            f"codice voce {voce[:40]!r} non valido: massimo 40 tra lettere, cifre e _",
        )
    reason = check_text(label)
    if reason is not None:
        add_error("testo_non_ammesso", f"etichetta della voce {voce[:40]!r}: {reason}")
    elif voce in voci and voci[voce] != label:
        add_error(
            "etichetta_voce_incoerente",
            f"la voce {voce!r} ha gia' l'etichetta {voci[voce]!r}, qui {label!r}",
        )

    anno = c["anno"]
    if _YEAR.fullmatch(anno) is None or not 1900 <= int(anno) <= 2100:
        add_error(
            "valore_non_valido",
            f"anno {anno[:20]!r} non valido: serve un anno a 4 cifre",
        )

    delitti = c["delitti"]
    if delitti and _INTEGER.fullmatch(delitti) is None:
        add_error(
            "valore_non_valido",
            f"delitti {delitti[:20]!r} non valido: serve un intero non negativo "
            "o vuoto",
        )
    tasso: float | None = None
    try:
        tasso = _number(c["tasso"])
    except ValueError:
        add_error(
            "valore_non_valido",
            f"tasso {c['tasso'][:20]!r} non valido: serve un numero non negativo "
            "con il punto decimale, o vuoto",
        )
    below_threshold = _yes_no(c.get("tasso_sotto_soglia", ""))
    if below_threshold is None:
        add_error(
            "valore_non_valido",
            f"tasso_sotto_soglia {c['tasso_sotto_soglia'][:20]!r} non valido: "
            "si oppure no",
        )
    if ok:
        if not delitti and (tasso is not None or below_threshold):
            add_error(
                "valore_non_valido",
                "senza il numero di delitti (dato mancante) tasso e "
                "tasso_sotto_soglia devono essere vuoti",
            )
        elif below_threshold and tasso is not None:
            add_error(
                "valore_non_valido",
                "con tasso_sotto_soglia=si il tasso deve essere vuoto",
            )
    if not ok:
        return
    per_year = valori.setdefault(place, {}).setdefault(voce, {})
    if anno in per_year:
        report.error(
            "chiave_duplicata",
            "data",
            f"luogo {place!r}, voce {voce!r}, anno {anno} compaiono piu' volte",
            line=row.line,
        )
        return
    voci.setdefault(voce, label)
    per_year[anno] = (
        YearValue(
            delitti=int(delitti),
            tasso=tasso,
            tasso_sotto_soglia=bool(below_threshold),
        )
        if delitti
        else None
    )


def _number(testo: str) -> float | None:
    """Non-negative decimal with the dot (``12`` or ``12.5``); ``None`` if empty.

    No ``_`` separators, exponents, ``nan``/``inf`` or non-ASCII digits:
    ``ValueError`` for everything else.
    """
    if not testo:
        return None
    if _DECIMAL.fullmatch(testo) is None:
        raise ValueError(testo)
    return float(testo)


def _offences_file(parsed_data: _Data, content: bytes) -> OffencesFile:
    versione = hashlib.sha256(content).hexdigest()[:12]
    return OffencesFile(
        dataset="caricato",
        titolo="Dati statistici caricati dall'utente",
        url="",
        estratto_il=versione,
        licenza="",
        anno=parsed_data.anno,
        anno_confronto=parsed_data.anno - _COMPARISON_YEARS,
        voci=dict(parsed_data.voci),
        valori=parsed_data.valori,
    )


# --- hazard -> item table ---


def _read_hazard(
    content: bytes,
    ontology_reading: OntologyReading | None,
    parsed_data: _Data | None,
    report: ValidationReport,
) -> tuple[frozenset[str], dict[str, HazardMapping]] | None:
    rows = read_csv(
        content,
        "hazard_table",
        required=HAZARD_COLUMNS,
        optional=HAZARD_OPTIONAL_COLUMNS,
        report=report,
    )
    if rows is None:
        return None
    seen: set[str] = set()
    valid: list[tuple[str, str | None, MatchKind | None, bool, str]] = []
    for row in rows:
        outcome = _hazard_row(row, ontology_reading, parsed_data, seen, report)
        if outcome is not None:
            valid.append(outcome)
    flags_per_item: dict[str, set[bool]] = {}
    for _, voce, _, break_flag, _ in valid:
        if voce is not None:
            flags_per_item.setdefault(voce, set()).add(break_flag)
    voci_rottura = frozenset(v for v, flag in flags_per_item.items() if True in flag)
    for voce in sorted(v for v, flag in flags_per_item.items() if len(flag) == 2):
        report.warning(
            "serie_non_confrontabile_incoerente",
            "hazard_table",
            f"la voce {voce!r} e' segnata serie_non_confrontabile=si in alcune "
            "righe e no in altre: vale si per tutta la voce",
        )
    mappatura = {
        hazard: HazardMapping(
            voce_istat=voce,
            corrispondenza=corrispondenza,
            rottura_2016=voce in voci_rottura if voce is not None else False,
            nota=nota,
        )
        for hazard, voce, corrispondenza, _, nota in valid
    }
    return voci_rottura, mappatura


def _hazard_row(
    row: CsvRow,
    ontology_reading: OntologyReading | None,
    parsed_data: _Data | None,
    seen: set[str],
    report: ValidationReport,
) -> tuple[str, str | None, MatchKind | None, bool, str] | None:
    c = row.cells
    hazard, voce, match_kind = c["hazard"], c["voce"], c["corrispondenza"]
    ok = True

    def add_error(codice: str, message: str) -> None:
        nonlocal ok
        ok = False
        report.error(codice, "hazard_table", message, line=row.line)

    if hazard in seen:
        add_error("chiave_duplicata", f"l'hazard {hazard[:40]!r} compare piu' volte")
    elif ontology_reading is not None and hazard not in ontology_reading.classes:
        add_error(
            "hazard_assente_dall_ontologia",
            f"l'hazard {hazard[:40]!r} non esiste nell'ontologia caricata",
        )
    if bool(voce) != bool(match_kind):
        add_error(
            "voce_corrispondenza_incoerenti",
            "voce e corrispondenza vanno compilate insieme o lasciate "
            "entrambe vuote (nessuna voce adeguata)",
        )
    elif voce:
        if match_kind not in _MATCHES:
            add_error(
                "corrispondenza_non_valida",
                f"corrispondenza {match_kind[:20]!r} non valida: {', '.join(_MATCHES)}",
            )
        if parsed_data is not None and voce not in parsed_data.voci:
            add_error(
                "voce_assente_dai_dati",
                f"la voce {voce[:40]!r} non compare nel file dei dati",
            )
    break_flag = _yes_no(c.get("serie_non_confrontabile", ""))
    if break_flag is None:
        add_error(
            "valore_non_valido",
            f"serie_non_confrontabile {c['serie_non_confrontabile'][:20]!r} "
            "non valido: si oppure no",
        )
    nota = c.get("nota", "")
    reason = check_note(nota)
    if reason is not None:
        add_error("testo_non_ammesso", reason)
    seen.add(hazard)
    if not ok or break_flag is None:
        return None
    return (
        hazard,
        voce or None,
        cast("MatchKind", match_kind) if match_kind else None,
        break_flag,
        nota,
    )


# --- boundaries ---


def _read_boundaries(content: bytes, report: ValidationReport) -> dict[str, Place]:
    try:
        root = cast("object", json.loads(content.decode("utf-8-sig")))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        report.error(
            "confini_illeggibili",
            "boundaries",
            f"il file dei confini non e' un JSON valido: {str(exc)[:200]}",
        )
        return {}
    if (
        not isinstance(root, dict)
        or cast("dict[str, object]", root).get("type") != "FeatureCollection"
        or not isinstance(cast("dict[str, object]", root).get("features"), list)
    ):
        report.error(
            "confini_non_validi",
            "boundaries",
            "il file dei confini deve essere un GeoJSON di tipo FeatureCollection",
        )
        return {}
    features = cast("list[object]", cast("dict[str, object]", root)["features"])
    luoghi: dict[str, Place] = {}
    for index, feature in enumerate(features, start=1):
        place = _feature(index, feature, report)
        if place is None:
            continue
        if place.codice in luoghi:
            report.error(
                "chiave_duplicata",
                "boundaries",
                f"feature {index}: il codice {place.codice!r} compare piu' volte",
            )
            continue
        luoghi[place.codice] = place
    return luoghi


def _feature(index: int, feature: object, report: ValidationReport) -> Place | None:
    def add_error(codice: str, message: str) -> None:
        report.error(codice, "boundaries", f"feature {index}: {message}")

    if not isinstance(feature, dict):
        add_error("confini_non_validi", "non e' un oggetto GeoJSON")
        return None
    fields = cast("dict[str, object]", feature)
    properties_raw = fields.get("properties")
    properties = (
        cast("dict[str, object]", properties_raw)
        if isinstance(properties_raw, dict)
        else {}
    )
    ok = True
    texts: dict[str, str] = {}
    for nome in ("codice", "tipo", "nome", "nome_breve"):
        value = properties.get(nome)
        if not isinstance(value, str) or not value.strip():
            add_error("confini_non_validi", f"manca la proprieta' {nome!r}")
            ok = False
        else:
            texts[nome] = value.strip()
    provincia_raw = properties.get("provincia")
    provincia = provincia_raw.strip() if isinstance(provincia_raw, str) else None
    if "codice" in texts and _PLACE_CODE.fullmatch(texts["codice"]) is None:
        add_error("codice_non_valido", f"codice {texts['codice'][:40]!r} non valido")
        ok = False
    if "tipo" in texts and texts["tipo"] not in _PLACE_TYPES:
        add_error(
            "confini_non_validi",
            f"tipo {texts['tipo'][:20]!r} non valido: comune o provincia",
        )
        ok = False
    for nome in ("nome", "nome_breve"):
        if nome in texts:
            reason = check_text(texts[nome])
            if reason is not None:
                add_error("testo_non_ammesso", f"proprieta' {nome!r}: {reason}")
                ok = False
    if provincia is not None and _PLACE_CODE.fullmatch(provincia) is None:
        add_error("codice_non_valido", f"provincia {provincia[:40]!r} non valida")
        ok = False
    geometry = fields.get("geometry")
    confine = _boundary(geometry, add_error)
    if not ok or confine is None:
        return None
    try:
        punto_interno = _interior_point(confine)
    except ValueError:
        add_error(
            "confini_non_validi",
            "non si trova un punto interno al poligono: geometria degenere",
        )
        return None
    return Place(
        codice=texts["codice"],
        tipo=cast("PlaceType", texts["tipo"]),
        nome=texts["nome"],
        nome_breve=texts["nome_breve"],
        provincia=provincia,
        bbox=_bbox(confine),
        punto_interno=punto_interno,
        confine=confine,
    )


def _boundary(
    geometry: object, add_error: Callable[[str, str], None]
) -> CityBoundary | None:
    if not isinstance(geometry, dict):
        add_error("confini_non_validi", "manca la geometria")
        return None
    geo = cast("dict[str, object]", geometry)
    tipo = geo.get("type")
    if tipo not in ("Polygon", "MultiPolygon"):
        add_error(
            "confini_non_validi",
            f"geometria {str(tipo)[:20]!r} non supportata: Polygon o MultiPolygon",
        )
        return None
    if not _numeric_coordinates(geo.get("coordinates")):
        add_error(
            "confini_non_validi",
            "le coordinate devono essere numeri JSON (non stringhe o booleani)",
        )
        return None
    try:
        confine = boundary_from_geojson(geo)
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        OverflowError,
        RecursionError,
    ):
        add_error("confini_non_validi", "coordinate della geometria malformate")
        return None
    if not confine.polygons:
        add_error("confini_non_validi", "la geometria non ha poligoni")
        return None
    for polygon in confine.polygons:
        if not polygon:
            add_error("confini_non_validi", "poligono senza anelli")
            return None
        for ring in polygon:
            if len(ring) < 4:
                add_error(
                    "confini_non_validi",
                    "ogni anello del poligono deve avere almeno 4 punti",
                )
                return None
            if ring[0] != ring[-1]:
                add_error(
                    "confini_non_validi",
                    "ogni anello deve essere chiuso: primo e ultimo punto uguali",
                )
                return None
            if _double_area(ring) == 0:
                add_error("confini_non_validi", "un anello ha area zero")
                return None
            for lon, lat in ring:
                if not (
                    math.isfinite(lon)
                    and math.isfinite(lat)
                    and -180 <= lon <= 180
                    and -90 <= lat <= 90
                ):
                    add_error(
                        "confini_non_validi",
                        "coordinate fuori range: longitudine -180..180, "
                        "latitudine -90..90",
                    )
                    return None
    return confine


def _numeric_coordinates(coordinates: object) -> bool:
    """``True`` if all the leaves are JSON numbers (no strings, no bool)."""
    stack: list[object] = [coordinates]
    while stack:
        leaf = stack.pop()
        if isinstance(leaf, list):
            stack.extend(cast("list[object]", leaf))
        elif isinstance(leaf, bool) or not isinstance(leaf, (int, float)):
            return False
    return True


def _double_area(ring: Ring) -> float:
    """Signed double area of the ring (shoelace formula)."""
    return sum(
        x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False)
    )


def _bbox(confine: CityBoundary) -> tuple[float, float, float, float]:
    points = [p for poly in confine.polygons for p in poly[0]]
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return (min(lons), min(lats), max(lons), max(lats))


def _interior_point(confine: CityBoundary) -> tuple[float, float]:
    """A point inside the largest polygon (the shape can be concave)."""
    main_polygon: Polygon = max(
        confine.polygons,
        key=lambda poly: (
            (max(p[0] for p in poly[0]) - min(p[0] for p in poly[0]))
            * (max(p[1] for p in poly[0]) - min(p[1] for p in poly[0]))
        ),
    )
    lats = [p[1] for p in main_polygon[0]]
    low, high = min(lats), max(lats)
    for fraction in (0.5, 0.25, 0.75, 0.4, 0.6, 0.1, 0.9):
        y = low + (high - low) * fraction
        crossings = sorted(_horizontal_crossings(main_polygon, y))
        intervals = list(zip(crossings[0::2], crossings[1::2], strict=False))
        if not intervals:
            continue
        x0, x1 = max(intervals, key=lambda i: i[1] - i[0])
        candidate = ((x0 + x1) / 2, y)
        if point_in_polygon(candidate, main_polygon):
            return candidate
    lon_min, lat_min, lon_max, lat_max = _bbox(confine)
    center = ((lon_min + lon_max) / 2, (lat_min + lat_max) / 2)
    if not any(point_in_polygon(center, poly) for poly in confine.polygons):
        raise ValueError("nessun punto interno trovato")
    return center


def _horizontal_crossings(polygon: Polygon, y: float) -> list[float]:
    crossings: list[float] = []
    for ring in polygon:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
            if (y1 > y) != (y2 > y):
                crossings.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    return crossings


def _choose_places(
    parsed_data: _Data,
    loaded: Mapping[str, Place],
    fallback: Sequence[Place],
    report: ValidationReport,
) -> tuple[Place, ...] | None:
    """Places of the data with boundaries (uploaded, then own); warns about others."""
    own_places = {place.codice: place for place in fallback}
    codes = sorted(set(parsed_data.valori) - {ITALY_CODE})
    chosen: list[Place] = []
    missing_boundaries: list[str] = []
    for codice in codes:
        place = loaded.get(codice) or own_places.get(codice)
        if place is None:
            missing_boundaries.append(codice)
        else:
            chosen.append(place)
    if not chosen:
        if not _unreadable_boundaries(report):
            report.error(
                "nessun_luogo_con_confini",
                "boundaries",
                "nessun luogo dei dati ha i confini, ne' caricati ne' nostri: "
                "carica il file dei confini con gli stessi codici dei dati",
            )
        return None
    if missing_boundaries:
        report.warning(
            "luogo_senza_confini",
            "data",
            f"luoghi senza confini, i POI al loro interno non avranno dati "
            f"statistici: {', '.join(missing_boundaries)}",
        )
    without_data = sorted(set(loaded) - set(codes))
    if without_data:
        report.warning(
            "luogo_senza_dati",
            "boundaries",
            "confini di luoghi che non hanno dati, ignorati: "
            f"{', '.join(without_data)}",
        )
    return tuple(sorted(chosen, key=lambda lg: (lg.tipo, lg.codice)))


def _unreadable_boundaries(report: ValidationReport) -> bool:
    return any(p.file == "boundaries" for p in report.errors)
