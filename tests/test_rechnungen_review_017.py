"""Review 0.17.0: Kleinigkeiten an Rechnungsliste und Zeitleiste.

Gefahren wird der echte Quelltext aus app.js unter node, mit Stubs für das,
was die Funktion von außen braucht.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

QUELLE = (Path(__file__).resolve().parent.parent / 'static' / 'app.js').read_text(encoding='utf-8')

pytestmark = pytest.mark.skipif(shutil.which('node') is None, reason='node fehlt')


def _funktion(name: str) -> str:
    treffer = re.search(rf'^(async )?function {name}\(', QUELLE, re.M)
    assert treffer, f'function {name} fehlt in app.js'
    return QUELLE[treffer.start():QUELLE.index('\n}', treffer.start()) + 2]


def _node(code: str):
    lauf = subprocess.run(['node', '-e', code], capture_output=True, text=True,
                          timeout=30, check=False)
    assert lauf.returncode == 0, lauf.stderr
    return json.loads(lauf.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize('bestand, titel', [
    ('[]', 'Noch keine Rechnungen erfasst'),
    ('[{ id: 1 }]', 'Keine Rechnungen gefunden'),
])
def test_die_leere_zeitleiste_unterscheidet_filter_und_bestand(bestand, titel):
    code = (f'const invoices = {bestand};\n'
            'const leerzustand = o => o.titel;\n'
            + _funktion('renderInvoiceZeitleiste') +
            '\nconst ziel = {}; renderInvoiceZeitleiste({ jahre: [] }, ziel);'
            '\nconsole.log(JSON.stringify(ziel.innerHTML));')
    assert _node(code) == titel


def test_die_summenzeile_zeigt_keine_negative_null():
    """0,30 - 0,10 - 0,20 ergab als Gleitkomma -2,8e-17, also „-0,00 €"."""
    zeile = re.search(r'const summe = ([^;]+);', _funktion('renderInvoices'))
    assert zeile, 'Die Summenzeile ist nicht auffindbar.'
    code = ('const filtered = [{ amount: 0.3 }, { amount: -0.1 }, { amount: -0.2 }];\n'
            + _funktion('geldText') +
            f'\nconst summe = {zeile.group(1)};'
            '\nconsole.log(JSON.stringify(geldText(summe)));')
    assert '-' not in _node(code)


def test_die_suche_laedt_die_zeitleiste_erst_wenn_die_eingabe_ruht():
    assert 'zeitleisteNachladen()' in _funktion('renderInvoices')
    assert 'ladeInvoiceZeitleiste()' not in _funktion('renderInvoices')
    code = ('let zeitleisteWartet = null; let geladen = 0; const offen = new Set();\n'
            'const ladeInvoiceZeitleiste = () => geladen++;\n'
            'const setTimeout = (fn, ms) => { const t = { fn, ms }; offen.add(t); return t; };\n'
            'const clearTimeout = t => offen.delete(t);\n'
            + _funktion('zeitleisteNachladen') +
            '\nzeitleisteNachladen(); zeitleisteNachladen(); zeitleisteNachladen();'
            '\nconst [letzter] = offen; letzter.fn();'
            '\nconsole.log(JSON.stringify([offen.size, geladen, letzter.ms > 0]));')
    assert _node(code) == [1, 1, True]


def test_der_eingesetzte_auswahlknopf_sendet_kein_formular_ab():
    code = ('const CSS = { supports: () => true };\n'
            'const document = { createElement: () => ({ append() {} }) };\n'
            'const feld = { style: {}, querySelector: () => null, prepend() {} };\n'
            'const wurzel = { querySelectorAll: () => [feld] };\n'
            + _funktion('auswahlKnoepfe') +
            '\nauswahlKnoepfe(wurzel);'
            '\nconsole.log(JSON.stringify(feld._auswahlKnopf.type));')
    assert _node(code) == 'button'
