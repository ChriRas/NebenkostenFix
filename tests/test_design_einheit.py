"""Ein Design auf jeder Seite, auch nach Phase 5 (NK-156, F-89).

Der Wächter aus Phase 5 (``test_ui_konsistenz.py``) prüft Farbwerte in
Inline-Stilen. Die Drift danach lag woanders: Karten mit eigenen
Schriftgrößen und Abständen, Emoji in Knöpfen, Leerzustände ohne nächsten
Schritt, sieben Einstellungskarten untereinander. Diese Prüfungen sehen auf
die Struktur.
"""

from __future__ import annotations

import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
SEITE = (WURZEL / 'static' / 'index.html').read_text(encoding='utf-8')
SKRIPT = (WURZEL / 'static' / 'app.js').read_text(encoding='utf-8')
STIL = (WURZEL / 'static' / 'style.css').read_text(encoding='utf-8')
ANMELDUNG = (WURZEL / 'static' / 'anmeldung.css').read_text(encoding='utf-8')

# Die Zahl sinkt nur. Wer einen Inline-Stil entfernt, senkt sie mit; wer
# einen braucht, nimmt eine Klasse aus style.css (Abschnitt NK-156).
# ``display: none;`` zählt nicht: das schaltet app.js um.
INLINE_STILE_HOECHSTENS = 107

KLEINE_SCHRIFT = re.compile(
    r'font-size:\s*(?:(?:[0-9]|1[0-2])(?:\.\d+)?px|0\.(?:[0-7]\d*|80?)(?:rem|em))\b')
EMOJI = re.compile('[\U0001F300-\U0001FAFF☀-➿⭐✅]')


def _ohne_kommentare_html(text: str) -> str:
    return re.sub(r'<!--.*?-->', ' ', text, flags=re.S)


def _ohne_kommentare_js(text: str) -> str:
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    return re.sub(r'^\s*//.*$', ' ', text, flags=re.M)


def test_inline_stile_werden_nicht_mehr():
    stile = [re.sub(r'\s+', ' ', s).strip()
             for s in re.findall(r'style="([^"]*)"', SEITE, flags=re.S)]
    zaehlbar = [s for s in stile if s != 'display: none;']
    assert len(zaehlbar) <= INLINE_STILE_HOECHSTENS, (
        f'{len(zaehlbar)} Inline-Stile in index.html (höchstens {INLINE_STILE_HOECHSTENS}). '
        'Bitte eine Klasse aus style.css nehmen.')


def test_keine_schrift_unter_13_pixel():
    funde = []
    for name, text in (('index.html', _ohne_kommentare_html(SEITE)),
                       ('app.js', _ohne_kommentare_js(SKRIPT)),
                       ('style.css', STIL), ('anmeldung.css', ANMELDUNG)):
        funde += [f'{name}: {m.group(0)}' for m in KLEINE_SCHRIFT.finditer(text)]
    assert funde == [], funde


def test_kein_emoji_in_der_oberflaeche():
    funde = []
    for name, text in (('index.html', _ohne_kommentare_html(SEITE)),
                       ('app.js', _ohne_kommentare_js(SKRIPT))):
        for nummer, zeile in enumerate(text.splitlines(), 1):
            if EMOJI.search(zeile):
                funde.append(f'{name}:{nummer}: {zeile.strip()[:80]}')
    assert funde == [], funde


def test_jeder_leerzustand_nennt_den_naechsten_schritt():
    """K4: der Knopf benennt den nächsten sinnvollen Schritt."""
    ohne = []
    for treffer in re.finditer(r'leerzustand\(\{', SKRIPT):
        tiefe, stelle = 1, treffer.end()
        while tiefe and stelle < len(SKRIPT):
            tiefe += {'{': 1, '}': -1}.get(SKRIPT[stelle], 0)
            stelle += 1
        rumpf = SKRIPT[treffer.end():stelle]
        if 'aktion' not in rumpf:
            titel = re.search(r"titel:\s*'([^']*)'", rumpf)
            ohne.append(titel.group(1) if titel else rumpf[:60])
    assert ohne == [], ohne


def test_einstellungen_in_gruppen():
    """K8: jede Karte gehört zu genau einer Gruppe, jede Gruppe hat einen Knopf."""
    anfang = SEITE.index('id="tab-settings"')
    ende = SEITE.index('</section>', anfang)
    bereich = SEITE[anfang:ende]
    karten = re.findall(r'<div([^>]*)class="dashboard-card', bereich)
    assert karten and all('data-gruppe="' in attribute for attribute in karten), karten
    gruppen_der_karten = set(re.findall(r'data-gruppe="([a-z]+)" class="dashboard-card', bereich))
    gruppen_der_knoepfe = set(re.findall(r'class="filter-pill" role="tab" data-gruppe="([a-z]+)"',
                                         bereich))
    assert gruppen_der_karten == gruppen_der_knoepfe
    for gruppe in gruppen_der_knoepfe:
        assert f"'{gruppe}'" in SKRIPT.split('const EINSTELLUNGS_GRUPPEN')[1].split(';')[0]


