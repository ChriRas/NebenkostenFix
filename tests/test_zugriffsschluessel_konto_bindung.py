"""Ein Zugriffsschlüssel gilt nur für das Konto, für das er angelegt wurde.

Gleiches Muster wie bei der Sitzung (``tests/test_nacht_sitzung_wiederverwendete_id.py``):
``api_schluessel.user_id`` verweist ohne ``ondelete`` auf ``users.id``, und
SQLite setzt den Fremdschlüssel ohne ``PRAGMA foreign_keys`` nicht durch.
Verschwindet ein Konto direkt in der Datenbank, bleibt sein Schlüssel
stehen. Das nächste neue Konto bekommt
dieselbe Nummer, und der alte Schlüssel galt für das neue Konto.

Seit dem Fix lehnt die Prüfung einen Schlüssel ab, der älter ist als sein
Konto (``angelegt_am`` vor ``users.created_at``). Verglichen wird auf die
Sekunde genau: ein Schlüssel aus derselben Sekunde wie das Konto bleibt
gültig. Naive Zeitstempel gelten als UTC (``nebenkostenfix/zeit.py``). Fehlt
eine der beiden Zeiten (in der Datenbank NOT NULL, hier nur zur Absicherung),
gilt der Schlüssel wie bisher.

Alle Daten fiktiv.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nebenkostenfix import zugriffsschluessel as zs
from nebenkostenfix.models import ApiSchluessel, User, db

PFAD = '/api/zugriffsschluessel'
PARTNER = 'bindung-partnerin'
PARTNER_PASSWORT = 'bindung-passwort-1'
NEUES_KONTO = 'bindung-neues-konto'
NEUES_PASSWORT = 'bindung-passwort-2'


def _kopf(schluessel):
    return {'Authorization': f'Bearer {schluessel}'}


def _konto_mit_schluessel(app_ctx, auth_client):
    """Zweites Konto über die Kontenverwaltung, das sich selbst einen
    Schlüssel anlegt. Konto und Schlüssel werden eine Stunde zurückdatiert:
    so alt sind sie, wenn das Konto später verschwindet und ein neues kommt."""
    assert auth_client.post('/api/konten', json={
        'username': PARTNER, 'password': PARTNER_PASSWORT}).status_code == 201
    geraet = app_ctx.app.test_client()
    assert geraet.post('/login', json={
        'username': PARTNER, 'password': PARTNER_PASSWORT}).status_code == 200
    antwort = geraet.post(PFAD, json={'name': 'Skript auf dem NAS', 'umfang': 'lesen'})
    assert antwort.status_code == 201, antwort.get_data(as_text=True)
    partner = User.query.filter_by(username=PARTNER).one()
    partner.created_at = partner.created_at - timedelta(hours=1)
    zeile = ApiSchluessel.query.one()
    zeile.angelegt_am = zeile.angelegt_am - timedelta(hours=1)
    db.session.commit()
    return antwort.get_json()['schluessel'], partner


def _direkt_loeschen(user):
    """Wie ein Eingriff in die Datenbank: der Schlüssel bleibt stehen."""
    db.session.delete(user)
    db.session.commit()
    assert ApiSchluessel.query.count() == 1


@pytest.mark.parametrize('neuer_name', [NEUES_KONTO, PARTNER])
def test_schluessel_des_geloeschten_kontos_gilt_nicht_fuer_das_neue(
        app_ctx, auth_client, anon_client, neuer_name):
    schluessel, partner = _konto_mit_schluessel(app_ctx, auth_client)
    alte_id = partner.id
    assert anon_client.get('/api/properties', headers=_kopf(schluessel)).status_code == 200

    _direkt_loeschen(partner)
    antwort = auth_client.post('/api/konten', json={
        'username': neuer_name, 'password': NEUES_PASSWORT})
    assert antwort.status_code == 201, antwort.get_data(as_text=True)
    neu = User.query.filter_by(username=neuer_name).one()
    assert neu.id == alte_id  # SQLite vergibt die Nummer wieder

    antwort = anon_client.get('/api/properties', headers=_kopf(schluessel))
    assert antwort.status_code == 401, (
        'alter Schlüssel gilt für das neue Konto mit derselben Nummer: '
        f'{antwort.get_data(as_text=True)}')
    assert antwort.get_json()['code'] == 'schluessel_ungueltig'
    assert anon_client.get('/api/auth/me', headers=_kopf(schluessel)).status_code == 401


def test_neuer_schluessel_des_neuen_kontos_gilt(app_ctx, auth_client, anon_client):
    """Gegenprobe: das neue Konto legt sich selbst einen Schlüssel an, der gilt."""
    _, partner = _konto_mit_schluessel(app_ctx, auth_client)
    _direkt_loeschen(partner)
    assert auth_client.post('/api/konten', json={
        'username': NEUES_KONTO, 'password': NEUES_PASSWORT}).status_code == 201
    geraet = app_ctx.app.test_client()
    assert geraet.post('/login', json={
        'username': NEUES_KONTO, 'password': NEUES_PASSWORT}).status_code == 200
    neu = geraet.post(PFAD, json={'name': 'Neues Skript', 'umfang': 'lesen'}).get_json()
    wer = anon_client.get('/api/auth/me', headers=_kopf(neu['schluessel'])).get_json()
    assert wer['username'] == NEUES_KONTO


def _zeitpunkte_setzen(konto_angelegt, schluessel_angelegt):
    user = User.query.one()
    user.created_at = konto_angelegt
    zeile = ApiSchluessel.query.one()
    zeile.angelegt_am = schluessel_angelegt
    db.session.commit()


@pytest.mark.parametrize('schluessel_angelegt, status', [
    # Dieselbe Sekunde wie das Konto, auch mit kleinerem Bruchteil: gültig.
    (datetime(2026, 3, 1, 12, 0, 0, 100000), 200),
    (datetime(2026, 3, 1, 12, 0, 0, 900000), 200),
    (datetime(2026, 3, 1, 12, 0, 0), 200),
    (datetime(2026, 3, 1, 12, 0, 1), 200),
    # Eine Sekunde davor: aus der Zeit vor diesem Konto.
    (datetime(2026, 3, 1, 11, 59, 59, 999999), 401),
    (datetime(2025, 12, 31, 23, 0, 0), 401),
])
def test_vergleich_auf_die_sekunde(auth_client, anon_client, schluessel_angelegt, status):
    neu = auth_client.post(PFAD, json={'name': 'MCP-Server', 'umfang': 'lesen'}).get_json()
    _zeitpunkte_setzen(datetime(2026, 3, 1, 12, 0, 0, 500000), schluessel_angelegt)
    antwort = anon_client.get('/api/properties', headers=_kopf(neu['schluessel']))
    assert antwort.status_code == status, antwort.get_data(as_text=True)


@pytest.mark.parametrize('konto, schluessel, aelter', [
    # Naiv gilt als UTC; mit Zone wird nach UTC gewandelt, ohne TypeError.
    (datetime(2026, 3, 1, 12, 0, 0), datetime(2026, 3, 1, 11, 0, 0), True),
    (datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
     datetime(2026, 3, 1, 12, 0, 0, 300000), False),
    (datetime(2026, 3, 1, 12, 0, 0),
     datetime(2026, 3, 1, 13, 0, 0, tzinfo=timezone(timedelta(hours=1))), False),
    (datetime(2026, 3, 1, 12, 0, 0),
     datetime(2026, 3, 1, 12, 59, 59, tzinfo=timezone(timedelta(hours=1))), True),
])
def test_naive_und_zonierte_zeitstempel(app_ctx, konto, schluessel, aelter):
    zeile = ApiSchluessel(angelegt_am=schluessel)
    zeile.user = User(username='bindung-attrappe', created_at=konto)
    assert zs.aelter_als_das_konto(zeile) is aelter


@pytest.mark.parametrize('konto, schluessel', [
    (None, datetime(2026, 3, 1, 12, 0, 0)),
    (datetime(2026, 3, 1, 12, 0, 0), None),
])
def test_ohne_anlagezeit_gilt_der_schluessel_wie_bisher(app_ctx, konto, schluessel):
    """Fehlt eine der beiden Zeiten (``users.created_at`` und
    ``api_schluessel.angelegt_am`` sind in der Datenbank NOT NULL, die
    Prüfung sichert hier nur ab), lässt sich nicht sagen, ob der Schlüssel
    älter ist, also gilt er wie bisher."""
    zeile = ApiSchluessel(angelegt_am=schluessel)
    zeile.user = User(username='bindung-attrappe', created_at=konto)
    assert zs.aelter_als_das_konto(zeile) is False
