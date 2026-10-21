"""Zahlen in den Umlagetexten deutsch und mit m² (NK-222).

Die Vorschau zeigte „Umlage nach qm (52.0 von 113.0 qm)“: der Punkt eines
floats und das verworfene „qm“ (Glossar, Regel 5) standen im Text, den der
Mieter liest. Ein Text ohne Komma oder mit „qm“ fällt hier auf.
"""

from dataclasses import replace
from decimal import Decimal

from nebenkostenfix.geld import text
from nebenkostenfix.rechenkern import Wohnung, menge_text, rechne, zahl_text

from tests.test_rechenkern import rechnung, vorgang


def test_zahl_text_deutsch_ohne_stellenverlust():
    assert zahl_text(52.0) == '52'
    assert zahl_text(113.25) == '113,25'
    assert zahl_text(1234567.5) == '1234567,5'
    assert zahl_text(100) == '100'


def test_menge_text_eine_stelle_mit_komma():
    assert menge_text(1234.56) == '1234,6'
    assert menge_text(0) == '0,0'


def test_umlage_nach_wohnflaeche_mit_komma_und_m2():
    meine = Wohnung(id=1, name='EG links', qm=52.5)
    andere = Wohnung(id=2, name='EG rechts', qm=60.75)
    v = replace(vorgang([rechnung('1132.50')]), wohnung=meine, wohnungen=(meine, andere))
    posten = rechne(v)['line_items'][0]
    assert posten['description'] == 'Umlage nach Wohnfläche (52,5 von 113,25 m²)'
    assert all('qm' not in s for s in posten.get('rechenweg', []))


def test_zahl_text_ohne_gleitkommareste():
    """NK-234: Wohnflächen sind floats, ihre Summe trägt Reste wie ...00000001."""
    assert zahl_text(55.1 + 62.2) == '117,3'
    assert zahl_text(0.1 + 0.2) == '0,3'


def test_umlage_mit_summe_aus_floats():
    meine = Wohnung(id=1, name='EG links', qm=55.1)
    andere = Wohnung(id=2, name='EG rechts', qm=62.2)
    v = replace(vorgang([rechnung('1173.00')]), wohnung=meine, wohnungen=(meine, andere))
    posten = rechne(v)['line_items'][0]
    assert posten['description'] == 'Umlage nach Wohnfläche (55,1 von 117,3 m²)'
    assert not any('0000' in s for s in posten.get('rechenweg', []))


def test_der_satz_und_die_spalte_schreiben_denselben_betrag():
    """Zwei Formatierer auf einem Blatt lesen sich wie zwei Dokumente.

    Bis Phase 60 gab es zwei: ``rechenkern.euro_text`` schrieb den Betrag
    im Rechenweg und im Anschreiben **ohne** Tausenderpunkt,
    ``pdf_stil.geld`` den in der Betragsspalte **mit**. Auf Seite 1 stand
    dadurch „4817,30 €" im Satz und „4.817,30 €" im Block darunter -- für
    denselben Betrag, auf derselben Seite.

    Der Test prüft die Gleichheit, nicht die eine Schreibweise: Wer sie
    ändern will, ändert ``geld.text`` und beide ziehen mit.
    """
    from nebenkostenfix import pdf_stil
    from nebenkostenfix.rechenkern import euro_text

    for betrag in (Decimal('0.01'), Decimal('999.99'), Decimal('1200'),
                   Decimal('4817.30'), Decimal('-1440'), Decimal('1234567.89')):
        assert euro_text(betrag) == pdf_stil.geld(betrag) == text(betrag), betrag