def test_globaler_kopf_traegt_nur_was_ueberall_gilt():
    """K2: Drucken und Abmelden; Exporte stehen in den Einstellungen --
    Belege unter Sicherung, der JSON-Datenauszug unter Datenschutz (NK-164)."""
    anfang = SEITE.index('<div class="kopf-aktionen">')
    kopf = SEITE[anfang:SEITE.index('</header>', anfang)]
    assert 'huelle.drucken()' in kopf and 'abmelden()' in kopf
    assert 'exportData()' not in kopf and '/api/belege/export' not in kopf
    sicherung = SEITE[SEITE.index('<h3>Sicherung</h3>'):]
    assert '/api/belege/export' in sicherung.split('data-gruppe=')[0]
    auszug = SEITE[SEITE.index('<h3>Datenauszug für andere Programme</h3>'):]
    assert 'exportData()' in auszug.split('data-gruppe=')[0]
    umzug = SEITE[SEITE.index('<h3>Umzug auf einen anderen Rechner</h3>'):]
    assert 'umzugExportieren()' in umzug.split('data-gruppe=')[0]


def test_begruessung_ohne_zurueck_beim_ersten_besuch():
    # Konzept D: der Gruß steht als Untertitel im Kopf von „Heute“.
    assert '<span id="begruessung">Willkommen bei NebenkostenFix!</span>' in SEITE
    assert "'Willkommen zurück!' : 'Willkommen bei NebenkostenFix!'" in SKRIPT


def test_platzhalter_sehen_nicht_wie_werte_aus():
    """Ein grauer Beispielwert ohne „z. B.“ wirkt wie schon ausgefüllt."""
    for platzhalter in re.findall(r'placeholder="([^"]*)"', SEITE):
        if re.search(r'Mustermann|DE\d{2}', platzhalter):
            assert platzhalter.startswith('z. B.'), platzhalter


def test_anmeldeseiten_nehmen_die_farben_der_anwendung():
    for variable in ('--primary', '--primary-hover', '--text-main'):
        wert_app = re.search(rf'{variable}:\s*([^;]+);', STIL).group(1).strip()
        wert_anmeldung = re.search(rf'{variable}:\s*([^;]+);', ANMELDUNG).group(1).strip()
        assert wert_app == wert_anmeldung, variable




def test_hidden_gilt_auch_fuer_knoepfe():
    """Ein Knopf mit ``hidden`` bleibt verborgen, auch wenn seine Klasse
    ``display`` setzt -- auch auf den Anmeldeseiten (NK-164: „Zur Anmeldung“
    stand dort vor der Übernahme)."""
    for stil in (STIL, ANMELDUNG):
        assert re.search(r'\[hidden\]\s*\{\s*display:\s*none\s*!important;', stil)


# --- Kontoblatt (Konzept A): flach, Farben nur über Tokens -----------------
# Ohne Schatten, Verläufe und Anheben beim Überfahren; jede Farbe kommt aus
# :root, damit ein dunkles Thema später nur die Tokens neu setzt.

def test_kontoblatt_halbtransparente_farben_nur_als_token():
    for zeile in STIL.splitlines():
        if 'rgba(' in zeile:
            assert zeile.strip().startswith('--'), zeile.strip()
    for name, text in (('index.html', SEITE), ('app.js', SKRIPT)):
        assert 'rgba(' not in text, name


def test_kontoblatt_ohne_schatten_und_anheben():
    # Konzept D: Inhalte dürfen beim Erscheinen aufsteigen (nur in @keyframes),
    # aber nichts hebt sich beim Überfahren.
    ohne_keyframes = re.sub(r'@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*\s*\}', '', STIL)
    for name, text in (('style.css', ohne_keyframes), ('index.html', SEITE), ('app.js', SKRIPT)):
        for wert in re.findall(r'box-shadow:\s*([^;"\'}]+)', text):
            assert wert.startswith(('none', 'inset')), f'{name}: box-shadow: {wert}'
        assert 'translateY' not in text, name
    for regel in re.findall(r'[^{}]*:hover[^{]*\{[^}]*\}', STIL):
        assert 'transform' not in regel.split('{')[1], regel.strip()
    assert 'background-blobs' not in SEITE and '.blob' not in STIL


def test_kontoblatt_verlauf_nur_als_ocker_schraffur_der_ueberlappung():
    for name, text in (('style.css', STIL), ('app.js', SKRIPT), ('index.html', SEITE)):
        for treffer in re.finditer(r'([a-z-]*gradient)\(([^;]*?)\);', text, flags=re.S):
            assert treffer.group(1) == 'repeating-linear-gradient', name
            assert 'var(--warning-' in treffer.group(2), name


