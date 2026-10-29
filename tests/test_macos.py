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
        self.sichtbar = True

    def load_url(self, adresse):
        pass

    def load_html(self, text):
        pass

    def evaluate_js(self, skript):
        self.skripte.append(skript)

    def destroy(self):
        pass

    def hide(self):
        self.sichtbar = False

    def show(self):
        self.sichtbar = True

    def restore(self):
        pass


def _fenster_starten(monkeypatch, tmp_path, *schritte):
    """fenster_starten mit einem nachgebauten pywebview. Die Schritte:

    ``zu``     roter Knopf oder Cmd-W: pywebview ruft ``closing`` auf,
    ``dock``   Klick aufs Dock-Symbol ohne sichtbares Fenster,
    ``cmd_q``  Beenden: der Delegate erfährt es, dann kommt ``closing``,
               danach endet der Prozess ohne Rückkehr aus ``webview.start``
               (Probe auf macOS 26),
    ``beenden`` wie ``cmd_q``, aber ``webview.start`` kehrt zurück.
    Nach den Schritten kehrt ``webview.start`` zurück (wie unter Windows).
    """
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'lokal'))
    fenster = _Fenster()
    ablauf = {'angehalten': []}
    monkeypatch.setattr(desktop, '_macos_anpassen', lambda mac: ablauf.__setitem__('mac', mac))

    def start(funktion, menu=(), **optionen):
        ablauf['menue'] = menu
        ablauf['optionen'] = optionen
        funktion()
        for schritt in schritte:
            if schritt == 'zu':
                ablauf['zu'] = [hook() for hook in fenster.events.closing]
                ablauf['nach_zu'] = list(ablauf['angehalten'])
            elif schritt == 'dock':
                ablauf['mac'].wieder_oeffnen(sichtbar=False)
            elif schritt in ('cmd_q', 'beenden'):
                if 'mac' in ablauf:
                    ablauf['mac'].beenden_angefordert()
                for hook in fenster.events.closing:
                    hook()
                if schritt == 'cmd_q':
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
    ablauf = _fenster_starten(monkeypatch, tmp_path, 'cmd_q')
    assert ablauf['beim_ende'] == [ablauf['server']]


def test_cmd_q_gibt_unter_macos_die_instanz_frei(system, monkeypatch, tmp_path):
    """Sonst bliebe instanz.json mit Port und abgelaufenem Token liegen."""
    system('darwin')
    ablauf = _fenster_starten(monkeypatch, tmp_path, 'cmd_q')
    assert ablauf['instanz_beim_ende'] is False


def test_beenden_haelt_unter_macos_nur_einmal_an(system, monkeypatch, tmp_path):
    system('darwin')
    ablauf = _fenster_starten(monkeypatch, tmp_path, 'beenden')
    assert ablauf['angehalten'] == [ablauf['server']]


def test_roter_knopf_versteckt_unter_macos_nur_das_fenster(system, monkeypatch, tmp_path):
    """Wie bei Mac-Apps üblich: Fenster zu heißt nicht Programm zu. Die App
    bleibt mit Punkt im Dock aktiv, der Server läuft weiter (Nutzer, 29.10.2026)."""
    system('darwin')
    ablauf = _fenster_starten(monkeypatch, tmp_path, 'zu')
    assert ablauf['zu'] == [False]            # pywebview bricht das Schließen ab
    assert ablauf['fenster'].sichtbar is False
    assert ablauf['nach_zu'] == []            # nichts angehalten


def test_dock_holt_das_fenster_zurueck(system, monkeypatch, tmp_path):
    system('darwin')
    ablauf = _fenster_starten(monkeypatch, tmp_path, 'zu', 'dock')
    assert ablauf['fenster'].sichtbar is True


def test_nach_dem_roten_knopf_beendet_cmd_q_wie_bisher(system, monkeypatch, tmp_path):
    system('darwin')
    ablauf = _fenster_starten(monkeypatch, tmp_path, 'zu', 'dock', 'zu', 'cmd_q')
    assert ablauf['beim_ende'] == [ablauf['server']]
    assert ablauf['instanz_beim_ende'] is False


def test_unter_windows_haelt_der_finally_block_an(system, monkeypatch, tmp_path):
    system('win32')
    ablauf = _fenster_starten(monkeypatch, tmp_path, 'zu')
    assert list(ablauf['fenster'].events.closing) == []
    assert 'mac' not in ablauf
    assert ablauf['angehalten'] == [ablauf['server']]


