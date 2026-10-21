"""NK-264: Anrede je Mieter und ich/wir nach der Art des Vermieters.

NK-247 und NK-248 machten Anschreiben und PDF neutral („Guten Tag …“,
keine ich/wir-Sätze), weil die Software nicht wusste, wer schreibt. Jetzt
sagt der Vermieter es: „privat“ spricht als ich, „firma“ als wir, leer
bleibt bei den neutralen Sätzen. Je Mieter darf eine eigene Anrede
stehen; ohne sie bleibt „Guten Tag <Name>,“.

Geprüft werden die Sätze in allen drei Formen (Vorgabe und PDF-Schluss),
die Anrede mit und ohne Feld auf dem Deckblatt und im gespeicherten PDF,
die Maskierung von Name und Anrede, die APIs von Mieter und Vermieter,
Mieter-Auskunft und Umzugspaket sowie die Felder der Oberfläche.
"""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
import reportlab.rl_config

from nebenkostenfix.anschreiben import (
    ANREDE, ARTEN, PLATZHALTER, VORGABE, anrede, saetze, text_fuer, vorgabe,
)
from nebenkostenfix.pdf_cover_page import build_cover_page_elements
from nebenkostenfix.pdf_generator import PDFGenerator
from test_anschreiben import ICH_WIR, _blaetter, _finalisiere, _welt
from test_pdf_belegliste import _geklebt, _posten
from test_umzug import bestand  # noqa: F401 -- Fixture

ROOT = Path(__file__).resolve().parents[1]
IBAN = 'DE89370400440532013000'
WERTE = dict(mieter_name='Anna Mieterin', wohnung_name='EG links',
             objekt_name='Haus', zeitraum='2025', gesamtsumme=Decimal('1200.00'),
             vorauszahlungen=Decimal('300.00'), saldo=Decimal('900.00'))


@pytest.fixture
def unkomprimiert(monkeypatch):
    """Seiten ohne Kompression, damit der Text lesbar im Strom steht."""
    monkeypatch.setattr(reportlab.rl_config, 'pageCompression', 0)


@pytest.fixture
def vermieter(app_ctx, monkeypatch):
    """Leere Vermieter-Tabelle ohne Umgebung; liefert einen Setzer."""
    from nebenkostenfix.models import Vermieterdaten, db

    monkeypatch.delenv('VERMIETER_NAME', raising=False)
    monkeypatch.delenv('VERMIETER_IBAN', raising=False)
    Vermieterdaten.query.delete()
    db.session.commit()

    def setzen(art, iban=None):
        db.session.add(Vermieterdaten(art=art, iban=iban))
        db.session.commit()
    return setzen


# --- Die Anrede ---------------------------------------------------------------


def test_ohne_eigene_anrede_bleibt_guten_tag():
    assert anrede('Anna Mieterin') == ANREDE.format(mieter_name='Anna Mieterin')
    assert anrede('Anna Mieterin', None) == 'Guten Tag Anna Mieterin,'
    assert anrede('Anna Mieterin', '   ') == 'Guten Tag Anna Mieterin,'


def test_die_eigene_anrede_bekommt_ihr_komma():
    assert anrede('Anna', 'Sehr geehrte Frau Muster') == 'Sehr geehrte Frau Muster,'
    assert anrede('Anna', ' Liebe Anna, ') == 'Liebe Anna,'
    assert anrede('Anna', 'Hallo Anna!') == 'Hallo Anna!'


def test_die_vorgabe_traegt_die_anrede_als_platzhalter():
    assert VORGABE.startswith('{anrede}\n\n') and 'anrede' in PLATZHALTER
    mit = text_fuer(VORGABE, mieter_anrede='Sehr geehrte Frau Mieterin', **WERTE)
    ohne = text_fuer(VORGABE, **WERTE)
    assert mit.startswith('Sehr geehrte Frau Mieterin,\n\n')
    assert ohne.startswith('Guten Tag Anna Mieterin,\n\n')


# --- ich, wir oder neutral ----------------------------------------------------


