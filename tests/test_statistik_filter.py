"""Review 0.17.0 (A3): die Filterknöpfe der Statistik nennen die Bereiche,
die der Server liefert.

Der Bereich heißt seit Issue #35 „Wärme“, der Knopf hieß weiter „Gas“ und
filterte auf einen Bereich, den es nicht mehr gibt: ein leeres Diagramm.
"""

import re
from pathlib import Path

from nebenkostenfix import betrkv

SEITE = (Path(__file__).resolve().parent.parent / 'static' / 'index.html').read_text(encoding='utf-8')


def test_jeder_filterknopf_trifft_einen_bereich():
    block = SEITE[SEITE.index('id="chart-building-filters"'):]
    block = block[:block.index('</div>')]
    knoepfe = re.findall(r'data-filter="([^"]+)"', block)
    bereiche = set(betrkv.BEREICHE.values()) | {'Sonstige Kosten'}
    assert set(knoepfe) == bereiche | {'Alle Kosten'}
