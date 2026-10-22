"""NK-144: Die Zeitleiste der Rechnungen, auf Basis des Rechnungsdatums.

Der Rechnungszeitraum (start_date/end_date) sagt, wofuer ein Beleg gilt;
das Rechnungsdatum (NK-058) sagt, wann er ausgestellt wurde. Fuer die
Frage „Was ist wann eingegangen?" zaehlt das Ausstellungsdatum -- deshalb
gruendiert die Zeitleiste darauf und nicht auf dem Zeitraum.

Der Altbestand traegt kein Rechnungsdatum; aus einem NULL wird nichts
geraten (D-57). Diese Rechnungen stehen in ihrer eigenen Gruppe am Ende,
statt in einem erfundenen Monat zu landen.
"""

from __future__ import annotations

from decimal import Decimal

from nebenkostenfix.models import CostInvoice

#: Monatsnamen fuer die Ueberschriften; die Ansicht sagt „April 2025",
#: nicht „2025-04".
MONATSNAMEN = ('Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli',
               'August', 'September', 'Oktober', 'November', 'Dezember')

NULL = Decimal('0.00')


def _eintrag(rechnung: CostInvoice) -> dict:
    return {
        'id': rechnung.id,
        'rechnungsdatum': (rechnung.rechnungsdatum.isoformat()
                           if rechnung.rechnungsdatum else None),
        'kategorie_name': rechnung.category.name,
        'provider_name': (rechnung.provider.name if rechnung.provider else None),
        'invoice_number': rechnung.invoice_number,
        'amount': rechnung.amount,
        'property_name': rechnung.property.name,
        'hat_beleg': bool(rechnung.document),
        'seiten': rechnung.document_pages,
    }


def _gruppe(monat: int) -> dict:
    return {'monat': monat, 'label': MONATSNAMEN[monat - 1],
            'summe': None, 'rechnungen': []}


#: Der Schluessel des Jahresfilters fuer Rechnungen ohne Rechnungsdatum --
#: derselbe Wert wie ``OHNE_DATUM`` in static/app.js.
OHNE_DATUM = 'ohne'


def passt(rechnung: CostInvoice, *, property_id: int | None = None,
          jahr: str | None = None, kategorie: str | None = None,
          suche: str | None = None) -> bool:
    """Dieselben Filter wie die Rechnungsliste (``renderInvoices`` in
    static/app.js): Immobilie aus dem Kopf, Jahr des Rechnungsdatums,
    Kostenart, Suche in Rechnungsnummer und Anbieter.

    Die Zeitleiste ist eine zweite Ansicht derselben Auswahl. Zeigte sie
    mehr als die Liste, waere der Filter oben eine Behauptung.
    """
    if property_id is not None and rechnung.property_id != property_id:
        return False
    if jahr:
        datum = rechnung.rechnungsdatum
        eigenes = str(datum.year) if datum else OHNE_DATUM
        if eigenes != jahr:
            return False
    if kategorie and rechnung.category.name != kategorie:
        return False
    if suche:
        nadel = suche.lower()
        nummer = (rechnung.invoice_number or '').lower()
        anbieter = (rechnung.provider.name if rechnung.provider else '').lower()
        if nadel not in nummer and nadel not in anbieter:
            return False
    return True


def erstellen(**filter_) -> dict:
    """Die Zeitleiste: Jahre und Monate absteigend, Altbestand am Ende.

    ``filter_`` nimmt die Schluessel von :func:`passt`; ohne sie zeigt die
    Zeitleiste den ganzen Bestand.
    """
    rechnungen = [r for r in CostInvoice.query.order_by(CostInvoice.id).all()
                  if passt(r, **filter_)]

    jahre: dict[int, dict] = {}
    ohne_datum = []
    for rechnung in rechnungen:
        eintrag = _eintrag(rechnung)
        datum = rechnung.rechnungsdatum
        if datum is None:
            ohne_datum.append(eintrag)
            continue
        jahr = jahre.setdefault(
            datum.year, {'jahr': datum.year, 'summe': None, 'monate': {}})
        gruppe = jahr['monate'].setdefault(datum.month, _gruppe(datum.month))
        gruppe['rechnungen'].append(eintrag)

    def summe(liste: list[dict]) -> Decimal:
        return sum((r['amount'] for r in liste), start=NULL)

    jahresliste = []
    for jahr in sorted(jahre, reverse=True):
        jahresgruppe = jahre[jahr]
        monatsliste = []
        for monat in sorted(jahresgruppe['monate'], reverse=True):
            gruppe = jahresgruppe['monate'][monat]
            gruppe['summe'] = summe(gruppe['rechnungen'])
            monatsliste.append(gruppe)
        jahresgruppe['monate'] = monatsliste
        jahresgruppe['summe'] = sum(
            (m['summe'] for m in monatsliste), start=NULL)
        jahresliste.append(jahresgruppe)

    gesamt = sum((j['summe'] for j in jahresliste), start=NULL)
    rest_summe = summe(ohne_datum)
    if ohne_datum:
        gesamt = gesamt + rest_summe

    return {
        'jahre': jahresliste,
        'ohne_datum': (None if not ohne_datum else {
            'summe': rest_summe, 'rechnungen': ohne_datum}),
        'gesamt': gesamt,
    }