def test_neutral_ist_die_vorgabe_von_bisher():
    assert vorgabe() == vorgabe(None) == VORGABE
    assert ICH_WIR.findall(text_fuer(VORGABE, **WERTE)) == []
    # Unbekannte Werte fallen auf neutral, nicht auf einen KeyError.
    assert saetze('irgendwas') == saetze(None)


@pytest.mark.parametrize('art, belege', [
    ('privat', 'Die Belege können Sie auf Verlangen bei mir einsehen.'),
    ('firma', 'Die Belege können Sie auf Verlangen bei uns einsehen.'),
])
def test_die_vorgabe_spricht_als_ich_oder_wir(art, belege):
    text = text_fuer(vorgabe(art), **WERTE)
    assert belege in text
    # Nur der Belegsatz wechselt; die Aufforderung bleibt neutral (NK-248).
    assert 'Bitte gleichen Sie den ausstehenden Betrag' in text
    assert text.replace(belege, saetze(None)['belege']) == text_fuer(VORGABE, **WERTE)


def test_jede_art_kennt_jeden_satz():
    assert set(ARTEN) == {'privat', 'firma'}
    for art in (None, *ARTEN):
        assert set(saetze(art)) == {'belege', 'konto', 'bekanntes_konto', 'rueckfragen'}


def _schluss(art, iban, vermieter) -> str:
    vermieter(art, iban)
    erzeuger = PDFGenerator(property_name='Haus am Anger', apartment_name='Wohnung 1',
                            tenant_name='Mustermann', start_date='2024-01-01',
                            end_date='2024-12-31')
    return _geklebt(erzeuger.generate([_posten()], Decimal('600.00'), Decimal('0.00')))


@pytest.mark.parametrize('art, konto, rueckfragen', [
    (None, 'aufdasKontomitderIBAN', 'RückfragenzurAbrechnungwerdengernbeantwortet.'),
    ('privat', 'aufmeinKontomitderIBAN', 'RückfragenzurAbrechnungbeantworteichgern.'),
    ('firma', 'aufunserKontomitderIBAN', 'RückfragenzurAbrechnungbeantwortenwirgern.'),
])
def test_der_pdf_schluss_mit_iban(unkomprimiert, vermieter, art, konto, rueckfragen):
    geklebt = _schluss(art, IBAN, vermieter)
    assert konto in geklebt and IBAN in geklebt.replace(' ', '')
    assert rueckfragen in geklebt


@pytest.mark.parametrize('art, konto', [
    (None, 'aufdasbekannteKonto.'),
    ('privat', 'aufmeinbekanntesKonto.'),
    ('firma', 'aufunserbekanntesKonto.'),
])
def test_der_pdf_schluss_ohne_iban(unkomprimiert, vermieter, art, konto):
    geklebt = _schluss(art, None, vermieter)
    assert konto in geklebt and 'IBAN' not in geklebt


# --- Deckblatt ------------------------------------------------------------------


def _deckblatt(tenant_name='Anna Mieterin', tenant_anrede=None) -> str:
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    elemente = build_cover_page_elements(
        property_name='Haus am Anger', apartment_name='EG links',
        tenant_name=tenant_name, start_date='2025-01-01', end_date='2025-12-31',
        total_amount=Decimal('1200.00'), prepaid_amount=Decimal('300.00'),
        balance=Decimal('900.00'), tenant_anrede=tenant_anrede)
    puffer = BytesIO()
    SimpleDocTemplate(puffer, pagesize=A4).build(elemente)
    return _blaetter(puffer.getvalue())[0]


def test_das_deckblatt_gruesst_mit_und_ohne_eigene_anrede(unkomprimiert):
    assert 'GutenTagAnnaMieterin,' in _deckblatt()
    blatt = _deckblatt(tenant_anrede='Sehr geehrte Frau Mieterin')
    assert 'SehrgeehrteFrauMieterin,' in blatt and 'GutenTag' not in blatt


def test_name_und_anrede_werden_maskiert(unkomprimiert):
    """„&“ und „<“ sind Text, kein Markup -- vorher fiel der Name im Kopf aus."""
    blatt = _deckblatt(tenant_name='Anna & Bert <GbR>',
                       tenant_anrede='Hallo Anna & Bert <GbR>')
    assert 'An:Anna&Bert<GbR>' in blatt
    assert 'HalloAnna&Bert<GbR>,' in blatt


