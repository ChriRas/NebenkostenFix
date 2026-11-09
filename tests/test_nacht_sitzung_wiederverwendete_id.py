"""Anmeldung: eine Sitzung überlebte das Löschen ihres Kontos.

Die Sitzung merkte sich nur ``user_id``. ``/api/anmeldung/aus`` löscht alle
Konten; legt danach jemand ein neues Konto an (Einrichtung oder
``flask users add``), vergibt SQLite dieselbe Nummer wieder. Ein Browser, der
vorher mit dem gelöschten Konto angemeldet war und seitdem nichts angefragt
hat (z. B. das zweite Gerät oder das des Partners), war damit ohne Passwort
als das *neue* Konto angemeldet -- R-DSGVO-01 (Zugang nur mit Anmeldung).

Seit dem Fix trägt die Sitzung zusätzlich Benutzername und die Anlagezeit
des Kontos (``auth.SESSION_KONTO_KEY``); passt eins davon nicht, ist sie
beendet.

Alle Daten fiktiv.
"""

from __future__ import annotations

import pytest

from nebenkostenfix.models import User, db

from tests.conftest import TEST_PASSWORD, TEST_USER


@pytest.fixture(autouse=True)
def eigener_datenordner(tmp_path, monkeypatch):
    """``/api/anmeldung/aus`` schreibt ``ohne_anmeldung=True`` in die
    Einstellungen des Datenordners. Im gemeinsamen Ordner liefen spätere
    Tests ohne Konto dann im offenen Modus -- darum ein eigener je Test,
    wie in tests/test_ohne_anmeldung.py."""
    from nebenkostenfix import datenordner
    monkeypatch.setattr(datenordner, "datenordner", lambda: tmp_path)
    return tmp_path


ALTES_KONTO = "nacht-altes-konto"
ALTES_PASSWORT = "Nacht-Passwort-123"
NEUES_KONTO = "nacht-neues-konto"
NEUES_PASSWORT = "nacht-neues-passwort-1"


def _konto_anlegen(name, passwort):
    user = User(username=name)
    user.set_password(passwort)
    db.session.add(user)
    db.session.commit()
    return user


def _angemeldeter_client(app_ctx, name, passwort):
    client = app_ctx.app.test_client()
    res = client.post("/login", json={"username": name, "password": passwort})
    assert res.status_code == 200, res.get_data(as_text=True)
    return client


def _zwei_geraete_und_ausschalten(app_ctx):
    """Konto anlegen, auf zwei Geräten anmelden, auf Gerät A die Anmeldung
    ausschalten. Liefert Gerät B und die alte id samt Anlagezeit."""
    alt = _konto_anlegen(ALTES_KONTO, ALTES_PASSWORT)
    alte_id, alte_anlage = alt.id, alt.created_at
    geraet_a = _angemeldeter_client(app_ctx, ALTES_KONTO, ALTES_PASSWORT)
    geraet_b = _angemeldeter_client(app_ctx, ALTES_KONTO, ALTES_PASSWORT)
    assert geraet_b.get("/api/auth/me").status_code == 200

    res = geraet_a.post("/api/anmeldung/aus", json={"password": ALTES_PASSWORT})
    assert res.status_code == 200, res.get_data(as_text=True)
    assert User.query.count() == 0
    return geraet_b, alte_id, alte_anlage


def test_alte_sitzung_gilt_nicht_fuer_ein_neues_konto(auth_client, app_ctx):
    # Zweites Gerät, mit demselben (alten) Konto angemeldet.
    anderes_geraet = app_ctx.app.test_client()
    res = anderes_geraet.post("/login", json={"username": TEST_USER,
                                              "password": TEST_PASSWORD})
    assert res.status_code == 200
    alte_id = User.query.filter_by(username=TEST_USER).one().id

    # Auf dem ersten Gerät: Anmeldung ausschalten, alle Konten weg.
    res = auth_client.post("/api/anmeldung/aus", json={"password": TEST_PASSWORD})
    assert res.status_code == 200, res.get_data(as_text=True)
    assert User.query.count() == 0

    # Später: neues Konto, z. B. per Einrichtung oder CLI.
    neu = User(username="nacht-neues-konto")
    neu.set_password("nacht-neues-passwort-1")
    db.session.add(neu)
    db.session.commit()
    assert neu.id == alte_id  # die Nummer wird wiederverwendet

    res = anderes_geraet.get("/api/auth/me")
    assert res.status_code == 401, (
        "alte Sitzung ist ohne Passwort als neues Konto angemeldet: "
        f"{res.get_json()}")


def test_neues_konto_mit_anderem_namen_und_derselben_id(app_ctx):
    geraet_b, alte_id, _ = _zwei_geraete_und_ausschalten(app_ctx)

    neu = _konto_anlegen(NEUES_KONTO, NEUES_PASSWORT)
    assert neu.id == alte_id

    res = geraet_b.get("/api/auth/me")
    assert res.status_code == 401, res.get_json()
    # Auch eine Fachroute bleibt zu, nicht nur /api/auth/me.
    assert geraet_b.get("/api/properties").status_code == 401


