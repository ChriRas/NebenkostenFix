"""Phase 54 (Issue #30): Eigene Kostenarten anlegen und bearbeiten.

Der Vermieter bekommt Abrechnungen seiner Hausverwaltung, deren Kostenarten
anders heißen als der Katalog. Diese Tests erlauben ihm eigene Namen unter
Pflicht-Nummer aus § 2 BetrKV und sperren, was den Rechenkern kippen kann:
Heizung und Warmwasser (Nr. 4-6) und die Entwässerungslogik an Nr. 3.
Alle Werte sind erfunden.
"""

from __future__ import annotations

from datetime import date

from nebenkostenfix import betrkv
from nebenkostenfix.models import CostCategory, TenantCostProfile, db
from tests import billing_factories as f

D = date

HINWEIS = ('Passt keine Nummer? Dann Nr. 17 <em>Sonstige Betriebskosten</em>. '
           'Das gilt nur, wenn sie im Mietvertrag einzeln vereinbart ist. '
           'Verwaltung, Instandhaltung und Rücklagen dürfen nie umgelegt werden.')


def _anlegen(client, name='Quartierservice', nr=14, verteilung='qm',
             zaehler=False):
    return client.post('/api/categories', data={
        'name': name, 'betrkv_nr': nr,
        'allocation_method': verteilung, 'requires_meter': zaehler})


def _rechnung(category, amount=1200):
    haus = f.house()
    return f.invoice(haus, category, amount)


# --- Anlegen -----------------------------------------------------------------

def test_anlegen_und_lesen(auth_client):
    antwort = _anlegen(auth_client)
    assert antwort.status_code == 201
    liste = auth_client.get('/api/categories').get_json()
    zeile = next(z for z in liste if z['name'] == 'Quartierservice')
    assert zeile['betrkv_nr'] == 14
    assert zeile['betrkv_bezeichnung'] == 'Hauswart'
    assert zeile['allocation_method'] == 'qm'
    assert zeile['requires_meter'] is False
    assert zeile['rechnungen'] == 0


def test_doppelter_name_wird_abgelehnt(auth_client):
    assert _anlegen(auth_client, name='Hauswart Süd').status_code == 201
    assert _anlegen(auth_client, name='Hauswart Süd', nr=17).status_code == 409


def test_nummer_ist_pflicht_und_bleibt_im_rahmen(auth_client):
    for nr in (None, 0, 18):
        daten = {'name': 'Eigenbau', 'allocation_method': 'qm'}
        if nr is not None:
            daten['betrkv_nr'] = nr
        assert auth_client.post('/api/categories', data=daten).status_code == 400
    assert auth_client.get('/api/categories').get_json() == [] or all(
        z['name'] != 'Eigenbau'
        for z in auth_client.get('/api/categories').get_json())


def test_heizung_und_warmwasser_bleiben_gesperrt(auth_client):
    for nr in (4, 5, 6):
        antwort = _anlegen(auth_client, name=f'Sperrtest {nr}', nr=nr)
        assert antwort.status_code == 400, nr
        assert 'gesperrt' in antwort.get_json()['error']
    # Der Seed trägt die Nummern selbst (Katalog); eine eigene zusätzliche
    # Kostenart unter 4-6 gibt es nach den Sperren nicht.


def test_verteilung_nur_aus_der_liste(auth_client):
    assert _anlegen(auth_client, verteilung='nach Augenschein').status_code == 400


# --- Namensfalle Nr. 3 --------------------------------------------------------

def test_niederschlagsname_unter_nr_3_wird_abgelehnt(auth_client):
    # „Regenwasser Zweitwehr" trägt ein Wort, das die App am Namen erkennt
    # (betrkv.ist_niederschlag) — genau die Namensfalle, die die Sperre schließt.
    antwort = _anlegen(auth_client, name='Regenwasser Zweitwehr', nr=3)
    assert antwort.status_code == 409
    assert 'Niederschlagswasser' in antwort.get_json()['error']


def test_zweite_abwasser_bedeutung_wird_abgelehnt(auth_client):
    # Der Seed hat „Abwasser" (Nr. 3, keine Niederschlagsbedeutung) — der
    # Schlüssel ist belegt, eine zweite Nr. 3 bräuchte eine andere Bedeutung.
    antwort = _anlegen(auth_client, name='Abwasserkanal', nr=3)
    assert antwort.status_code == 409


# --- Bearbeiten ---------------------------------------------------------------

def test_umbenennen_geht_auch_mit_rechnungen(auth_client):
    kat = CostCategory.query.filter_by(name='Hauswart').first() or \
        CostCategory.query.filter_by(name='Gartenpflege').first()
    _rechnung(kat)
    antwort = auth_client.put(f'/api/categories/{kat.id}',
                              data={'name': 'Grünanlage'})
    assert antwort.status_code == 200
    assert CostCategory.query.get(kat.id).name == 'Grünanlage'


def test_nummer_mit_rechnung_geht_nicht(auth_client):
    kat = CostCategory.query.filter_by(name='Gartenpflege').first()
    _rechnung(kat)
    antwort = auth_client.put(f'/api/categories/{kat.id}',
                              data={'name': 'Gartenpflege', 'betrkv_nr': 17})
    assert antwort.status_code == 409
    assert 'Rechnung' in antwort.get_json()['error']


def test_nummer_mit_zaehler_geht_nicht(auth_client):
    kat = CostCategory.query.filter_by(name='Gartenpflege').first()
    # Ein echter Zähler hängt an der Kostenart: Nummer und Zählerkennung
    # einfrieren, solange er da ist.
    kat.requires_meter = True
    db.session.commit()
    f.meter(f.house(), kat, 'Z-1', is_main=True)
    antwort = auth_client.put(f'/api/categories/{kat.id}',
                              data={'name': 'Gartenpflege',
                                    'requires_meter': 'false'})
    assert antwort.status_code == 409
    assert 'Zähler' in antwort.get_json()['error']


