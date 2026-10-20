"""Phase 55, Schritt 1: Die Einheit bekommt ein Feld am Zähler.

Bisher leitete der Kern aus der BetrKV-Nummer ab, was ein Zähler misst --
Nr. 5 Warmwasser heißt „m³", also Wasserzähler. Ein Warmwasser-
Wärmemengenzähler in kWh hat damit keinen Platz, obwohl § 9 Abs. 2 Satz 1
HeizkostenV ihn ausdrücklich vorsieht und er bei Wärmepumpen der übliche
Aufbau ist (Nachfrage zu Live-Issue #32, Befund F-NEU-2).

Dieser Schritt legt nur das Feld und füllt es für den Bestand mit genau
dem, was die Ableitung heute ergibt. **Niemand liest es bisher** -- der
Kern und die API entscheiden weiter über ``einheit_fuer``. Deshalb kann
sich für eine bestehende Abrechnung nichts ändern, und genau das halten
diese Tests fest. Die Umstellung der Leser kommt in den nächsten
Schritten; dass sie nichts verändert, belegen dann die Bestandstests in
``test_zaehler_einheit.py``, ``test_katalog_quelle.py`` und
``test_warmwassertrennung.py``, die unverändert grün bleiben müssen.

Alle Werte sind erfunden.
"""

from __future__ import annotations

import re

import json
import subprocess
import sys

from nebenkostenfix.models import Meter
from nebenkostenfix.rechenkern import einheit_fuer
from tests.test_migrations import WURZEL, _umgebung

# Der Schnappschuss in der Wanderung muss dasselbe antworten wie der Kern.
# Beides steht absichtlich getrennt: die Wanderung darf sich nicht mit dem
# Katalog weiterdrehen, sonst schriebe sie in fünf Jahren andere Werte in
# denselben Bestand. Dieser Test hält die zwei Fassungen aneinander.
from migrations.versions.e8b4a7c25f91_zaehler_einheit import (  # noqa: E402
    EINHEITEN_NACH_NUMMER,
    VORGABE,
    _abgeleitet,
)


# --- Der Schnappschuss der Wanderung gegen den Kern ----------------------------

def test_der_schnappschuss_antwortet_wie_der_kern_ueber_die_nummer():
    """Für jede BetrKV-Nummer dieselbe Einheit wie ``einheit_fuer``."""
    for nummer in range(1, 18):
        assert _abgeleitet('egal', nummer) == einheit_fuer('egal', nummer), nummer


def test_der_schnappschuss_antwortet_wie_der_kern_ueber_den_namen():
    """Auch der Rückfall auf das Wort stimmt überein (Zähler ohne Nummer)."""
    for name in ('Allgemeinstrom', 'Kaltwasser', 'Gas', 'Entwässerung',
                 'Wärmemenge', 'Waermemenge', 'Heizung', 'Hauswart', ''):
        assert _abgeleitet(name, None) == einheit_fuer(name, None), name


def test_der_schnappschuss_vertraegt_fehlende_angaben():
    """Edge case: kein Name, keine Nummer, eine unbekannte Nummer."""
    assert _abgeleitet(None, None) == VORGABE
    assert _abgeleitet('', None) == VORGABE
    assert _abgeleitet('egal', 99) == VORGABE


def test_die_nummern_vier_bis_sechs_sind_der_fall_aus_issue_32():
    """Warum es das Feld braucht: Nr. 5 kennt nur m³.

    Heizung (4) und die verbundene Anlage (6) messen kWh, Warmwasser (5)
    m³. Wer eine Wärmepumpe mit Warmwasser-Wärmemengenzähler hat, findet
    unter Nr. 5 keine Einheit für seinen Zähler.
    """
    assert EINHEITEN_NACH_NUMMER[4] == 'kWh'
    assert EINHEITEN_NACH_NUMMER[5] == 'm³'
    assert EINHEITEN_NACH_NUMMER[6] == 'kWh'


# --- Das Feld am Modell --------------------------------------------------------

