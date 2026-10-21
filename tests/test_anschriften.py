"""Phase 58 (Issue #35, Punkt 1): Anschriften von Mieter und Vermieter.

Der Melder wollte „die Adresse des Mieters, und falls bekannt eine zweite
Adresse für die Zustellung nach dem Auszug". Bis 0.16.0 hatte **niemand**
eine Anschrift: ``Tenant`` kannte Name, Ein- und Auszug, Anrede; die
``Vermieterdaten`` Name, IBAN und Art. Das Anschreiben (NK-064) stand mit
dreizehn Platzhaltern bereit, ohne einen fuer eine Adresse.

Der fachliche Kern steckt in der **Auswahl**, nicht in den Feldern: Die
Abrechnungsfrist des § 556 Abs. 3 BGB laeuft ueber den **Zugang** beim
Mieter. Eine Abrechnung an die alte Wohnung geht ins Leere, die Frist
laeuft trotzdem weiter. Darum gehoert die Auswahl in den Kern, mit Tests
in beide Richtungen -- auch die, die wehtut: Solange der Mieter noch
wohnt, gilt die alte Anschrift, selbst wenn die neue schon bekannt ist.

Der Hinweis ist die zweite Haelfte derselben Sache. Ein ausgezogener
Mieter ohne Zustellanschrift ist der Fall, in dem der Vermieter die Frist
verliert, ohne es zu merken -- deshalb sagt es ihm hier etwas.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from nebenkostenfix import anschreiben, anschrift
from nebenkostenfix.models import Tenant, Vermieterdaten
from tests import billing_factories as f

WURZEL = Path(__file__).resolve().parent.parent
OBERFLAECHE = WURZEL / 'static' / 'index.html'
SKRIPT = WURZEL / 'static' / 'app.js'

HIER = 'Musterweg 1\n12345 Musterstadt'
DORT = 'Neue Straße 9\n54321 Anderswo'


# --- Der Kern: saeubern und zeilen -------------------------------------

def test_saeubern_raeumt_leerzeilen_und_raender():
    """Was aus einem Textfeld kommt, hat Rand und Leerzeilen."""
    roh = '  Musterweg 1  \n\n\n  12345 Musterstadt \n  '

    assert anschrift.saeubern(roh) == HIER


def test_saeubern_haelt_nichts_fuer_etwas():
    """Kein Feld, nur Leerzeichen, nur Umbrueche -- alles dasselbe: leer."""
    for leer in (None, '', '   ', '\n\n', ' \n \n '):
        assert anschrift.saeubern(leer) == ''


def test_zeilen_gibt_die_zeilen_des_briefkopfs():
    """Das Blatt setzt Zeile fuer Zeile; die Reihenfolge ist die Eingabe."""
    assert anschrift.zeilen(HIER) == ['Musterweg 1', '12345 Musterstadt']
    assert anschrift.zeilen(None) == []


# --- Der Kern: ausgezogen oder nicht -----------------------------------

def test_ohne_auszugsdatum_ist_niemand_ausgezogen():
    assert anschrift.ist_ausgezogen(None, date(2026, 1, 1)) is False


def test_der_auszugstag_selbst_zaehlt_noch_als_wohnen():
    """Das Auszugsdatum ist der letzte Miettag (so sagt es der Dialog)."""
    assert anschrift.ist_ausgezogen(date(2026, 1, 1), date(2026, 1, 1)) is False
    assert anschrift.ist_ausgezogen(date(2026, 1, 1), date(2026, 1, 2)) is True


# --- Der Kern: die Auswahl ---------------------------------------------

def test_nach_dem_auszug_gilt_die_zustellanschrift():
    gewaehlt = anschrift.fuer_zustellung(HIER, DORT, ausgezogen=True)

    assert gewaehlt == DORT


def test_ohne_zustellanschrift_bleibt_es_bei_der_alten():
    """Besser die alte Adresse als keine -- ein Nachsender kann greifen."""
    gewaehlt = anschrift.fuer_zustellung(HIER, '', ausgezogen=True)

    assert gewaehlt == HIER


def test_solange_der_mieter_wohnt_gilt_seine_wohnung():
    """Die Richtung, die wehtut: die neue Adresse ist schon bekannt.

    Wer sie trotzdem nimmt, schickt die Abrechnung in eine Wohnung, in
    die der Mieter erst noch zieht. Das Feld heisst „ab Auszug“.
    """
    gewaehlt = anschrift.fuer_zustellung(HIER, DORT, ausgezogen=False)

    assert gewaehlt == HIER


def test_ohne_jede_anschrift_bleibt_es_leer():
    """Kein erfundener Platzhalter -- der Briefkopf bleibt sichtbar leer."""
    assert anschrift.fuer_zustellung('', '', ausgezogen=True) == ''
    assert anschrift.fuer_zustellung(None, None, ausgezogen=False) == ''


# --- Der Kern: der Hinweis ---------------------------------------------

def test_ausgezogen_ohne_zustellanschrift_wird_gesagt():
    """Der Fall, in dem die Frist still verfaellt (§ 556 Abs. 3 BGB)."""
    hinweis = anschrift.zustellhinweis(HIER, '', ausgezogen=True)

    assert hinweis and '556' in hinweis


def test_mit_zustellanschrift_gibt_es_nichts_zu_sagen():
    assert anschrift.zustellhinweis(HIER, DORT, ausgezogen=True) is None


def test_wer_noch_wohnt_braucht_keinen_hinweis():
    assert anschrift.zustellhinweis(HIER, '', ausgezogen=False) is None


# --- Die Felder --------------------------------------------------------

def test_der_mieter_traegt_zwei_anschriften(app_ctx):
    spalten = Tenant.__table__.columns

    for name in ('anschrift', 'zustellanschrift'):
        assert name in spalten, f'Tenant.{name} fehlt.'
        assert spalten[name].nullable, (
            f'Tenant.{name} ist Pflicht. Der Bestand hat keine Anschriften; '
            'eine Pflichtspalte sperrt jeden vorhandenen Mieter aus.')


def test_der_vermieter_traegt_eine_anschrift(app_ctx):
    spalten = Vermieterdaten.__table__.columns

    assert 'anschrift' in spalten, 'Vermieterdaten.anschrift fehlt.'
    assert spalten['anschrift'].nullable


# --- Die Routen --------------------------------------------------------

def test_die_mieterroute_nimmt_und_gibt_beide_anschriften(auth_client, app_ctx):
    wohnung = f.apt(f.house(), 'W1', 60.0)

    antwort = auth_client.post('/api/tenants', data={
        'apartment_id': wohnung.id,
        'name': 'Mieter Muster',
        'move_in_date': '2025-01-01',
        'anschrift': HIER,
        'zustellanschrift': DORT,
    })
    assert antwort.status_code == 201, antwort.get_data(as_text=True)

    [mieter] = auth_client.get('/api/tenants').get_json()
    assert mieter['anschrift'] == HIER
    assert mieter['zustellanschrift'] == DORT


def test_ein_geleertes_feld_raeumt_die_anschrift_wirklich_aus(auth_client, app_ctx):
    """Sonst klebt eine falsche Adresse am Mietverhaeltnis fest."""
    mieter = f.tenant(f.apt(f.house(), 'W1', 60.0), 'Mieter Muster', date(2025, 1, 1))
    mieter.anschrift = HIER
    from nebenkostenfix.models import db
    db.session.commit()

    antwort = auth_client.put(f'/api/tenants/{mieter.id}', data={'anschrift': ''})
    assert antwort.status_code == 200, antwort.get_data(as_text=True)

    [stand] = auth_client.get('/api/tenants').get_json()
    assert stand['anschrift'] is None


def test_die_vermieterroute_traegt_die_anschrift(auth_client, app_ctx):
    antwort = auth_client.put('/api/vermieter', json={
        'name': 'Max Mustermann',
        'iban': '',
        'anschrift': HIER,
    })
    assert antwort.status_code == 200, antwort.get_data(as_text=True)
    assert antwort.get_json()['anschrift'] == HIER

    assert auth_client.get('/api/vermieter').get_json()['anschrift'] == HIER


def test_die_dsgvo_auskunft_nennt_die_anschriften(auth_client, app_ctx):
    """NK-078: was gespeichert ist, steht in der Auskunft (DSGVO Art. 15)."""
    from nebenkostenfix import mieter_daten
    from nebenkostenfix.models import db

    mieter = f.tenant(f.apt(f.house(), 'W1', 60.0), 'Mieter Muster', date(2025, 1, 1))
    mieter.anschrift = HIER
    mieter.zustellanschrift = DORT
    db.session.commit()

    _bytes, inhalt = mieter_daten.export_erstellen(mieter)

    assert inhalt['mieter']['anschrift'] == HIER
    assert inhalt['mieter']['zustellanschrift'] == DORT


# --- Das Anschreiben ---------------------------------------------------

def test_das_anschreiben_kennt_beide_anschriften_als_platzhalter():
    for name in ('mieter_anschrift', 'vermieter_anschrift'):
        assert name in anschreiben.PLATZHALTER, (
            f'„{{{name}}}“ fehlt in der Liste, die die Route dem Vermieter '
            'nennt. Ein Platzhalter, den niemand kennt, wird nie benutzt.')


def _text(**zusatz) -> str:
    grund = dict(
        mieter_name='Mieter Muster', wohnung_name='W1', objekt_name='Haus',
        zeitraum='01.01.2025 bis 31.12.2025', gesamtsumme=0, vorauszahlungen=0,
        saldo=0,
    )
    grund.update(zusatz)
    from decimal import Decimal
    for geld in ('gesamtsumme', 'vorauszahlungen', 'saldo'):
        grund[geld] = Decimal(grund[geld])
    return anschreiben.text_fuer(
        '{mieter_anschrift}|{vermieter_anschrift}|{anrede}', **grund)


def test_die_anschriften_werden_eingesetzt():
    text = _text(mieter_anschrift=HIER, vermieter_anschrift=DORT)

    assert HIER in text
    assert DORT in text


def test_eine_fehlende_anschrift_bleibt_ein_sichtbares_loch():
    """Ein leerer Briefkopf schweigt, ein sichtbarer Platzhalter schreit."""
    text = _text()

    assert '{mieter_anschrift}' in text, (
        'Die fehlende Mieteranschrift verschwindet still. Dann geht ein '
        'Brief ohne Empfänger raus und die Frist läuft trotzdem.')
    assert '{vermieter_anschrift}' in text


# --- Die Oberflaeche ---------------------------------------------------

@pytest.fixture(scope='module')
def html() -> str:
    return OBERFLAECHE.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def js() -> str:
    return SKRIPT.read_text(encoding='utf-8')


def test_der_mieterdialog_hat_zwei_anschriftenfelder(html):
    """Mehrzeilig: eine Anschrift ist kein einzeiliges Feld."""
    for kennung in ('tenant-anschrift', 'tenant-zustellanschrift'):
        feld = re.search(rf'<textarea id="{kennung}"', html)
        assert feld, f'Das mehrzeilige Feld {kennung} fehlt im Mieterdialog.'


def test_das_zweite_feld_erklaert_warum_es_da_ist(html):
    """Ohne den Grund sieht es aus wie ein zweites Feld fuer dasselbe."""
    assert '556' in html, (
        'Der Hilfetext zur Zustelladresse nennt § 556 Abs. 3 BGB nicht. '
        'Dann weiß der Vermieter nicht, warum die zweite Adresse zählt.')


def test_die_einstellungen_haben_die_anschrift_des_vermieters(html):
    assert re.search(r'<textarea id="vermieter-anschrift"', html), (
        'Die Vermieterkarte hat kein Feld für die eigene Anschrift.')


def test_die_oberflaeche_schickt_beide_felder_immer(js):
    """Nur ein immer mitgeschicktes Feld laesst sich leeren (wie `anrede`)."""
    speichern = re.search(r'const formData = new FormData\(\);.*?fetch\(url',
                          js, re.S)
    assert speichern, 'Das Speichern des Mieters ist nicht auffindbar.'
    text = speichern.group(0)

    for feld in ('anschrift', 'zustellanschrift'):
        assert f"formData.append('{feld}'" in text, (
            f'„{feld}“ wird nicht mitgeschickt.')
        assert f"if (anschrift) formData.append('{feld}'" not in text, (
            f'„{feld}“ wird nur bedingt geschickt -- dann lässt sich die '
            'Anschrift nie wieder leeren.')


def test_der_dialog_fuellt_und_raeumt_beide_felder(js):
    """Ein Rest aus dem vorigen Mieter im Feld ist ein echter Fehler."""
    dialog = re.search(r'function openAddTenantModal\(.*?\n\}', js, re.S)
    assert dialog, 'openAddTenantModal() ist nicht auffindbar.'
    text = dialog.group(0)

    for kennung in ('tenant-anschrift', 'tenant-zustellanschrift'):
        assert text.count(f"'{kennung}'") >= 2, (
            f'{kennung} wird im Dialog nicht beides -- gefüllt und geräumt.')


def test_der_cache_buster_steigt_mit_der_aenderung(html):
    js_version = re.search(r'/static/app\.js\?v=(\d+)', html)

    assert js_version and int(js_version.group(1)) >= 41, (
        'Der Cache-Buster von app.js steht noch unter 41 (Phase 58).')
