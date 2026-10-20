"""Eine Abrechnungstabelle fuer „Details zur Abrechnung“ und die Vorschau.

Befund: in „Abrechnung ansehen“ liefen
Texte ueber vier Zeilen, weil Unterposten nur die halbe Breite hatten; der
Beleg stand als langer Dateiname in der Zeile, die Schaetzung als „~“ mit
Rechner-Symbol. Vorschau und Details bauten dieselbe Tabelle zweimal, mit
festen Inline-Stilen.

Jetzt:
* je Kostenart eine Zeile (Name, Zeitraum klein darunter, Betrag, Beleg-Symbol),
  die Aufschluesselung klappt per Klick auf und laeuft ueber die volle Breite;
* „geschätzt“ als Etikett, Tooltip auch per Tastatur, Klick oeffnet den Rechenweg;
* das Ergebnis (Gesamt, Vorauszahlungen, Saldo) steht ueber der Tabelle;
* Texte in zwei Ebenen: Name kraeftig, Klammerinhalt grau;
* beide Fenster nutzen dieselben Funktionen, Stile als abr-* mit Tokens.

*Haette den Befund gefunden:* jeder Test hier (gegen fa065b0 rot).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
QUELLE = (WURZEL / 'static' / 'app.js').read_text(encoding='utf-8')
CSS = (WURZEL / 'static' / 'style.css').read_text(encoding='utf-8')

BAUSTEINE = ('escapeHtml', 'dateiAdresse', 'interpolationsTooltip', 'interpolationsKlickAttr',
             'umlageTeile', 'umlageTextHtml', 'geschaetztHtml', 'saldoText',
             'abrechnungsErgebnis', 'abrPostenUmschalten', 'abrechnungsDetailZeilen',
             'abrechnungsTabelle')
KONSTANTEN = ('euroText', 'datumText', 'formatiereVerbrauch')
# Klassen nur als Anker fuer Tests und Lesbarkeit, ohne eigene Regel.
ANKER = {'abr-haupt', 'abr-summe', 'abr-zaehler'}

braucht_node = pytest.mark.skipif(shutil.which('node') is None, reason='node fehlt')


def _funktionsrumpf(name: str) -> str:
    treffer = re.search(rf'^(async )?function {name}\(', QUELLE, re.M)
    assert treffer, f'function {name} fehlt in app.js'
    return QUELLE[treffer.start():QUELLE.index('\n}', treffer.start()) + 2]


def _konstante(name: str) -> str:
    beginn = QUELLE.index(f'const {name} =')
    return QUELLE[beginn:QUELLE.index('\n', beginn) + 1]


def _js(aufruf: str):
    code = (''.join(_konstante(n) for n in KONSTANTEN)
            + 'let abrDetailNr = 0;\n'
            + ''.join(_funktionsrumpf(n) + '\n' for n in BAUSTEINE)
            + f'console.log(JSON.stringify({aufruf}));')
    aus = subprocess.run(['node', '-e', code], capture_output=True, text=True, check=True)
    return json.loads(aus.stdout)


def _tabelle(data: dict) -> str:
    return _js(f'abrechnungsTabelle({json.dumps(data)})')


def _posten(**felder) -> dict:
    return {'category': 'Wasserversorgung', 'period': '01.01.2025 – 31.12.2025',
            'tenant_cost': 120.5, 'description': 'Personentage (365 von 730)', **felder}


SCHAETZUNG = {'is_interpolated': True, 'status': 'ok', 'unit': 'm³', 'meter_id': 7,
              'target_start_date': '2025-01-01', 'target_end_date': '2025-12-31'}


@braucht_node
@pytest.mark.parametrize('text, titel, info', [
    ('Personentage (365 von 730)', 'Personentage', '365 von 730'),
    ('Anteil Allgemein (Haus gesamt: 12,0 m³ (geschätzt))', 'Anteil Allgemein',
     'Haus gesamt: 12,0 m³ (geschätzt)'),
    ('Grundsteuer', 'Grundsteuer', ''),
    ('Wohnflaeche (50 m²) + Personen (2)', 'Wohnflaeche (50 m²) + Personen (2)', ''),
    ('(nur Klammer)', '(nur Klammer)', ''),
    (None, '', ''),
])
def test_text_in_zwei_ebenen_name_und_klammer(text, titel, info):
    assert _js(f'umlageTeile({json.dumps(text)})') == {'titel': titel, 'info': info}


@braucht_node
def test_klammerinhalt_grau_name_kraeftig():
    html = _js('umlageTextHtml("Personentage (365 von 730)")')
    assert html == ('<span class="abr-text-titel">Personentage</span> '
                    '<span class="abr-text-info">365 von 730</span>')
    assert _js('umlageTextHtml("Grundsteuer")') == '<span class="abr-text-titel">Grundsteuer</span>'
    assert re.search(r'\.abr-text-titel\s*\{[^}]*font-weight:\s*600', CSS)
    assert re.search(r'\.abr-text-info\s*\{[^}]*color:\s*var\(--text-muted\)', CSS)


@braucht_node
def test_drei_spalten_zeitraum_und_beleg_als_symbol():
    html = _tabelle({'line_items': [
        _posten(doc_path='x.pdf', doc_name='Rechnung Stadtwerke.pdf', invoice_id=42),
        _posten(category='Grundsteuer'),
    ], 'total_amount': 241, 'prepaid_amount': 200, 'balance': 41})
    kopf = re.search(r'<thead>(.*?)</thead>', html, re.S).group(1)
    assert re.findall(r'<th scope="col"[^>]*>([^<]*)</th>', kopf) == ['Kostenart', 'Betrag', 'Beleg']
    assert 'colspan="2"' not in html
    assert html.count('<span class="abr-zeitraum">01.01.2025 – 31.12.2025</span>') == 2
    assert ('<a class="abr-beleg-link" href="/api/dateien/rechnung/42" target="_blank" '
            'rel="noopener" title="Beleg ansehen: Rechnung Stadtwerke.pdf" '
            'aria-label="Beleg ansehen: Rechnung Stadtwerke.pdf">') in html
    # Der Dateiname steht nicht mehr als Text in der Zeile.
    assert '>Rechnung Stadtwerke.pdf<' not in html
    assert '<span class="abr-ohne-beleg" aria-label="kein Beleg">–</span>' in html


@braucht_node
def test_details_starten_zugeklappt_mit_passender_id():
    html = _tabelle({'line_items': [_posten(), _posten(category='Muell')]})
    knoepfe = re.findall(r'aria-expanded="false" aria-controls="(abr-d-\d+)"', html)
    details = re.findall(r'<tbody class="abr-details" id="(abr-d-\d+)" hidden>', html)
    assert len(knoepfe) == 2 and knoepfe == details and len(set(knoepfe)) == 2
    assert 'aria-expanded="true"' not in html


@braucht_node
def test_umschalter_klappt_auf_und_zu():
    zustand = _js('''(() => {
        const ziel = { hidden: true };
        globalThis.document = { getElementById: id => id === 'abr-d-1' ? ziel : null };
        const attr = { 'aria-expanded': 'false', 'aria-controls': 'abr-d-1' };
        const knopf = { getAttribute: k => attr[k], setAttribute: (k, v) => { attr[k] = v; } };
        const spur = [];
        abrPostenUmschalten(knopf); spur.push([attr['aria-expanded'], ziel.hidden]);
        abrPostenUmschalten(knopf); spur.push([attr['aria-expanded'], ziel.hidden]);
        return spur;
    })()''')
    assert zustand == [['true', False], ['false', True]]


@braucht_node
def test_geschaetzt_als_etikett_statt_tilde():
    mit_klick = _js(f'abrechnungsDetailZeilen({json.dumps(_posten(billing_type="direkt", meter_details={"unit": "m³", "tenant_consumption": 12.5, "tenant_meter": SCHAETZUNG}))})')
    assert ('<button type="button" class="abr-geschaetzt" '
            "onclick=\"openInterpolationAudit(7, '2025-01-01', '2025-12-31')\">geschätzt"
            # Der Knopfname nennt die Handlung (Glossar Par. 6), sichtbar bleibt das Etikett.
            '<span class="sr-only"> – Rechenweg ansehen</span></button>') in mit_klick
    assert 'role="tooltip"' in mit_klick
    assert '~' not in mit_klick and 'ph-calculator' not in mit_klick

    ohne_zaehler = {k: v for k, v in SCHAETZUNG.items() if k != 'meter_id'}
    ohne_klick = _js(f'geschaetztHtml({json.dumps(ohne_zaehler)})')
    assert '<span class="abr-geschaetzt" tabindex="0">geschätzt</span>' in ohne_klick
    assert 'onclick' not in ohne_klick


def test_tooltip_auch_per_tastatur():
    assert re.search(r'\.interpolated-wrapper:focus-within \.glass-tooltip', CSS)


@braucht_node
def test_unterposten_ueber_volle_breite_mit_symbol():
    item = _posten(billing_type='verbrauch', sub_items=[
        {'type': 'eigenverbrauch', 'description': 'Eigenverbrauch (12,5 m³)', 'cost': 30},
        {'type': 'allgemein', 'description': 'Anteil Allgemein (Haus gesamt: 4,0 m³)', 'cost': 5},
    ])
    html = _js(f'abrechnungsDetailZeilen({json.dumps(item)})')
    zeilen = re.findall(r'<tr class="abr-unter">(.*?)</tr>', html, re.S)
    assert len(zeilen) == 2
    # Text in der ersten Zelle, Betrag rechts; die Kostenart-Spalte ist volle Breite.
    assert all(re.search(r'<td><div class="abr-unter-text">', z) for z in zeilen)
    assert 'ph-door abr-symbol abr-symbol-eigen' in zeilen[0] and 'ph-house abr-symbol' in zeilen[1]
    assert '<span class="abr-text-info">Haus gesamt: 4,0 m³</span>' in zeilen[1]
    assert '30,00' in zeilen[0] and '5,00' in zeilen[1]


@braucht_node
def test_heizkosten_hauptbeschreibung_bleibt_sichtbar():
    beschreibung = 'Heizkosten nach HeizkostenV (Ersatzmaßstab nach § 9b)'
    html = _js(f'abrechnungsDetailZeilen({json.dumps(_posten(billing_type="heizkosten", description=beschreibung, sub_items=[{"type": "verbrauch", "description": "Verbrauchskosten 70 % (3 von 10 MWh)", "cost": 70}]))})')
    assert 'Ersatzmaßstab nach § 9b' in html
    assert 'Verbrauchskosten 70 %' in html


@braucht_node
def test_zaehlerkasten_zeigt_keine_angabe_statt_luecke():
    md = {'unit': 'm³', 'tenant_consumption': None, 'main_consumption': 80,
          'allgemein_consumption': 4, 'tenant_meter': {'status': 'ok'},
          'main_meter': {'status': 'ok', 'target_start_date': '2025-01-01',
                         'target_end_date': '2025-12-31'}}
    html = _js(f'abrechnungsDetailZeilen({json.dumps(_posten(billing_type="direkt", meter_details=md))})')
    kasten = re.search(r'<dl class="abr-zaehlerkasten">(.*?)</dl>', html, re.S).group(1)
    angaben = dict(re.findall(r'<dt>(.*?)</dt><dd>(.*?)</dd>', kasten))
    assert angaben['Ihr Wohnungszähler'] == 'keine Angabe'
    assert angaben['Hauptzähler (01.01.2025 bis 31.12.2025)'].startswith('80,0 m³')
    assert angaben['Allgemeinverbrauch'].startswith('4,0 m³')
    assert '<tr class="abr-zaehler"><td colspan="3">' in html


@braucht_node
def test_texte_aus_daten_werden_maskiert():
    boese = '<img src=x onerror=alert(1)>'
    html = _tabelle({'line_items': [_posten(
        category=boese, period=boese, description=f'{boese} ({boese})',
        doc_path='x', doc_name=boese, invoice_id=1,
        sub_items=[{'type': 'allgemein', 'description': boese, 'cost': 1}])]})
    assert '<img' not in html
    assert '&lt;img src=x onerror=alert(1)&gt;' in html


@braucht_node
@pytest.mark.parametrize('saldo, text, klasse', [
    (41, 'Nachzahlung des Mieters', ''),
    (-12.5, 'Guthaben des Mieters', 'abr-guthaben'),
    (0, 'Saldobetrag', ''),
])
def test_ergebnis_nennt_saldo_ohne_vorzeichen(saldo, text, klasse):
    html = _js(f'abrechnungsErgebnis({json.dumps({"total_amount": 241, "prepaid_amount": 200, "balance": saldo})})')
    assert re.findall(r'class="abr-ergebnis-name">([^<]*)<', html) == ['Gesamtkosten', 'Vorauszahlungen', text]
    assert f'abr-ergebnis-saldo {klasse}"' in html
    assert '-' not in re.findall(r'class="abr-ergebnis-wert">([^<]*)<', html)[2]


@pytest.mark.parametrize('fenster', ['openReportDetails', 'generateBillPreview'])
def test_beide_fenster_nutzen_dieselbe_tabelle_ergebnis_zuerst(fenster):
    rumpf = _funktionsrumpf(fenster)
    assert '<table' not in rumpf and '<th' not in rumpf
    assert rumpf.count('abrechnungsTabelle(data)') == 1
    assert rumpf.index('abrechnungsErgebnis(data)') < rumpf.index('abrechnungsTabelle(data)')


def test_keine_inline_stile_in_der_tabelle():
    for name in BAUSTEINE[4:]:
        assert 'style=' not in _funktionsrumpf(name), name


def test_jede_klasse_hat_eine_regel_mit_tokens():
    klassen = set()
    for name in BAUSTEINE:
        for wert in re.findall(r'class="([^"$]*)', _funktionsrumpf(name)):
            klassen.update(k for k in wert.split() if k.startswith('abr-'))
    assert klassen, 'keine abr-Klassen gefunden'
    ohne_regel = sorted(k for k in klassen - ANKER if not re.search(rf'\.{k}\b', CSS))
    assert ohne_regel == []
    block = CSS[CSS.index('/* Runde 7: eine Abrechnungstabelle'):]
    assert re.findall(r'#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(', block) == []


def test_handy_zeilen_als_raster_ohne_seitliches_scrollen():
    """Bei 390 px liefen drei Spalten über (Tabelle 350 px, Rahmen 286 px)."""
    block = CSS[CSS.index('/* Runde 7: eine Abrechnungstabelle'):]
    handy = block[block.index('@media (max-width: 560px)'):]
    assert re.search(r'\.abr-tabelle tr\s*\{[^}]*display:\s*grid', handy)
    assert re.search(r'grid-template-columns:\s*minmax\(0,\s*1fr\)\s+auto', handy)
    assert re.search(r'\.abr-haupt > td:first-child\s*\{[^}]*grid-row:\s*span 2', handy)
    # Kopf bleibt für Vorleser da, eingeklappte Details bleiben versteckt
    assert re.search(r'\.abr-tabelle thead\s*\{[^}]*clip:', handy)
    assert 'tbody:not([hidden])' in handy