def test_kontoblatt_schriften_nur_ueber_tokens():
    for name, text in (('style.css', STIL), ('app.js', SKRIPT), ('index.html', SEITE)):
        for wert in re.findall(r'font-family:\s*([^;"\'}]+)', text):
            assert wert.strip() in ('var(--font-sans)', 'var(--font-mono)', 'inherit'), \
                f'{name}: font-family: {wert}'
    assert "--font-sans: 'Geist'" in STIL
    assert "--font-mono: 'Geist Mono'" in STIL
    for css in ('geist/geist.css', 'geist-mono/geist-mono.css'):
        assert f'/static/vendor/fonts/{css}' in SEITE


# Kontoblatt-Skala für Inline-Stile: Text 13/15/18/24/32 px, Stärken bis 600.
# Symbole (Phosphor-<i class="ph …">, icon.style) dürfen eigene Größen haben.
SKALA_PX = {'13px', '15px', '18px', '24px', '32px'}
STAERKEN = {'400', '500', '600', 'normal', 'inherit'}
RASTER_PX = {0, 4, 8, 12, 16, 24, 32, 48}
ABSTAND = re.compile(
    r'(?<![-\w])(?:margin|padding)(?:-(?:top|bottom|left|right|inline|block))?\s*:\s*([^;"\'`]+)'
    r'|(?<![-\w])(?:row-|column-)?gap\s*:\s*([^;"\'`]+)'
    r'|\.style\.(?:margin|padding|gap)\w*\s*=\s*[\'"]([^\'"]+)')


def _inline_quellen():
    return (('index.html', _ohne_kommentare_html(SEITE)), ('app.js', _ohne_kommentare_js(SKRIPT)))


def test_kontoblatt_inline_schrift_nur_auf_der_skala():
    funde = []
    for name, text in _inline_quellen():
        for nr, zeile in enumerate(text.splitlines(), 1):
            if 'class="ph ' in zeile or re.search(r'[iI]con\.style', zeile):
                continue
            funde += [f'{name}:{nr} font-size: {w}'
                      for w in re.findall(r'font-size:\s*([0-9.]+(?:px|rem|em))', zeile)
                      if w not in SKALA_PX]
            funde += [f'{name}:{nr} font-weight: {w}'
                      for w in re.findall(r'font-weight:\s*(\w+)', zeile) if w not in STAERKEN]
    assert funde == [], funde


def test_kontoblatt_inline_abstaende_auf_dem_raster():
    funde = []
    for name, text in _inline_quellen():
        for m in ABSTAND.finditer(text):
            wert = next(g for g in m.groups() if g is not None)
            for zahl, einheit in re.findall(r'(-?\d+(?:\.\d+)?)(px|rem|em|%)?', wert):
                if einheit == '%':
                    continue
                if einheit in ('rem', 'em') or (abs(float(zahl)) not in RASTER_PX):
                    nr = text.count('\n', 0, m.start()) + 1
                    funde.append(f'{name}:{nr} {m.group(0).strip()}')
    assert funde == [], funde


def test_kontoblatt_seitentitel_und_tabellenkopf_einheitlich():
    # Jede Seite beginnt mit einem Kopf samt h2; die gemeinsame Regel macht
    # daraus das Seitenband mit dem 28-px-Titel (Konzept D).
    seiten = list(re.finditer(r'<section[^>]*\btab-content\b[^>]*>', SEITE))
    assert len(seiten) >= 10
    for seite in seiten:
        tab = re.search(r'id="([^"]+)"', seite.group(0)).group(1)
        rest = SEITE[seite.end():]
        erstes = re.search(r'<(\w+)([^>]*)>', rest)
        assert 'section-header' in erstes.group(2), f'{tab} beginnt nicht mit .section-header'
        assert re.match(r'\s*(?:<div>\s*)?<h2\b', rest[erstes.end():]), f'{tab}: Kopf ohne h2 vorn'
    titel = re.search(r'\n\.tab-content > \.section-header:first-child h2\s*\{([^}]*)\}', STIL)
    assert titel and 'font-size: 28px' in titel.group(1), 'Seitentitel-Regel fehlt'
    kopf = re.search(r'\nthead th,\s*\.zaehler-kopf th\s*\{([^}]*)\}', STIL)
    assert kopf and 'text-transform: uppercase' in kopf.group(1), 'Spaltenkopf-Regel fehlt'
    # h3 ohne eigene Klasse ist Kartentitel: dieselbe Stufe wie .karten-kopf.
    assert re.search(r'\nh3 \{\s*font-size: 18px;', STIL)


def test_betraege_in_geist_mono():
    """Ein Euro-Betrag, den ein nacktes <strong>/<span> umschließt, erbte die
    Textschrift (Zahlungskarte). Beträge tragen .tabular-nums."""
    nackt = re.findall(
        r'<(?:strong|b|span)(?: style="[^"]*")?>\$\{[^}]*currency', _ohne_kommentare_js(SKRIPT))
    assert not nackt, nackt


# --- Konzept D „Aufgaben“ ----------------------------------------------------

