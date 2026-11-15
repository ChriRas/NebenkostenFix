"""PDF: die Aufstellung riet die Rubrik aus dem Namen (R-DOC-04).

R-DOC-04: „Die Gruppe kommt aus ``betrkv.RUBRIKEN`` über die BetrKV-Nummer
der Kostenart.“ Das Übersichtsblatt hält sich daran (``katalognummer`` liest
``CostCategory.betrkv_nr``; sein Docstring nennt den Fall: „Eine ‚Nahwärme‘
mit Nr. 4 hielt ``zuordnung`` für Nr. 17“). Die Aufstellung der Kosten in
``PDFGenerator.generate`` rief dagegen
``betrkv.rubrik(betrkv.zuordnung(item['category']))`` auf -- die Vermutung
aus dem Namen, die nur für den Altbestand gedacht ist.

Folge: Eine Kostenart „Nahwärme“, gepflegt als Nr. 4 (Heizkosten), stand im
selben PDF auf dem Übersichtsblatt unter den Heizkosten und in der
Aufstellung unter BETRIEBSKOSTEN. Erwartet: in der Aufstellung unter ENERGIE.

Alle Daten fiktiv.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
import reportlab.rl_config
from flask import has_app_context

from nebenkostenfix import betrkv
from nebenkostenfix.models import CostCategory, db
from nebenkostenfix.pdf_generator import PDFGenerator
from nebenkostenfix import pdf_uebersicht

#: Die Rubrikzeilen der Aufstellung, so wie das PDF sie setzt.
RUBRIKEN = ('ENERGIE', 'WASSER & ABWASSER', 'BETRIEBSKOSTEN')


def _entschluesselt(stueck: str) -> str:
    aus, i = [], 0
    while i < len(stueck):
        z = stueck[i]
        if z == '\\' and i + 1 < len(stueck):
            if stueck[i + 1] in '01234567':
                j, ziffern = i + 1, ''
                while j < len(stueck) and len(ziffern) < 3 and stueck[j] in '01234567':
                    ziffern += stueck[j]
                    j += 1
                aus.append(chr(int(ziffern, 8)))
                i = j
                continue
            aus.append(stueck[i + 1])
            i += 2
            continue
        aus.append(z)
        i += 1
    return ''.join(aus)


def _zeilen(pdf: bytes) -> list[str]:
    stuecke = []
    for roh in pdf.split(b'stream')[1:]:
        roh = roh.split(b'endstream')[0]
        stuecke.extend(_entschluesselt(m) for m in re.findall(
            r'\(((?:\\.|[^\\)])*)\)', roh.decode('latin-1', 'replace')))
    return stuecke


def _posten(kategorie: str, betrag: str) -> dict:
    return {
        'category': kategorie,
        'period': '01.01.2025 - 31.12.2025',
        'description': 'Umlage nach Wohnfläche (50 von 100 m²)',
        'billing_type': 'qm',
        'tenant_cost': Decimal(betrag),
        'invoice_days': 365,
        'overlap_days': 365,
        'invoice_total_amount': Decimal(betrag) * 2,
        'prorated_amount': Decimal(betrag) * 2,
        'invoice_number': 'R-2025-1',
    }


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_nahwaerme_mit_nr_4_steht_unter_energie(app_ctx, monkeypatch, detailliert):
    monkeypatch.setattr(reportlab.rl_config, 'pageCompression', 0)
    db.session.add(CostCategory(name='Nahwärme', allocation_method='qm',
                                requires_meter=False, betrkv_nr=4))
    db.session.commit()

    posten = [_posten('Nahwärme', '300.00'), _posten('Grundsteuer', '100.00')]
    # Das Übersichtsblatt liest die Nummer aus dem Bestand: Heizkosten.
    assert pdf_uebersicht.ist_heizkosten(posten[0])

    pdf = PDFGenerator(
        property_name='Teststraße 1', apartment_name='Wohnung 1',
        tenant_name='Mieter Eins', start_date='2025-01-01',
        end_date='2025-12-31', detailliert=detailliert,
    ).generate(posten, Decimal('400.00'), Decimal('0.00'))
    zeilen = _zeilen(pdf)

    gruppen = [i for i, z in enumerate(zeilen) if z in ('ENERGIE', 'BETRIEBSKOSTEN')]
    assert gruppen, 'keine Rubriken in der Aufstellung gefunden'
    namen = {zeilen[i]: i for i in gruppen}
    assert 'ENERGIE' in namen, (
        'Die Aufstellung kennt keine Rubrik ENERGIE, obwohl „Nahwärme“ als '
        'Nr. 4 gepflegt ist; Rubriken: ' + str([zeilen[i] for i in gruppen]))
    nahwaerme = [i for i, z in enumerate(zeilen) if z == 'Nahwärme' and i > gruppen[0]]
    assert nahwaerme, 'Nahwärme fehlt in der Aufstellung'
    rubrik_davor = max((i for i in gruppen if i < nahwaerme[0]))
    assert zeilen[rubrik_davor] == 'ENERGIE', (
        f'Nahwärme (Nr. 4) steht unter {zeilen[rubrik_davor]} statt ENERGIE')


# ---------------------------------------------------------------------------
# Der Fall aus dem Testplan: ein Mieter, drei Kostenarten, eine Wohnung.
# ---------------------------------------------------------------------------

def _kostenart(name: str, nr: int) -> None:
    """Legt die Kostenart an, wenn der Seed sie nicht schon mitbringt."""
    zeile = CostCategory.query.filter_by(name=name).first()
    if zeile is None:
        db.session.add(CostCategory(name=name, allocation_method='qm',
                                    requires_meter=False, betrkv_nr=nr))
        db.session.commit()
        return
    assert zeile.betrkv_nr == nr, f'{name} steht im Seed unter Nr. {zeile.betrkv_nr}'


def _bestand() -> list[dict]:
    _kostenart('Nahwärme', 4)
    _kostenart('Grundsteuer', 1)
    _kostenart('Kaltwasser', 2)
    return [_posten('Nahwärme', '300.00'), _posten('Grundsteuer', '100.00'),
            _posten('Kaltwasser', '80.00')]


def _aufstellung(posten: list[dict], gesamt: str, detailliert: bool) -> list[str]:
    """Die Textstücke der Aufstellung: von der ersten Rubrik bis zum Summenblock."""
    pdf = PDFGenerator(
        property_name='Teststraße 1', apartment_name='W1',
        tenant_name='Mieter Rubrik', start_date='2025-01-01',
        end_date='2025-12-31', detailliert=detailliert,
    ).generate(posten, Decimal(gesamt), Decimal('400.00'))
    zeilen = _zeilen(pdf)
    anfang = min(i for i, z in enumerate(zeilen) if z in RUBRIKEN)
    ende = zeilen.index('Gesamtkosten der Periode', anfang)
    return zeilen[anfang:ende]


def _rubrik_von(aufstellung: list[str], name: str) -> str:
    """Unter welcher Rubrik der Aufstellung steht die Kostenart?"""
    assert name in aufstellung, f'{name} fehlt in der Aufstellung'
    stelle = aufstellung.index(name)
    return [z for z in aufstellung[:stelle] if z in RUBRIKEN][-1]


def _zwischensumme(aufstellung: list[str], rubrik: str) -> str:
    stelle = aufstellung.index(f'Zwischensumme {rubrik}')
    return aufstellung[stelle + 1]


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_jede_kostenart_steht_unter_der_rubrik_ihrer_nummer(
        app_ctx, monkeypatch, detailliert):
    monkeypatch.setattr(reportlab.rl_config, 'pageCompression', 0)
    aufstellung = _aufstellung(_bestand(), '480.00', detailliert)

    # Alle drei Rubriken, in der festen Reihenfolge der Aufstellung.
    assert [z for z in aufstellung if z in RUBRIKEN] == list(RUBRIKEN)
    assert _rubrik_von(aufstellung, 'Nahwärme') == 'ENERGIE'
    # Wie bisher: Nr. 1 und Nr. 2 behalten ihre Rubrik.
    assert _rubrik_von(aufstellung, 'Grundsteuer') == 'BETRIEBSKOSTEN'
    assert _rubrik_von(aufstellung, 'Kaltwasser') == 'WASSER & ABWASSER'


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_rubriksummen_folgen_der_nummer_und_die_gesamtsumme_bleibt(
        app_ctx, monkeypatch, detailliert):
    monkeypatch.setattr(reportlab.rl_config, 'pageCompression', 0)
    posten = _bestand()
    pdf = PDFGenerator(
        property_name='Teststraße 1', apartment_name='W1',
        tenant_name='Mieter Rubrik', start_date='2025-01-01',
        end_date='2025-12-31', detailliert=detailliert,
    ).generate(posten, Decimal('480.00'), Decimal('400.00'))
    zeilen = _zeilen(pdf)
    anfang = min(i for i, z in enumerate(zeilen) if z in RUBRIKEN)
    aufstellung = zeilen[anfang:]

    assert _zwischensumme(aufstellung, 'Energie') == '300,00'
    assert _zwischensumme(aufstellung, 'Wasser & Abwasser') == '80,00'
    assert _zwischensumme(aufstellung, 'Betriebskosten') == '100,00'
    # Der Summenblock unter der Aufstellung: unverändert 480,00 €. Die
    # Standardschrift kodiert das Eurozeichen in WinAnsi als 0x80.
    stelle = aufstellung.index('Gesamtkosten der Periode')
    assert aufstellung[stelle + 1].replace('\x80', '€') == '480,00 €'
    assert sum(p['tenant_cost'] for p in posten) == Decimal('480.00')


def test_uebersichtsblatt_und_aufstellung_lesen_dieselbe_nummer(app_ctx, monkeypatch):
    """Beide Richtungen: Nahwärme ist Nr. 4, obwohl der Name Nr. 17 vermuten
    ließe; die „Gaslaterne“ ist Nr. 11 (Beleuchtung), obwohl das Teilwort
    „gas“ Nr. 4 vermuten ließe."""
    monkeypatch.setattr(reportlab.rl_config, 'pageCompression', 0)
    _kostenart('Gaslaterne', 11)
    posten = _bestand() + [_posten('Gaslaterne', '20.00')]
    # Der Name allein führte beide Male woanders hin.
    assert betrkv.zuordnung('Nahwärme') == 17
    assert betrkv.zuordnung('Gaslaterne') == 4

    aufstellung = _aufstellung(posten, '500.00', detailliert=False)
    for p in posten:
        auf_dem_blatt = pdf_uebersicht.ist_heizkosten(p)
        in_der_aufstellung = _rubrik_von(aufstellung, p['category']) == 'ENERGIE'
        assert auf_dem_blatt == in_der_aufstellung, (
            f"{p['category']}: Übersichtsblatt Heizkosten={auf_dem_blatt}, "
            f"Aufstellung {_rubrik_von(aufstellung, p['category'])}")
    assert _rubrik_von(aufstellung, 'Gaslaterne') == 'BETRIEBSKOSTEN'

    # Die eine Funktion, aus der beide ihre Nummer holen.
    assert pdf_uebersicht.katalognummer('Nahwärme') == 4
    assert pdf_uebersicht.katalognummer('Gaslaterne') == 11


def test_ohne_bestandszeile_bleibt_die_vermutung_aus_dem_namen(app_ctx, monkeypatch):
    """Gegenprobe: ein Name, den es im Bestand nicht (mehr) gibt.

    Der Seed bringt „Hauswart“ als Nr. 14 mit; der fiktive Altname
    „Hausmeisterdienst“ hat keine Zeile und fällt über ``zuordnung`` auf
    Nr. 14, „Fernwärme Altvertrag“ auf Nr. 4."""
    monkeypatch.setattr(reportlab.rl_config, 'pageCompression', 0)
    for name in ('Hausmeisterdienst', 'Fernwärme Altvertrag'):
        assert CostCategory.query.filter_by(name=name).first() is None

    posten = _bestand() + [_posten('Hausmeisterdienst', '40.00'),
                           _posten('Fernwärme Altvertrag', '60.00')]
    aufstellung = _aufstellung(posten, '580.00', detailliert=False)

    assert _rubrik_von(aufstellung, 'Hausmeisterdienst') == betrkv.rubrik(14).upper()
    assert _rubrik_von(aufstellung, 'Hausmeisterdienst') == 'BETRIEBSKOSTEN'
    assert _rubrik_von(aufstellung, 'Fernwärme Altvertrag') == 'ENERGIE'

    assert pdf_uebersicht.katalognummer('Hausmeisterdienst') == 14
    assert pdf_uebersicht.katalognummer('Fernwärme Altvertrag') == 4


def test_ohne_anwendungskontext_bleibt_die_vermutung_aus_dem_namen():
    assert not has_app_context()
    for name in ('Nahwärme', 'Grundsteuer', 'Kaltwasser', 'Hauswart', None):
        assert pdf_uebersicht.katalognummer(name) == betrkv.zuordnung(name)


# ---------------------------------------------------------------------------
# Nachbesserung: Übersichtsblatt und Aufstellung entscheiden über dieselbe
# Funktion -- auch für eine Zeile, die der Kern über die Heizungsanlage
# gerechnet hat (``billing_type == 'heizkosten'``), deren Name aber eine
# andere Nummer vermuten lässt.
# ---------------------------------------------------------------------------

HEIZNAME = 'Heizkosten (Haus am Kanal)'


def _heizposten(betrag: str) -> dict:
    posten = _posten(HEIZNAME, betrag)
    posten['billing_type'] = 'heizkosten'
    posten['description'] = 'Verteilung nach HeizkostenV'
    return posten


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_heizkostenzeile_aus_der_anlage_steht_unter_energie(
        app_ctx, monkeypatch, detailliert):
    monkeypatch.setattr(reportlab.rl_config, 'pageCompression', 0)
    # Vorbedingung: keine Bestandszeile, und der Name allein führt auf
    # Nr. 3 (Entwässerung, „Kanal“) -- also Wasser & Abwasser.
    assert CostCategory.query.filter_by(name=HEIZNAME).first() is None
    assert betrkv.zuordnung(HEIZNAME) == 3

    posten = _bestand() + [_heizposten('120.00')]
    # Das Übersichtsblatt zählt die Zeile zu den Heizkosten ...
    assert pdf_uebersicht.ist_heizkosten(posten[-1])

    aufstellung = _aufstellung(posten, '600.00', detailliert)
    # ... und die Aufstellung muss sie dann unter ENERGIE führen.
    assert _rubrik_von(aufstellung, HEIZNAME) == 'ENERGIE', (
        f'{HEIZNAME} (billing_type heizkosten) steht unter '
        f'{_rubrik_von(aufstellung, HEIZNAME)} statt ENERGIE')
    assert _zwischensumme(aufstellung, 'Energie') == '420,00'
    assert _zwischensumme(aufstellung, 'Wasser & Abwasser') == '80,00'
    assert _zwischensumme(aufstellung, 'Betriebskosten') == '100,00'

    # Der Summenblock darunter: unverändert die Summe aller Posten.
    pdf = PDFGenerator(
        property_name='Teststraße 1', apartment_name='W1',
        tenant_name='Mieter Rubrik', start_date='2025-01-01',
        end_date='2025-12-31', detailliert=detailliert,
    ).generate(posten, Decimal('600.00'), Decimal('400.00'))
    zeilen = _zeilen(pdf)
    stelle = zeilen.index('Gesamtkosten der Periode')
    assert zeilen[stelle + 1].replace('\x80', '€') == '600,00 €'
    assert sum(p['tenant_cost'] for p in posten) == Decimal('600.00')


def test_rubrik_und_heizkosten_sind_eine_entscheidung(app_ctx):
    """``ist_heizkosten`` ist genau „Rubrik Energie“, für jeden Posten.

    Das beruht auf einer Gleichheit: Nr. 4, 5, 6 sind sowohl HeizkostenV
    (``HEIZKOSTENNUMMERN``) als auch die Rubrik Energie in ``betrkv``."""
    energie = {nr for nr, name in betrkv.RUBRIKEN.items() if name == 'Energie'}
    assert energie == set(pdf_uebersicht.HEIZKOSTENNUMMERN) == {4, 5, 6}

    _kostenart('Gaslaterne', 11)
    posten = _bestand() + [_posten('Gaslaterne', '20.00'),
                           _posten('Fernwärme Altvertrag', '60.00'),
                           _heizposten('120.00')]
    for p in posten:
        assert pdf_uebersicht.ist_heizkosten(p) == (
            pdf_uebersicht.rubrik(p) == 'Energie'), p['category']
    assert pdf_uebersicht.rubrik(_heizposten('1.00')) == 'Energie'
    assert pdf_uebersicht.rubrik(_posten('Nahwärme', '1.00')) == 'Energie'
    assert pdf_uebersicht.rubrik(_posten('Kaltwasser', '1.00')) == 'Wasser & Abwasser'
    assert pdf_uebersicht.rubrik(_posten('Gaslaterne', '1.00')) == 'Betriebskosten'

    # Die Prüfung beim Import schlägt an, sobald die Listen auseinanderlaufen
    # (fiktive Rubrikentabelle, in der Nr. 6 fehlt).
    pdf_uebersicht.pruefe_heizkostennummern()
    with pytest.raises(RuntimeError, match='HEIZKOSTENNUMMERN'):
        pdf_uebersicht.pruefe_heizkostennummern(
            {2: 'Wasser & Abwasser', 4: 'Energie', 5: 'Energie'})
