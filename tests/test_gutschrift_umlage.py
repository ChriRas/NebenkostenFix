"""Eine Gutschrift nach Fläche oder Personen kommt beim Mieter an.

Befund: Eine Rechnung mit negativem Betrag -- eine Gutschrift, etwa die
Rückerstattung eines Versorgers -- ergibt bei der Umlage nach Fläche oder
nach Personen einen negativen Mieteranteil. ``rechne`` nahm eine solche
Zeile nur auf, wenn der Anteil **größer** als null war. Die Gutschrift fiel
still aus der Abrechnung: kein Posten, keine Kürzung der Summe, und der
Mieter bekam von der Rückerstattung des Versorgers nichts.

Seitdem steht die Gutschrift als eigene Zeile mit negativem Betrag in der
Aufstellung und senkt die Summe des Mieters um seinen Anteil. Ein
Gutschriftanteil, der auf 0,00 EUR rundet, bleibt weg -- eine Zeile
„-0,00 €“ erklärt nichts. (Ein positiver Anteil unter einem halben Cent
steht dagegen wie bisher als 0,00 € da.)

Alle Daten sind erfunden, gerechnet in 2025 (365 Tage).
"""

from datetime import date
from decimal import Decimal

from nebenkostenfix.rechenkern import (Kategorie, Mieter, Rechnung, Vorgang,
                                       Wohnung, Zahlung, rechne)

JAHR_BEGINN = date(2025, 1, 1)
JAHR_ENDE = date(2025, 12, 31)

MUELL = Kategorie(id=1, name='Müllabfuhr', braucht_zaehler=False)
REINIGUNG = Kategorie(id=2, name='Hausreinigung', braucht_zaehler=False)


def _welt(rechnungen, *, wer=1, dritte_leer=False, zahlungen=()):
    """Zwei vermietete Wohnungen mit 60 und 40 qm, je ein Einpersonenhaushalt.

    ``dritte_leer`` stellt eine dritte, leere Wohnung mit 100 qm dazu, damit
    ein Teil jeder Rechnung beim Vermieter bleibt.
    """
    wohnungen = (
        Wohnung(id=1, name='Wohnung 1', qm=60.0),
        Wohnung(id=2, name='Wohnung 2', qm=40.0),
    )
    if dritte_leer:
        wohnungen += (Wohnung(id=3, name='Wohnung 3', qm=100.0),)
    mieter = (
        Mieter(id=1, name='Mieter 1', einzug=JAHR_BEGINN, auszug=None, wohnung_id=1),
        Mieter(id=2, name='Mieter 2', einzug=JAHR_BEGINN, auszug=None, wohnung_id=2),
    )
    return Vorgang(
        mieter=mieter[wer - 1],
        wohnung=wohnungen[wer - 1],
        immobilie_id=1,
        immobilie_name='Musterweg 1',
        beginn=JAHR_BEGINN,
        ende=JAHR_ENDE,
        wohnungen=wohnungen,
        mieter_der_immobilie=mieter,
        profile={MUELL.id: 'qm', REINIGUNG.id: 'personen'},
        rechnungen=tuple(rechnungen),
        zahlungen=tuple(zahlungen),
    )


def _rechnung(id, kategorie, betrag, nummer):
    return Rechnung(id=id, kategorie=kategorie, betrag=Decimal(betrag),
                    beginn=JAHR_BEGINN, ende=JAHR_ENDE, nummer=nummer)


def _zeile(ergebnis, nummer):
    treffer = [z for z in ergebnis['line_items'] if z['invoice_number'] == nummer]
    assert len(treffer) == 1, [z['invoice_number'] for z in ergebnis['line_items']]
    return treffer[0]


def test_gutschrift_nach_flaeche_senkt_die_summe_des_mieters():
    """500,00 EUR Rechnung und 100,00 EUR Gutschrift, beide nach Fläche.

    Mieter 1 hat 60 von 100 qm: 300,00 EUR aus der Rechnung, -60,00 EUR aus
    der Gutschrift, zusammen 240,00 EUR. Bei 200,00 EUR Vorauszahlung bleiben
    40,00 EUR Nachzahlung -- ohne die Gutschrift wären es 100,00 EUR.
    """
    ergebnis = rechne(_welt(
        [_rechnung(1, MUELL, '500.00', 'R-1'),
         _rechnung(2, MUELL, '-100.00', 'GS-1')],
        zahlungen=[Zahlung(datum=date(2025, 6, 1), betrag=Decimal('200.00'))]))

    gutschrift = _zeile(ergebnis, 'GS-1')
    assert gutschrift['tenant_cost'] == Decimal('-60.00')
    assert gutschrift['billing_type'] == 'qm'
    assert gutschrift['total_amount'] == Decimal('-100.00')
    assert gutschrift['description'] == 'Umlage nach Wohnfläche (60 von 100 m²)'
    assert [p['cost'] for p in gutschrift['sub_items']] == [Decimal('-60.00')]
    assert gutschrift['rechenweg'][-1].betrag == Decimal('-60.00')

    assert _zeile(ergebnis, 'R-1')['tenant_cost'] == Decimal('300.00')
    assert ergebnis['total_amount'] == Decimal('240.00')
    assert ergebnis['balance'] == Decimal('40.00')


