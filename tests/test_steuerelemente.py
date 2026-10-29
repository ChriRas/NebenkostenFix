"""Formulare im Hausstil: kein rohes Steuerelement rutscht mehr durch.

Gegenproben für ``pruefe_steuerelemente()`` (scripts/ui_beschriftungen.py):
der Prüfer schlägt bei einem nackten Dateifeld, einem Kästchen mit eigener
Größe, einem englischen Browsertext und einem Stylesheet ohne die Hausregeln
an, und lässt die beiden Hausmuster durch. Die Echtprüfung am Ende liest die
wirklichen Dateien; sie war vor dem Umbau rot.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASIS = Path(__file__).resolve().parents[1]
if str(BASIS) not in sys.path:
    sys.path.insert(0, str(BASIS))

from scripts.ui_beschriftungen import (  # noqa: E402
    STYLE,
    pruefe_sperrliste,
    pruefe_steuerelemente,
)

CSS = STYLE.read_text(encoding="utf-8")


def _probe(html: str) -> list[str]:
    return pruefe_steuerelemente({"probe.html": html}, CSS)


def test_nacktes_dateifeld_faellt_auf():
    verstoesse = _probe('<label for="x">Paket</label>\n<input type="file" id="x">')
    assert any("Dateifeld #x" in v for v in verstoesse), verstoesse


def test_dateifeld_im_rahmen_ohne_hauslabel_faellt_auf():
    verstoesse = _probe('<div class="file-upload-wrapper">\n'
                        '    <input type="file" id="x">\n'
                        '    <label for="x">Datei auswählen …</label>\n</div>')
    assert any("Dateifeld #x" in v for v in verstoesse), verstoesse


def test_muster_flaeche_ist_gruen():
    assert _probe('<div class="file-upload-wrapper">\n'
                  '    <input type="file" id="x" accept=".pdf"\n'
                  '        onchange="zeige(this.files[0])">\n'
                  '    <label for="x" class="file-upload-label"><span>Datei auswählen …</span></label>\n'
                  '</div>') == []


def test_muster_knopf_ist_gruen():
    assert _probe('<input type="file" id="x" hidden onchange="gewaehlt(this)">\n'
                  '<button class="btn-secondary" onclick="x.click()">Paket auswählen</button>') == []


def test_kaestchen_mit_eigener_groesse_faellt_auf():
    verstoesse = _probe('<input type="checkbox" id="k" style="width:16px">')
    assert any("checkbox #k" in v for v in verstoesse), verstoesse
    # Ein style am Nachbarelement zählt nicht:
    assert _probe('<th style="width: 40px"><input type="checkbox" id="k"></th>') == []


def test_stylesheet_ohne_hausregeln_faellt_auf():
    verstoesse = pruefe_steuerelemente({}, "input[type=\"checkbox\"] { accent-color: red; }")
    assert any("Kästchen und Optionsfelder" in v for v in verstoesse), verstoesse
    assert any("Feldregel" in v for v in verstoesse), verstoesse


def test_appearance_auto_nur_im_hochkontrast():
    zusatz = '\n.liste input[type="checkbox"] { appearance: auto; }'
    assert any("appearance: auto" in v for v in pruefe_steuerelemente({}, CSS + zusatz))
    assert pruefe_steuerelemente({}, CSS) == []


def test_englische_browsertexte_fallen_auf():
    for text in ("Choose File", "No file chosen", "mm/dd/yyyy"):
        verstoesse = pruefe_sperrliste(f"<span>{text}</span>", "index.html")
        assert any(text in v for v in verstoesse), (text, verstoesse)


def test_echte_oberflaeche_ist_im_hausstil():
    """index.html, app.js, auth.py und style.css: Umzug, Import, Einrichtung
    und die Kästchen mit Inline-Größe waren vor dem Umbau rot."""
    verstoesse = pruefe_steuerelemente()
    assert verstoesse == [], "\n".join(verstoesse)
