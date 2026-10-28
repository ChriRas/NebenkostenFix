"""Die Hülle unter macOS, ohne Mac geprüft (#44, Schritt 2).

Jede Stelle hat zwei Seiten: Unter ``win32`` bleibt alles wie bisher, unter
``darwin`` kommt der neue Zweig. Das System schalten die Tests über
``aktualisierung.betriebssystem()`` um, ``sys.platform`` bleibt unberührt.
Die Befunde dahinter stammen aus einer Probe mit pywebview 6.2.1 auf
macOS 26 (Phase 0): Cmd-Q übergeht den ``finally``-Block, die CSP sperrt die
Brücke, und der Dateidialog kennt keine Doppelendung.
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

import desktop
from nebenkostenfix import aktualisierung
from nebenkostenfix import auth
from nebenkostenfix import uploads
from nebenkostenfix import windows_ordner


@pytest.fixture
def system(monkeypatch):
    """Schaltet das Betriebssystem für die Hülle um."""
    def setzen(name):
        monkeypatch.setattr(aktualisierung, 'betriebssystem', lambda: name)
    return setzen


@pytest.fixture
def heim(tmp_path, monkeypatch):
    """Eigenes Heimverzeichnis, kein LOCALAPPDATA (wie auf dem Mac).
    ``Path.home()`` liest unter Windows USERPROFILE, sonst HOME."""
    monkeypatch.setenv('HOME', str(tmp_path / 'heim'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'heim'))
    monkeypatch.delenv('LOCALAPPDATA', raising=False)
    return tmp_path / 'heim'


@pytest.fixture
def aufrufe(monkeypatch):
    """subprocess.run in desktop.py, ohne etwas zu starten."""
    liste = []

    def run(befehl, **optionen):
        liste.append((befehl, optionen))
        return types.SimpleNamespace(returncode=aufrufe_rueckgabe['code'],
                                     stdout=aufrufe_rueckgabe['aus'], stderr='')
    aufrufe_rueckgabe = {'code': 0, 'aus': ''}
    monkeypatch.setattr(subprocess, 'run', run)
    return types.SimpleNamespace(liste=liste, rueckgabe=aufrufe_rueckgabe)


# --- Lokaler Ordner und Datenordner -------------------------------------------

def test_lokaler_ordner_unter_macos_in_application_support(heim, system):
    system('darwin')
    assert windows_ordner.lokaler_ordner() == heim / 'Library' / 'Application Support' / 'NebenkostenFix'
    assert windows_ordner.einstellungen_datei().parent == windows_ordner.lokaler_ordner()


def test_lokaler_ordner_unter_linux_wie_bisher(heim, system):
    system('linux')
    assert windows_ordner.lokaler_ordner() == heim / '.local' / 'share' / 'NebenkostenFix'


@pytest.mark.parametrize('name', ['win32', 'darwin'])
def test_localappdata_geht_vor(tmp_path, monkeypatch, system, name):
    """Unter Windows wie bisher; gesetzt hat es sonst nur ein Test oder eine Probe."""
    system(name)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'lokal'))
    assert windows_ordner.lokaler_ordner() == tmp_path / 'lokal' / 'NebenkostenFix'


def test_datenordner_unter_macos_nicht_in_dokumente(heim, system, monkeypatch):
    """Vorgabe des Maintainers: nicht in „Dokumente“, das iCloud mit
    „Schreibtisch & Dokumente“ synchronisiert. Ein Unterordner trennt die
    Daten von Einstellungen, Sperre und Protokoll."""
    system('darwin')
    monkeypatch.setattr(windows_ordner, 'dokumente_ordner', lambda: heim / 'Documents')
    (heim / 'Documents' / 'Nebenkostenabrechnung').mkdir(parents=True)
    (heim / 'Documents' / 'Nebenkostenabrechnung' / 'nebenkosten.db').write_bytes(b'')
    erwartet = heim / 'Library' / 'Application Support' / 'NebenkostenFix' / 'Daten'
    assert windows_ordner.vorgabe_datenordner() == erwartet
    assert desktop.datenordner_bestimmen() == erwartet


def test_datenordner_unter_windows_wie_bisher(tmp_path, system, monkeypatch):
    system('win32')
    monkeypatch.setattr(windows_ordner, 'dokumente_ordner', lambda: tmp_path / 'Dokumente')
    assert windows_ordner.vorgabe_datenordner() == tmp_path / 'Dokumente' / 'NebenkostenFix'
    alt = tmp_path / 'Dokumente' / 'Nebenkostenabrechnung'
    alt.mkdir(parents=True)
    (alt / 'nebenkosten.db').write_bytes(b'')
    assert windows_ordner.vorgabe_datenordner() == alt   # D-95


# --- Schreibprobe ------------------------------------------------------------

def _gesperrt(tmp_path) -> Path:
    datei = tmp_path / 'eine-datei'
    datei.write_text('x')
    return datei / 'darunter'


def test_schreibprobe_unter_macos_nennt_die_systemeinstellungen(tmp_path, system):
    system('darwin')
    meldung = windows_ordner.schreibprobe(_gesperrt(tmp_path))
    assert 'Datenschutz & Sicherheit' in meldung and 'Dateien und Ordner' in meldung
    assert 'Windows' not in meldung and 'Überwachte' not in meldung


def test_schreibprobe_unter_windows_wortgleich(tmp_path, system):
    system('win32')
    meldung = windows_ordner.schreibprobe(_gesperrt(tmp_path))
    assert meldung.endswith(
        'Häufigster Grund unter Windows ist der „Überwachte Ordnerzugriff“ '
        '(Windows-Sicherheit → Viren- & Bedrohungsschutz → Ransomware-Schutz). '
        'Lassen Sie dort unter „App durch überwachten Ordnerzugriff zulassen“ '
        'NebenkostenFix zu, oder wählen Sie in den Einstellungen '
        'einen anderen Datenordner.')


# --- Meldungen ---------------------------------------------------------------

def test_meldung_unter_macos_per_osascript_mit_dem_text_als_argument(system, aufrufe):
    """Der Text geht als Argument an ``on run argv``, nie ins Skript: Ein
    Anführungszeichen im Pfad kann nichts ausführen."""
    system('darwin')
    text = 'Ordner „/tmp/a\" & do shell script \"x“ fehlt.'
    assert desktop._meldung(text) is False
    befehl, optionen = aufrufe.liste[0]
    assert befehl[0] == '/usr/bin/osascript'
    assert befehl[-2:] == [desktop.TITEL, text]
    skript = ' '.join(befehl[1:-2])
    assert text not in skript and 'on run argv' in skript
    assert optionen.get('check') is False and not optionen.get('shell')


@pytest.mark.parametrize('ausgabe, code, antwort', [
    ('button returned:Ja\n', 0, True),
    ('button returned:Nein\n', 0, False),
    ('', 1, False),                      # osascript scheitert: wie „Nein“
])
def test_frage_unter_macos(system, aufrufe, ausgabe, code, antwort):
    system('darwin')
    aufrufe.rueckgabe.update(aus=ausgabe, code=code)
    assert desktop._meldung('Lokal speichern?', frage=True) is antwort
    skript = ' '.join(aufrufe.liste[0][0][1:-2])
    assert '"Nein"' in skript and '"Ja"' in skript


@pytest.mark.skipif(sys.platform == 'win32', reason='unter Windows kommt die MessageBox')
def test_meldung_unter_linux_nur_im_protokoll(system, aufrufe):
    system('linux')
    assert desktop._meldung('Text') is False
    assert aufrufe.liste == []


# --- Standardprogramm --------------------------------------------------------

def test_standardprogramm_unter_windows_mit_startfile(system, aufrufe, monkeypatch, tmp_path):
    system('win32')
    gestartet = []
    monkeypatch.setattr(desktop.os, 'startfile', gestartet.append, raising=False)
    desktop.standardprogramm_oeffnen(tmp_path)
    assert gestartet == [tmp_path] and aufrufe.liste == []


def test_standardprogramm_unter_macos_mit_open(system, aufrufe, tmp_path):
    system('darwin')
    desktop.standardprogramm_oeffnen(tmp_path / '-a Rechner')
    befehl, optionen = aufrufe.liste[0]
    assert befehl == ['/usr/bin/open', '--', str(tmp_path / '-a Rechner')]
    assert optionen.get('check') is False and not optionen.get('shell')


def test_standardprogramm_unter_linux_tut_nichts(system, aufrufe, tmp_path):
    system('linux')
    desktop.standardprogramm_oeffnen(tmp_path)
    assert aufrufe.liste == []


def test_pdf_oeffnet_unter_macos_im_standardprogramm(system, aufrufe, monkeypatch, tmp_path):
    """Bisher legte die App das PDF nur ab und öffnete nichts."""
    system('darwin')
    monkeypatch.setattr(desktop.tempfile, 'gettempdir', lambda: str(tmp_path))
    inhalt = base64.b64encode(b'%PDF-1.4').decode()
    bruecke = desktop.Bruecke()
    pdf = bruecke.oeffnen('rechnung.pdf', inhalt)
    weiter = bruecke.oeffnen('rechnung.pdf', inhalt, 3)
    assert [b[0][-1] for b in aufrufe.liste] == [pdf, weiter]
    assert weiter.endswith('.html')


# --- CSP der Brücke ----------------------------------------------------------

def _antwort(koepfe):
    def anwendung(umgebung, antworten):
        antworten('200 OK', list(koepfe))
        return [b'innen']
    return anwendung


def _koepfe(anwendung):
    schutz = desktop.HuellenSchutz(anwendung, 'geheim-123')
    ergebnis = {}
    umgebung = {'PATH_INFO': '/', 'QUERY_STRING': '',
                'HTTP_COOKIE': f'{desktop.COOKIE}=geheim-123'}
    b''.join(schutz(umgebung, lambda status, koepfe, *rest: ergebnis.update(koepfe)))
    return ergebnis


def test_csp_unter_macos_erlaubt_die_bruecke(system):
    """pywebview baut ``window.pywebview.api`` mit ``new Function`` und
    ``evaluate_js`` mit ``eval``; WKWebView sperrt beides ohne
    ``'unsafe-eval'``. Ohne Brücke scheitern Export, Ordnerwahl, Umzug,
    Drucken und „Über“."""
    system('darwin')
    csp = _koepfe(_antwort([('Content-Security-Policy', auth.CSP)]))['Content-Security-Policy']
    assert "script-src 'self' 'unsafe-inline' 'unsafe-eval';" in csp
    assert csp.replace(" 'unsafe-eval'", '') == auth.CSP


@pytest.mark.parametrize('streng', [uploads.CSP_BILD, uploads.CSP_PDF, uploads.CSP_DOWNLOAD])
def test_csp_unter_macos_laesst_strengere_regeln_stehen(system, streng):
    """Die Dateiauslieferung setzt ihre eigene CSP (NK-129); die bleibt."""
    system('darwin')
    assert _koepfe(_antwort([('Content-Security-Policy', streng)])) == {
        'Content-Security-Policy': streng}


@pytest.mark.parametrize('name', ['win32', 'linux'])
def test_csp_sonst_unveraendert(system, name):
    system(name)
    assert _koepfe(_antwort([('Content-Security-Policy', auth.CSP), ('X-A', '1')])) == {
        'Content-Security-Policy': auth.CSP, 'X-A': '1'}


# --- Dateifilter -------------------------------------------------------------

def _paketfilter(monkeypatch, tmp_path):
    from nebenkostenfix import umzug
    gesehen = []
    paket = tmp_path / 'umzug.nkfix'
    paket.write_bytes(b'')

    class Fenster:
        def create_file_dialog(self, art, file_types=(), **_):
            gesehen.extend(file_types)
            return (str(paket),)

    monkeypatch.setitem(sys.modules, 'webview', types.SimpleNamespace(OPEN_DIALOG=10))
    monkeypatch.setattr(umzug, '_freigegeben', set())
    bruecke = desktop.Bruecke()
    bruecke._fenster = Fenster()
    assert bruecke.paket_waehlen() == os.path.realpath(paket)
    return gesehen


def test_paketfilter_unter_macos_ohne_doppelendung(system, monkeypatch, tmp_path):
    """Der Dialog von macOS vergleicht nur die letzte Endung: ``*.tar.gz``
    graute ``.tar.gz`` aus. Ob es ein Paket ist, prüft der Server."""
    system('darwin')
    gueltig = r'^([\w ]+)\((\*(?:\.(?:\w+|\*))*(?:;\*(?:\.(?:\w+|\*))*)*)\)$'
    filter_ = _paketfilter(monkeypatch, tmp_path)
    assert filter_[0] == 'NebenkostenFix Paket (*.nkfix;*.nkbak;*.gz)'
    assert all(re.search(gueltig, f) for f in filter_)


def test_paketfilter_unter_windows_wortgleich(system, monkeypatch, tmp_path):
    system('win32')
    assert _paketfilter(monkeypatch, tmp_path) == [
        'NebenkostenFix Paket (*.nkfix;*.nkbak;*.tar.gz)', 'Alle Dateien (*.*)']


# --- Fenster: Menü und Cmd-Q -------------------------------------------------

class _Ereignis(list):
    def __iadd__(self, funktion):
        self.append(funktion)
        return self


class _Fenster:
    def __init__(self):
        self.events = types.SimpleNamespace(closing=_Ereignis())
        self.skripte = []

    def load_url(self, adresse):
        pass

    def load_html(self, text):
        pass

    def evaluate_js(self, skript):
        self.skripte.append(skript)

    def destroy(self):
        pass


def _fenster_starten(monkeypatch, tmp_path, cmd_q):
    """fenster_starten mit einem nachgebauten pywebview. ``cmd_q``: Beim
    Beenden über das App-Menü kommt nur ``closing``, danach endet der
    Prozess ohne Rückkehr aus ``webview.start`` (Probe auf macOS 26)."""
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'lokal'))
    fenster = _Fenster()
    ablauf = {'angehalten': []}

    def start(funktion, menu=(), **optionen):
        ablauf['menue'] = menu
        ablauf['optionen'] = optionen
        funktion()
        for beim_schliessen in fenster.events.closing:
            beim_schliessen()
        if cmd_q:
            # AppKit beendet den Prozess in C; der finally-Block kommt nicht mehr dran.
            ablauf['beim_ende'] = list(ablauf['angehalten'])
            ablauf['instanz_beim_ende'] = (
                tmp_path / 'lokal' / 'NebenkostenFix' / 'instanz.json').exists()
            raise SystemExit(0)

    class Eintrag:
        def __init__(self, titel, inhalt=None):
            self.titel, self.inhalt = titel, inhalt

    webview = types.ModuleType('webview')
    webview.create_window = lambda *a, **k: fenster
    webview.start = start
    menue = types.ModuleType('webview.menu')
    menue.Menu = menue.MenuAction = Eintrag
    menue.MenuSeparator = lambda: Eintrag('—')
    monkeypatch.setitem(sys.modules, 'webview', webview)
    monkeypatch.setitem(sys.modules, 'webview.menu', menue)

    server = types.SimpleNamespace(effective_port=1234)
    monkeypatch.setattr(desktop, 'anwendung_laden', lambda ordner: types.SimpleNamespace(app=None))
    monkeypatch.setattr(desktop, 'server_starten', lambda wsgi: (server, None))
    monkeypatch.setattr(desktop, 'anhalten',
                        lambda s, modul: ablauf['angehalten'].append(s))
    try:
        desktop.fenster_starten(tmp_path / 'daten')
    except SystemExit:
        pass
    ablauf['server'] = server
    ablauf['fenster'] = fenster
    return ablauf


def _menue(ablauf):
    return {m.titel: [e.titel for e in m.inhalt] for m in ablauf['menue']}


def test_cmd_q_haelt_den_server_unter_macos_an(system, monkeypatch, tmp_path):
    """Ohne den Hook blieb die WAL-Datei liegen (1,1 MB in der Probe)."""
    system('darwin')
    ablauf = _fenster_starten(monkeypatch, tmp_path, cmd_q=True)
    assert ablauf['beim_ende'] == [ablauf['server']]


def test_cmd_q_gibt_unter_macos_die_instanz_frei(system, monkeypatch, tmp_path):
    """Sonst bliebe instanz.json mit Port und abgelaufenem Token liegen."""
    system('darwin')
    ablauf = _fenster_starten(monkeypatch, tmp_path, cmd_q=True)
    assert ablauf['instanz_beim_ende'] is False


def test_fenster_schliessen_haelt_unter_macos_nur_einmal_an(system, monkeypatch, tmp_path):
    system('darwin')
    ablauf = _fenster_starten(monkeypatch, tmp_path, cmd_q=False)
    assert ablauf['angehalten'] == [ablauf['server']]


def test_unter_windows_haelt_der_finally_block_an(system, monkeypatch, tmp_path):
    system('win32')
    ablauf = _fenster_starten(monkeypatch, tmp_path, cmd_q=False)
    assert list(ablauf['fenster'].events.closing) == []
    assert ablauf['angehalten'] == [ablauf['server']]


def test_menue_unter_macos_ohne_zweites_beenden(system, monkeypatch, tmp_path):
    """Das App-Menü von macOS hat „Beenden“ mit Cmd-Q schon."""
    system('darwin')
    assert _menue(_fenster_starten(monkeypatch, tmp_path, cmd_q=False))['Datei'] == [
        'Drucken', '—', 'Mit einem Server verbinden …']


def test_menue_unter_windows_wortgleich(system, monkeypatch, tmp_path):
    system('win32')
    assert _menue(_fenster_starten(monkeypatch, tmp_path, cmd_q=False)) == {
        'Datei': ['Drucken', '—', 'Mit einem Server verbinden …', '—', 'Beenden'],
        'Hilfe': ['Passwort vergessen …', 'Datenordner anzeigen', '—',
                  'Über NebenkostenFix']}


def test_datenordner_anzeigen_nimmt_das_standardprogramm(system, monkeypatch, tmp_path):
    system('darwin')
    geoeffnet = []
    monkeypatch.setattr(desktop, 'standardprogramm_oeffnen', geoeffnet.append)
    ablauf = _fenster_starten(monkeypatch, tmp_path, cmd_q=False)
    hilfe = next(m for m in ablauf['menue'] if m.titel == 'Hilfe')
    next(e for e in hilfe.inhalt if e.titel == 'Datenordner anzeigen').inhalt()
    assert geoeffnet == [tmp_path / 'daten']


def test_webview_speicher_unter_macos_ohne_eigenen_ordner(system, monkeypatch, tmp_path):
    """WKWebView ignoriert ``storage_path`` (pywebview#1714) und legt die
    Daten nach der Bundle-ID ab; ein Ordner „WebView2“ bliebe leer."""
    system('darwin')
    optionen = _fenster_starten(monkeypatch, tmp_path, cmd_q=False)['optionen']
    assert 'storage_path' not in optionen and optionen['private_mode'] is False


def test_webview_speicher_unter_windows_wie_bisher(system, monkeypatch, tmp_path):
    system('win32')
    optionen = _fenster_starten(monkeypatch, tmp_path, cmd_q=False)['optionen']
    assert optionen['storage_path'] == str(tmp_path / 'lokal' / 'NebenkostenFix' / 'WebView2')
    assert optionen['private_mode'] is False