# --- Durch die App: Festsetzung, Anschreiben-Route ------------------------------


def test_die_festsetzung_druckt_anrede_und_art(auth_client, app_ctx, unkomprimiert,
                                               vermieter):
    from nebenkostenfix.models import Tenant, db

    mieter_id, _, _ = _welt(app_ctx)
    vermieter('privat')
    db.session.get(Tenant, mieter_id).anrede = 'Sehr geehrte Frau Mieterin'
    db.session.commit()

    report = _finalisiere(auth_client, mieter_id)
    blatt = ''.join(_blaetter(
        (Path(os.environ['NAS_MOUNT_PATH']) / report.document_path).read_bytes()))
    assert 'SehrgeehrteFrauMieterin,' in blatt and 'GutenTag' not in blatt
    assert 'DieBelegekönnenSieaufVerlangenbeimireinsehen.' in blatt
    assert 'RückfragenzurAbrechnungbeantworteichgern.' in blatt


def test_die_anschreiben_route_liefert_die_vorgabe_der_art(auth_client, app_ctx, vermieter):
    from billing_factories import house
    from nebenkostenfix.models import db

    objekt = house()
    db.session.commit()
    vermieter('firma')
    antwort = auth_client.get(f'/api/properties/{objekt.id}/anschreiben').get_json()
    assert antwort['text'] == vorgabe('firma') and 'bei uns einsehen' in antwort['text']
    geloescht = auth_client.delete(f'/api/properties/{objekt.id}/anschreiben').get_json()
    assert geloescht['text'] == vorgabe('firma')


# --- Mieter-API ---------------------------------------------------------------


def test_die_mieter_api_haelt_die_anrede(auth_client, app_ctx):
    from billing_factories import apt, house
    from nebenkostenfix.models import Tenant, db

    wohnung = apt(house(), 'EG links', 50.0)
    db.session.commit()
    angelegt = auth_client.post('/api/tenants', content_type='multipart/form-data', data={
        'apartment_id': str(wohnung.id), 'name': 'Anna Mieterin',
        'move_in_date': '2025-01-01', 'anrede': '  Sehr geehrte Frau Mieterin '})
    assert angelegt.status_code == 201, angelegt.get_data(as_text=True)
    mieter_id = angelegt.get_json()['id']

    def gelesen():
        return next(t['anrede'] for t in auth_client.get('/api/tenants').get_json()
                    if t['id'] == mieter_id)
    assert gelesen() == 'Sehr geehrte Frau Mieterin'

    # Ein PUT ohne Feld lässt die Anrede stehen, ein leeres Feld löscht sie.
    assert auth_client.put(f'/api/tenants/{mieter_id}',
                           json={'name': 'Anna M.'}).status_code == 200
    assert gelesen() == 'Sehr geehrte Frau Mieterin'
    assert auth_client.put(f'/api/tenants/{mieter_id}',
                           json={'anrede': 'Liebe Anna'}).status_code == 200
    assert gelesen() == 'Liebe Anna'
    assert auth_client.put(f'/api/tenants/{mieter_id}', json={'anrede': '  '}).status_code == 200
    assert gelesen() is None
    db.session.expire_all()
    assert db.session.get(Tenant, mieter_id).anrede is None


# --- Vermieter-API ------------------------------------------------------------


def test_die_vermieter_api_haelt_die_art(auth_client, vermieter):
    assert auth_client.get('/api/vermieter').get_json()['art'] is None
    antwort = auth_client.put('/api/vermieter', json={'name': 'Erika', 'iban': '', 'art': 'firma'})
    assert antwort.status_code == 200 and antwort.get_json()['art'] == 'firma'
    # Ältere Oberfläche ohne Feld: die Art bleibt stehen.
    assert auth_client.put('/api/vermieter', json={'name': 'Erika'}).get_json()['art'] == 'firma'
    # Leer heißt zurück zu neutral.
    assert auth_client.put('/api/vermieter', json={'name': 'Erika', 'art': ''}).get_json()['art'] is None