def test_das_modell_hat_die_einheit(app_ctx):
    """Das Feld existiert, ist kurz und zunächst frei (die Wanderung füllt es)."""
    assert hasattr(Meter, 'einheit')
    spalte = Meter.__table__.columns['einheit']
    assert spalte.type.length == 10
    assert spalte.nullable is True


# --- Der Upgrade-Weg: der Bestand behält sein Verhalten ------------------------

CODE_UPGRADE_WEG = '''
import json, os, sys
sys.path.insert(0, os.getcwd())
os.environ.setdefault('SECRET_KEY', 'nur-fuer-die-wanderungsprobe-xyz')
from app import app
from nebenkostenfix.models import db
from flask_migrate import downgrade, upgrade
from sqlalchemy import text

with app.app_context():
    db.create_all()
    upgrade()
    # Zurueck auf den Stand vor Phase 55: die Spalte gibt es dann nicht.
    downgrade(revision='d5c9f3b7e2a8')
    v = db.session.execute
    v(text("DELETE FROM meters"))
    v(text("DELETE FROM cost_categories"))
    db.session.commit()

    # Ein Bestand wie bei einem Nutzer, der von 0.15.0 aktualisiert: fuenf
    # Kostenarten mit Nummern, je ein Zaehler. Alles per SQL, damit kein
    # Modell mit dem neuen Feld dazwischenkommt. Die Pflichtspalten sind aus
    # PRAGMA table_info genommen (notnull=1 ohne Default), nicht geraten --
    # der Python-Default eines Modells greift bei rohem SQL nicht.
    v(text("INSERT INTO properties (id, name, is_standalone) VALUES (1, 'Haus', 0)"))
    v(text("INSERT INTO apartments (id, property_id, name, sqm, is_active) "
           "VALUES (1, 1, 'EG', 50, 1)"))
    # Eine Kostenart ohne Nummer gibt es hier nicht: cost_categories.betrkv_nr
    # ist NOT NULL. Der Namens-Rueckfall in einheit_fuer trifft also nur von
    # Hand gebaute Testobjekte, nie einen migrierten Bestand.
    arten = [(1, 'Heizung', 4), (2, 'Warmwasser', 5), (3, 'Kaltwasser', 2),
             (4, 'Hauswart', 14), (5, 'Allgemeinstrom', 11)]
    for kid, name, nr in arten:
        v(text("INSERT INTO cost_categories (id, name, allocation_method, requires_meter, "
               "betrkv_nr) VALUES (:id, :name, 'qm', 0, :nr)"),
          {'id': kid, 'name': name, 'nr': nr})
        v(text("INSERT INTO meters (id, category_id, property_id, apartment_id, "
               "is_main_meter, meter_number, has_dual_tariff, is_official) "
               "VALUES (:id, :cid, 1, 1, 0, :nummer, 0, 0)"),
          {'id': kid, 'cid': kid, 'nummer': 'Z-%d' % kid})
    db.session.commit()

    spalten_vorher = [r[1] for r in v(text("PRAGMA table_info(meters)")).fetchall()]

    upgrade()   # das Update auf den Kopf

    zeilen = v(text("SELECT m.id, c.name, c.betrkv_nr, m.einheit FROM meters m "
                    "JOIN cost_categories c ON c.id = m.category_id ORDER BY m.id")).fetchall()
    db.session.commit()

print(json.dumps({
    'einheit_vorher_vorhanden': 'einheit' in spalten_vorher,
    'nachher': [[z[1], z[2], z[3]] for z in zeilen],
    'keine_leer': all(z[3] for z in zeilen),
}))
'''