def test_menue_unter_macos_heisst_ablage_ohne_zweites_beenden(system, monkeypatch, tmp_path):
    """„Ablage“ ist Apples deutscher Name für das Menü „File“; „Beenden“ mit
    Cmd-Q steht schon im App-Menü."""
    system('darwin')
    menue = _menue(_fenster_starten(monkeypatch, tmp_path))
    assert list(menue) == ['Ablage', 'Hilfe']
    assert menue['Ablage'] == ['Fenster zeigen', '—', 'Drucken', '—',
                               'Mit einem Server verbinden …']


def _aktion(ablauf, menue, titel):
    eintrag = next(m for m in ablauf['menue'] if m.titel == menue)
    return next(e for e in eintrag.inhalt if e.titel == titel).inhalt


@pytest.mark.parametrize('menue, titel', [
    ('Ablage', 'Fenster zeigen'), ('Ablage', 'Drucken'), ('Ablage', 'Mit einem Server verbinden …'),
    ('Hilfe', 'Passwort vergessen …'), ('Hilfe', f'Über {desktop.TITEL}'),
])
def test_menue_holt_das_versteckte_fenster_zurueck(system, monkeypatch, tmp_path, menue, titel):
    """Nach dem roten Knopf bleibt die Menüleiste; eine Aktion, die im
    Fenster wirkt, darf dann nicht unsichtbar ins Leere laufen (Review C, R1/R2).
    Cmd-Tab zur App schickt kein Ereignis wie der Klick aufs Dock-Symbol."""
    system('darwin')
    ablauf = _fenster_starten(monkeypatch, tmp_path, 'zu')
    assert ablauf['fenster'].sichtbar is False
    _aktion(ablauf, menue, titel)()
    assert ablauf['fenster'].sichtbar is True


def test_menue_unter_windows_wortgleich(system, monkeypatch, tmp_path):
    system('win32')
    assert _menue(_fenster_starten(monkeypatch, tmp_path)) == {
        'Datei': ['Drucken', '—', 'Mit einem Server verbinden …', '—', 'Beenden'],
        'Hilfe': ['Passwort vergessen …', 'Datenordner anzeigen', '—',
                  'Über NebenkostenFix']}


def test_standardmenues_unter_macos_auf_deutsch(system, monkeypatch, tmp_path):
    """pywebview baut App-, Bearbeiten- und Ansicht-Menü sonst englisch."""
    system('darwin')
    texte = _fenster_starten(monkeypatch, tmp_path)['optionen']['localization']
    assert texte == desktop.MENUE_TEXTE_MACOS
    assert {texte['cocoa.menu.edit'], texte['cocoa.menu.view'], texte['cocoa.menu.paste']} == {
        'Bearbeiten', 'Darstellung', 'Einsetzen'}
    # Titel des Sichern-Dialogs (Datenauszug, Umzugspaket), sonst „Save file“
    assert texte['global.saveFile'] == 'Sichern' and texte['global.cancel'] == 'Abbrechen'


def test_standardmenues_unter_windows_unveraendert(system, monkeypatch, tmp_path):
    system('win32')
    assert 'localization' not in _fenster_starten(monkeypatch, tmp_path)['optionen']


def test_datenordner_anzeigen_nimmt_das_standardprogramm(system, monkeypatch, tmp_path):
    system('darwin')
    geoeffnet = []
    monkeypatch.setattr(desktop, 'standardprogramm_oeffnen', geoeffnet.append)
    ablauf = _fenster_starten(monkeypatch, tmp_path)
    hilfe = next(m for m in ablauf['menue'] if m.titel == 'Hilfe')
    next(e for e in hilfe.inhalt if e.titel == 'Datenordner anzeigen').inhalt()
    assert geoeffnet == [tmp_path / 'daten']


def test_webview_speicher_unter_macos_ohne_eigenen_ordner(system, monkeypatch, tmp_path):
    """WKWebView ignoriert ``storage_path`` (pywebview#1714) und legt die
    Daten nach der Bundle-ID ab; ein Ordner „WebView2“ bliebe leer."""
    system('darwin')
    optionen = _fenster_starten(monkeypatch, tmp_path)['optionen']
    assert 'storage_path' not in optionen and optionen['private_mode'] is False


def test_webview_speicher_unter_windows_wie_bisher(system, monkeypatch, tmp_path):
    system('win32')
    optionen = _fenster_starten(monkeypatch, tmp_path)['optionen']
    assert optionen['storage_path'] == str(tmp_path / 'lokal' / 'NebenkostenFix' / 'WebView2')
    assert optionen['private_mode'] is False


# --- Menüleiste und Fenster ohne AppKit --------------------------------------

class _Eintrag:
    def __init__(self, titel, aktion=None, untermenue=None):
        self._titel, self._aktion, self._untermenue = titel, aktion, untermenue

    def title(self):
        return self._titel

    def setTitle_(self, titel):
        self._titel = titel

    def action(self):
        return self._aktion

    def submenu(self):
        return self._untermenue


