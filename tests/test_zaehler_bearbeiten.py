"""NK-258: Zähler bearbeiten, Zählerwechsel und Eichfrist.

Vorher ließ sich ein Zähler nur anlegen und löschen; ein Tippfehler in der
Nummer hieß: löschen, mit allen Ständen. Ein Tausch ließ sich gar nicht
erfassen -- der Kern rechnete den alten Zähler über den Ausbau hinaus hoch.
Und „geeicht bis“ (R-EICH-01) gab es nicht. Alle Werte sind erfunden.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from nebenkostenfix import eichfrist, zeit
from nebenkostenfix.billing_engine import BillingEngine
from nebenkostenfix.models import Meter, MeterReading, db
from tests import billing_factories as f

WURZEL = Path(__file__).resolve().parent.parent
JAHR = (date(2024, 1, 1), date(2024, 12, 31))


def _heute():
    return zeit.als_ortsdatum(zeit.jetzt_utc())


@pytest.fixture
def zaehler(app_ctx):
    haus = f.house()
    z = f.meter(haus, f.category('Wasser'), 'WZ-1', is_main=False,
                apartment=f.apt(haus, 'EG', 50))
    f.reading(z, date(2024, 1, 1), 100.0)
    return z


def _wechsel(client, z, **mehr):
    daten = {'datum': '2024-07-01', 'endstand': '400', 'meter_number': 'WZ-2',
             'anfangsstand': '0', **mehr}
    return client.post(f'/api/meters/{z.id}/wechsel', data=daten)


def _liste(client):
    return {m['id']: m for m in client.get('/api/meters').get_json()}


# --- Bearbeiten -------------------------------------------------------------------

def test_bearbeiten_aendert_nur_was_mitkommt(auth_client, zaehler):
    """Vorher: 405 -- es gab keinen Weg, eine Nummer zu berichtigen."""
    antwort = auth_client.put(f'/api/meters/{zaehler.id}',
                              json={'meter_number': 'WZ-1a', 'ort': 'Keller'})
    assert antwort.status_code == 200
    m = _liste(auth_client)[zaehler.id]
    assert (m['meter_number'], m['ort'], m['apartment_name']) == ('WZ-1a', 'Keller', 'EG')
    assert MeterReading.query.filter_by(meter_id=zaehler.id).count() == 1


def test_bearbeiten_prueft_wie_das_anlegen(auth_client, zaehler):
    leer = auth_client.put(f'/api/meters/{zaehler.id}', json={'meter_number': ''})
    assert leer.status_code == 400 and leer.get_json()['feld'] == 'meter_number'
    lang = auth_client.put(f'/api/meters/{zaehler.id}', json={'ort': 'x' * 101})
    assert lang.status_code == 400 and lang.get_json()['feld'] == 'ort'
    assert auth_client.put('/api/meters/99999', json={'ort': 'x'}).status_code == 404


def test_die_kostenart_bleibt_in_einer_kette(auth_client, zaehler):
    andere = f.category('Grundsteuer').id
    assert _wechsel(auth_client, zaehler).status_code == 201
    antwort = auth_client.put(f'/api/meters/{zaehler.id}', json={'category_id': andere})
    assert antwort.status_code == 400 and antwort.get_json()['feld'] == 'category_id'


# --- Zählerwechsel ------------------------------------------------------------------

def test_der_wechsel_legt_den_neuen_zaehler_mit_beiden_staenden_an(auth_client, zaehler):
    antwort = _wechsel(auth_client, zaehler, ort='Bad')
    assert antwort.status_code == 201
    neu = db_meter(antwort.get_json()['id'])
    assert (neu.ersetzt_id, neu.apartment_id, neu.category_id, neu.ort) == \
        (zaehler.id, zaehler.apartment_id, zaehler.category_id, 'Bad')
    assert [(r.reading_date, r.value) for r in zaehler.readings][-1] == (date(2024, 7, 1), 400.0)
    assert [(r.reading_date, r.value) for r in neu.readings] == [(date(2024, 7, 1), 0.0)]
    liste = _liste(auth_client)
    assert liste[zaehler.id]['ersetzt_durch'] == neu.id
    assert liste[neu.id]['ersetzt_id'] == zaehler.id


def db_meter(id):
    return Meter.query.get(id)


def test_ein_zweiter_wechsel_desselben_zaehlers_geht_nicht(auth_client, zaehler):
    assert _wechsel(auth_client, zaehler).status_code == 201
    assert _wechsel(auth_client, zaehler, meter_number='WZ-3').status_code == 400
    assert Meter.query.count() == 2


def test_staende_nach_dem_wechseltag_halten_ihn_auf(auth_client, zaehler):
    f.reading(zaehler, date(2024, 9, 1), 500.0)
    antwort = _wechsel(auth_client, zaehler)
    assert antwort.status_code == 400 and antwort.get_json()['feld'] == 'datum'
    assert Meter.query.count() == 1


def test_der_endstand_wird_geprueft_wie_jeder_stand(auth_client, zaehler):
    """NK-216 gilt auch hier: rückwärts ist eine Frage, negativ ein Fehler."""
    frage = _wechsel(auth_client, zaehler, endstand='50')
    assert frage.status_code == 409 and frage.get_json()['nachfrage'] is True
    assert Meter.query.count() == 1
    assert _wechsel(auth_client, zaehler, endstand='50', trotzdem='1').status_code == 201

    zaehler2 = f.meter(zaehler.property, zaehler.category, 'WZ-9', is_main=False)
    negativ = _wechsel(auth_client, zaehler2, endstand='-1')
    assert negativ.status_code == 400 and negativ.get_json()['feld'] == 'endstand'
    zukunft = _wechsel(auth_client, zaehler2, datum=(_heute() + timedelta(days=1)).isoformat())
    assert zukunft.status_code == 400 and zukunft.get_json()['feld'] == 'datum'
    anfang = _wechsel(auth_client, zaehler2, anfangsstand='-1')
    assert anfang.status_code == 400 and anfang.get_json()['feld'] == 'anfangsstand'


def test_beim_zweitarifzaehler_gehoeren_beide_zaehlwerke_dazu(auth_client, zaehler):
    zaehler.has_dual_tariff = True
    db.session.commit()
    ohne = _wechsel(auth_client, zaehler)
    assert ohne.status_code == 400 and ohne.get_json()['feld'] == 'endstand_nt'
    mit = _wechsel(auth_client, zaehler, endstand_nt='40', anfangsstand_nt='0')
    assert mit.status_code == 201
    neu = db_meter(mit.get_json()['id'])
    assert neu.has_dual_tariff is True
    assert neu.readings[0].value_nt == 0.0


def test_loeschen_des_alten_zaehlers_loest_die_kette(auth_client, zaehler):
    neu = _wechsel(auth_client, zaehler).get_json()['id']
    assert auth_client.delete(f'/api/meters/{zaehler.id}').status_code == 200
    assert db_meter(neu).ersetzt_id is None


def _abrechnung_wasser(mit_wechsel: bool):
    """Wohnung A mit oder ohne Tausch; der Verbrauch ist beide Male 550.

    Jedes Mal ein eigenes Haus: der Hauptzähler gilt je Immobilie.
    """
    haus = f.house('Mit Wechsel' if mit_wechsel else 'Ohne Wechsel')
    a, b = f.apt(haus, 'A', 50), f.apt(haus, 'B', 50)
    mieter = f.tenant(a, 'Mieter A')
    f.tenant(b, 'Mieter B')
    kat = f.category('Wasser')
    f.profile(mieter, kat, 'direkt')
    f.invoice(haus, kat, 1000.0)
    haupt = f.meter(haus, kat, 'H', is_main=True)
    f.reading(haupt, date(2024, 1, 1), 0.0)
    f.reading(haupt, date(2025, 1, 1), 1000.0)
    zb = f.meter(haus, kat, 'B', is_main=False, apartment=b)
    f.reading(zb, date(2024, 1, 1), 0.0)
    f.reading(zb, date(2025, 1, 1), 450.0)
    za = f.meter(haus, kat, 'A', is_main=False, apartment=a)
    f.reading(za, date(2024, 1, 1), 100.0)
    if mit_wechsel:
        f.reading(za, date(2024, 7, 1), 400.0)
        neu = Meter(category_id=kat.id, property_id=haus.id, apartment_id=a.id,
                    is_main_meter=False, meter_number='A2', ersetzt_id=za.id)
        db.session.add(neu)
        db.session.commit()
        f.reading(neu, date(2024, 7, 1), 0.0)
        f.reading(neu, date(2025, 1, 1), 250.0)
    else:
        f.reading(za, date(2025, 1, 1), 650.0)
    return mieter.id, BillingEngine(mieter.id, *JAHR).calculate_bill()['line_items'][0]


def test_die_abrechnung_mit_wechsel_gleicht_der_ohne(app_ctx):
    """Vorher rechnete der alte Zähler allein: 300 m³ auf das Jahr ≈ 602 statt 550."""
    _, mit = _abrechnung_wasser(True)
    _, ohne = _abrechnung_wasser(False)
    assert mit['tenant_cost'] == ohne['tenant_cost']
    assert '550' in mit['description']


# --- Eichfrist (R-EICH-01) ----------------------------------------------------------

@pytest.mark.parametrize('art,jahr,bis', [
    ('kaltwasser', 2020, date(2026, 12, 31)),
    ('strom_elektronisch', 2020, date(2028, 12, 31)),
    ('strom_ferraris', 2010, date(2026, 12, 31)),
    ('gas', 2024, date(2029, 12, 31)),
    ('sonstige', 2024, date(2026, 12, 31)),
])
def test_r_eich_01_frist_endet_am_jahresende(art, jahr, bis):
    assert eichfrist.geeicht_bis(jahr, art) == bis


def test_r_eich_01_hinweis_bei_ablauf_und_kurz_davor():
    bis = date(2026, 12, 31)
    assert eichfrist.hinweis(bis, date(2027, 1, 1)) == 'Eichfrist abgelaufen am 31.12.2026'
    assert eichfrist.hinweis(bis, date(2026, 10, 3)) == 'Eichfrist endet am 31.12.2026'
    assert eichfrist.hinweis(bis, date(2026, 10, 1)) is None
    assert eichfrist.hinweis(None, date(2026, 10, 1)) is None


def test_r_eich_01_der_vorschlag_ueber_die_api(auth_client):
    antwort = auth_client.get('/api/eichfrist?eichjahr=2020&art=kaltwasser')
    assert antwort.get_json() == {'geeicht_bis': '2026-12-31'}
    falsch = auth_client.get('/api/eichfrist?eichjahr=2020&art=bier')
    assert falsch.status_code == 400 and falsch.get_json()['feld'] == 'art'
    # Ein Tippfehler im Jahr ist ein 400, kein Überlauf im Datum (500).
    fern = auth_client.get('/api/eichfrist?eichjahr=9999&art=kaltwasser')
    assert fern.status_code == 400 and fern.get_json()['feld'] == 'eichjahr'


def test_r_eich_01_abgelaufene_frist_zeigt_den_hinweis_und_rechnet_gleich(auth_client):
    mieter, vorher = _abrechnung_wasser(False)
    z = Meter.query.filter_by(meter_number='A').one()
    antwort = auth_client.put(f'/api/meters/{z.id}', json={'geeicht_bis': '2020-12-31'})
    assert antwort.status_code == 200
    assert _liste(auth_client)[z.id]['eichhinweis'] == 'Eichfrist abgelaufen am 31.12.2020'
    nachher = BillingEngine(mieter, *JAHR).calculate_bill()['line_items'][0]
    assert nachher == vorher


def test_r_eich_01_der_dialog_kennt_jede_zaehlerart():
    """Die Auswahl im Zählerdialog nennt dieselben Arten und Jahre wie das Modul."""
    html = (WURZEL / 'static' / 'index.html').read_text(encoding='utf-8')
    auswahl = re.search(r'<select id="meter-eichart"[^>]*>(.*?)</select>', html, re.S).group(1)
    optionen = dict(re.findall(r'<option value="(\w+)">[^<]*?(\d+) Jahre', auswahl))
    assert optionen == {k: str(j) for k, (_, j) in eichfrist.EICHFRISTEN.items()}