def _regel(selektor: str, text: str = STIL) -> str:
    treffer = re.search(r'(?:^|\n)\s*' + re.escape(selektor) + r' \{([^}]*)\}', text)
    assert treffer, selektor
    return treffer.group(1)


def _media(bedingung: str) -> str:
    """Alle Blöcke einer Media-Query hintereinander (ohne Kommentare)."""
    stil = re.sub(r'/\*.*?\*/', '', STIL, flags=re.S)
    teile = stil.split('@media ' + bedingung + ' {')[1:]
    return '\n'.join(t.split('\n}\n')[0] for t in teile)


def test_konzept_d_leiste_mit_fuenf_bereichen():
    """Die dunkle Leiste trägt die Bereiche; jeder Reiter gehört genau einem."""
    leiste = re.findall(r'class="leiste-eintrag[^"]*" data-gruppe="(\w+)"', SEITE)
    assert leiste == ['heute', 'haus', 'kosten', 'abrechnung', 'einstellungen']
    reiter = dict(re.findall(r'class="nav-item[^"]*" data-tab="(\w+)" data-gruppe="(\w+)"', SEITE))
    assert reiter == {'dashboard': 'heute', 'properties': 'haus', 'tenants': 'haus', 'meters': 'haus',
                      'invoices': 'kosten', 'payments': 'kosten', 'billing': 'abrechnung',
                      'reports': 'abrechnung', 'settings': 'einstellungen'}
    # „Einstellungen“ passt in 13 px nicht in die 72 px des Entwurfs.
    assert 'width: 88px;' in _regel('.leiste-eintrag')


def test_konzept_d_befehlspalette():
    knopf = SEITE[SEITE.index('id="befehl-oeffnen"'):SEITE.index('</button>', SEITE.index('id="befehl-oeffnen"'))]
    assert 'aria-keyshortcuts="Control+K"' in knopf and '<kbd>Strg</kbd><kbd>K</kbd>' in knopf
    dialog = SEITE[SEITE.index('id="befehl-dialog"'):]
    assert 'role="combobox"' in dialog.split('</div>')[0] + dialog
    for hinweis in ('<kbd>↑</kbd><kbd>↓</kbd> wählen', '<kbd>Enter</kbd> öffnen', '<kbd>Esc</kbd> schließen'):
        assert hinweis in dialog, hinweis
    assert "(e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k'" in SKRIPT
    assert 'initBefehl();' in SKRIPT


def test_konzept_d_kopf_bricht_erst_unter_1100_pixel_um():
    """Bei 1280 px stand der Kopf zweizeilig: die Suche gibt jetzt Platz ab."""
    knopf = _regel('.befehl-knopf')
    assert 'flex: 0 1 640px;' in knopf and 'min-width: 0;' in knopf
    assert 'flex-wrap' not in _regel('.top-header')
    assert re.search(r'\.top-header \{\s*flex-wrap: wrap;', _media('(max-width: 1100px)'))
    # Mit Kontomenü passt der Kopf bis 721 px in eine Zeile (Sichtprüfung 2026-10-14).
    assert re.search(r'\.befehl-knopf \{\s*flex: 1 1 160px;', _media('(max-width: 1100px)'))
    # Nicht schrumpfende Aktionen nur auf breiten Fenstern: sonst 136 px Überlauf am Handy.
    assert re.search(r'\.top-header > \.kopf-aktionen \{\s*flex-shrink: 0;', _media('(min-width: 1101px)'))


def test_konzept_d_handykopf_einzeilig():
    """Am Handy stapelten sich Suche, Hauswahl und vier Knöpfe (233 px hoch)."""
    schmal = _media('(max-width: 560px)')
    assert 'flex: 0 0 var(--knopf-hoehe);' in _regel('.befehl-knopf', schmal)
    text = _regel('.befehl-text', schmal)
    # Der Suchtext bleibt als Name des Knopfs für Screenreader erhalten.
    assert 'display: none' not in text and 'clip: rect(0 0 0 0);' in text
    assert 'flex-wrap: nowrap;' in _regel('.top-header', schmal)
    assert 'flex: 1 1 auto;' in _regel('.leiste-eintrag', _media('(max-width: 720px)') + schmal)


def test_konzept_d_hauswahl_im_feldstil():
    assert 'class="haus-wahl form-group" id="haus-wahl-feld" hidden' in SEITE


