"""NK-265: Prüfstand vor dem Festsetzen.

Ein Haus, an dem nichts auffällt; jeder Test baut genau einen Fehler ein und
erwartet genau die eine Warnung, mit dem Ziel, an dem sie sich beheben
lässt. Alle Werte sind erfunden.
"""

from __future__ import annotations

from datetime import date

import pytest

from nebenkostenfix.jahresabrechnung import stand
from nebenkostenfix.models import Payment, db
from tests import billing_factories as f

D = date
JAHR = 2024
HEUTE = D(2025, 6, 1)


@pytest.fixture
def haus(app_ctx):
    h = f.house('Haus P')
    h.abrechnungsjahr_beginn = '01-01'
    w = f.apt(h, 'EG', 50)
    a = f.tenant(w, 'Mieter A', D(2023, 1, 1))
    grundsteuer = f.category('Grundsteuer')
    for jahr in (2023, JAHR):
        r = f.invoice(h, grundsteuer, 500, D(jahr, 1, 1), D(jahr, 12, 31))
        r.document_path = 'belege/grundsteuer.pdf'
    f.payment(a, 100, D(JAHR, 1, 3))
    db.session.commit()
    return h


def _befunde(haus):
    return stand(haus.id, JAHR, HEUTE)['pruefstand']


def _einziger(haus, art):
    befunde = _befunde(haus)
    assert [b['art'] for b in befunde] == [art], befunde
    return befunde[0]


def _wohnung(haus):
    return haus.apartments[0]


def _mieter(haus):
    return _wohnung(haus).tenants[0]


def test_ein_sauberes_jahr_hat_keine_warnung(haus):
    assert _befunde(haus) == []


def test_euro_je_qm_gegen_vorjahr(haus):
    rechnung = [r for r in haus.invoices if r.start_date.year == JAHR][0]
    rechnung.amount = 650
    db.session.commit()
    b = _einziger(haus, 'kosten_je_qm')
    assert '13,00 €/m² statt 10,00 €/m²' in b['text'] and '+30 %' in b['text']
    assert b['tun'].startswith('Prüfen Sie die Rechnungen')
    assert b['ziel'] == {'aktion': 'rechnungen', 'id': None}


def test_zaehlersprung_und_ruhiger_zaehler(haus):
    wasser = f.category('Wasserversorgung')
    w = _wohnung(haus)
    springt = f.meter(haus, wasser, 'P-1', is_main=False, apartment=w)
    for tag, stand_ in ((D(2023, 1, 1), 0), (D(2023, 12, 31), 100), (D(2024, 12, 31), 300)):
        f.reading(springt, tag, stand_)
    ruhig = f.meter(haus, wasser, 'P-2', is_main=False, apartment=w)
    for tag, stand_ in ((D(2023, 1, 1), 0), (D(2023, 12, 31), 100), (D(2024, 12, 31), 210)):
        f.reading(ruhig, tag, stand_)
    b = _einziger(haus, 'zaehlersprung')
    assert b['text'].startswith('Zähler P-1 (EG)') and 'im Vorjahr (+' in b['text']
    assert b['ziel'] == {'aktion': 'zaehler', 'id': springt.id}


def test_rechnung_ohne_beleg(haus):
    rechnung = [r for r in haus.invoices if r.start_date.year == JAHR][0]
    rechnung.document_path = None
    db.session.commit()
    b = _einziger(haus, 'ohne_beleg')
    assert '„Grundsteuer“ über 500,00 €' in b['text'] and 'keinen Beleg' in b['text']
    assert b['ziel'] == {'aktion': 'rechnung', 'id': rechnung.id}


def test_rechnung_ausserhalb_des_zeitraums(haus):
    r = f.invoice(haus, f.category('Sach- und Haftpflichtversicherung'), 365,
                  D(JAHR, 7, 1), D(JAHR + 1, 6, 30))
    r.document_path = 'belege/versicherung.pdf'
    db.session.commit()
    b = _einziger(haus, 'ausserhalb')
    assert 'es zählen 184 von 365 Tagen' in b['text']
    assert b['ziel'] == {'aktion': 'rechnung', 'id': r.id}


def test_leerstand_aber_nicht_eigennutzung(haus):
    _mieter(haus).move_out_date = D(JAHR, 6, 30)
    selbst = f.apt(haus, 'DG', 40)
    selbst.eigennutzung = True
    db.session.commit()
    b = _einziger(haus, 'leerstand')
    assert b['text'] == 'Die Wohnung EG stand 184 Tage leer; diesen Anteil tragen Sie.'
    assert b['ziel'] == {'aktion': 'mieter', 'id': _wohnung(haus).id}


def test_mieter_ohne_vorauszahlung(haus):
    a = _mieter(haus)
    Payment.query.delete()
    f.payment(a, 700, D(JAHR, 2, 1), 'Miete')  # Miete ist keine Vorauszahlung
    b = _einziger(haus, 'ohne_vorauszahlung')
    assert b['text'] == 'Für Mieter A (EG) ist im Zeitraum keine Vorauszahlung erfasst.'
    assert b['ziel'] == {'aktion': 'zahlung', 'id': a.id}


def test_fehlende_ablesung_beim_wechsel_einmal_je_wechsel(haus):
    w = _wohnung(haus)
    _mieter(haus).move_out_date = D(JAHR, 6, 30)
    b_mieter = f.tenant(w, 'Mieter B', D(JAHR, 7, 1))
    f.payment(b_mieter, 100, D(JAHR, 7, 3))
    z = f.meter(haus, f.category('Wasserversorgung'), 'P-3', is_main=False, apartment=w)
    f.reading(z, D(JAHR - 1, 12, 31), 10)
    f.reading(z, D(JAHR, 12, 31), 20)
    # Auszug am 30.06. und Einzug am 01.07. sind ein Wechsel, keine zwei.
    b = _einziger(haus, 'wechsel_ablesung')
    assert b['text'] == 'Zähler P-3 (EG) hat keinen Stand zum Mieterwechsel am 30.06.2024.'
    assert b['ziel'] == {'aktion': 'ablesung', 'id': z.id}


def test_jede_warnung_sagt_was_zu_tun_ist(haus):
    _mieter(haus).move_out_date = D(JAHR, 6, 30)
    Payment.query.delete()
    for r in haus.invoices:
        r.document_path = None
    db.session.commit()
    befunde = _befunde(haus)
    assert {b['art'] for b in befunde} == {'leerstand', 'ohne_vorauszahlung', 'ohne_beleg'}
    for b in befunde:
        assert b['text'] and b['tun'].split()[1] == 'Sie', b


def test_die_route_liefert_den_pruefstand(auth_client, haus):
    antwort = auth_client.get(f'/api/jahresabrechnung?property_id={haus.id}&jahr={JAHR}')
    assert antwort.status_code == 200
    assert antwort.get_json()['pruefstand'] == []
