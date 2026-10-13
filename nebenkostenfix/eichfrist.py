"""Eichfristen der Verbrauchszaehler (NK-258, R-EICH-01).

§ 34 MessEV mit Anlage 7: die Frist in Jahren je Zaehlerart; sie endet erst
am Ende des Jahres, in dem sie rechnerisch ablaeuft. Die Software macht
daraus einen Vorschlag fuer „geeicht bis“ und einen Hinweis, wenn die Frist
bald oder schon abgelaufen ist. Sie rechnet trotzdem weiter -- ob ein Wert
verwertbar ist, entscheidet nicht die Software.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

# Schluessel -> (Anzeige, Jahre). Reihenfolge = Reihenfolge im Dialog.
EICHFRISTEN = {
    'kaltwasser': ('Kaltwasserzähler', 6),
    'warmwasser': ('Warmwasserzähler', 6),
    'waerme': ('Wärmezähler', 6),
    'gas_balgen': ('Gaszähler (Balgen bis 10 m³/h)', 8),
    'gas': ('Gaszähler, sonstige', 5),
    'strom_elektronisch': ('Stromzähler, elektronisch', 8),
    'strom_ferraris': ('Stromzähler, Ferraris', 16),
    'sonstige': ('Sonstiges Messgerät', 2),
}

VORWARNUNG = timedelta(days=90)


def geeicht_bis(eichjahr: int, art: str) -> date:
    """Ende der Eichfrist: 31.12. des Jahres, in dem sie rechnerisch endet.

    KeyError bei unbekannter Art -- die Grenze prueft die Route.
    """
    return date(eichjahr + EICHFRISTEN[art][1], 12, 31)


def hinweis(bis: Optional[date], heute: date) -> Optional[str]:
    """Text fuer die Zaehlerliste, oder None ohne Anlass."""
    if bis is None:
        return None
    if heute > bis:
        return f'Eichfrist abgelaufen am {bis:%d.%m.%Y}'
    if bis - heute < VORWARNUNG:
        return f'Eichfrist endet am {bis:%d.%m.%Y}'
    return None