class _Menue:
    """Die Methoden von NSMenu, die ``_menueleiste_ordnen`` braucht."""
    def __init__(self, eintraege):
        self.eintraege = list(eintraege)

    def itemArray(self):
        return list(self.eintraege)

    def itemAtIndex_(self, index):
        return self.eintraege[index]

    def indexOfItemWithTitle_(self, titel):
        return next((i for i, e in enumerate(self.eintraege) if e.title() == titel), -1)

    def removeItemAtIndex_(self, index):
        del self.eintraege[index]

    def insertItem_atIndex_(self, eintrag, index):
        self.eintraege.insert(index, eintrag)


def _leiste_wie_pywebview(selektor=str):
    """So baut pywebview 6.2.1 die Leiste mit den deutschen Texten: Bearbeiten
    und Darstellung an Index 1, eigene Menüs hinten, der App-Name hinten an.
    Menüs ohne eigenen Titel heißen dort „NSMenuItem“. ``action()`` liefert
    mit PyObjC 12 einen ``str``, ältere Fassungen ``bytes``."""
    def aktion(name):
        return name.encode('ascii') if selektor is bytes else name
    app = _Menue([_Eintrag('Über NebenkostenFix', aktion('orderFrontStandardAboutPanel:')),
                  _Eintrag('Dienste'),
                  _Eintrag('ausblenden NebenkostenFix', aktion('hide:')),
                  _Eintrag('Andere ausblenden', aktion('hideOtherApplications:')),
                  _Eintrag('Alle einblenden', aktion('unhideAllApplications:')),
                  _Eintrag('beenden NebenkostenFix', aktion('terminate:'))])
    return _Menue([_Eintrag('NSMenuItem', untermenue=app), _Eintrag('NSMenuItem'),
                   _Eintrag('NSMenuItem'), _Eintrag('Ablage'), _Eintrag('Hilfe')])


def test_menueleiste_in_der_reihenfolge_von_macos():
    leiste = _leiste_wie_pywebview()
    desktop._menueleiste_ordnen(leiste)
    assert [e.title() for e in leiste.itemArray()] == [
        'NSMenuItem', 'Ablage', 'NSMenuItem', 'NSMenuItem', 'Hilfe']
    desktop._menueleiste_ordnen(leiste)   # pywebview baut die Leiste neu: bleibt so
    assert [e.title() for e in leiste.itemArray()][1] == 'Ablage'


@pytest.mark.parametrize('selektor', [str, bytes])
def test_app_menue_mit_dem_namen_vorn(selektor):
    leiste = _leiste_wie_pywebview(selektor)
    desktop._menueleiste_ordnen(leiste)
    titel = [e.title() for e in leiste.itemAtIndex_(0).submenu().itemArray()]
    assert 'NebenkostenFix ausblenden' in titel and 'NebenkostenFix beenden' in titel
    assert 'Über NebenkostenFix' in titel


def test_mac_fenster_ohne_appkit():
    fenster = _Fenster()
    beendet = []
    mac = desktop.MacFenster(fenster, lambda: beendet.append(True))
    assert mac.schliessen() is False and fenster.sichtbar is False and beendet == []
    mac.wieder_oeffnen(sichtbar=True)          # schon ein Fenster da: nichts tun
    assert fenster.sichtbar is False
    mac.wieder_oeffnen(sichtbar=False)
    assert fenster.sichtbar is True
    mac.beenden_angefordert()
    assert mac.schliessen() is None and beendet == [True]


def test_pywebview_hat_die_stellen_fuer_die_anpassung():
    """``_macos_anpassen`` greift in pywebview ein (Delegate, Menüaufbau);
    eine öffentliche Stelle dafür gibt es nicht. Ändert ein Update sie, wird
    das hier rot statt erst auf dem Mac sichtbar."""
    cocoa = pytest.importorskip('webview.platforms.cocoa')
    assert hasattr(cocoa.BrowserView, '_recreate_menus')
    assert hasattr(cocoa.BrowserView, '_shared_app_delegate')
    assert hasattr(cocoa.BrowserView.AppDelegate, 'applicationShouldTerminate_')


def test_macos_anpassung_nur_einmal(monkeypatch):
    """Ein zweiter Aufruf würde die ObjC-Klasse neu anlegen (objc.error) und
    den Menüaufbau doppelt umhüllen (Review C, R5)."""
    monkeypatch.setattr(desktop, '_MACOS_ANGEPASST', True)
    desktop._macos_anpassen(object())   # kehrt zurück, ohne pywebview anzufassen

