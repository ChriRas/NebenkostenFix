"""NK-262 (R-FRIST-05): Fristenkalender als Liste und als ``.ics``-Datei.

Vorher standen die Fristen verstreut: die Abrechnungsfrist an der Abrechnung,
die Eichfrist am Zähler, die neue Vorauszahlung im Soll. In einen Kalender
kamen sie nur von Hand. Alle Werte sind erfunden.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from nebenkostenfix import fristenkalender as fk
from nebenkostenfix import zeit
from nebenkostenfix.frist import einwendungsfrist, frist_ende
from nebenkostenfix.models import Meter, TenantBillingReport, VorauszahlungSoll, db
from tests import billing_factories as f

D = date
HEUTE = D(2025, 1, 10)


def _arten(liste):
    return [(t['art'], t['datum']) for t in liste]


# --- Kern ----------------------------------------------------------------------

def test_fristende_am_monatsende_und_im_schaltjahr_kommt_aus_frist_py():
    berichte = [(1, 'A', frist_ende(D(2024, 2, 29)), None),
                (2, 'B', frist_ende(D(2024, 12, 31)), None),
                (3, 'C', D(2024, 6, 30), D(2024, 2, 29))]
    liste = fk.termine(berichte, [], [], [], HEUTE)
    assert ('abrechnungsfrist', '2025-02-28') in _arten(liste)
    assert ('abrechnungsfrist', '2025-12-31') in _arten(liste)
    assert ('einwendungsfrist', einwendungsfrist(D(2024, 2, 29)).isoformat()) in _arten(liste)
    assert einwendungsfrist(D(2024, 2, 29)) == D(2025, 2, 28)


def test_ohne_zugang_keine_einwendungsfrist_mit_zugang_keine_abrechnungsfrist():
    liste = fk.termine([(1, 'A', D(2025, 12, 31), None), (2, 'B', D(2025, 12, 31), D(2025, 3, 1))],
                       [], [], [], HEUTE)
    assert _arten(liste) == [('abrechnungsfrist', '2025-12-31'),
                             ('einwendungsfrist', '2026-03-01')]
    assert [t['uid'] for t in liste] == ['abrechnungsfrist-1@nebenkostenfix',
                                         'einwendungsfrist-2@nebenkostenfix']


def test_vergangene_termine_fehlen_der_heutige_bleibt():
    liste = fk.termine([(1, 'A', D(2025, 1, 9), None), (2, 'B', HEUTE, None)], [], [],
                       [(7, 'Wasser', D(2024, 12, 31))], HEUTE)
    assert _arten(liste) == [('abrechnungsfrist', '2025-01-10')]


def test_ablesung_zaehlt_den_schalttag_mit():
    assert fk.naechste_ablesung(D(2023, 2, 28)) == D(2024, 2, 29)
    assert fk.naechste_ablesung(D(2024, 12, 31)) == D(2025, 12, 31)
    liste = fk.termine([], [(4, 'Haus H', D(2023, 2, 28))], [], [], D(2024, 1, 1))
    assert liste == [{'datum': '2024-02-29', 'art': 'ablesung',
                      'titel': 'Zähler ablesen: Haus H (Ende des Abrechnungszeitraums)',
                      'uid': 'ablesung-4-20240229@nebenkostenfix'}]


def test_ablesung_rollt_ueber_nicht_abgerechnete_jahre_weiter():
    liste = fk.termine([], [(4, 'Haus H', D(2022, 12, 31))], [], [], HEUTE)
    assert _arten(liste) == [('ablesung', '2025-12-31')]


def test_vorauszahlung_und_eichfrist_mit_betrag_im_deutschen_format():
    liste = fk.termine([], [], [(5, 'Mieter A', D(2025, 3, 1), 1234.5)],
                       [(6, 'Kaltwasser 1 (Haus H)', D(2025, 12, 31))], HEUTE)
    assert [t['titel'] for t in liste] == [
        'Neue Vorauszahlung: Mieter A, 1234,50 € je Monat',
        'Eichfrist endet: Kaltwasser 1 (Haus H)']


def test_ics_hat_kopf_und_je_termin_uid_dtstamp_und_ganztaegiges_datum():
    liste = fk.termine([(1, 'A', D(2025, 12, 31), None)], [], [],
                       [(6, 'Wasser', D(2026, 12, 31))], HEUTE)
    text = fk.ics(liste, datetime(2025, 1, 10, 8, 30, 0))
    zeilen = text.split('\r\n')
    assert zeilen[:5] == ['BEGIN:VCALENDAR', 'VERSION:2.0', f'PRODID:{fk.PRODID}',
                          'CALSCALE:GREGORIAN', 'METHOD:PUBLISH']
    assert zeilen[-2:] == ['END:VCALENDAR', '']
    assert '\n' not in text.replace('\r\n', '')
    assert text.count('BEGIN:VEVENT') == 2 == text.count('END:VEVENT')
    assert 'UID:abrechnungsfrist-1@nebenkostenfix' in zeilen
    assert zeilen.count('DTSTAMP:20250110T083000Z') == 2
    assert 'DTSTART;VALUE=DATE:20251231' in zeilen
    assert 'DTSTART;VALUE=DATE:20261231' in zeilen
    assert not any(z.startswith('DTSTART:') for z in zeilen)


def test_ics_maskiert_text_und_faltet_lange_zeilen_ohne_utf8_zu_teilen():
    titel = 'Ende der Abrechnungsfrist: Müller; Meier, Ä\\B ' + 'ö' * 60
    text = fk.ics([{'datum': '2025-12-31', 'art': 'x', 'titel': titel, 'uid': 'x-1@n'}],
                  datetime(2025, 1, 1))
    roh = text.encode('utf-8')
    for zeile in roh.split(b'\r\n'):
        assert len(zeile) <= 75
        zeile.decode('utf-8')  # keine halben Zeichen an der Faltstelle
    entfaltet = text.replace('\r\n ', '')
    assert 'SUMMARY:Ende der Abrechnungsfrist: Müller\\; Meier\\, Ä\\\\B ' + 'ö' * 60 \
        in entfaltet.split('\r\n')


# --- Über die API --------------------------------------------------------------

@pytest.fixture
def bestand(app_ctx, monkeypatch):
    monkeypatch.setattr(zeit, 'jetzt_utc', lambda: datetime(2025, 1, 10, 12, 0, 0))
    haus = f.house('Haus H')
    wohnung = f.apt(haus, 'EG', 50)
    a = f.tenant(wohnung, 'Mieter A', D(2024, 1, 1))
    for zugestellt in (None, D(2025, 1, 5)):
        db.session.add(TenantBillingReport(
            tenant_id=a.id, start_date=D(2024, 1, 1), end_date=D(2024, 12, 31),
            frist_ende=frist_ende(D(2024, 12, 31)), zugestellt_am=zugestellt))
    db.session.add(VorauszahlungSoll(tenant_id=a.id, gueltig_ab=D(2025, 4, 1), betrag=95))
    db.session.add(VorauszahlungSoll(tenant_id=a.id, gueltig_ab=D(2024, 1, 1), betrag=80))
    wasser = f.category('Wasser')
    alt = f.meter(haus, wasser, 'W-1', is_main=True)
    alt.geeicht_bis = D(2025, 12, 31)
    neu = f.meter(haus, wasser, 'W-2', is_main=True)
    neu.geeicht_bis, neu.ersetzt_id = D(2030, 12, 31), alt.id
    f.meter(haus, wasser, 'W-3', is_main=True)  # ohne Eichdatum: kein Termin
    db.session.commit()
    return a


def test_die_api_sammelt_alle_arten_und_laesst_abgeloeste_zaehler_weg(auth_client, bestand):
    res = auth_client.get('/api/fristen')
    assert res.status_code == 200
    liste = res.get_json()['termine']
    assert [(t['art'], t['datum']) for t in liste] == [
        ('vorauszahlung', '2025-04-01'),
        ('abrechnungsfrist', '2025-12-31'),
        ('ablesung', '2025-12-31'),
        ('einwendungsfrist', '2026-01-05'),
        ('eichfrist', '2030-12-31'),
    ]
    assert 'W-1' not in str(liste) and 'W-3' not in str(liste)
    assert liste[-1]['titel'].endswith('W-2 (Haus H)')
    assert liste[0]['titel'] == 'Neue Vorauszahlung: Mieter A, 95,00 € je Monat'


def test_die_ics_datei_wird_heruntergeladen(auth_client, bestand):
    res = auth_client.get('/api/fristen.ics')
    assert res.status_code == 200
    assert res.mimetype == 'text/calendar'
    assert 'attachment' in res.headers['Content-Disposition']
    assert 'fristen.ics' in res.headers['Content-Disposition']
    text = res.get_data(as_text=True)
    assert text.startswith('BEGIN:VCALENDAR\r\n') and text.count('BEGIN:VEVENT') == 5
    assert 'DTSTAMP:20250110T120000Z' in text


def test_eine_auszugsabrechnung_verschiebt_den_ablesestichtag_nicht(auth_client, bestand):
    # Der Stichtag ist das Ende des Abrechnungsjahres des Hauses, nicht der Auszugstag.
    wohnung = f.apt(bestand.apartment.property, 'OG', 40)
    b = f.tenant(wohnung, 'Mieter B', D(2024, 1, 1), D(2025, 3, 15))
    db.session.add(TenantBillingReport(
        tenant_id=b.id, start_date=D(2025, 1, 1), end_date=D(2025, 3, 15),
        frist_ende=frist_ende(D(2025, 3, 15))))
    db.session.commit()
    liste = auth_client.get('/api/fristen').get_json()['termine']
    assert [t['datum'] for t in liste if t['art'] == 'ablesung'] == ['2025-12-31']


def test_gesperrte_mieter_stehen_nicht_im_kalender(auth_client, bestand):
    # Gesperrte Mieter sind aus allen Listen ausgeblendet (R-DSGVO-02); der
    # Ablesestichtag des Hauses bleibt, er nennt keinen Mieter.
    bestand.gesperrt_bis = D(2027, 1, 1)
    db.session.commit()
    liste = auth_client.get('/api/fristen').get_json()['termine']
    assert 'Mieter A' not in str(liste)
    assert [t['art'] for t in liste] == ['ablesung', 'eichfrist']
    assert 'Mieter A' not in auth_client.get('/api/fristen.ics').get_data(as_text=True)


def test_ein_soll_nach_dem_auszug_steht_nicht_im_kalender(auth_client, bestand):
    # NK-269: Das Soll ab 01.04. gilt nicht mehr, der Mieter zieht am 31.03. aus.
    bestand.move_out_date = D(2025, 3, 31)
    db.session.commit()
    liste = auth_client.get('/api/fristen').get_json()['termine']
    assert 'vorauszahlung' not in [t['art'] for t in liste]

def test_ohne_bestand_ist_der_kalender_leer_aber_gueltig(auth_client):
    assert auth_client.get('/api/fristen').get_json() == {'termine': []}
    text = auth_client.get('/api/fristen.ics').get_data(as_text=True)
    assert text.startswith('BEGIN:VCALENDAR') and 'VEVENT' not in text


def test_der_kalender_braucht_eine_anmeldung(anon_client):
    assert anon_client.get('/api/fristen').status_code == 401
    assert anon_client.get('/api/fristen.ics').status_code == 401
