"""NK-152: Oberfläche hüllenfest (F-81).

Fenster, Downloads und Druck laufen über die eine Hilfsfunktion ``huelle``
in static/app.js. Im Browser verhält sie sich wie bisher, in der Windows-App
nimmt sie die Brücke der Hülle. Der Wächter verbietet neue direkte Aufrufe.
"""

import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
APP_JS = (WURZEL / 'static' / 'app.js').read_text(encoding='utf-8')
INDEX = (WURZEL / 'static' / 'index.html').read_text(encoding='utf-8')


def _huelle_block():
    anfang = APP_JS.index('const huelle = {')
    ende = APP_JS.index('window.huelle = huelle;')
    return APP_JS[anfang:ende]


def _ohne_huelle():
    return APP_JS.replace(_huelle_block(), '')


def test_kein_direktes_window_open_ausserhalb_der_huelle():
    rest = re.sub(r'//.*', '', _ohne_huelle())
    assert 'window.open(' not in rest


def test_kein_blob_download_ausserhalb_der_huelle():
    rest = _ohne_huelle()
    assert 'URL.createObjectURL' not in rest
    assert not re.search(r'\.download\s*=', rest)


def test_drucken_nur_ueber_die_huelle():
    assert 'window.print' not in _ohne_huelle()
    assert 'window.print' not in INDEX
    assert INDEX.count('huelle.drucken()') == 2


def test_die_huelle_nutzt_die_bruecke_der_app():
    block = _huelle_block()
    for methode in ('speichern(', 'oeffnen(', 'ordner_waehlen('):
        assert f'window.pywebview.api.{methode}' in block


def test_links_mit_target_blank_gehen_in_der_app_an_die_huelle():
    assert "closest('a[target=\"_blank\"], a[download]')" in APP_JS


def test_ordnerwahl_nur_in_der_app_sichtbar():
    assert 'id="btn-sicherung-ordner" style="display: none;"' in INDEX
    assert "ordnerKnopf.style.display = huelle.kann('ordner_waehlen') ? '' : 'none'" in APP_JS


def test_die_huelle_gibt_die_pdf_seite_an_die_app_weiter():
    """Fund 0.9.2: fetch verwirft den Anker #page=N, die Brücke bekam nur die
    Datei. Die Hülle muss die Seite selbst mitgeben."""
    import json
    import shutil
    import subprocess
    import pytest
    node = shutil.which('node')
    if not node:
        pytest.skip('node fehlt')
    probe = '''
        let aufruf = null;
        const window = {pywebview: {api: {oeffnen: async (...a) => { aufruf = a; }}}};
        const fetch = async () => ({ok: true, headers: {get: () => 'inline; filename="r.pdf"'},
                                   blob: async () => null});
        const showError = m => { throw new Error(m); };
        const meldungZu = e => String(e);
        ''' + _huelle_block() + '''
        huelle._base64 = async () => 'QQ==';
        (async () => {
            const ergebnis = [];
            for (const adresse of ['http://h/api/dateien/rechnung/5#page=3', 'http://h/api/dateien/rechnung/5']) {
                await huelle.oeffnen(adresse);
                ergebnis.push(aufruf);
            }
            console.log(JSON.stringify(ergebnis));
        })();
    '''
    ausgabe = subprocess.run([node, '-e', probe], capture_output=True, text=True, timeout=30, check=True)
    mit, ohne = json.loads(ausgabe.stdout)
    assert mit == ['r.pdf', 'QQ==', 3]
    assert ohne == ['r.pdf', 'QQ==', None]


# --- #45: Servermodus ------------------------------------------------------

# Diese drei kann jede Brücke, auch die kleine im Servermodus.
_GRUNDMETHODEN = {'speichern', 'oeffnen', 'extern_oeffnen'}


def test_brueckenaufrufe_brauchen_kann():
    """Die Server-Brücke kennt nur speichern, oeffnen und extern_oeffnen. Jeder
    andere Aufruf muss vorher fragen, sonst wirft er im Servermodus."""
    for treffer in re.finditer(r'window\.pywebview\.api\.(\w+)\(', APP_JS):
        name = treffer.group(1)
        if name in _GRUNDMETHODEN:
            continue
        davor = APP_JS[max(0, treffer.start() - 400):treffer.start()]
        assert f"kann('{name}')" in davor, name


