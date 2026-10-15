"""Reste aus dem Review (NK-260): Struktur, die sonst still zurückkäme."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from nebenkostenfix import vorauszahlung

WURZEL = Path(__file__).resolve().parents[1]
APP = (WURZEL / 'app.py').read_text(encoding='utf-8')
SKRIPT = (WURZEL / 'static' / 'app.js').read_text(encoding='utf-8')
STIL = (WURZEL / 'static' / 'style.css').read_text(encoding='utf-8')


def test_heute_ruft_nur_das_modul_selbst():
    """(b) ``vz._heute()`` war ein privater Griff von außen; ohne Stichtag
    nimmt ``vorschlag`` selbst heute."""
    fremde = [p.name for p in [WURZEL / 'app.py', *(WURZEL / 'nebenkostenfix').glob('*.py')]
              if p.name != 'vorauszahlung.py'
              and re.search(r'\w\._heute\(', p.read_text(encoding='utf-8'))]
    assert fremde == []


def test_vorschlag_ohne_stichtag_rechnet_ab_heute(monkeypatch):
    monkeypatch.setattr(vorauszahlung, '_heute', lambda: date(2026, 3, 15))
    zahlungen = [(date(2025, m, 1), Decimal('80')) for m in range(1, 13)]
    ohne = vorauszahlung.vorschlag(Decimal('1200'), date(2025, 1, 1), date(2025, 12, 31),
                                   None, zahlungen)
    mit = vorauszahlung.vorschlag(Decimal('1200'), date(2025, 1, 1), date(2025, 12, 31),
                                  None, zahlungen, date(2026, 3, 15))
    assert ohne == mit and ohne['ab'] == '2026-05-01'


def test_models_werden_nur_oben_importiert():
    """(c) ``Payment`` stand sechsmal als Import in Funktionen."""
    assert not re.search(r'(?m)^[ \t]+from nebenkostenfix\.models import', APP)
    assert re.search(r'(?m)^from nebenkostenfix\.models import [^\n]*\bPayment\b', APP)


def _funktion(name: str) -> str:
    start = SKRIPT.index(f'function {name}(')
    return SKRIPT[start:SKRIPT.index('\n}\n', start)]


def test_kpi_kacheln_ohne_inline_style():
    """(d) Die Kacheln trugen Farben, Abstand und Hover im Markup; der
    Innenabstand gehört nach NK-067 allein ``.dashboard-card``."""
    kacheln = _funktion('renderBuildingVitalSigns')
    for verboten in ('style=', 'onmouseenter', 'onmouseleave', 'color: var('):
        assert verboten not in kacheln, verboten
    klassen = {k for attr in re.findall(r'class="([^"]*)"', kacheln) for k in attr.split()}
    klassen |= set(re.findall(r"'(kpi-[a-z-]+)'", kacheln))
    assert {'kpi-karte', 'kpi-trend--hoch', 'kpi-wert--offen'} <= klassen
    for klasse in sorted(k for k in klassen if k.startswith('kpi-')):
        assert re.search(rf'\.{re.escape(klasse)}\b', STIL), klasse
    assert re.search(r'\.kpi-clickable:hover\s*\{[^}]*background', STIL)
    assert 'translateY' not in STIL  # Kontoblatt: Hover hebt nichts an