def test_konzept_d_hausfilter_gilt_fuer_die_ganze_app():
    """Vorher: die Auswahl oben rechts sprang nur zur Immobilie, Mieter und
    Kosten zeigten weiter alle Immobilien. Jede geladene Liste läuft jetzt
    durch imHaus, die Auswahl wird gemerkt."""
    for zuweisung in ("allApartments = imHaus(await response.json(), 'wohnungen');",
                      "tenants = imHaus(await response.json(), 'mieter');",
                      "meters = imHaus(await res.json(), 'zaehler');",
                      "readings = imHaus(await res.json());", "invoices = imHaus(await res.json());",
                      "currentDocuments = imHaus(await res.json());",
                      "const suggestions = imHaus(await res.json());",
                      "const history = imHaus(await res.json());", "payments = imHaus(await res.json());",
                      "properties = hausFilter ? alleHaeuser.filter(p => p.id === hausFilter.id) : alleHaeuser;"):
        assert zuweisung in SKRIPT, zuweisung
    init = SKRIPT[SKRIPT.index("function initApp("):]
    init = init[:init.index("\n}\n")]
    assert "hausFilterSetzen(gemerkterHausFilter());" in init
    assert "fetchTenants();" not in init  # sonst liefe ein ungefilterter Abruf mit
    setzen = SKRIPT[SKRIPT.index("async function hausFilterSetzen("):]
    setzen = setzen[:setzen.index("\n}\n")]
    assert "try {\n        localStorage.setItem('nk-haus-filter'" in setzen
    assert "await ladeHausListen();" in setzen
    wahl = SKRIPT[SKRIPT.index("function fuelleHausWahl("):]
    assert "'<option value=\"\">Alle Immobilien</option>'" in wahl[:600]
    assert "classList.toggle('gefiltert', !!hausFilter)" in wahl[:600]
    assert '<span class="sr-only">Nach Immobilie filtern</span>' in SEITE
    assert ".top-header .haus-wahl.gefiltert select {" in STIL


def test_konzept_d_statistik_ansichten_als_filterpillen():
    menue = SKRIPT[SKRIPT.index('const pille = (ansicht, inhalt) =>'):]
    assert "'filter-pill active' : 'filter-pill'" in menue[:600]
    assert "setAttribute('aria-pressed'" in menue[:600]
    assert "'btn-primary' : 'btn-secondary'" not in SKRIPT[SKRIPT.index("getElementById('analytics-nav')"):][:1500]
    assert re.search(r'\.filter-pill\.active \{\s*background: var\(--text-main\);', STIL)


def test_lange_woerter_brechen_im_dialog_um():
    assert 'overflow-wrap: break-word;' in _regel('.modal')


def test_pruefskripte_wechseln_reiter_ueber_die_funktion():
    """Reiter anderer Bereiche sind verborgen; ein Klick auf .nav-item ginge ins Leere."""
    for skript in ('live_abgleich_ui.py', 'probe_ersteinrichtung.py'):
        text = (WURZEL / 'scripts' / skript).read_text(encoding='utf-8')
        assert 'wechsleZuTab(' in text, skript


# --- Konzept D: Bewegung und Kontomenü --------------------------------------

def test_konzept_d_bewegung_ueber_tokens_und_abschaltbar():
    for token in ('--dauer-kurz:', '--dauer-mittel:', '--kurve:'):
        assert token in STIL, token
    for regel in ('.tab-content.active > *', '.modal-overlay.active > *', '.leiste-eintrag.active::before'):
        block = STIL[STIL.index(regel + ' {'):]
        block = block[:block.index('}')]
        assert 'animation:' in block and 'var(--kurve)' in block, regel
    # Wer weniger Bewegung wünscht, sieht keine; nur der Ladekreisel dreht weiter.
    reduziert = STIL[STIL.rindex('@media (prefers-reduced-motion: reduce)'):]
    assert '*:not(.ph-spin)' in reduziert
    assert 'animation-duration: 1ms !important;' in reduziert
    assert 'transition-duration: 1ms !important;' in reduziert


def test_konzept_d_kontomenue_im_kopf_auf_jeder_breite():
    js = SKRIPT[SKRIPT.index('function initKopfMenues'):]
    js = js[:js.index('\n}\n')]
    assert "knopf.classList.add('konto-knopf')" in js
    assert "getElementById('angemeldeterBenutzer')" in js
    # Am Schreibtisch klappt das Menü auf, statt drei Rahmenknöpfe zu zeigen.
    assert re.search(r'^\.top-header > \.kopf-menue-knopf \{\s*display: inline-flex;', STIL, re.M)
    menue = STIL[STIL.index('.top-header > .kopf-aktionen.mit-menue {'):]
    menue = menue[:menue.index('}')]
    assert 'display: none;' in menue and 'position: absolute;' in menue
    assert re.search(r'\.top-header > \.kopf-aktionen\.mit-menue\.offen \{\s*display: flex;', STIL)


# --- Konzept D: Beleg-Eingang ------------------------------------------------

def test_konzept_d_eingang_liste_vorschau_formular():
    eingang = SEITE[SEITE.index('id="kosten-eingang"'):SEITE.index('id="kosten-rechnungen"')]
    # Rechnung in der Mitte: Belegliste, Vorschau, Formular in dieser Reihenfolge.
    reihe = [eingang.index(f'id="{i}"') for i in ('documents-container', 'eingang-vorschau', 'eingang-formular')]
    assert reihe == sorted(reihe)
    assert 'grid-template-columns: 280px minmax(0, 1fr) 400px;' in STIL


