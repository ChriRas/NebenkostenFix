"""Anmeldung: die Laufzeit verriet, welche Konten es gibt.

``/login`` sagte im Kommentar: „Immer beide Pruefungen durchlaufen, damit ein
falscher Benutzername nicht schneller antwortet als ein falsches Passwort.“
Der Code dazu war aber

    ok = user is not None and user.is_active and user.check_password(password)

und ``and`` bricht ab: Für einen Namen, den es nicht gibt (oder ein
stillgelegtes Konto), wird nie ein Passwort-Hash gerechnet. scrypt kostet
spürbar Zeit, die Antwort für „gibt es nicht“ kommt also messbar schneller
als die für „Passwort falsch“. Wer im LAN misst, erfährt so die Kontennamen
-- genau das, was ``anmeldeschutz`` vermeiden will („Gezaehlt wird auch fuer
Konten, die es nicht gibt -- sonst verriete die Sperre, welche Namen
existieren“).

Belegt wird es ohne Stoppuhr: gezählt wird, wie oft werkzeug intern einen
Passwort-Hash rechnet. Bei einem bekannten Konto mit falschem Passwort ist
das einmal, bei einem unbekannten Namen, einem stillgelegten Konto und einem
leeren Namen muss es ebenso oft sein, mit demselben Verfahren.

Der Blindhash für die Fälle ohne aktives Konto entsteht einmal pro Prozess.
Damit sein Erzeugen nicht mitzählt, läuft vor jeder Zählung ein Versuch zum
Aufwärmen. Zwischen den Versuchen wird der Anmeldeschutz zurückgesetzt,
damit keine Sperre greift.

Alle Daten fiktiv.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import werkzeug.security

from nebenkostenfix import anmeldeschutz, auth
from tests.conftest import TEST_USER

AKTIV = "nacht-aktiv"
AKTIV_PASSWORT = "Nacht-Passwort-123"
STILL = "nacht-still"
STILL_PASSWORT = "Nacht-Passwort-456"
UNBEKANNT = "nacht-gibtsnicht"
FALSCH = "falsches-passwort-123"
FEHLTEXT = "Benutzername oder Passwort stimmt nicht."


@pytest.fixture
def hash_zaehler(monkeypatch):
    aufrufe = []
    echt = werkzeug.security._hash_internal

    def gezaehlt(method, salt, password):
        aufrufe.append(method)
        return echt(method, salt, password)

    monkeypatch.setattr(werkzeug.security, "_hash_internal", gezaehlt)
    return aufrufe


@pytest.fixture(autouse=True)
def ohne_wartezeit(monkeypatch):
    monkeypatch.setattr(anmeldeschutz, "wartezeit", lambda anzahl: 0)


@pytest.fixture
def konten(app_ctx):
    from nebenkostenfix.models import User, db

    aktiv = User(username=AKTIV)
    aktiv.set_password(AKTIV_PASSWORT)
    still = User(username=STILL, is_active=False)
    still.set_password(STILL_PASSWORT)
    db.session.add_all([aktiv, still])
    db.session.commit()
    return app_ctx


def _verfahren_von_set_password(name):
    from nebenkostenfix.models import User

    return User.query.filter_by(username=name).one().password_hash.split("$", 1)[0]


def _schutz_zuruecksetzen():
    anmeldeschutz.zuruecksetzen(auth._anmeldeschutz_ordner())
    anmeldeschutz.zuruecksetzen(None)


def _anmelden(app_ctx, name, passwort):
    client = app_ctx.app.test_client()
    return client.post("/login", json={"username": name, "password": passwort})


def _gezaehlt_anmelden(app_ctx, zaehler, name, passwort):
    """Eine Anmeldung nach einem Aufwärm-Versuch; liefert Antwort und Verfahren."""
    _anmelden(app_ctx, "nacht-aufwaermen", "Aufwaerm-Passwort-789")
    _schutz_zuruecksetzen()
    zaehler.clear()
    antwort = _anmelden(app_ctx, name, passwort)
    verfahren = list(zaehler)
    _schutz_zuruecksetzen()
    return antwort, verfahren


def _ist_fehlschlag(antwort):
    assert antwort.status_code == 401
    assert antwort.get_json() == {"error": FEHLTEXT}


def test_unbekannter_name_rechnet_ebenso_einen_hash_wie_falsches_passwort(
        auth_client, app_ctx, hash_zaehler):
    falsch, bei_bekanntem_konto = _gezaehlt_anmelden(
        app_ctx, hash_zaehler, TEST_USER, FALSCH)
    assert falsch.status_code == 401
    assert len(bei_bekanntem_konto) >= 1  # scrypt wurde gerechnet

    unbekannt, bei_unbekanntem = _gezaehlt_anmelden(
        app_ctx, hash_zaehler, "nacht-gibt-es-nicht", FALSCH)
    assert unbekannt.status_code == 401
    assert len(bei_unbekanntem) == len(bei_bekanntem_konto), (
        "Für einen unbekannten Benutzernamen rechnet /login keinen Passwort-"
        "Hash und antwortet dadurch schneller -- die Laufzeit verrät, welche "
        "Konten es gibt.")


def test_aktives_konto_falsches_passwort_rechnet_genau_einen_hash(
        konten, hash_zaehler):
    antwort, verfahren = _gezaehlt_anmelden(konten, hash_zaehler, AKTIV, FALSCH)
    _ist_fehlschlag(antwort)
    assert verfahren == [_verfahren_von_set_password(AKTIV)]


def test_unbekannter_name_rechnet_genau_einen_hash_mit_demselben_verfahren(
        konten, hash_zaehler):
    erwartet = [_verfahren_von_set_password(AKTIV)]
    # Mehrmals hintereinander: der Blindhash entsteht nur einmal pro Prozess,
    # jede weitere Anmeldung rechnet nur noch die eine Prüfung.
    for passwort in (FALSCH, AKTIV_PASSWORT, "noch-ein-passwort-1"):
        antwort, verfahren = _gezaehlt_anmelden(
            konten, hash_zaehler, UNBEKANNT, passwort)
        _ist_fehlschlag(antwort)
        assert verfahren == erwartet, (
            "Ein unbekannter Name muss genau einen Hash mit demselben "
            "Verfahren wie User.set_password rechnen.")


@pytest.mark.parametrize("passwort", [FALSCH, STILL_PASSWORT])
def test_stillgelegtes_konto_rechnet_genau_einen_hash(
        konten, hash_zaehler, passwort):
    antwort, verfahren = _gezaehlt_anmelden(konten, hash_zaehler, STILL, passwort)
    _ist_fehlschlag(antwort)
    assert verfahren == [_verfahren_von_set_password(STILL)]


@pytest.mark.parametrize("name", ["", "   "])
def test_leerer_name_rechnet_genau_einen_hash(konten, hash_zaehler, name):
    antwort, verfahren = _gezaehlt_anmelden(konten, hash_zaehler, name, FALSCH)
    _ist_fehlschlag(antwort)
    assert verfahren == [_verfahren_von_set_password(AKTIV)]


def test_gegenprobe_richtiges_passwort_meldet_an(konten, hash_zaehler):
    antwort, verfahren = _gezaehlt_anmelden(
        konten, hash_zaehler, AKTIV, AKTIV_PASSWORT)
    assert antwort.status_code == 200
    assert antwort.get_json() == {"username": AKTIV}
    assert len(verfahren) == 1


@pytest.mark.parametrize("name, passwort", [
    (UNBEKANNT, ""),
    (UNBEKANNT, AKTIV_PASSWORT),
    (UNBEKANNT, STILL_PASSWORT),
    ("", ""),
    (STILL, ""),
    (STILL, STILL_PASSWORT),
])
def test_ohne_aktives_konto_wird_nie_angemeldet(konten, name, passwort):
    client = konten.app.test_client()
    antwort = client.post("/login", json={"username": name, "password": passwort})
    _ist_fehlschlag(antwort)
    _schutz_zuruecksetzen()
    # Auch die Sitzung trägt danach kein Konto.
    assert client.get("/api/auth/me").status_code == 401


def test_sperre_nach_fuenf_fehlversuchen_mit_unbekanntem_namen(konten):
    client = konten.app.test_client()
    for _ in range(anmeldeschutz.GRENZE_KONTO):
        antwort = client.post(
            "/login", json={"username": UNBEKANNT, "password": FALSCH})
        _ist_fehlschlag(antwort)
    gesperrt = client.post(
        "/login", json={"username": UNBEKANNT, "password": FALSCH})
    assert gesperrt.status_code == 429
    assert gesperrt.get_json()["code"] == "anmeldung_gesperrt"
    assert int(gesperrt.headers["Retry-After"]) > 0
    # Auch das richtige Passwort eines anderen Kontos ändert an der Sperre
    # für diesen Namen nichts.
    nochmal = client.post(
        "/login", json={"username": UNBEKANNT, "password": AKTIV_PASSWORT})
    assert nochmal.status_code == 429


def test_blindhash_steht_nicht_im_code():
    quelle = Path(auth.__file__).read_text(encoding="utf-8")
    assert not re.search(r"(scrypt|pbkdf2):[0-9:a-z]*\$", quelle), (
        "Der Blindhash darf nicht als Literal in auth.py stehen.")
