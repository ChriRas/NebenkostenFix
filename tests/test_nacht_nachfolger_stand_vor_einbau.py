"""Zählerwechsel: ein Stand am Nachfolgezähler vor dem Einbau ging still durch.

Der Wechseldialog weist Stände des alten Zählers nach dem Wechseltag ab.
Die Gegenrichtung fehlte: ``POST /api/readings`` nahm am **neuen** Zähler
einen Stand vor dem Wechseltag an, ohne Frage (der Stand 0 ist weder
kleiner als ein vorheriger noch größer als der folgende Anfangsstand 0).
``_anschliessen`` nimmt aber den frühesten Stand des Nachfolgers als
Wechseltag: aus 100 → 400 (alt) und 0 → 250 (neu) = 550 m³ wurden 250 m³,
der Verbrauch des alten Zählers verschwand. Alle Werte sind erfunden.

Der Wechseltag eines Nachfolgers ist der Tag des letzten Stands seines
Vorgängers, also der Endstand aus dem Wechsel. Davor nimmt der Nachfolger
keinen Stand an: nicht über das Formular, nicht über eine Berichtigung und
nicht über den Tabellenimport -- hart, ohne Rückfrage, wie der Wechseldialog
in der Gegenrichtung.
"""

from __future__ import annotations

import io
from datetime import date

import pytest

from nebenkostenfix.models import Meter, MeterReading
from tests import billing_factories as f


def test_stand_am_nachfolger_vor_dem_wechseltag_wird_nicht_still_gespeichert(
        auth_client, app_ctx):
    haus = f.house('Nachthaus Tausch')
    wohnung = f.apt(haus, 'DG', 62)
    alt = f.meter(haus, f.category('Wasser'), 'KW-ALT-7', is_main=False, apartment=wohnung)
    f.reading(alt, date(2024, 1, 1), 100.0)

    wechsel = auth_client.post(f'/api/meters/{alt.id}/wechsel', data={
        'datum': '2024-07-01', 'endstand': '400', 'anfangsstand': '0',
        'meter_number': 'KW-NEU-8'})
    assert wechsel.status_code == 201, wechsel.get_data(as_text=True)
    neu_id = wechsel.get_json()['id']

    # Vertipptes Datum: März statt Dezember -- vor dem Einbau des neuen Zählers.
    antwort = auth_client.post('/api/readings', data={
        'meter_id': str(neu_id), 'reading_date': '2024-03-01', 'value': '0'})

    staende = MeterReading.query.filter_by(meter_id=neu_id).count()
    assert antwort.status_code in (400, 409), (
        f'Status {antwort.status_code}: Stand vor dem Einbau am Nachfolger '
        f'gespeichert ({staende} Stände)')
    assert staende == 1


# --- Testhaus Nachtweg: alt 100 → 400 bis 01.07.2024, neu 0 → 250 bis 31.12.2024 --

WECHSELTAG = date(2024, 7, 1)


@pytest.fixture
def kette(auth_client, app_ctx):
    """Kaltwasser in W1: NZ-ALT-01 am 01.07.2024 gegen NZ-NEU-01 getauscht."""
    haus = f.house('Testhaus Nachtweg')
    w1 = f.apt(haus, 'W1', 45)
    alt = f.meter(haus, f.category('Wasser'), 'NZ-ALT-01', is_main=False, apartment=w1)
    f.reading(alt, date(2024, 1, 1), 100.0)
    wechsel = auth_client.post(f'/api/meters/{alt.id}/wechsel', data={
        'datum': '2024-07-01', 'endstand': '400', 'anfangsstand': '0',
        'meter_number': 'NZ-NEU-01'})
    assert wechsel.status_code == 201, wechsel.get_data(as_text=True)
    neu_id = wechsel.get_json()['id']
    ende = auth_client.post('/api/readings', data={
        'meter_id': str(neu_id), 'reading_date': '2024-12-31', 'value': '250'})
    assert ende.status_code == 201, ende.get_data(as_text=True)
    return {'client': auth_client, 'haus': haus, 'wohnung': w1, 'alt_id': alt.id,
            'neu_id': neu_id, 'ende_id': ende.get_json()['id']}


def _stand(client, meter_id, tag, wert, **mehr):
    return client.post('/api/readings', data={
        'meter_id': str(meter_id), 'reading_date': tag, 'value': wert, **mehr})


def _staende(meter_id):
    return sorted(r.reading_date for r in MeterReading.query.filter_by(meter_id=meter_id))


