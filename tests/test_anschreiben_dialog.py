"""„Anschreiben bearbeiten“ öffnet den Dialog (NK-124, Backend NK-064).

Die Route liefert die Platzhalter als Wörterbuch {Name: Erklärung}
(``PLATZHALTER`` in ``anschreiben.py``). ``openAnschreibenModal`` rief
darauf ``.map`` wie auf einer Liste auf -- der TypeError landete im
``catch``, und der Dialog meldete bei jedem Objekt „Die Anschreiben-Vorlage
konnte nicht geladen werden.“ Der Test schickt die echte Antwort der Route
durch den echten Funktionsrumpf aus ``app.js``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

QUELLE = (Path(__file__).resolve().parents[1] / 'static' / 'app.js').read_text(encoding='utf-8')

braucht_node = pytest.mark.skipif(shutil.which('node') is None, reason='node fehlt')


def _funktionsrumpf(name: str) -> str:
    treffer = re.search(rf'^(async )?function {name}\(', QUELLE, re.M)
    assert treffer, f'function {name} fehlt in app.js'
    return QUELLE[treffer.start():QUELLE.index('\n}', treffer.start()) + 2]


def _node(code: str):
    lauf = subprocess.run(['node', '-e', code], capture_output=True, text=True, timeout=30,
                          check=False)
    assert lauf.returncode == 0, lauf.stderr
    return json.loads(lauf.stdout.strip().splitlines()[-1])


@braucht_node
def test_der_dialog_oeffnet_mit_vorgabe_und_platzhaltern(auth_client, app_ctx):
    from billing_factories import house
    from nebenkostenfix.anschreiben import PLATZHALTER
    objekt = house()
    antwort = auth_client.get(f'/api/properties/{objekt.id}/anschreiben').get_json()

    code = (
        'const felder = {}; const klassen = new Set(); const fehler = [];\n'
        'const document = { getElementById: id => (felder[id] = felder[id] || '
        '{ value: "", textContent: "", classList: { add: k => klassen.add(id + ":" + k) } }) };\n'
        'const serverFehler = async () => new Error("server"); const meldungZu = (e, t) => t;\n'
        'const showError = t => fehler.push(t);\n'
        'let anschreibenPropertyId = null; let anschreibenIstVorgabe = false;\n'
        f'const fetch = async () => ({{ ok: true, json: async () => ({json.dumps(antwort)}) }});\n'
        + _funktionsrumpf('openAnschreibenModal') + '\n'
        + f'(async () => {{ await openAnschreibenModal({objekt.id});\n'
        '  console.log(JSON.stringify({ fehler, offen: klassen.has("anschreiben-modal:active"),\n'
        '    vorgabe: anschreibenIstVorgabe, text: felder["anschreiben-text"].value,\n'
        '    platzhalter: felder["anschreiben-platzhalter"].textContent })); })();'
    )
    ergebnis = _node(code)
    assert ergebnis['fehler'] == []
    assert ergebnis['offen'] is True
    assert ergebnis['vorgabe'] is True
    assert ergebnis['text'] == antwort['text']
    # jsonify sortiert die Schluessel; es zaehlt, dass jeder Platzhalter erscheint.
    assert sorted(ergebnis['platzhalter'].split()) == sorted(f'{{{name}}}' for name in PLATZHALTER)
