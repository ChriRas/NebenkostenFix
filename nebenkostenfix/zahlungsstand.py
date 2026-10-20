"""Zahlungsstand einer Abrechnung, abgeleitet statt gespeichert (Phase 47).

Das Ergebnis der Abrechnung ist positiv bei einer Nachzahlung des Mieters,
negativ bei einem Guthaben. Dagegen zählen die Nebenkostenzahlungen, die der
Abrechnung zugeordnet sind; ein ausgezahltes Guthaben ist eine negative
Zahlung. Der Rest trägt das Vorzeichen des Ergebnisses: positiv schuldet der
Mieter noch, negativ zahlt der Vermieter noch aus.
"""

from __future__ import annotations

from decimal import Decimal

from nebenkostenfix.geld import dec, runde, summe


def zahlungsstand(ergebnis, zahlungen) -> tuple[str, Decimal]:
    """(Stand, Rest) mit Stand aus offen, teilweise, beglichen, ueberzahlt, ausgeglichen."""
    soll = runde(ergebnis)
    rest = runde(soll - summe(dec(z) for z in zahlungen))
    if rest == 0:
        return ('ausgeglichen' if soll == 0 else 'beglichen'), rest
    if soll == 0:
        return 'ueberzahlt', rest
    if rest == soll:
        return 'offen', rest
    if (rest > 0) == (soll > 0):
        return 'teilweise', rest
    return 'ueberzahlt', rest