def test_neues_konto_mit_demselben_namen_und_derselben_id(app_ctx):
    """Nur am Benutzernamen festgemacht reichte es nicht: das neue Konto
    darf wieder so heißen wie das gelöschte."""
    geraet_b, alte_id, alte_anlage = _zwei_geraete_und_ausschalten(app_ctx)

    neu = _konto_anlegen(ALTES_KONTO, "nacht-anderes-passwort-2")
    assert neu.id == alte_id
    assert neu.username == ALTES_KONTO
    assert neu.created_at != alte_anlage

    res = geraet_b.get("/api/auth/me")
    assert res.status_code == 401, (
        "alte Sitzung gilt für das neue Konto mit demselben Namen: "
        f"{res.get_json()}")
    # Die Sitzung ist gelöscht, nicht nur abgewiesen.
    with geraet_b.session_transaction() as sitzung:
        assert "user_id" not in sitzung


def test_einzeln_geloeschtes_konto_und_neues_ueber_die_kontenverwaltung(app_ctx):
    """Zwei Konten; das zweite verschwindet (z. B. per Datenbank oder einer
    eingespielten Sicherung), danach legt das erste über die Oberfläche ein
    neues an. SQLite vergibt die frei gewordene Nummer wieder."""
    _konto_anlegen(ALTES_KONTO, ALTES_PASSWORT)
    partner = _konto_anlegen("nacht-partner", "nacht-partner-passwort-3")
    partner_id = partner.id
    besitzer = _angemeldeter_client(app_ctx, ALTES_KONTO, ALTES_PASSWORT)
    partner_geraet = _angemeldeter_client(app_ctx, "nacht-partner",
                                          "nacht-partner-passwort-3")

    db.session.delete(partner)
    db.session.commit()
    res = besitzer.post("/api/konten", json={"username": NEUES_KONTO,
                                             "password": NEUES_PASSWORT})
    assert res.status_code == 201, res.get_data(as_text=True)
    neu = User.query.filter_by(username=NEUES_KONTO).one()
    assert neu.id == partner_id

    assert partner_geraet.get("/api/auth/me").status_code == 401
    # Der Besitzer bleibt angemeldet.
    assert besitzer.get("/api/auth/me").get_json()["username"] == ALTES_KONTO


def test_gegenprobe_normale_anmeldung_und_passwortwechsel(app_ctx):
    _konto_anlegen(ALTES_KONTO, ALTES_PASSWORT)
    client = _angemeldeter_client(app_ctx, ALTES_KONTO, ALTES_PASSWORT)

    res = client.get("/api/auth/me")
    assert res.status_code == 200
    assert res.get_json()["username"] == ALTES_KONTO

    res = client.put("/api/konto/passwort", json={
        "altes_passwort": ALTES_PASSWORT,
        "neues_passwort": "Nacht-Passwort-456"})
    assert res.status_code == 200, res.get_data(as_text=True)

    # Der Passwortwechsel beendet die eigene Sitzung nicht.
    res = client.get("/api/auth/me")
    assert res.status_code == 200
    assert res.get_json()["username"] == ALTES_KONTO
    assert client.get("/api/properties").status_code == 200


def test_sitzung_ohne_stempel_gilt_als_abgemeldet(app_ctx):
    """Eine Sitzung von vor dem Update trägt nur user_id und username. Sie
    endet einmal, danach meldet man sich neu an."""
    user = _konto_anlegen(ALTES_KONTO, ALTES_PASSWORT)
    client = app_ctx.app.test_client()
    with client.session_transaction() as sitzung:
        sitzung["user_id"] = user.id
        sitzung["username"] = user.username

    res = client.get("/api/auth/me")
    assert res.status_code == 401, res.get_json()
    with client.session_transaction() as sitzung:
        assert "user_id" not in sitzung
        assert "username" not in sitzung

    # Neu anmelden geht wie immer.
    res = client.post("/login", json={"username": ALTES_KONTO,
                                      "password": ALTES_PASSWORT})
    assert res.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_sitzung_mit_fremdem_benutzernamen_gilt_als_abgemeldet(app_ctx):
    """Stempel stimmt, Name nicht: auch das ist nicht die Sitzung dieses
    Kontos."""
    user = _konto_anlegen(ALTES_KONTO, ALTES_PASSWORT)
    client = _angemeldeter_client(app_ctx, ALTES_KONTO, ALTES_PASSWORT)
    with client.session_transaction() as sitzung:
        assert sitzung["user_id"] == user.id
        sitzung["username"] = "nacht-anderer-name"

    assert client.get("/api/auth/me").status_code == 401