def test_konzept_d_formular_wird_spalte_und_kehrt_zurueck():
    js = SKRIPT[SKRIPT.index('async function openAddInvoiceModal'):]
    js = js[:js.index('\n}\n')]
    # Dasselbe #invoice-modal dient als Spalte; ohne Spalte zieht es zurück in den body.
    assert 'const ziel = spalte || document.body;' in js
    assert "dialog.classList.toggle('als-spalte', !!spalte);" in js
    assert "if (!spalte) dialog.classList.add('active');" in js
    # „Übernehmen“ steht am Fuß der Spalte, Schließen gibt es dort nicht.
    fuss = STIL[STIL.index('.als-spalte .modal-footer {'):]
    assert re.match(r'\.als-spalte \.modal-footer \{\s*position: sticky;\s*bottom: 0;', fuss)
    assert re.search(r'\.als-spalte \.modal-footer \.btn-secondary \{\s*display: none;', STIL)


def test_konzept_d_drei_ansichten_mit_kopfzahl():
    # Runde 2: Pillen Eingang · Alle Rechnungen · Nach Kostenart, darüber die Summe.
    for ansicht in ('eingang', 'alle', 'kostenart'):
        assert re.search(rf'id="pill-{ansicht}"\s+onclick="zeigeKostenAnsicht\(\'{ansicht}\'\)"', SEITE)
    assert 'id="kosten-kopfzahl"' in SEITE
    js = SKRIPT[SKRIPT.index('function zeigeKostenAnsicht'):]
    js = js[:js.index('\n}\n')]
    # Eingang und „Alle“ teilen den Dreispalter, nur „Nach Kostenart“ zeigt die Tabelle.
    assert "document.getElementById('kosten-eingang').hidden = ansicht === 'kostenart';" in js
    assert "kostenAnsicht === 'alle'" in SKRIPT and 'function renderAlleRechnungen' in SKRIPT


def test_konzept_d_beleg_hochladen_links_und_blaettern():
    # Links „Beleg hochladen“ und der Hinweis „J K blättern“ unter der Liste.
    links = SEITE[SEITE.index('class="eingang-links"'):SEITE.index('id="eingang-vorschau"')]
    assert 'onchange="belegGewaehlt(this)"' in links
    assert '<kbd>J</kbd> <kbd>K</kbd> blättern' in links
    gewaehlt = SKRIPT[SKRIPT.index('async function belegGewaehlt'):]
    gewaehlt = gewaehlt[:gewaehlt.index('\n}\n')]
    # Ungespeicherte Eingaben fragen nach, die Blob-Adresse wird wieder frei.
    assert 'darfDialogSchliessen' in gewaehlt and 'huelle.vorschauAdresse(datei)' in gewaehlt
    assert 'URL.revokeObjectURL(neueDateiAdresse)' in SKRIPT
    # Die Datei landet im Dateifeld des Formulars, Speichern lädt sie mit hoch.
    assert "document.getElementById('invoice-file').files = uebergabe.files;" in SKRIPT
    tasten = SKRIPT[SKRIPT.index('// J/K blättern'):]
    tasten = tasten[:tasten.index('\n});\n')]
    # Nicht in Eingabefeldern und nicht, solange ein Dialog offen ist.
    assert "closest('input, textarea, select, [contenteditable]')" in tasten
    assert "document.querySelector('.modal-overlay.active')" in tasten
    # Enter speichert: der Hinweis kommt aus CSS, der Knopftext bleibt prüfbar.
    assert re.search(r'\.als-spalte #btn-save-invoice::after \{\s*content: "Enter" / "";', STIL)


def test_konzept_d_leerer_eingang_blendet_formular_aus():
    # #invoice-modal bleibt in der Spalte, :empty greift dann nicht (Sichtprüfung 2026-10-14).
    assert re.search(r'\.eingang-leer \.eingang-formular \{\s*display: none;', STIL)
    assert "eingang.classList.toggle('eingang-leer', !eingangBeleg);" in SKRIPT


# --- Konzept D: Zähler als Liste plus Detail --------------------------------

def test_konzept_d_zaehler_liste_und_detail():
    # Das Detail liegt neben, nicht in #meters-container: ERSTER_STAND_JS
    # (scripts/rundgang.py) erwartet dort nur Zählerzeilen.
    ansicht = SEITE[SEITE.index('class="zaehler-ansicht"'):]
    ansicht = ansicht[:ansicht.index('</aside>')]
    assert '<div class="spalte" id="meters-container"></div>' in ansicht
    assert 'id="zaehler-detail"' in ansicht
    assert 'function zeigeZaehlerDetail(' in SKRIPT
    assert "fuelleAblesungen(detail.querySelector('.ablese-tabelle'), m);" in SKRIPT
    # Auf der Zählerseite ersetzt das Detail den Verlaufsdialog, im Jahresassistenten nicht.
    verlauf = SKRIPT[SKRIPT.index('function openHistoryModal('):]
    verlauf = verlauf[:verlauf.index('\n}\n')]
    assert 'zeigeZaehler(meterId);' in verlauf
    assert ".modal-overlay.active:not(.als-spalte)" in verlauf