def test_formular_weist_den_stand_vor_dem_wechseltag_am_feld_ab(kette):
    antwort = _stand(kette['client'], kette['neu_id'], '2024-03-01', '0')

    assert antwort.status_code == 400, antwort.get_data(as_text=True)
    rumpf = antwort.get_json()
    assert rumpf['feld'] == 'reading_date'
    assert 'nachfrage' not in rumpf
    assert '01.07.2024' in rumpf['error'] and 'alten Zähler' in rumpf['error']
    assert _staende(kette['neu_id']) == [WECHSELTAG, date(2024, 12, 31)]


def test_auch_trotzdem_speichert_keinen_stand_vor_dem_wechseltag(kette):
    antwort = _stand(kette['client'], kette['neu_id'], '2024-03-01', '0', trotzdem='true')

    assert antwort.status_code == 400, antwort.get_data(as_text=True)
    assert antwort.get_json()['feld'] == 'reading_date'
    assert _staende(kette['neu_id']) == [WECHSELTAG, date(2024, 12, 31)]


def test_die_absage_kommt_vor_dem_foto(kette, monkeypatch):
    """Ein abgewiesener Stand legt auch kein Foto in die Ablage."""
    import app as app_module
    gespeichert = []
    monkeypatch.setattr(app_module.nas_handler, 'save_reading_photo',
                        lambda **kw: gespeichert.append(kw) or 'foto.jpg')
    antwort = kette['client'].post('/api/readings', data={
        'meter_id': str(kette['neu_id']), 'reading_date': '2024-03-01', 'value': '0',
        'file': (io.BytesIO(b'\xff\xd8\xff\xe0fiktiv'), 'stand.jpg')},
        content_type='multipart/form-data')

    assert antwort.status_code == 400, antwort.get_data(as_text=True)
    assert gespeichert == []


def test_die_kette_rechnet_nach_den_absagen_weiter_550(kette):
    from nebenkostenfix.abrechnungsdaten import lade_zaehler
    from nebenkostenfix.rechenkern import verbrauch_in, verkette
    from nebenkostenfix.zeitraum import grenze

    client = kette['client']
    assert _stand(client, kette['neu_id'], '2024-03-01', '0').status_code == 400
    assert _stand(client, kette['neu_id'], '2024-03-01', '0',
                  trotzdem='true').status_code == 400

    [zaehler] = verkette((lade_zaehler(kette['alt_id']), lade_zaehler(kette['neu_id'])))
    # Von Stand zu Stand: 100 → 400 am alten, 0 → 250 am neuen Zähler.
    d = verbrauch_in(zaehler, date(2024, 1, 1), date(2024, 12, 31))
    assert d['consumption'] == pytest.approx(550.0)
    assert d['zaehlerwechsel'][0]['datum'] == '2024-07-01'
    # Bis zur Jahresgrenze rechnet der Kern den letzten Tag hoch, der alte
    # Zähler bleibt drin (ohne ihn wären es rund 250).
    jahr = verbrauch_in(zaehler, date(2024, 1, 1), grenze(date(2024, 12, 31)))
    assert jahr['consumption'] == pytest.approx(550.0, abs=2.0)


def test_berichtigung_legt_den_stand_nicht_vor_den_wechseltag(kette):
    client = kette['client']
    antwort = client.put(f'/api/readings/{kette["ende_id"]}',
                         data={'reading_date': '2024-05-01'})

    assert antwort.status_code == 400, antwort.get_data(as_text=True)
    assert antwort.get_json()['feld'] == 'reading_date'
    stand = MeterReading.query.get(kette['ende_id'])
    assert stand.reading_date == date(2024, 12, 31)
    assert stand.value == 250.0

    # Auch mit Bestätigung nicht.
    wieder = client.put(f'/api/readings/{kette["ende_id"]}',
                        data={'reading_date': '2024-05-01', 'trotzdem': 'true'})
    assert wieder.status_code == 400
    assert MeterReading.query.get(kette['ende_id']).reading_date == date(2024, 12, 31)


def test_berichtigung_nach_dem_wechseltag_bleibt_moeglich(kette):
    antwort = kette['client'].put(f'/api/readings/{kette["ende_id"]}',
                                  data={'reading_date': '2024-11-30', 'value': '230'})
    assert antwort.status_code == 200, antwort.get_data(as_text=True)
    assert MeterReading.query.get(kette['ende_id']).reading_date == date(2024, 11, 30)


def _csv(*zeilen: str) -> bytes:
    return ('﻿' + '\r\n'.join(zeilen) + '\r\n').encode('utf-8')


