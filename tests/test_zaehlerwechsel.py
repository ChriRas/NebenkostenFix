"""NK-258: der Zählerwechsel im Rechenkern.

Wird ein Zähler getauscht, liest der Vermieter am selben Tag den Endstand
des alten und den Anfangsstand des neuen ab. Der Verbrauch im Zeitraum ist
die Summe beider Teile. Vorher kannte der Kern nur einen Zähler je Wohnung
und Kostenart: er nahm den mit der kleinsten id -- den alten -- und rechnete
dessen Stände über den Ausbau hinaus hoch. Alle Werte sind erfunden.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from nebenkostenfix.rechenkern import (
    Stand, Zaehler, fallende_staende, unterzaehler, verbrauch_in, verkette,
    wohnungszaehler,
)
from nebenkostenfix.zeitraum import grenze
from tests.test_pdf_rechenweg import unkomprimiert  # noqa: F401
from tests.test_pdf_verbrauchsnachweis import kasten
from tests.test_rechenkern import kategorie, rechne, rechnung, vorgang

JAHR = (date(2024, 1, 1), date(2025, 1, 1))
WECHSEL = date(2024, 7, 1)


def _z(id, *staende, ersetzt=None, wohnung=1, kat=2, name='Wasser', haupt=False):
    return Zaehler(id=id, nummer=f'Z-{id}', kategorie_id=kat, kategorie_name=name,
                   ist_hauptzaehler=haupt, immobilie_id=1, wohnung_id=wohnung,
                   staende=tuple(Stand(d, w, nt) for d, w, nt in staende),
                   ersetzt_id=ersetzt)


def _paar():
    """Alt: 100 → 400 bis zum Wechsel. Neu: 0 → 250 bis Jahresende. Zusammen 550."""
    alt = _z(1, (date(2024, 1, 1), 100, None), (WECHSEL, 400, None))
    neu = _z(2, (WECHSEL, 0, None), (date(2025, 1, 1), 250, None), ersetzt=1)
    return alt, neu


# --- Wechsel mitten im Zeitraum ----------------------------------------------------

def test_wechsel_mitten_im_jahr_summiert_beide_teile():
    """Vorher: nur der alte Zähler, 300 m³ auf das Jahr hochgerechnet ≈ 603 m³."""
    [kette] = verkette(_paar())
    d = verbrauch_in(kette, *JAHR)
    assert d['consumption'] == pytest.approx(550.0)
    assert d['is_interpolated'] is False


def test_die_wohnung_findet_die_kette_statt_des_alten_zaehlers():
    v = vorgang(zaehler=_paar())
    z = wohnungszaehler(v, 2)
    assert z.id == 2
    assert z.nummer == 'Z-1 / Z-2'
    assert verbrauch_in(z, *JAHR)['consumption'] == pytest.approx(550.0)


def test_ein_teilzeitraum_nimmt_den_passenden_teil():
    """Auszug am 1.10.: 300 vom alten, 92 der 184 Tage des neuen = 125."""
    [kette] = verkette(_paar())
    assert verbrauch_in(kette, date(2024, 1, 1), date(2024, 10, 1))['consumption'] == \
        pytest.approx(300 + 250 * 92 / 184)
    # Nur die Zeit nach dem Wechsel: allein der neue Zähler.
    assert verbrauch_in(kette, WECHSEL, date(2025, 1, 1))['consumption'] == pytest.approx(250.0)


def test_die_auskunft_nennt_echte_staende_und_den_wechsel():
    """Das Blatt zeigt, was auf den Zählern stand -- nicht die verschobenen Zahlen."""
    [kette] = verkette(_paar())
    d = verbrauch_in(kette, *JAHR)
    assert d['stand_beginn'] == pytest.approx(100.0)
    assert d['stand_ende'] == pytest.approx(250.0)
    assert d['zaehlerwechsel'] == [{'datum': '2024-07-01', 'alt': 'Z-1', 'endstand': 400.0,
                                    'neu': 'Z-2', 'anfangsstand': 0.0}]
    assert [b['total'] for b in d['basis_readings']] == [100.0, 400.0, 250.0]


def test_der_niedertarif_wird_getrennt_angeschlossen():
    alt = _z(1, (date(2024, 1, 1), 100, 50), (WECHSEL, 400, 150, ))
    neu = _z(2, (WECHSEL, 10, 5), (date(2025, 1, 1), 110, 45), ersetzt=1)
    [kette] = verkette((alt, neu))
    d = verbrauch_in(kette, *JAHR)
    assert d['ht'] == pytest.approx(300 + 100)
    assert d['nt'] == pytest.approx(100 + 40)
    assert d['consumption'] == pytest.approx(540)


# --- Wechsel am Stichtag ----------------------------------------------------------

def _am_stichtag():
    alt = _z(1, (date(2024, 1, 1), 100, None), (date(2025, 1, 1), 500, None))
    neu = _z(2, (date(2025, 1, 1), 0, None), (date(2026, 1, 1), 300, None), ersetzt=1)
    return verkette((alt, neu))[0]


def test_wechsel_am_stichtag_trennt_die_jahre_sauber():
    """Vorher rechnete 2025 der ausgebaute Zähler weiter: 400 statt 300."""
    kette = _am_stichtag()
    vorjahr = verbrauch_in(kette, *JAHR)
    jahr = verbrauch_in(kette, date(2025, 1, 1), date(2026, 1, 1))
    assert vorjahr['consumption'] == pytest.approx(400.0)
    assert jahr['consumption'] == pytest.approx(300.0)
    # Kein Wechsel innerhalb der Jahre; die Grenzen zeigen den passenden Zähler.
    assert vorjahr['zaehlerwechsel'] == [] and jahr['zaehlerwechsel'] == []
    assert vorjahr['stand_ende'] == pytest.approx(500.0)
    assert jahr['stand_beginn'] == pytest.approx(0.0)
    assert jahr['stand_ende'] == pytest.approx(300.0)


# --- Ketten und was unverändert bleibt -------------------------------------------

def test_zwei_wechsel_hintereinander():
    a = _z(1, (date(2024, 1, 1), 100, None), (date(2024, 5, 1), 200, None))
    b = _z(2, (date(2024, 5, 1), 0, None), (date(2024, 9, 1), 50, None), ersetzt=1)
    c = _z(3, (date(2024, 9, 1), 7, None), (date(2025, 1, 1), 27, None), ersetzt=2)
    [kette] = verkette((c, a, b))
    d = verbrauch_in(kette, *JAHR)
    assert d['consumption'] == pytest.approx(100 + 50 + 20)
    assert kette.nummer == 'Z-1 / Z-2 / Z-3'
    assert [(w['alt'], w['endstand'], w['anfangsstand']) for w in d['zaehlerwechsel']] == \
        [('Z-1', 200.0, 0.0), ('Z-2', 50.0, 7.0)]
    assert d['stand_ende'] == pytest.approx(27.0)


def test_ohne_wechselverweis_bleibt_alles_wie_es_war():
    a = _z(1, (date(2024, 1, 1), 1, None), (date(2025, 1, 1), 2, None))
    b = _z(2, (date(2024, 1, 1), 3, None), (date(2025, 1, 1), 4, None), wohnung=2)
    assert verkette((a, b)) == [a, b]


def test_unterzaehler_zaehlen_die_kette_einmal():
    """Sonst stünde der alte Zähler hochgerechnet ein zweites Mal im Nenner."""
    v = vorgang(zaehler=_paar())
    assert [z.id for z in unterzaehler(v, 2)] == [2]


def test_ein_verweis_im_kreis_haengt_nicht():
    """Die API legt keinen Kreis an; der Kern bricht trotzdem nicht in Rekursion."""
    a = _z(1, (date(2024, 1, 1), 1, None), ersetzt=2)
    b = _z(2, (date(2024, 1, 1), 1, None), ersetzt=1)
    verkette((a, b))


def test_der_wechsel_ist_kein_rueckwaerts_laufender_stand():
    """Die Prüfung auf fallende Stände sieht die echten Zähler, nicht die Kette."""
    v = vorgang(zaehler=_paar())
    assert fallende_staende(v, []) == []


def test_die_umlage_rechnet_mit_beiden_zaehlern():
    """Allgemeinstrom direkt nach Verbrauch (wie NK-105): 1000 → 1100, Tausch, 0 → 150."""
    kat = kategorie(id=11, name='Allgemeinstrom', braucht_zaehler=False)
    name = 'Allgemeinstrom'
    alt = _z(1, (date(2024, 1, 1), 1000, None), (WECHSEL, 1100, None), kat=11, name=name)
    neu = _z(2, (WECHSEL, 0, None), (date(2025, 1, 1), 150, None), ersetzt=1, kat=11, name=name)
    v = vorgang([rechnung('100.00', kat=kat)], profile={11: 'direkt'}, zaehler=[alt, neu])
    zeile = rechne(v)['line_items'][0]
    assert zeile['tenant_cost'] == Decimal('100.00')
    assert 'Eigenverbrauch ohne Hauptzähler (250,0 kWh' in zeile['description']


def test_der_jahresstichtag_als_grenze():
    """Die Abrechnung endet am 31.12.; ihre Grenze ist der 1.1. -- der Wechseltag."""
    kette = _am_stichtag()
    assert verbrauch_in(kette, date(2024, 1, 1), grenze(date(2024, 12, 31)))['consumption'] == \
        pytest.approx(400.0)


# --- Das Blatt (detailliertes PDF) --------------------------------------------------


def test_das_blatt_zeigt_den_wechsel_und_geht_auf(unkomprimiert):
    """(400 − 100) + (250 − 0) = 550: jede Zahl steht so auf einem Zähler."""
    [kette] = verkette(_paar())
    text = kasten(verbrauch_in(kette, *JAHR))
    assert 'ZählerstandBeginn01.01.2024(abgelesen):100,000m³' in text
    assert 'Zählerwechsel01.07.2024:EndstandZ-1400,000,AnfangsstandZ-20,000m³' in text
    assert 'ZählerstandEnde31.12.2024(abgelesen):250,000m³' in text
    assert 'Eigenverbrauch(beideZähler):550,000m³' in text
    assert 'ZugrundeliegendeAblesungen:01.01.2024:100,000·01.07.2024:400,000·01.01.2025:250,000' in text