def test_ohne_rechnung_und_zaehler_ist_alles_aenderbar(auth_client):
    kat = CostCategory.query.filter_by(name='Gartenpflege').first()
    antwort = auth_client.put(f'/api/categories/{kat.id}', data={
        'name': 'Grünpflege', 'betrkv_nr': 10,
        'allocation_method': 'personen', 'requires_meter': 'true'})
    assert antwort.status_code == 200
    frisch = CostCategory.query.get(kat.id)
    assert (frisch.name, frisch.betrkv_nr, frisch.allocation_method,
            frisch.requires_meter) == ('Grünpflege', 10, 'personen', True)


def test_die_route_kann_versionen_nicht_beruehren(auth_client):
    # Versionen werden nur geschrieben, nie geändert (models.py). Der Schutz
    # der Route: solange eine Rechnung hängt, gehen nur Namen durch -- und der
    # Name steht im Schnappschuss der Version unveränderlich als Text.
    kat = CostCategory.query.filter_by(name='Gartenpflege').first()
    _rechnung(kat)
    assert auth_client.put(f'/api/categories/{kat.id}',
                           data={'name': 'Grünanlage'}).status_code == 200
    # Die betrkv_nr, nach der Versionen rechnen, ist mit einer Rechnung
    # eingefroren:
    assert auth_client.put(f'/api/categories/{kat.id}',
                           data={'name': 'Grünanlage', 'betrkv_nr': 17}).status_code == 409


# --- Löschen ------------------------------------------------------------------

def test_loeschen_mit_rechnung_geht_nicht(auth_client):
    kat = CostCategory.query.filter_by(name='Gartenpflege').first()
    _rechnung(kat)
    assert auth_client.delete(f'/api/categories/{kat.id}').status_code == 409


def test_katalogeintrag_laesst_sich_nicht_loeschen(auth_client):
    kat = CostCategory.query.filter_by(name='Gartenpflege').first()
    antwort = auth_client.delete(f'/api/categories/{kat.id}')
    assert antwort.status_code == 409
    assert 'Katalog' in antwort.get_json()['error']


def test_unbenutzt_kann_weg_mit_kostenprofilen(auth_client):
    assert _anlegen(auth_client, name='Winterdienst').status_code == 201
    kat = CostCategory.query.filter_by(name='Winterdienst').one()
    haus = f.house()
    mieter = f.tenant(f.apt(haus, 'EG', 50), 'Mieter K', D(2024, 1, 1), None)
    db.session.add(TenantCostProfile(tenant_id=mieter.id, category_id=kat.id,
                                     billing_type='qm'))
    db.session.commit()
    assert auth_client.delete(f'/api/categories/{kat.id}').status_code == 200
    assert CostCategory.query.get(kat.id) is None
    assert TenantCostProfile.query.filter_by(category_id=kat.id).count() == 0


def test_seed_legt_nach_um_benennen_keine_dublette_an(auth_client):
    from app import seed_database
    kat = CostCategory.query.filter_by(name='Gartenpflege').first()
    auth_client.put(f'/api/categories/{kat.id}', data={'name': 'Grünanlage'})
    seed_database()
    namen = [z.name for z in CostCategory.query.all()]
    assert namen.count('Gartenpflege') == 0
    assert namen.count('Grünanlage') == 1


# --- Nummernvorschlag ----------------------------------------------------------

def test_nummernvorschlag_aus_den_stichwoertern():
    assert betrkv.nummernvorschlag('Hauswart') == 14
    assert betrkv.nummernvorschlag('Aufzugswartung') == 7
    assert betrkv.nummernvorschlag('Eigenbrötlerei') is None
    # Gesperrte Nummern werden nie vorgeschlagen.
    for name in ('Heizkosten', 'Warmwasser'):
        vorschlag = betrkv.nummernvorschlag(name)
        assert vorschlag is None or vorschlag not in (4, 5, 6)


# --- Abrechnung ----------------------------------------------------------------

def test_eigene_kostenart_laueft_ueber_nummer_und_name():
    # Der Name „Hauswart" ist im Katalog, der Pdf-Zuordnung bekannt; ein
    # eigenwilliger Name fällt auf Nr. 17 und verliert so nie die Rubrik.
    assert betrkv.zuordnung('Hauswart') == 14
    assert betrkv.zuordnung('Quartierservice') == 17
    from nebenkostenfix.rechenkern import einheit_fuer
    assert einheit_fuer('Quartierservice', 14) == betrkv.einheit(14)


# --- Oberfläche ------------------------------------------------------------------

def test_die_oberflaeche_hat_die_verdrahtung():
    import os
    WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = open(f'{WURZEL}/static/app.js', encoding='utf-8').read()
    seite = open(f'{WURZEL}/static/index.html', encoding='utf-8').read()
    assert 'data-gruppe="kostenarten"' in seite
    assert 'id="kategorie-modal"' in seite
    assert HINWEIS in seite
    assert '/api/categories' in app
    assert 'function nummernVorschlag(' in app
    assert "frage(" in app  # Nr. 17 fragt nach der vertraglichen Vereinbarung


def test_kein_neues_feld_ohne_migration():
    # Phase 54 braucht kein neues Datenbankfeld: name, betrkv_nr,
    # allocation_method und requires_meter tragen alles.
    spalten = {c.name for c in CostCategory.__table__.columns}
    assert spalten == {'id', 'name', 'allocation_method', 'requires_meter',
                       'betrkv_nr'}