def _import(client, inhalt, schritt):
    gelesen = client.post('/api/import/zaehlerstaende/lesen',
                          data={'datei': (io.BytesIO(inhalt), 'staende.csv')},
                          content_type='multipart/form-data')
    assert gelesen.status_code == 200, gelesen.get_data(as_text=True)
    kopf = gelesen.get_json()
    return client.post(f'/api/import/zaehlerstaende/{schritt}', json={
        'kennung': kopf['kennung'], 'zuordnung': kopf['zuordnung']})


KOPF = 'Immobilie;Zählernummer;Ablesedatum;Stand;Stand Niedertarif;Zwischenablesung'


def test_import_meldet_die_zeile_vor_dem_wechseltag(kette):
    vorher = MeterReading.query.count()
    antwort = _import(kette['client'], _csv(
        KOPF, 'Testhaus Nachtweg;NZ-NEU-01;01.03.2024;0;;nein'), 'uebernehmen')

    bericht = antwort.get_json()
    assert antwort.status_code == 400, bericht
    assert [z['zeile'] for z in bericht['fehler']] == [2]
    assert bericht['fehler'][0]['meldung'].startswith('Ablesedatum:')
    assert '01.07.2024' in bericht['fehler'][0]['meldung']
    assert MeterReading.query.count() == vorher
    assert _staende(kette['neu_id']) == [WECHSELTAG, date(2024, 12, 31)]


def test_import_nimmt_staende_ab_dem_wechseltag_weiter_an(kette):
    antwort = _import(kette['client'], _csv(
        KOPF, 'Testhaus Nachtweg;NZ-NEU-01;30.09.2024;120;;nein'), 'uebernehmen')
    assert antwort.status_code == 200, antwort.get_json()
    assert date(2024, 9, 30) in _staende(kette['neu_id'])


# --- Gegenproben ----------------------------------------------------------------

def test_ein_stand_nach_dem_wechseltag_geht_wie_bisher(kette):
    antwort = _stand(kette['client'], kette['neu_id'], '2024-09-30', '120')
    assert antwort.status_code == 201, antwort.get_data(as_text=True)
    assert date(2024, 9, 30) in _staende(kette['neu_id'])


def test_am_wechseltag_selbst_kommt_die_bekannte_rueckfrage(kette):
    """Der Wechseltag ist nicht „davor“: dort fragt nur der doppelte Tag nach."""
    antwort = _stand(kette['client'], kette['neu_id'], '2024-07-01', '0')
    assert antwort.status_code == 409, antwort.get_data(as_text=True)
    assert antwort.get_json()['nachfrage'] is True
    assert 'schon einen Stand' in antwort.get_json()['error']


def test_zaehler_ohne_vorgaenger_nimmt_fruehe_staende_an(kette):
    solo = f.meter(kette['haus'], f.category('Wasser'), 'NZ-SOLO-01', is_main=False,
                   apartment=kette['wohnung'])
    antwort = _stand(kette['client'], solo.id, '2024-03-01', '12')
    assert antwort.status_code == 201, antwort.get_data(as_text=True)


def test_der_alte_zaehler_selbst_bleibt_unberuehrt(kette):
    """Vor dem Wechseltag darf der alte Zähler weiter Stände bekommen."""
    antwort = _stand(kette['client'], kette['alt_id'], '2024-04-01', '250')
    assert antwort.status_code == 201, antwort.get_data(as_text=True)


def test_wechseltag_ohne_vorgaenger_oder_ohne_staende(kette):
    from nebenkostenfix.zaehlerkette import vor_dem_wechseltag, wechseltag
    neu = Meter.query.get(kette['neu_id'])
    alt = Meter.query.get(kette['alt_id'])
    assert wechseltag(neu) == WECHSELTAG
    assert wechseltag(alt) is None
    assert vor_dem_wechseltag(alt, date(2000, 1, 1)) is None
    assert vor_dem_wechseltag(neu, WECHSELTAG) is None
    assert 'seit dem 01.07.2024' in vor_dem_wechseltag(neu, date(2024, 6, 30))

    # Ein Vorgänger ohne einen einzigen Stand liefert keinen Wechseltag.
    leer = f.meter(kette['haus'], f.category('Wasser'), 'NZ-LEER-01', is_main=False)
    neu.ersetzt_id = leer.id
    assert wechseltag(neu) is None
    assert vor_dem_wechseltag(neu, date(2000, 1, 1)) is None
