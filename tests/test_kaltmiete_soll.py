"""Phase 49 (N1): Kaltmiete-Soll und Erinnerung an die Mieterhöhung.

Die vereinbarte Kaltmiete stand bisher nirgends -- sie war nur als Betrag in
den Zahlungen zu raten. Mit dem Soll (Muster ``VorauszahlungSoll``) gibt es
einen Stichtagsverlauf, und der Fristenkalender erinnert an den frühesten
Tag, an dem die nächste Erhöhung verlangt werden darf: § 558 BGB nach
15 Monaten, bei der Indexmiete (§ 557b BGB) nach 12 Monaten. Alle Werte
sind erfunden.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from nebenkostenfix import fristenkalender
from nebenkostenfix.models import KaltmieteSoll, Tenant, db
from tests import billing_factories as f
from tests.test_migrations import WURZEL, _umgebung

D = date


# --- Kern: Fristenrechnung -------------------------------------------------------

def test_die_naechste_erhoehung_ist_nach_15_monaten_moeglich():
    """§ 558: 15 Monate nach der letzten Erhöhung (§ 558 Abs. 1 BGB)."""
    assert fristenkalender.mietanpassung(D(2024, 3, 15)) == D(2025, 6, 15)


def test_indexmiete_ist_nach_12_monaten_moeglich():
    """§ 557b: ein Jahr nach der letzten Änderung."""
    assert fristenkalender.mietanpassung(D(2024, 3, 15), indexmiete=True) == D(2025, 3, 15)


def test_monatsgrenze_klemmt_aufs_monatsende():
    """Auf den 31.01. folgt kein 31.04.: der Tag rutscht aufs Monatsende."""
    assert fristenkalender.mietanpassung(D(2026, 1, 31)) == D(2027, 4, 30)


def test_schalttag_klemmt_auch():
    assert fristenkalender.mietanpassung(D(2024, 2, 29), indexmiete=True) == D(2025, 2, 28)


def test_termine_nennen_die_frueheste_erhoehung():
    termine = fristenkalender.termine([], [], [], [], D(2024, 4, 1),
                                      kaltmiete=[(7, 'Mieter A', D(2024, 3, 15), False)])
    assert [(t['art'], t['datum'], t['titel']) for t in termine] == \
        [('mietanpassung', '2025-06-15', 'Früheste Mieterhöhung: Mieter A')]
    assert termine[0]['uid'] == 'mietanpassung-7@nebenkostenfix'


def test_eine_vergangene_erhoehung_steht_nicht_im_kalender():
    """Der Termin ist am ersten möglichen Tag einmal da und bleibt: er gilt
    weiter, bis eine neue Erhöhung kommt. Vor dem Stichtag steht er nicht."""
    termine = fristenkalender.termine([], [], [], [], D(2025, 7, 1),
                                      kaltmiete=[(7, 'Mieter A', D(2024, 3, 15), False)])
    assert termine == []


def test_ics_enthaelt_die_erhoehung():
    from datetime import datetime, timezone
    termine = fristenkalender.termine([], [], [], [], D(2024, 4, 1),
                                      kaltmiete=[(7, 'Mieter A', D(2024, 3, 15), False)])
    text = fristenkalender.ics(termine, datetime(2024, 4, 1, 12, 0, tzinfo=timezone.utc))
    assert 'UID:mietanpassung-7@nebenkostenfix' in text
    assert 'SUMMARY:Früheste Mieterhöhung: Mieter A' in text
    assert 'DTSTART;VALUE=DATE:20250615' in text


# --- Modell und API --------------------------------------------------------------

@pytest.fixture
def mieter(app_ctx):
    haus = f.house()
    return f.tenant(f.apt(haus, 'EG', 50), 'Mieter A', D(2024, 1, 1), D(2024, 3, 31))


def test_das_soll_anlegen_berichtigen_und_loeschen(auth_client, mieter):
    url = f'/api/tenants/{mieter.id}/kaltmiete_soll'
    assert auth_client.post(url, data={'gueltig_ab': '2024-01-01', 'betrag': '700'}).status_code == 201
    berichtigt = auth_client.post(url, data={'gueltig_ab': '2024-01-01', 'betrag': '750'})
    assert berichtigt.status_code == 200
    assert [(s.gueltig_ab, str(s.betrag)) for s in mieter.kaltmiete_soll] == \
        [(D(2024, 1, 1), '750.00')]
    vorher = auth_client.post(url, data={'gueltig_ab': '2023-12-31', 'betrag': '700'})
    assert vorher.status_code == 400 and vorher.get_json()['feld'] == 'gueltig_ab'
    negativ = auth_client.post(url, data={'gueltig_ab': '2024-02-01', 'betrag': '-1'})
    assert negativ.status_code == 400 and negativ.get_json()['feld'] == 'betrag'
    ansicht = auth_client.get(f'/api/tenants/{mieter.id}/kaltmiete').get_json()
    assert ansicht['soll'] == [
        {'id': mieter.kaltmiete_soll[0].id, 'gueltig_ab': '2024-01-01',
         'betrag': '750.00', 'indexmiete': False}]
    id_ = mieter.kaltmiete_soll[0].id
    assert auth_client.delete(f'/api/kaltmiete_soll/{id_}').status_code == 200
    assert KaltmieteSoll.query.count() == 0
    assert auth_client.post('/api/tenants/99999/kaltmiete_soll',
                            data={'gueltig_ab': '2024-01-01', 'betrag': '1'}).status_code == 404


def test_ein_soll_nach_dem_auszug_wird_abgelehnt(auth_client, mieter):
    url = f'/api/tenants/{mieter.id}/kaltmiete_soll'
    danach = auth_client.post(url, data={'gueltig_ab': '2024-04-01', 'betrag': '700'})
    assert danach.status_code == 400 and danach.get_json()['feld'] == 'gueltig_ab'
    assert auth_client.post(url, data={'gueltig_ab': '2024-03-31', 'betrag': '700'}).status_code == 201
    assert [s.gueltig_ab for s in mieter.kaltmiete_soll] == [D(2024, 3, 31)]


def test_indexmiete_ist_ein_flag_am_stichtag(auth_client, mieter):
    """Eine Indexanpassung (§ 557b) wird als Stichtag mit Kennzeichen erfasst;
    sie ist die „letzte Änderung“, von der der Fristenkalender zählt."""
    url = f'/api/tenants/{mieter.id}/kaltmiete_soll'
    assert auth_client.post(
        url, data={'gueltig_ab': '2024-01-01', 'betrag': '700', 'indexmiete': 'true'}
    ).status_code == 201
    d = auth_client.get(f'/api/tenants/{mieter.id}/kaltmiete').get_json()
    assert d['soll'][0]['indexmiete'] is True


def test_das_modell_ist_doppelt_gesichert(app_ctx, mieter):
    """Derselbe Stichtag nur einmal, kein negativer Betrag -- wie beim VZ-Soll."""
    db.session.add(KaltmieteSoll(tenant_id=mieter.id, gueltig_ab=D(2024, 1, 1), betrag=700))
    db.session.commit()
    doppelt = KaltmieteSoll(tenant_id=mieter.id, gueltig_ab=D(2024, 1, 1), betrag=700)
    db.session.add(doppelt)
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()
    negativ = KaltmieteSoll(tenant_id=mieter.id, gueltig_ab=D(2024, 2, 1), betrag=-5)
    db.session.add(negativ)
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


def test_der_kalender_nennt_die_erhoehung_pro_mieter_einmal(app_ctx, auth_client):
    """Nur der jüngste Stichtag zählt: ältere Stichtage sind überholt."""
    haus = f.house()
    bewohner = f.tenant(f.apt(haus, 'EG', 50), 'Mieter A', D(2024, 1, 1))
    url = f'/api/tenants/{bewohner.id}/kaltmiete_soll'
    auth_client.post(url, data={'gueltig_ab': '2024-01-01', 'betrag': '700'})
    auth_client.post(url, data={'gueltig_ab': '2025-08-01', 'betrag': '750'})
    d = auth_client.get('/api/fristen').get_json()
    erhoehungen = [t for t in d['termine'] if t['art'] == 'mietanpassung']
    assert [t['titel'] for t in erhoehungen] == ['Früheste Mieterhöhung: Mieter A']
    assert erhoehungen[0]['datum'] == '2026-11-01'


# --- Migration -------------------------------------------------------------------

CODE_MIGRATION = """
import json
from sqlalchemy import inspect, text
from flask_migrate import downgrade, upgrade
import app as anwendung
from nebenkostenfix.models import db

with anwendung.app.app_context():
    vor = 'kaltmiete_soll' in inspect(db.engine).get_table_names()
    downgrade(revision='b4e7c1d92a58')
    ohne = 'kaltmiete_soll' in inspect(db.engine).get_table_names()
    upgrade()
    wieder = 'kaltmiete_soll' in inspect(db.engine).get_table_names()
print(json.dumps({'vor': vor, 'ohne': ohne, 'wieder': wieder}))
"""


def test_die_migration_laeuft_hin_und_zurueck(tmp_path):
    """Die neue Tabelle kommt mit der Migration und geht mit dem Rückweg weg."""
    dbdatei = tmp_path / 'wanderung.db'
    ergebnis = subprocess.run(
        [sys.executable, '-c', CODE_MIGRATION],
        cwd=str(WURZEL), env=_umgebung(dbdatei, tmp_path),
        capture_output=True, text=True, timeout=180)
    assert ergebnis.returncode == 0, f'{ergebnis.stdout}\n{ergebnis.stderr}'
    assert json.loads(ergebnis.stdout.strip().splitlines()[-1]) == \
        {'vor': True, 'ohne': False, 'wieder': True}