def test_konzept_d_zaehler_auswahl_und_bewegung():
    assert re.search(r'\.zaehler-tabelle tr\[aria-current="true"\] > td:first-child \{\s*box-shadow: inset 3px 0 0 var\(--primary\);', STIL)
    assert "tr.setAttribute('aria-current', 'true')" in SKRIPT
    assert 'animation: auftauchen' in _regel('.zaehler-detail.blendet-ein')
    # Breit trägt das Detail die Handlungen; schmal bleiben sie in der Zeile (NK-252).
    assert 'td.zaehler-aktionen' in _media('(min-width: 1101px)')


def test_konzept_d_zaehler_aktionen_brechen_bis_1100_um():
    # Sichtprüfung 1024 px: „Ersten Stand erfassen“ machte die Aktionsspalte 499 px
    # breit, die Tabelle lief aus dem Behälter. NK-219 hält das inline nowrap.
    assert 'td.zaehler-aktionen {\n        white-space: normal !important;' in _media('(max-width: 1100px)')


def test_konzept_d_zaehler_filter_bricht_um():
    # Sichtprüfung 390 px: die Pille „Wasserversorgung“ schob die Seite auf 487 px.
    assert "pillen.className = 'knopf-zeile';" in SKRIPT
    assert 'flex-wrap: wrap' in _regel('.knopf-zeile')


def test_tabellen_zeilen_hover_einheitlich():
    # Tabellen-Leitfaden (setproduct): Zeilen-Hover hilft beim Lesen über die Zeile.
    hover = _media('(hover: hover)')
    assert '.tabelle tbody tr:hover' in hover
    assert '.zaehler-tabelle tr[data-zaehler]:not([aria-current="true"]):hover' in hover
    assert 'background: var(--bg-hover);' in hover



def test_seitenband_titel_und_unterzeile_auf_jeder_seite():
    # Konzept D: jedes Seitenband trägt Titel und eine Zeile, wozu die Seite da ist.
    seite = _ohne_kommentare_html(SEITE)
    seiten = re.findall(r'<section[^>]*\bid="(tab-\w+)"', seite)
    assert len(seiten) == 10
    for tab in seiten:
        kopf = re.search(
            rf'id="{tab}"[^>]*>\s*<div class="section-header">\s*<div>\s*<h2>.*?</h2>\s*'
            r'<p class="section-untertitel">', seite, re.S)
        assert kopf, f'{tab}: Seitenband ohne Titelblock mit Unterzeile'


def test_rechnungsfilter_bricht_mobil_um():
    # Inline flex: 2 und .feld-breit setzen die Basis auf 0: bei 390 px schrumpfte die Suche auf „Su“.
    leiste = re.search(r'id="invoice-filter">(.*?)</select>', SEITE, re.S).group(1)
    assert leiste.count('<div class="form-group">') == 2
    assert 'flex: 1 1 280px;' in _regel('.controls-bar .form-group')


def test_kategorie_chip_zaehlt_einzahl():
    # Der Chip der Rechnungskategorie zeigte „1 Einträge“.
    assert ' Einträge</span>' not in SKRIPT.replace("'Eintrag' : 'Einträge'}</span>", '')
    assert "catInvoices.length === 1 ? 'Eintrag' : 'Einträge'" in SKRIPT


def test_konzept_d_login_swoosh_und_einflug():
    """Runde 2: Nach „Anmelden“ wischt Indigo über die Seite, die App schiebt
    sich danach herein. Beides entfällt ohne Bewegungswunsch."""
    formular = (WURZEL / 'static' / 'formular.js').read_text(encoding='utf-8')
    for teil in ("'nk-einflug'", 'requestSubmit', 'prefers-reduced-motion', "'pageshow'"):
        assert teil in formular, teil
    assert '@keyframes wischen' in ANMELDUNG
    ruhig = ANMELDUNG[ANMELDUNG.rindex('prefers-reduced-motion'):]
    assert '.swoosh' in ruhig and 'animation: none' in ruhig
    assert "classList.add('einflug')" in SEITE and "removeItem('nk-einflug')" in SEITE
    for teil in ('html.einflug body::after', '@keyframes deckblatt-weg', 'html.einflug .app-container'):
        assert teil in STIL, teil
    # Einflug-Regeln stehen vor dem zentralen Reduced-Motion-Block, der sie abschaltet.
    assert STIL.index('@keyframes deckblatt-weg') < STIL.rindex('prefers-reduced-motion')


