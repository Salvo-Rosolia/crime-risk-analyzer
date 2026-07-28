from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from crime_risk_analyzer.i18n import terminus_labels as tl


@pytest.fixture(autouse=True)
def _isola_cache_vocabolario() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Ripulisce la cache del vocabolario in ENTRATA e in USCITA da ogni test qui.

    I test di questo modulo sostituiscono il file dati (``_DATA_PATH``), e
    ``monkeypatch`` ripristina l'attributo ma NON il contenuto dell'``lru_cache`` di
    ``_records()``: senza la pulizia in uscita, il vocabolario finto — o vuoto, per
    ``test_missing_data_file_yields_empty_records`` — resta in memoria per tutto il
    resto del processo pytest. Ogni test successivo che asserisce un'etichetta reale
    leggerebbe lo stub e passerebbe o fallirebbe per la ragione sbagliata: e' emerso
    con #256, dove ``Hostages`` tornava ``Hostages`` invece di ``Ostaggi`` solo nella
    suite intera. La fixture e' ``autouse`` cosi' nessun test del modulo puo'
    dimenticarsene, nemmeno quelli che patchano da soli nel corpo.
    """
    tl._records.cache_clear()  # pyright: ignore[reportPrivateUsage]
    yield
    tl._records.cache_clear()  # pyright: ignore[reportPrivateUsage]


@pytest.fixture()
def _fake_data(  # pyright: ignore[reportUnusedFunction]
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    data = [
        {
            "identifier": "Bank_robbery",
            "label_en": "Bank robbery",
            "label_it": "Rapina in banca",
            "category": "hazard",
        },
        {
            "identifier": "Empty_it",
            "label_en": "Empty it",
            "label_it": "",
            "category": "hazard",
        },
    ]
    path = tmp_path / "terminus_labels.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(tl, "_DATA_PATH", path)
    tl._records.cache_clear()  # pyright: ignore[reportPrivateUsage]
    yield path
    # La cache va ripulita ANCHE in uscita: ``monkeypatch`` ripristina ``_DATA_PATH``,
    # non il contenuto dell'``lru_cache``, che resterebbe popolato col vocabolario
    # finto di due voci per tutto il resto del processo. Ogni test successivo che
    # asserisce un'etichetta reale leggerebbe lo stub e passerebbe (o fallirebbe) per
    # la ragione sbagliata: e' emerso con #256, dove `Hostages` tornava `Hostages`
    # invece di `Ostaggi` solo nella suite intera.
    tl._records.cache_clear()  # pyright: ignore[reportPrivateUsage]


def test_label_it_returns_curated_value(_fake_data: Path) -> None:
    assert tl.label_it("Bank_robbery") == "Rapina in banca"


def test_label_it_falls_back_to_label_en_when_it_empty(_fake_data: Path) -> None:
    assert tl.label_it("Empty_it") == "Empty it"


def test_label_it_falls_back_to_normalized_identifier_when_absent(
    _fake_data: Path,
) -> None:
    assert tl.label_it("Unknown_class") == "Unknown class"


def test_label_en_returns_corrected_value(_fake_data: Path) -> None:
    assert tl.label_en("Bank_robbery") == "Bank robbery"


def test_label_en_falls_back_to_normalized_identifier(_fake_data: Path) -> None:
    assert tl.label_en("Unknown_class") == "Unknown class"


def test_controlled_vocab_for_is_deduped_and_stable(_fake_data: Path) -> None:
    vocab = tl.controlled_vocab_for(["Bank_robbery", "Bank_robbery", "Empty_it"])
    assert vocab == ["Rapina in banca", "Empty it"]


def test_missing_data_file_yields_empty_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tl, "_DATA_PATH", tmp_path / "does_not_exist.json")
    tl._records.cache_clear()  # pyright: ignore[reportPrivateUsage]
    assert tl.label_it("Whatever_class") == "Whatever class"