def test_der_upgrade_weg_schreibt_die_abgeleitete_einheit(tmp_path):
    """Ein Bestand aus 0.15.0 behält nach dem Update sein Verhalten.

    Das ist der Kern der Abwärtskompatibilität: die Wanderung schreibt für
    jeden vorhandenen Zähler genau die Einheit, die der Kern vorher
    abgeleitet hätte. Danach kann dasselbe Ergebnis aus einem Feld kommen
    statt aus einer Ableitung -- für den Bestand ein Nullwechsel.
    """
    ergebnis = subprocess.run(
        [sys.executable, '-c', CODE_UPGRADE_WEG],
        cwd=str(WURZEL), env=_umgebung(tmp_path / 'aufstieg.db', tmp_path),
        capture_output=True, text=True, timeout=300)
    assert ergebnis.returncode == 0, f'{ergebnis.stdout}\n{ergebnis.stderr}'
    stand = json.loads(ergebnis.stdout.strip().splitlines()[-1])

    # Vor dem Update gab es die Spalte nicht -- der Bestand ist echt.
    assert stand['einheit_vorher_vorhanden'] is False
    # Kein Zähler bleibt ohne Einheit.
    assert stand['keine_leer'] is True
    # Und jede Einheit ist die, die der Kern abgeleitet hätte.
    assert stand['nachher'] == [
        ['Heizung', 4, 'kWh'],
        ['Warmwasser', 5, 'm³'],      # der Fall aus Issue #32: nur m³ möglich
        ['Kaltwasser', 2, 'm³'],
        ['Hauswart', 14, 'Einheiten'],
        ['Allgemeinstrom', 11, 'kWh'],
    ]
    for name, nummer, einheit in stand['nachher']:
        assert einheit == einheit_fuer(name, nummer), (name, nummer)


# --- Über die API: die Maßeinheit wählen und prüfen ----------------------------

def test_ein_zaehler_nimmt_die_gewaehlte_masseinheit(auth_client, app_ctx):
    """Der Fall aus Issue #32: Warmwasser (Nr. 5) mit Wärmemengenzähler.

    Die Kostenart gibt m³ vor, der Zähler misst kWh. Ohne das Feld wäre
    dieser Aufbau nicht erfassbar.
    """
    from nebenkostenfix.models import CostCategory
    from tests import billing_factories as f
    haus = f.house()
    warmwasser = CostCategory.query.filter_by(betrkv_nr=5).first()
    antwort = auth_client.post('/api/meters', data={
        'category_id': warmwasser.id, 'property_id': haus.id,
        'meter_number': 'WMZ-WW-1', 'einheit': 'kWh'})
    assert antwort.status_code == 201, antwort.get_json()
    [zaehler] = [z for z in auth_client.get('/api/meters').get_json()
                 if z['meter_number'] == 'WMZ-WW-1']
    assert zaehler['einheit'] == 'kWh'


def test_ohne_wahl_kommt_die_masseinheit_aus_der_kostenart(auth_client, app_ctx):
    """Leer heißt „wie bisher" -- das hält die Abwärtskompatibilität."""
    from nebenkostenfix.models import CostCategory
    from tests import billing_factories as f
    haus = f.house()
    warmwasser = CostCategory.query.filter_by(betrkv_nr=5).first()
    antwort = auth_client.post('/api/meters', data={
        'category_id': warmwasser.id, 'property_id': haus.id,
        'meter_number': 'WZ-WW-2'})
    assert antwort.status_code == 201, antwort.get_json()
    [zaehler] = [z for z in auth_client.get('/api/meters').get_json()
                 if z['meter_number'] == 'WZ-WW-2']
    assert zaehler['einheit'] == 'm³'


def test_eine_masseinheit_daneben_wird_abgelehnt(auth_client, app_ctx):
    """Dasselbe Muster wie bei der Zahlungsart: ein Auswahlfeld wird geprüft."""
    from nebenkostenfix.models import CostCategory, Meter
    from tests import billing_factories as f
    haus = f.house()
    kategorie = CostCategory.query.filter_by(betrkv_nr=5).first()
    antwort = auth_client.post('/api/meters', data={
        'category_id': kategorie.id, 'property_id': haus.id,
        'meter_number': 'Z-X', 'einheit': 'Liter'})
    assert antwort.status_code == 400, antwort.get_json()
    fehler = antwort.get_json()
    assert 'Liter' in fehler['error'] and 'kWh' in fehler['error']
    assert fehler.get('feld') == 'einheit'
    assert Meter.query.filter_by(meter_number='Z-X').count() == 0