def test_eine_falsche_art_wird_abgewiesen(auth_client, vermieter):
    from nebenkostenfix.models import Vermieterdaten

    auth_client.put('/api/vermieter', json={'name': 'Erika', 'art': 'privat'})
    antwort = auth_client.put('/api/vermieter', json={'name': 'Erika', 'art': 'verein'})
    assert antwort.status_code == 400 and antwort.get_json()['feld'] == 'art'
    assert Vermieterdaten.einziger().art == 'privat'


# --- Auskunft und Umzug -------------------------------------------------------


def test_die_mieter_auskunft_nennt_die_anrede(auth_client, app_ctx):
    from billing_factories import apt, house, tenant
    from nebenkostenfix.models import db

    mieter = tenant(apt(house(), 'EG links', 50.0), 'Anna Mieterin')
    mieter.anrede = 'Sehr geehrte Frau Mieterin'
    db.session.commit()
    antwort = auth_client.get(f'/api/tenants/{mieter.id}/export')
    assert antwort.status_code == 200
    with zipfile.ZipFile(io.BytesIO(antwort.data)) as paket:
        name = next(n for n in paket.namelist() if n.endswith('.json'))
        inhalt = json.loads(paket.read(name))
    assert inhalt['mieter']['anrede'] == 'Sehr geehrte Frau Mieterin'


def test_das_umzugspaket_traegt_anrede_und_art(bestand, tmp_path):
    from billing_factories import apt, tenant
    from nebenkostenfix import umzug
    from nebenkostenfix.models import Property, Tenant, Vermieterdaten, db

    haus = Property.query.one()
    mieter = tenant(apt(haus, 'EG links', 50.0), 'Anna Mieterin')
    mieter.anrede = 'Sehr geehrte Frau Mieterin'
    db.session.add(Vermieterdaten(name='Erika', art='firma'))
    db.session.commit()
    paket = umzug.paket_erstellen(bestand.app, tmp_path / 'NebenkostenFix-test.nkfix')

    # Auf dem „neuen Rechner“ steht etwas anderes -- das Paket ersetzt es.
    mieter.anrede = None
    Vermieterdaten.einziger().art = 'privat'
    db.session.commit()
    db.session.remove()

    umzug.uebernehmen(bestand.app, paket)
    with bestand.app.app_context():
        assert Tenant.query.one().anrede == 'Sehr geehrte Frau Mieterin'
        assert Vermieterdaten.einziger().art == 'firma'
        db.session.remove()


# --- Oberfläche ---------------------------------------------------------------


def _funktion(quelle: str, name: str) -> str:
    anfang = quelle.index(f'function {name}(')
    return quelle[anfang:quelle.index('\n}\n', anfang)]


def test_die_oberflaeche_fuehrt_beide_felder():
    html = (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')
    js = (ROOT / 'static' / 'app.js').read_text(encoding='utf-8')
    assert re.search(r'<input[^>]*id="tenant-anrede"[^>]*maxlength="200"', html)
    auswahl = re.search(r'<select[^>]*id="vermieter-art".*?</select>', html, re.S).group(0)
    assert re.findall(r'value="(\w*)"', auswahl) == ['', 'privat', 'firma']
    assert html.count('for="tenant-anrede"') == 1 and html.count('for="vermieter-art"') == 1

    assert "formData.append('anrede'" in _funktion(js, 'saveTenant')
    oeffnen = _funktion(js, 'openAddTenantModal')
    assert oeffnen.count("getElementById('tenant-anrede').value") == 2
    # Die Absicht ist „die Art geht mit", nicht „sie steht als Letztes im
    # Rumpf": Phase 58 hat `anschrift` dahinter gesetzt, und der Test fiel
    # um, obwohl die Art unverändert mitging.
    sichern = _funktion(js, 'saveVermieterdaten')
    rumpf = re.search(r'JSON\.stringify\(\{([^}]*)\}\)', sichern)
    assert rumpf and 'art' in [w.strip() for w in rumpf.group(1).split(',')]
    assert "getElementById('vermieter-art').value = stand.art" in _funktion(
        js, 'fetchVermieterdaten')