def test_gutschrift_nach_personen_senkt_die_summe_des_mieters():
    """200,00 EUR Rechnung und 50,00 EUR Gutschrift, beide nach Personen.

    Zwei Einpersonenhaushalte, das ganze Jahr: 365 von 730 Personentagen.
    100,00 EUR aus der Rechnung, -25,00 EUR aus der Gutschrift, zusammen
    75,00 EUR.
    """
    ergebnis = rechne(_welt(
        [_rechnung(1, REINIGUNG, '200.00', 'R-2'),
         _rechnung(2, REINIGUNG, '-50.00', 'GS-2')]))

    gutschrift = _zeile(ergebnis, 'GS-2')
    assert gutschrift['tenant_cost'] == Decimal('-25.00')
    assert gutschrift['billing_type'] == 'personen'
    assert gutschrift['description'] == 'Umlage nach Personen (365 von 730 Personentagen)'
    assert [p['cost'] for p in gutschrift['sub_items']] == [Decimal('-25.00')]

    assert _zeile(ergebnis, 'R-2')['tenant_cost'] == Decimal('100.00')
    assert ergebnis['total_amount'] == Decimal('75.00')


def test_gutschrift_mit_leerstand_geht_auf():
    """Mieter und Vermieter teilen sich die Gutschrift ohne Rest.

    Eine leere dritte Wohnung mit 100 von 200 qm: von 100,00 EUR Gutschrift
    tragen Mieter 1 -30,00 EUR, Mieter 2 -20,00 EUR, der Vermieter -50,00
    EUR. Zusammen ergibt das wieder die Gutschrift.
    """
    rechnungen = [_rechnung(2, MUELL, '-100.00', 'GS-1')]
    erster = rechne(_welt(rechnungen, wer=1, dritte_leer=True))
    zweiter = rechne(_welt(rechnungen, wer=2, dritte_leer=True))

    assert _zeile(erster, 'GS-1')['tenant_cost'] == Decimal('-30.00')
    assert _zeile(zweiter, 'GS-1')['tenant_cost'] == Decimal('-20.00')
    assert erster['landlord_share']['total_amount'] == Decimal('-50.00')
    assert (erster['total_amount'] + zweiter['total_amount']
            + erster['landlord_share']['total_amount']) == Decimal('-100.00')


def test_gutschrift_nach_personen_mit_leerstand_geht_auf():
    """Beim Personenschlüssel trägt der Vermieter den Leerstand mit.

    Die leere dritte Wohnung zählt wie ein Einpersonenhaushalt (NK-098):
    365 von 1095 Personentagen je Wohnung. Von 90,00 EUR Gutschrift tragen
    Mieter 1 und Mieter 2 je -30,00 EUR, der Vermieter für den Leerstand
    -30,00 EUR. Zusammen ergibt das wieder die Gutschrift.
    """
    rechnungen = [_rechnung(2, REINIGUNG, '-90.00', 'GS-4')]
    erster = rechne(_welt(rechnungen, wer=1, dritte_leer=True))
    zweiter = rechne(_welt(rechnungen, wer=2, dritte_leer=True))

    gutschrift = _zeile(erster, 'GS-4')
    assert gutschrift['billing_type'] == 'personen'
    assert gutschrift['tenant_cost'] == Decimal('-30.00')
    assert gutschrift['description'] == 'Umlage nach Personen (365 von 1095 Personentagen)'
    assert _zeile(zweiter, 'GS-4')['tenant_cost'] == Decimal('-30.00')

    vermieter = erster['landlord_share']
    assert [p['invoice_number'] for p in vermieter['positions']] == ['GS-4']
    assert vermieter['leerstand_amount'] == Decimal('-30.00')
    assert vermieter['eigennutzung_amount'] == Decimal('0.00')
    assert vermieter['total_amount'] == Decimal('-30.00')
    assert (erster['total_amount'] + zweiter['total_amount']
            + vermieter['total_amount']) == Decimal('-90.00')


def test_gutschrift_unter_einem_halben_cent_bleibt_draussen():
    """Ein Gutschriftanteil, der auf 0,00 EUR rundet, ergibt keine Zeile „-0,00 €“.

    1 Cent Gutschrift nach Fläche: Mieter 1 trägt -0,006 EUR, gerundet
    -0,01 EUR -- die Zeile steht. Mieter 2 trägt -0,004 EUR, gerundet null
    -- die Zeile entfällt und die Summe bleibt 0,00 EUR.
    """
    rechnungen = [_rechnung(2, MUELL, '-0.01', 'GS-3')]
    erster = rechne(_welt(rechnungen, wer=1))
    zweiter = rechne(_welt(rechnungen, wer=2))

    assert _zeile(erster, 'GS-3')['tenant_cost'] == Decimal('-0.01')
    assert zweiter['line_items'] == []
    assert zweiter['total_amount'] == Decimal('0.00')