def test_die_masseinheit_laesst_sich_aendern(auth_client, app_ctx):
    """Wer sie beim Anlegen vergisst, kann sie nachtragen (PUT)."""
    from nebenkostenfix.models import CostCategory
    from tests import billing_factories as f
    haus = f.house()
    kategorie = CostCategory.query.filter_by(betrkv_nr=5).first()
    angelegt = auth_client.post('/api/meters', data={
        'category_id': kategorie.id, 'property_id': haus.id,
        'meter_number': 'Z-AEND'}).get_json()
    antwort = auth_client.put(f"/api/meters/{angelegt['id']}", data={'einheit': 'kWh'})
    assert antwort.status_code == 200, antwort.get_json()
    [zaehler] = [z for z in auth_client.get('/api/meters').get_json()
                 if z['meter_number'] == 'Z-AEND']
    assert zaehler['einheit'] == 'kWh'


def test_die_oberflaeche_hat_das_auswahlfeld():
    """Das Feld steht im Zählerdialog und heißt nicht „Einheit".

    Der Begriffskatalog hält „Einheit" für die Wohnung frei (§ 7 des
    Glossars), deshalb „Maßeinheit".
    """
    from tests.test_ui_konsistenz import INDEX, _liest
    html = _liest(INDEX)
    tag = re.search(r'<select id="meter-einheit"[^>]*>(.*?)</select>', html, re.S)
    assert tag, 'Feld meter-einheit fehlt'
    assert 'value="m³"' in tag.group(1) and 'value="kWh"' in tag.group(1)
    assert 'Maßeinheit' in html


# --- Wer die Einheit nennt, muss sie vom Zähler nehmen ------------------------
# Befund aus der Durchsicht vor 0.16.0: die Zählerliste nahm die Einheit vom
# Zähler, zwei andere Wege leiteten sie weiter aus der Kostenart ab. Für den
# Aufbau aus Issue #32 (Warmwasser Nr. 5, Wärmemengenzähler in kWh) hieß das:
# dieselbe Zahl, drei Mal gezeigt, zwei Mal mit der falschen Einheit daneben.


def _wmz_mit_ablesungen(auth_client):
    """Ein Warmwasserzähler (Nr. 5), der kWh misst, mit zwei Ablesungen."""
    from nebenkostenfix.models import CostCategory
    from tests import billing_factories as f
    haus = f.house()
    wohnung = f.apt(haus, 'EG links', 60.0)
    warmwasser = CostCategory.query.filter_by(betrkv_nr=5).first()
    antwort = auth_client.post('/api/meters', data={
        'category_id': warmwasser.id, 'property_id': haus.id,
        'apartment_id': wohnung.id, 'meter_number': 'WMZ-API-1',
        'einheit': 'kWh'})
    assert antwort.status_code == 201, antwort.get_json()
    zaehler_id = antwort.get_json()['id']
    for datum, wert in (('2025-01-01', 1000), ('2025-12-31', 2400)):
        a = auth_client.post('/api/readings', data={
            'meter_id': zaehler_id, 'reading_date': datum, 'value': wert})
        assert a.status_code == 201, a.get_json()
    return wohnung, zaehler_id


def test_die_ableseliste_nennt_die_einheit_des_zaehlers(auth_client, app_ctx):
    """``GET /api/readings`` darf nicht wieder aus der Kostenart ableiten."""
    _wmz_mit_ablesungen(auth_client)
    zeilen = [z for z in auth_client.get('/api/readings').get_json()
              if z['meter_number'] == 'WMZ-API-1']
    assert zeilen, 'keine Ablesung gefunden'
    for zeile in zeilen:
        assert zeile['einheit'] == 'kWh', zeile


def test_der_eigenverbrauch_nennt_die_einheit_des_zaehlers(auth_client, app_ctx):
    """Die Verbrauchsübersicht einer Wohnung ebenso."""
    wohnung, _ = _wmz_mit_ablesungen(auth_client)
    antwort = auth_client.get(f'/api/analytics/apartment/{wohnung.id}')
    assert antwort.status_code == 200, antwort.get_json()
    zeilen = antwort.get_json().get('own_consumption') or []
    assert zeilen, 'kein Eigenverbrauch berechnet'
    for zeile in zeilen:
        assert zeile['unit'] == 'kWh', zeile
