"""Der Ausweis der Lohnanteile nach § 35a EStG (NK-268, R-35A-01).

Ein Ausweis, keine Steuerlogik: der Mieter sieht, welcher Teil
seiner Kosten Lohn fuer haushaltsnahe Dienstleistungen oder
Handwerkerleistungen war -- so, wie der Vermieter ihn an der Rechnung
erfasst hat. Kein Steuersatz, kein Hoechstbetrag.
"""

from decimal import Decimal

from nebenkostenfix.geld import NULL, runde, summe

# Die Reihenfolge ist die der Tabelle im PDF.
ARTEN = {
    'haushaltsnah': 'Haushaltsnahe Dienstleistungen',
    'handwerker': 'Handwerkerleistungen',
}

HINWEIS = (
    'Die Beträge beruhen auf den Lohnanteilen, die der Vermieter an den Rechnungen '
    'angegeben hat, und sind wie die Kosten auf Sie umgelegt. Sie sind nicht '
    'steuerlich geprüft; ob und in welcher Höhe eine Steuerermäßigung möglich ist, '
    'klären Sie mit Ihrem Finanzamt oder Ihrer steuerlichen Beratung.')


def mieteranteil(lohnanteil, mieterkosten, betrag) -> Decimal:
    """Der Anteil des Mieters am Lohn einer Rechnung, ungerundet.

    Der Lohn folgt der Rechnung: wer ein Viertel des Betrags traegt, traegt
    ein Viertel des Lohns. Zeitanteil, Schluessel und Leerstand stecken so
    schon in ``mieterkosten``.
    """
    if not betrag:
        return NULL
    return lohnanteil * mieterkosten / betrag


def ausweis(beitraege: dict):
    """Die Tabelle aus ``{(kostenart, art): Decimal}`` -- oder ``None``.

    Je Zeile auf Cent gerundet, die Summe je Art ist die Summe der
    gerundeten Zeilen (R-NUM-02). Zeilen mit 0,00 EUR entfallen; bleibt
    keine, gibt es keinen Ausweis.
    """
    gruppen = []
    for art, text in ARTEN.items():
        zeilen = [{'kostenart': kostenart, 'betrag': runde(wert)}
                  for (kostenart, a), wert in beitraege.items()
                  if a == art and runde(wert) != NULL]
        if zeilen:
            gruppen.append({'art': art, 'art_text': text, 'zeilen': zeilen,
                            'summe': summe(z['betrag'] for z in zeilen)})
    return {'gruppen': gruppen, 'hinweis': HINWEIS} if gruppen else None
