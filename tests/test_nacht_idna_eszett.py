"""Servermodus: eine Serveradresse mit „ß“ darf nie zu einer „ss“-Domain werden.

Pythons ``str.encode('idna')`` ist IDNA 2003 und bildet ß auf „ss“ ab, ς auf σ
und lässt ZWNJ/ZWJ weg. WebView2/Chromium und die DENIC (.de) behandeln diese
Zeichen nach IDNA 2008/UTS 46 als eigene Zeichen: straße.example ist dort
xn--strae-oqa.example. ``strasse.example`` ist eine andere, frei registrierbare
Domain. Würde sie statt der eingetragenen Adresse geprüft, gespeichert und
geladen, gingen Anmeldung und Mieterdaten an einen fremden Host. Ohne neue
Abhängigkeit lehnt die App solche Adressen deshalb ab; die Punycode-Form geht
weiter durch. Alle Adressen sind fiktiv (.example).
"""

import urllib.request

import pytest

import desktop
from nebenkostenfix import windows_ordner

ABWEICHEND = [
    'straße.example',
    'https://Straße.example:8443',
    'faß.example',
    'STRAẞE.example',        # großes ẞ (U+1E9E)
    'http://λόγος.example',  # Schluss-Sigma ς (U+03C2)
]
UNSICHTBAR = [
    'nk‍server.example',  # ZWJ mitten im Label
    'nk‌server.example',  # ZWNJ mitten im Label
]
FREMDE_SS_DOMAINS = {'https://strasse.example', 'https://strasse.example:8443',
                     'https://fass.example'}


@pytest.fixture
def keine_verbindung(monkeypatch):
    """Jeder Versuch, eine Verbindung aufzubauen, lässt den Test scheitern."""
    def oeffnen(self, adresse, *args, **kwargs):
        pytest.fail(f'Verbindung aufgebaut: {getattr(adresse, "full_url", adresse)}')
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', oeffnen)


@pytest.mark.parametrize('eingabe', ABWEICHEND)
def test_abweichende_zeichen_werden_abgelehnt(eingabe):
    assert desktop.adresse_normieren(eingabe) is None


def test_nie_eine_fremde_ss_domain():
    ergebnisse = {desktop.adresse_normieren(eingabe) for eingabe in ABWEICHEND + UNSICHTBAR}
    assert not ergebnisse & FREMDE_SS_DOMAINS


def test_server_pruefen_baut_keine_verbindung_auf(keine_verbindung):
    ok, meldung, endadresse = desktop.server_pruefen('straße.example')
    assert (ok, endadresse) == (False, None)
    assert meldung == desktop.NUR_PUNYCODE
    assert 'xn--' in meldung


@pytest.mark.parametrize('eingabe', UNSICHTBAR)
def test_unsichtbare_verbinder_abgelehnt_mit_hinweis(eingabe, keine_verbindung):
    assert desktop.adresse_normieren(eingabe) is None
    assert desktop.server_pruefen(eingabe) == (False, desktop.NUR_PUNYCODE, None)


def test_pfad_bleibt_der_grund_auch_mit_eszett(keine_verbindung):
    """Der eigene Hinweis kommt nur, wenn ß & Co. der einzige Grund sind."""
    assert desktop.server_pruefen('https://straße.example') == (False, desktop.NUR_PUNYCODE, None)
    assert desktop.server_pruefen('https://straße.example/nk') == (False, desktop.OHNE_PFAD, None)
    assert desktop.server_pruefen('https://nk.example/straße') == (False, desktop.OHNE_PFAD, None)


def test_server_verbinden_speichert_keine_ss_domain(tmp_path, monkeypatch, keine_verbindung):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'lokal'))

    class Fenster:
        def get_current_url(self):
            return 'http://127.0.0.1:50123/#/einstellungen'

    bruecke = desktop.Bruecke()
    bruecke._fenster = Fenster()
    bruecke._basis = 'http://127.0.0.1:50123'
    bruecke._neustart = lambda: pytest.fail('Neustart trotz abgelehnter Adresse')

    for eingabe in ABWEICHEND:
        assert bruecke.server_verbinden(eingabe) == {'ok': False, 'meldung': desktop.NUR_PUNYCODE}
    assert windows_ordner.einstellungen_lesen()['server'] is None


def test_punycode_und_andere_umlaute_gehen_weiter_durch():
    """Gegenprobe: nur ß & Co. fallen heraus, der Weg über Punycode bleibt offen."""
    assert desktop.adresse_normieren('straße.example') is None
    for eingabe, erwartet in (
            ('xn--strae-oqa.example', 'https://xn--strae-oqa.example'),
            ('https://XN--STRAE-OQA.example:8443', 'https://xn--strae-oqa.example:8443'),
            ('bücher.example', 'https://xn--bcher-kva.example'),
            ('strasse.example', 'https://strasse.example'),
            ('http://ΛΌΓΟΣ.example', desktop.adresse_normieren('http://λόγοσ.example')),
    ):
        assert desktop.adresse_normieren(eingabe) == erwartet, eingabe