def test_verbindungskarte_nur_mit_server_verbinden():
    karte = INDEX.index('id="server-karte"')
    assert INDEX.index('id="umzug-karte"') > karte
    kopf = INDEX[INDEX.rindex('<div', 0, karte):INDEX.index('>', karte)]
    assert 'data-gruppe="sicherung"' in kopf
    assert 'style="display: none;"' in kopf
    assert "serverKarte.style.display = huelle.kann('server_verbinden') ? '' : 'none'" in APP_JS
    # Ohne den Haken bleibt der Knopf aus.
    knopf = INDEX[INDEX.index('id="btn-server-verbinden"'):]
    assert knopf[:knopf.index('>')].count('disabled') == 1
    # Knopftext „Verbinden“. „prüfen“ hieße Probelauf ohne Änderung (Glossar),
    # der Knopf schreibt aber die INI und startet neu.
    assert knopf[:knopf.index('</button>')].rstrip().endswith('> Verbinden')


def _node(probe):
    import json
    import shutil
    import subprocess
    import pytest
    node = shutil.which('node')
    if not node:
        pytest.skip('node fehlt')
    ausgabe = subprocess.run([node, '-e', probe], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(ausgabe.stdout)


def test_kann_prueft_die_methode_der_bruecke():
    probe = '''
        let aufrufe = [];
        const window = {pywebview: {api: {
            oeffnen: async () => {}, speichern: async () => {}, extern_oeffnen: async () => {},
        }}};
        const showError = m => { throw new Error(m); };
        const meldungZu = e => String(e);
        ''' + _huelle_block() + '''
        (async () => {
            const klein = [huelle.aktiv(), huelle.kann('oeffnen'), huelle.kann('ordner_waehlen'),
                           await huelle.ordnerWaehlen(), await huelle.serverVerbinden('https://x')];
            window.pywebview.api.server_verbinden = async a => { aufrufe.push(a); return {ok: true}; };
            const gross = [huelle.kann('server_verbinden'), await huelle.serverVerbinden('https://x')];
            delete window.pywebview;
            const browser = [huelle.kann('oeffnen'), huelle.kann('server_verbinden')];
            console.log(JSON.stringify([klein, gross, browser, aufrufe]));
        })();
    '''
    klein, gross, browser, aufrufe = _node(probe)
    assert klein == [True, True, False, None, None]
    assert gross == [True, {'ok': True}]
    assert browser == [False, False]
    assert aufrufe == ['https://x']


def _funktion(name):
    anfang = APP_JS.index(f'function {name}(')
    ende = APP_JS.index('\n}\n', anfang) + 3
    return APP_JS[anfang:ende]


def test_leerzustand_zweite_aktion():
    probe = _funktion('leerzustand') + '''
        const basis = {icon: 'ph-x', titel: 'T', text: 'X',
                       aktion: {label: 'Eins', fn: 'a()', icon: 'ph-plus'}};
        console.log(JSON.stringify([
            leerzustand(basis),
            leerzustand({...basis, aktion2: {label: 'Zwei', fn: 'b()', icon: 'ph-plugs-connected'}}),
        ]));
    '''
    einfach, doppelt = _node(probe)
    assert einfach.count('<button') == 1 and 'btn-primary' in einfach and 'btn-secondary' not in einfach
    assert doppelt.count('<button') == 2
    assert 'class="btn-secondary" onclick="b()"' in doppelt
    assert doppelt.index('Eins') < doppelt.index('Zwei')
    assert "aktion2: huelle.kann('server_verbinden')" in APP_JS


# --- #45: Servermodus sichtbar, Rückweg aus den Einstellungen ---------------

# Kleiner DOM-Ersatz für die Node-Proben. innerHTML wirft: die Anzeige im
# Servermodus schreibt nur textContent.
_DOM = '''
    const elemente = {};
    const fokus = [];
    function element(id) {
        if (elemente[id]) return elemente[id];
        const klassen = new Set();
        return elemente[id] = {
            id, hidden: true, style: {display: 'none'}, textContent: '', disabled: false,
            dataset: {},
            classList: {
                toggle: (k, an) => { if (an) klassen.add(k); else klassen.delete(k); },
                add: k => klassen.add(k), remove: k => klassen.delete(k),
                contains: k => klassen.has(k),
            },
            get klassen() { return [...klassen]; },
            set innerHTML(_) { throw new Error('innerHTML im Servermodus'); },
            focus() { fokus.push(id); },
            scrollIntoView() {},
        };
    }
    const document = {getElementById: element};
    const location = {protocol: 'http:', host: 'nas.example:8080', origin: 'http://nas.example:8080'};
    const window = {};
    const fehler = [];
    const showError = m => fehler.push(m);
    const meldungZu = (e, ersatz) => ersatz;
'''

_LOKALE_API = '{speichern() {}, oeffnen() {}, extern_oeffnen() {}, server_verbinden() {}}'
_SERVER_API = '{speichern() {}, oeffnen() {}, extern_oeffnen() {}, lokal_arbeiten() {}}'


def test_lokal_arbeiten_braucht_kann():
    probe = _DOM + _huelle_block() + '''
        (async () => {
            const aufrufe = [];
            const ohne = await huelle.lokalArbeiten();
            window.pywebview = {api: {speichern() {}, server_verbinden() { aufrufe.push('v'); }}};
            const lokal = await huelle.lokalArbeiten();
            window.pywebview.api = {lokal_arbeiten: async () => { aufrufe.push('l'); return true; }};
            const server = await huelle.lokalArbeiten();
            console.log(JSON.stringify([ohne, lokal, server, aufrufe]));
        })();
    '''
    assert _node(probe) == [False, False, True, ['l']]


def test_server_anzeige_nur_mit_lokal_arbeiten():
    probe = _DOM + _huelle_block() + _funktion('serverAnzeige') + f'''
        const stand = () => {{
            const chip = element('kopf-server'), karte = element('server-verbunden-karte');
            return {{chip: !chip.hidden, karte: karte.style.display !== 'none',
                     text: element('kopf-server-text').textContent, klassen: chip.klassen,
                     titel: chip.title,
                     adresse: element('server-verbunden-adresse').textContent,
                     warnung: !element('server-verbunden-unverschluesselt').hidden}};
        }};
        const ergebnis = [];
        serverAnzeige(); ergebnis.push(stand());
        window.pywebview = {{api: {_LOKALE_API}}};
        serverAnzeige(); ergebnis.push(stand());
        window.pywebview = {{api: {_SERVER_API}}};
        serverAnzeige(); ergebnis.push(stand());
        Object.assign(location, {{protocol: 'https:', host: 'nas.example', origin: 'https://nas.example'}});
        serverAnzeige(); ergebnis.push(stand());
        console.log(JSON.stringify(ergebnis));
    '''
    browser, lokal, http, https = _node(probe)
    for aus in (browser, lokal):
        assert not aus['chip'] and not aus['karte']
    assert http['chip'] and http['karte']
    assert http['text'] == 'Verbunden mit nas.example:8080 (unverschlüsselt)'
    assert http['klassen'] == ['unverschluesselt'] and http['warnung']
    assert http['adresse'] == 'http://nas.example:8080'
    # Der Chip kürzt ab; der Tooltip trägt den vollen Text samt Warnzusatz.
    assert http['titel'].startswith('Verbunden mit nas.example:8080 (unverschlüsselt). ')
    assert https['titel'].startswith('Verbunden mit nas.example. ')
    assert https['chip'] and https['karte']
    assert https['text'] == 'Verbunden mit nas.example'
    assert https['klassen'] == [] and not https['warnung']
    assert https['adresse'] == 'https://nas.example'


def test_zeige_server_karte_waehlt_die_sichtbare_karte():
    probe = _DOM + _huelle_block() + _funktion('zeigeServerKarte') + f'''
        const tabs = [];
        const wechsleZuTab = t => tabs.push(t);
        const zeigeEinstellungsgruppe = g => tabs.push(g);
        window.pywebview = {{api: {_SERVER_API}}};
        zeigeServerKarte();
        const server = [fokus.splice(0), elemente['server-karte'] ? 'angefasst' : 'unberührt'];
        window.pywebview = {{api: {_LOKALE_API}}};
        zeigeServerKarte();
        console.log(JSON.stringify([server, fokus, tabs,
            element('server-karte').style.display]));
    '''
    server, lokal, tabs, anzeige = _node(probe)
    assert server == [['btn-lokal-arbeiten'], 'unberührt']
    assert lokal == ['server-adresse'] and anzeige == ''
    assert tabs == ['settings', 'sicherung'] * 2


def test_bruecke_kommt_spaet():
    """pywebview meldet die Brücke womöglich erst nach initApp (#45)."""
    treffer = re.search(r"window\.addEventListener\('pywebviewready', \(\) => \{(.*?)\}\);", APP_JS)
    assert treffer and 'serverAnzeige()' in treffer.group(1)
    assert 'haftungServerKnopf()' in treffer.group(1)
    start = _funktion('initApp')
    assert 'serverAnzeige();' in start


def _kopf(id_):
    stelle = INDEX.index(f'id="{id_}"')
    return INDEX[INDEX.rindex('<', 0, stelle):INDEX.index('>', stelle)]


def test_servermodus_anzeige_im_html():
    assert INDEX.index('id="server-verbunden-karte"') < INDEX.index('id="server-karte"')
    karte = _kopf('server-verbunden-karte')
    assert 'data-gruppe="sicherung"' in karte and 'style="display: none;"' in karte
    chip = _kopf('kopf-server')
    assert chip.startswith('<a ') and ' hidden' in chip
    knopf = INDEX[INDEX.index('id="btn-lokal-arbeiten"'):]
    assert knopf[:knopf.index('</button>')].rstrip().endswith('Zurück zu den Daten auf diesem Rechner')
    # Die einzige Bestätigung kommt von Windows; die Seite fragt nicht selbst.
    rueckweg = _funktion('lokalArbeiten')
    assert 'frage(' not in rueckweg and 'confirm(' not in rueckweg
    # Erster Start: der Server-Knopf steht versteckt vor „Verstanden“.
    haftung = _kopf('haftung-server')
    assert haftung.startswith('<button ') and ' hidden' in haftung
    fuss = INDEX[INDEX.index('id="haftung-server"'):]
    assert fuss.index('Mit einem Server verbinden') < fuss.index('Verstanden')


# --- #45: erster Start, „Mit einem Server verbinden“ im Hinweis -------------

def test_haftung_serverknopf_nur_erstmals_in_der_app():
    probe = _DOM + _huelle_block() + _funktion('haftungServerKnopf') + f'''
        const ergebnis = [];
        for (const api of [null, {_LOKALE_API}, {_SERVER_API}]) {{
            for (const erstmals of ['1', '']) {{
                if (api) window.pywebview = {{api}}; else delete window.pywebview;
                element('haftung-modal').dataset.erstmals = erstmals;
                haftungServerKnopf();
                ergebnis.push(!element('haftung-server').hidden);
            }}
        }}
        console.log(JSON.stringify(ergebnis));
    '''
    # Browser, lokale App, Server-Brücke je erstmals ja/nein: sichtbar nur lokal + erstmals.
    assert _node(probe) == [False, False, True, False, False, False]


def test_haftung_fokus_auf_verstanden_nicht_auf_dem_serverknopf():
    """Wer den Hinweis mit Enter bestätigt, landet nicht im Server-Dialog."""
    fuss = INDEX[INDEX.index('id="haftung-server"'):]
    verstanden = fuss[fuss.rindex('<button', 0, fuss.index('>Verstanden<')):fuss.index('>Verstanden<')]
    assert 'data-autofokus' in verstanden and 'haftungBestaetigen()' in verstanden
    probe = _funktion('fokussierbar') + _funktion('ersterFokus') + '''
        const fokus = [];
        const knopf = (name, auto) => ({tagName: 'BUTTON', disabled: false, offsetParent: {},
                                         auto, focus() { fokus.push(name); }});
        const knoepfe = [knopf('server', false), knopf('verstanden', true)];
        const koerper = {querySelectorAll: () => []};
        const modal = {
            querySelector: sel => sel === '.modal-body' ? koerper
                : sel === '[data-autofokus]' ? knoepfe.find(k => k.auto) || null : null,
            querySelectorAll: () => knoepfe,
            contains: () => false,
        };
        const document = {activeElement: null};
        ersterFokus({querySelector: () => modal});
        knoepfe[1].auto = false;
        ersterFokus({querySelector: () => modal});
        console.log(JSON.stringify(fokus));
    '''
    # Mit data-autofokus der Hauptknopf; ohne bleibt es beim ersten Knopf wie bisher.
    assert _node(probe) == ['verstanden', 'server']


def test_haftung_server_waehlen_erst_nach_bestaetigung():
    # _funktion schneidet das vorangestellte async ab.
    probe = (_DOM + 'async ' + _funktion('haftungServerWaehlen') + 'async ' + _funktion('haftungBestaetigen') + '''
        const karte = [];
        const zeigeServerKarte = () => karte.push('karte');
        const serverFehler = async res => new Error('abgelehnt');
        let antwort = {ok: true};
        const posts = [];
        const fetch = async (url, optionen) => { posts.push([url, optionen.body]); return antwort; };
        const overlay = element('haftung-modal');
        overlay.dataset.version = '2';
        (async () => {
            overlay.classList.add('active');
            await haftungServerWaehlen();
            const ok = [karte.length, overlay.classList.contains('active')];
            antwort = {ok: false, status: 409};
            overlay.classList.add('active');
            await haftungServerWaehlen();
            const abgelehnt = [karte.length, overlay.classList.contains('active'), fehler];
            console.log(JSON.stringify([ok, abgelehnt, posts]));
        })();
    ''')
    ok, abgelehnt, posts = _node(probe)
    assert ok == [1, False]
    assert abgelehnt == [1, True, ['Der Hinweis konnte nicht gespeichert werden.']]
    # Derselbe POST wie „Verstanden“, kein eigener Weg.
    assert posts == [['/api/haftung', '{"version":2}']] * 2


def test_tour_bleibt_in_den_einstellungen():
    versuch = re.search(r'const versuch = \(\) => \{[\s\S]*?\n    \};', APP_JS).group(0)
    assert "getElementById('tab-settings').classList.contains('active')) return;" in versuch
    # Die Zeile für die Hilfe bleibt wörtlich (Rauchtest).
    assert "getElementById('tab-hilfe').classList.contains('active')) return;" in versuch
