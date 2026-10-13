"""Der Zahlungsblock bricht nicht über eine Seitengrenze (NK-270).

Der Satz „Bitte überweisen …“, der Rückfragen-Satz und der GiroCode-Kasten
gehören zusammen. Bisher standen sie lose hintereinander: Reichte die
Belegliste weit genug nach unten, stand der Satz auf der einen Seite und
der Kasten zerriss -- Überschrift hier, QR-Code und Verwendungszweck auf
der nächsten. In der ausführlichen Fassung stand der Kasten sogar erst
hinter den Verbrauchsnachweisen. Jetzt folgt der Block geschlossen auf
die Belegliste; passt er nicht mehr, rückt er als Ganzes auf die nächste
Seite.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from nebenkostenfix.rechenkern import Stand, verbrauch_in
from tests.test_pdf_belegliste import _entschluesselt, _pdf, _posten, unkomprimiert  # noqa: F401
from tests.test_pdf_verbrauchsnachweis import zaehler, zaehlerzeile

TEILE = ('Bitteüberweisen', 'RückfragenzurAbrechnung', 'ZahlungperGiroCode', 'Verwendungszweck:')


@pytest.fixture
def mit_girocode(monkeypatch):
    monkeypatch.setenv('VERMIETER_NAME', 'Erika Musterfrau')
    monkeypatch.setenv('VERMIETER_IBAN', 'DE89370400440532013000')


def _seiten(pdf: bytes) -> list[str]:
    """Der geklebte Text je Inhaltsstrom -- ein Strom je Seite."""
    seiten = []
    for roh in pdf.split(b'stream')[1:]:
        roh = roh.split(b'endstream')[0].decode('latin-1', 'replace')
        seiten.append(re.sub(r'\s+', '', ''.join(
            _entschluesselt(m) for m in re.findall(r'\(((?:\\.|[^\\)])*)\)', roh))))
    return [s for s in seiten if s]


def _block_auf_einer_seite(pdf: bytes) -> bool:
    return any(all(t in s for t in TEILE) for s in _seiten(pdf))


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_der_zahlungsblock_bleibt_zusammen(unkomprimiert, mit_girocode, detailliert):
    # Jede Länge der Belegliste schiebt den Block ein Stück weiter nach
    # unten; irgendeine davon trifft die Seitengrenze.
    zerrissen = [n for n in range(1, 31)
                 if not _block_auf_einer_seite(_pdf(detailliert, [_posten()] * n))]
    assert not zerrissen, f'Zahlungsblock zerrissen bei {zerrissen} Positionen'


def test_ausfuehrlich_steht_der_girocode_vor_den_nachweisen(unkomprimiert, mit_girocode):
    tm = verbrauch_in(zaehler([Stand(date(2024, 1, 1), 10.0), Stand(date(2025, 1, 1), 20.0)]),
                      date(2024, 1, 1), date(2025, 1, 1))
    pdf = _pdf(True, [_posten(), zaehlerzeile(tm)])
    assert _block_auf_einer_seite(pdf)
    text = ''.join(_seiten(pdf))
    assert text.index('ZahlungperGiroCode') < text.index('DetaillierteVerbrauchsnachweise')
