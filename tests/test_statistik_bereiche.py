"""Phase 56 (Issue #35, Punkt 4): die Statistik nennt Wärme nicht „Gas".

Der Melder hat eine zentrale Wärmepumpe und las in der Auswertung „Gas". Das
war kein Zuordnungsfehler: Die Anwendung kennt den **Energietraeger nirgends**.
Die `Heizungsanlage` hat vier Felder -- Name, versorgt, Verbrauchsanteil,
Sonderfall 70 -- und keines davon sagt, womit geheizt wird. Der Bereich kam
allein aus der Nummer der BetrKV, und die sagt, **wofuer** die Kosten
anfallen, nicht **womit**.

Der alte Kommentar im Kern begruendete den Namen mit „alles, was brennt".
Eine Waermepumpe brennt nicht, eine Fernwaermeuebergabe auch nicht. „Waerme"
ist deshalb nicht nur freundlicher, sondern das, was die Daten hergeben --
und es kann nie wieder falsch werden.

Der zweite Test ist der wichtigere: Der Bereich entsteht im Kern, die
Oberflaeche zeichnet ihn. Wer nur eine der beiden Seiten umbenennt, bekommt
eine Zeitreihe ohne Farbe und ohne Symbol, und zwar stumm. Dieselbe Klasse
wie B-02 und B-04 aus dem Review von 0.16.0: die Oberflaeche darf keinen
eigenen Begriffsvorrat fuehren.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nebenkostenfix import betrkv

WURZEL = Path(__file__).resolve().parent.parent
OBERFLAECHE = WURZEL / 'static' / 'app.js'

#: Was der Kern ausser den Nummern noch ausgeben kann.
AUFFANG = 'Sonstige Kosten'


@pytest.mark.parametrize('nr', sorted(betrkv.NUMMERN_HEIZUNG)
                         if hasattr(betrkv, 'NUMMERN_HEIZUNG') else [4, 5, 6])
def test_die_heizkostennummern_heissen_waerme(nr):
    """Nr. 4, 5 und 6 sind Waerme -- unabhaengig vom Energietraeger."""
    assert betrkv.bereich(nr) == 'Wärme'


def test_kein_bereich_heisst_mehr_nach_einem_brennstoff():
    """„Gas" war eine Behauptung ueber die Anlage, die niemand erhoben hat."""
    assert 'Gas' not in set(betrkv.BEREICHE.values()), (
        'Ein Bereich heisst wieder „Gas". Die Anwendung kennt den '
        'Energieträger nicht; sie darf ihn deshalb auch nicht benennen.')


def test_die_anderen_bereiche_bleiben_wie_sie_waren():
    """Nur die Waerme wird umbenannt, sonst nichts (Issue #35, Punkt 4)."""
    assert betrkv.bereich(2) == betrkv.bereich(3) == 'Wasser'
    assert betrkv.bereich(11) == 'Strom'
    assert betrkv.bereich(9) == AUFFANG


def test_die_oberflaeche_kennt_jeden_bereich_des_kerns():
    """Der Kern benennt, die Oberflaeche zeichnet -- beide dieselbe Liste.

    Ohne diesen Waechter faellt ein umbenannter Bereich stumm aus der
    Darstellung: keine Farbe, kein Symbol, keine Zeile. Der Test prueft die
    Richtung, die weh tut -- jeder Name, den der Server senden kann, muss in
    der Oberflaeche vorkommen.
    """
    text = OBERFLAECHE.read_text(encoding='utf-8')
    bereiche = set(betrkv.BEREICHE.values()) | {AUFFANG}

    fehlend = [name for name in sorted(bereiche)
               if f"'{name}'" not in text]

    assert not fehlend, (
        f'static/app.js kennt diese Bereiche nicht: {fehlend}. Der Kern '
        'sendet sie trotzdem — sie erscheinen dann ohne Farbe und ohne '
        'Symbol.')


def test_die_oberflaeche_fuehrt_keinen_bereich_mehr_der_nicht_existiert():
    """Die Gegenrichtung: ein Name, den der Kern nie sendet, ist tot."""
    text = OBERFLAECHE.read_text(encoding='utf-8')

    assert "'Gas'" not in text, (
        'static/app.js führt noch einen Bereich „Gas". Der Kern sendet den '
        'nicht mehr; die Karte wäre tot und die Wärme ohne Farbe.')