def test_konzept_d_gerichtete_seitenwechsel_und_kopfzahl():
    for richtung in ('zurueck', 'rechts', 'links'):
        assert f'.tab-content.active[data-richtung="{richtung}"] > *' in STIL, richtung
    assert 'targetTab.dataset.richtung = seitenRichtung(vorher, item)' in SKRIPT
    assert 'backdrop-filter: blur(' in STIL
    kopf = SKRIPT[SKRIPT.index('function zeigeKopfzahl'):]
    assert 'zaehleHoch(summe' in kopf[:kopf.index('\n}')]
    hoch = SKRIPT[SKRIPT.index('function zaehleHoch'):]
    hoch = hoch[:hoch.index('\n}')]
    # Ein neuer Lauf startet bei der sichtbaren Zahl, nicht beim alten Ziel (sonst Sprung).
    assert 'el.dataset.wert = wert' in hoch and 'el.dataset.wert = ziel' not in hoch


def test_runde2_kleinfehler_datum_einzahl_zeitraum():
    """Runde 2: Datumsanzeigen laufen über datumText (keine UTC-Verschiebung,
    Zeitstempel erlaubt), „1 Rechnung“ in Einzahl, Von–bis-Felder bündig."""
    import re
    # Nur echte Date-Objekte (Überschneidungsprüfung) dürfen noch direkt formatieren.
    assert not re.search(r"new Date\([^()]*\)\.toLocaleDateString\('de-DE'\)", SKRIPT)
    assert "cat.invoice_count === 1 ? 'Rechnung' : 'Rechnungen'" in SKRIPT
    assert '.zeitraum-felder {' in STIL
    for feld in ('billing-period-start', 'frei-period-start'):
        assert 'class="zeitraum-felder"' in SEITE[SEITE.index(f'id="{feld}"') - 300:SEITE.index(f'id="{feld}"')], feld


def _regel(selektor: str, text: str = STIL) -> str:
    start = text.index(selektor + ' {')
    return text[start:text.index('}', start)]


def test_runde3_feldpaare_unten_buendig():
    """Runde 3: Bricht in einem Feldpaar eine Beschriftung um, bleiben die
    Eingabefelder auf einer Linie. Hilfetexte stehen deshalb unter der Zeile,
    nie in nur einer Hälfte. Unter 640 px stapeln die Felder in voller Breite."""
    assert 'align-items: flex-end' in _regel('.felder-nebeneinander')
    assert '.felder-nebeneinander { flex-direction: column; align-items: stretch; }' in STIL
    seite = _ohne_kommentare_html(SEITE)
    paare = seite.split('<div class="felder-nebeneinander">')[1:]
    assert len(paare) >= 17
    for paar in paare:
        # Das Paar endet, wo die öffnenden und schließenden divs aufgehen.
        tiefe, pos = 1, 0
        while tiefe:
            auf, zu = paar.find('<div', pos), paar.find('</div>', pos)
            if auf != -1 and auf < zu:
                tiefe, pos = tiefe + 1, auf + 4
            else:
                tiefe, pos = tiefe - 1, zu + 6
        assert '<small' not in paar[:pos], paar[:200]


def test_runde3_fotovorschau_nicht_vom_tabellenrahmen_beschnitten():
    """Runde 3: Die Fotovorschau einer Ablesung liegt fest im Fenster. Absolut
    beschnitt sie das overflow-x der Tabellenrolle (oberste Zeile halb)."""
    regel = _regel('.image-hover-preview')
    assert 'position: fixed' in regel
    assert 'bottom: 100%' not in regel
    assert "ereignis.target.closest('.image-hover-container')" in SKRIPT


def test_runde3_pdf_ohne_browser_viewer():
    """PDF-Belege zeichnet pdf.js auf das eigene Blatt, ein Rahmen statt zwei.

    Der iframe mit dem PDF-Viewer des Browsers bleibt nur als Rückfall in
    zeichnePdf, vorschauHtml selbst setzt ihn nicht mehr.
    """
    start = SKRIPT.index('function vorschauHtml(')
    vorschau = SKRIPT[start:SKRIPT.index('\n}\n', start)]
    assert '<iframe' not in vorschau
    assert 'beleg-pdf' in vorschau
    zeichnen = SKRIPT[SKRIPT.index('async function zeichnePdf('):]
    zeichnen = zeichnen[:zeichnen.index('\n}\n')]
    assert "import('/static/vendor/pdfjs/pdf.min.js')" in zeichnen
    assert 'isEvalSupported: false' in zeichnen   # CSP ohne unsafe-eval
    assert 'datei.arrayBuffer()' in zeichnen       # fetch auf blob: sperrt die CSP
    assert '<iframe' in zeichnen                   # Rückfall
    assert SKRIPT.count("zeichnePdf(vorschau.querySelector('.beleg-pdf')") == 2
    regel = _regel('.vorschau-blatt.beleg-pdf')
    assert 'overflow-y: auto' in regel and 'position: relative' in regel
    assert 'justify-content: flex-start' in regel   # Seite 1 bleibt erreichbar
    assert 'border:' not in _regel('.pdf-seite')   # kein zweiter Rahmen
