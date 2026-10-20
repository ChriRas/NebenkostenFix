"""Phase 55: Warmwasser mit Waermemengenzaehler -- § 9 Abs. 2 Satz 1 HeizkostenV.

Der Fall kommt aus der Nachfrage zu Live-Issue #32: eine zentrale Waermepumpe
fuer Heizung **und** Warmwasser (verbundene Anlage, § 9), und in jeder Wohnung
**zwei Waermemengenzaehler** -- einer fuer die Heizung, einer fuer das
Warmwasser, beide in Kilowattstunden. § 8 Abs. 1 spricht von Kubikmetern
Warmwasser, aber § 9 Abs. 2 Satz 1 erlaubt ausdruecklich, die Warmwasser-
Waermemenge zu messen; bei Waermepumpen ist genau das der uebliche Aufbau.

Zwei Dinge muessen dabei gelten, und sie ziehen in verschiedene Richtungen:

1. Der kWh-Zaehler am Warmwasser bleibt ein **Warmwasserzaehler** -- er gehoert
   in den Nenner des § 8 und nicht in den des § 7. Das entscheidet der Zweck
   (die BetrKV-Nummer der Kostenart), nicht die Masseinheit.
2. Die Abrechnung muss **kWh** nennen und nicht m3. Die Verteilung ist
   einheitenneutral (der Anteil kuerzt sich heraus), aber eine falsche Einheit
   ist eine falsche Angabe -- R-DOC-01 verlangt einen nachvollziehbaren
   Rechenweg.

Die Zahlen sind mit der Hand nachgerechnet und stehen im Docstring.
Ohne Datenbank, wie der ganze Kern seit NK-037.
"""

from datetime import date
from decimal import Decimal

from nebenkostenfix import heizung
from nebenkostenfix.rechenkern import (
    Heizungsanlage,
    Kategorie,
    Mieter,
    Rechnung,
    Stand,
    Vorgang,
    Wohnung,
    Zaehler,
    ist_warmwasserzaehler,
    rechne,
)

JAHR_BEGINN = date(2024, 1, 1)
JAHR_ENDE = date(2024, 12, 31)

WAERME = Kategorie(id=9, name='Heizung', braucht_zaehler=True, betrkv_nr=4)
WARMWASSER = Kategorie(id=10, name='Warmwasser', braucht_zaehler=True,
                       betrkv_nr=5)


def _zaehler(id, wohnung_id, verbraucht, kategorie, einheit=None):
    return Zaehler(
        id=id,
        nummer=f'WMZ-{id}',
        kategorie_id=kategorie.id,
        kategorie_name=kategorie.name,
        kategorie_betrkv_nr=kategorie.betrkv_nr,
        ist_hauptzaehler=False,
        immobilie_id=1,
        wohnung_id=wohnung_id,
        staende=(Stand(datum=JAHR_BEGINN, wert=0.0),
                 Stand(datum=date(2025, 1, 1), wert=verbraucht)),
        heizungsanlage_id=1,
        einheit=einheit,
    )


#: Der Aufbau des Melders: vier Waermemengenzaehler, alle in kWh. Die beiden
#: am Warmwasser haengen an der Kostenart Nr. 5 -- im Katalog eine
#: Kubikmeter-Kostenart -- und tragen ihre Einheit jetzt selbst.
ZAEHLER_WAERMEPUMPE = (
    _zaehler(1, 1, 1200.0, WAERME),
    _zaehler(2, 2, 800.0, WAERME),
    _zaehler(3, 1, 4000.0, WARMWASSER, einheit='kWh'),
    _zaehler(4, 2, 6000.0, WARMWASSER, einheit='kWh'),
)

#: Derselbe Aufbau mit Wasserzaehlern, wie ihn der Bestand hat: kein Feld
#: gesetzt, die Einheit kommt aus der Kostenart. Das ist die Gegenprobe.
ZAEHLER_BESTAND = (
    _zaehler(1, 1, 1200.0, WAERME),
    _zaehler(2, 2, 800.0, WAERME),
    _zaehler(3, 1, 30.0, WARMWASSER),
    _zaehler(4, 2, 70.0, WARMWASSER),
)


def waermepumpe():
    """Eine verbundene Anlage, die ein Viertel ihrer Waerme ans Wasser gibt."""
    return Heizungsanlage(
        id=1,
        name='Waermepumpe',
        versorgt=heizung.VERBUNDEN,
        verbrauchsanteil_prozent=70,
        warmwasser_weg=heizung.WW_ZAEHLER,
        warmwasser_kwh=Decimal('15000'),
        brennstoff_menge=Decimal('60000'),
    )


def haus(zaehler=ZAEHLER_WAERMEPUMPE):
    """Zwei gleich grosse Wohnungen, mein Mieter wohnt in der linken."""
    meine = Wohnung(id=1, name='EG links', qm=50.0)
    andere = Wohnung(id=2, name='EG rechts', qm=50.0)
    ich = Mieter(id=1, name='Anna Mieterin', einzug=date(2020, 1, 1),
                 auszug=None, wohnung_id=1)
    nachbar = Mieter(id=2, name='Bert Nachbar', einzug=date(2020, 1, 1),
                     auszug=None, wohnung_id=2)
    return Vorgang(
        mieter=ich,
        wohnung=meine,
        immobilie_id=1,
        immobilie_name='Hauptstrasse 1',
        beginn=JAHR_BEGINN,
        ende=JAHR_ENDE,
        wohnungen=(meine, andere),
        mieter_der_immobilie=(ich, nachbar),
        profile={},
        rechnungen=(Rechnung(
            id=1, kategorie=WAERME, betrag=Decimal('10000.00'),
            beginn=JAHR_BEGINN, ende=JAHR_ENDE,
            heizungsanlage_id=1, heizkostenart='brennstoff'),),
        zaehler=tuple(zaehler),
        heizungsanlagen=(waermepumpe(),),
    )


def zeilen(ergebnis):
    """Die Zeilen der Anlage, nach Zweck."""
    return {
        z['heizung_details']['zweck']: z
        for z in ergebnis['line_items'] if z['billing_type'] == 'heizkosten'
    }


# --- Der Zweck entscheidet, nicht die Masseinheit ---------------------------


def test_der_warmwasser_waermezaehler_bleibt_in_paragraf_8():
    """Nr. 5 heisst Warmwasser -- auch wenn der Zaehler kWh misst.

    Das ist der Kern des Falls: wuerde die Masseinheit entscheiden, fiele
    dieser Zaehler in den Nenner des § 7 und wuerde dem Mieter Heizkosten
    nach seinem Warmwasserverbrauch zuteilen. Die Trennung folgt dem Zweck.
    """
    warm = [z for z in ZAEHLER_WAERMEPUMPE if z.kategorie_betrkv_nr == 5]
    assert [z.einheit for z in warm] == ['kWh', 'kWh']
    assert all(ist_warmwasserzaehler(z) for z in warm)

    heiz = [z for z in ZAEHLER_WAERMEPUMPE if z.kategorie_betrkv_nr == 4]
    assert not any(ist_warmwasserzaehler(z) for z in heiz)


def verbrauchsposten(zeile):
    """Der Unterposten, der den Rechenweg des Verbrauchs ausweist."""
    return next(u['description'] for u in zeile['sub_items']
                if u['type'] == 'heizung_verbrauch')


def test_die_nenner_bleiben_getrennt():
    """2.000 kWh im § 7-Nenner, 10.000 kWh im § 8-Nenner -- nicht 12.000.

    Beide Nenner sind jetzt in kWh, und gerade deshalb muessen sie getrennt
    bleiben: eine Summe ueber alle vier Zaehler waere rechnerisch moeglich
    und fachlich falsch.
    """
    zwei = zeilen(rechne(haus()))

    assert 'von 2000,0 kWh' in verbrauchsposten(zwei[heizung.HEIZUNG])
    assert 'von 10000,0 kWh' in verbrauchsposten(zwei[heizung.WARMWASSER])


# --- Die Abrechnung nennt die richtige Einheit ------------------------------


def test_die_warmwasserzeile_nennt_kilowattstunden():
    """Der rote Nachweis: heute steht hier m3, weil Nr. 5 so im Katalog steht."""
    zwei = zeilen(rechne(haus()))

    assert zwei[heizung.WARMWASSER]['heizung_details']['unit'] == 'kWh'
    assert zwei[heizung.HEIZUNG]['heizung_details']['unit'] == 'kWh'


def test_der_rechenweg_im_posten_nennt_kilowattstunden():
    """R-DOC-01: der Mieter liest den Rechenweg, nicht das Feld.

    Das ist die Zeile, die in seiner Abrechnung steht. Vor Phase 55 hiess
    sie "4000,0 von 10000,0 m3" -- dieselben Zahlen, die falsche Einheit.
    """
    text = verbrauchsposten(zeilen(rechne(haus()))[heizung.WARMWASSER])

    assert text == 'Verbrauchskosten 70 % (4000,0 von 10000,0 kWh)'


# --- Die Betraege aendern sich nicht ----------------------------------------


def test_die_betraege_stimmen_auf_den_cent():
    """15.000 von 60.000 kWh ans Wasser: aus 10.000 werden 2.500 und 7.500.

    Heizung: Verbrauchsteil 7.500 · 0,7 = 5.250, davon 1.200 von 2.000 kWh
    = 3.150; Grundteil 2.250, davon 50 von 100 qm = 1.125. Zusammen 4.275,00.

    Warmwasser: Verbrauchsteil 2.500 · 0,7 = 1.750, davon 4.000 von 10.000
    kWh = 700; Grundteil 750, davon 50 von 100 qm = 375. Zusammen 1.075,00.
    """
    ergebnis = rechne(haus())
    zwei = zeilen(ergebnis)

    assert zwei[heizung.HEIZUNG]['tenant_cost'] == Decimal('4275.00')
    assert zwei[heizung.WARMWASSER]['tenant_cost'] == Decimal('1075.00')
    assert ergebnis['total_amount'] == Decimal('5350.00')


def test_der_bestand_rechnet_unveraendert():
    """Gegenprobe: ohne Feld am Zaehler bleibt alles, wie es war.

    Dieselbe Anlage mit Wasserzaehlern (30 von 100 m3): 1.750 · 0,3 = 525
    plus 375 Grundteil = 900,00 -- die Zahl aus test_warmwassertrennung.
    Das belegt, dass die Umstellung den Bestand nicht beruehrt.
    """
    ergebnis = rechne(haus(ZAEHLER_BESTAND))
    zwei = zeilen(ergebnis)

    assert zwei[heizung.HEIZUNG]['tenant_cost'] == Decimal('4275.00')
    assert zwei[heizung.WARMWASSER]['tenant_cost'] == Decimal('900.00')
    assert zwei[heizung.WARMWASSER]['heizung_details']['unit'] == 'm³'
    assert ergebnis['total_amount'] == Decimal('5175.00')


# --- Die Umstellung selbst war ein Nullwechsel -----------------------------


def test_die_zweckregel_deckt_sich_mit_der_alten_einheitenregel():
    """Der Beweis, dass Phase 55 am Bestand nichts verschoben hat.

    Bis Phase 55 entschied ``ist_warmwasserzaehler`` nach der Einheit aus
    dem Katalog. Seitdem entscheidet ``betrkv.NUMMERN_WARMWASSER``. Beide
    Regeln muessen fuer **jede** Katalognummer dasselbe sagen -- sonst
    waere eine Altabrechnung von der Umstellung betroffen, und das waere
    verschobenes Geld.

    Wer ``NUMMERN_WARMWASSER`` aendert, muss hier vorbei: entweder ist die
    Aenderung falsch, oder sie ist eine bewusste fachliche Entscheidung und
    braucht eine Wanderung fuer den Bestand.
    """
    from nebenkostenfix import betrkv

    nach_zweck = {nr for nr in betrkv.EINHEITEN
                  if nr in betrkv.NUMMERN_WARMWASSER}
    nach_einheit = {nr for nr, e in betrkv.EINHEITEN.items() if e == 'm³'}

    assert nach_zweck == nach_einheit == {2, 3, 5}


def test_ein_zaehler_ohne_nummer_faellt_auf_den_namen_zurueck():
    """Eine Probe ohne Katalog rechnet weiter wie vorher (NK-121)."""
    ohne_nummer = Zaehler(
        id=99, nummer='P-1', kategorie_id=99, kategorie_name='Warmwasser',
        kategorie_betrkv_nr=None, ist_hauptzaehler=False, immobilie_id=1,
        wohnung_id=1)
    waerme = Zaehler(
        id=98, nummer='P-2', kategorie_id=98, kategorie_name='Heizung',
        kategorie_betrkv_nr=None, ist_hauptzaehler=False, immobilie_id=1,
        wohnung_id=1)

    assert ist_warmwasserzaehler(ohne_nummer)
    assert not ist_warmwasserzaehler(waerme)


# --- Gemischte Einheiten in einem Nenner sind kein Nenner ------------------


def test_gemischte_einheiten_verteilen_nach_flaeche():
    """Ein m3-Zaehler und ein kWh-Zaehler ergeben keine Summe (Klasse B).

    Der Fall entsteht beim Umbau: eine Wohnung bekommt den neuen
    Waermemengenzaehler, die andere haengt noch am Wasserzaehler. 30 m3
    plus 6.000 kWh ist keine Menge, und ein Anteil daran ist keine Zahl.
    Die App darf das nicht stillschweigend addieren -- sie verteilt dann
    ganz nach Flaeche und sagt, warum. Dem Mieter steht dafuer das
    Kuerzungsrecht des § 12 HeizkostenV zu (NK-052).
    """
    gemischt = (
        _zaehler(1, 1, 1200.0, WAERME),
        _zaehler(2, 2, 800.0, WAERME),
        _zaehler(3, 1, 30.0, WARMWASSER),                   # m³
        _zaehler(4, 2, 6000.0, WARMWASSER, einheit='kWh'),  # kWh
    )
    warm = zeilen(rechne(haus(gemischt)))[heizung.WARMWASSER]

    # Ganz nach Flaeche: 2.500 · 50/100 = 1.250,00.
    assert warm['tenant_cost'] == Decimal('1250.00')
    assert 'kein erfasster Verbrauch' in warm['description']
    details = warm['heizung_details']
    assert details['erfasst'] is False
    assert details['fehlgrund'] == (
        'verschiedene Maßeinheiten an den Zählern: kWh und m³')

    # Die Heizungsseite bleibt unberuehrt -- ihr Nenner ist einheitlich.
    heiz = zeilen(rechne(haus(gemischt)))[heizung.HEIZUNG]
    assert heiz['tenant_cost'] == Decimal('4275.00')


def test_ein_einheitlicher_kwh_nenner_bleibt_erfasst():
    """Die Gegenprobe: beide auf kWh ist einheitlich und wird gerechnet."""
    warm = zeilen(rechne(haus()))[heizung.WARMWASSER]

    assert warm['tenant_cost'] == Decimal('1075.00')
    assert 'kein erfasster Verbrauch' not in warm['description']


def test_der_vermieter_erfaehrt_warum_und_was_es_ihn_kostet():
    """Der Grund steht in der Abrechnung, und § 12 wird ausgeloest.

    Die Warnmaschinerie der App nimmt den neuen Grund von selbst auf -- er
    geht denselben Weg wie ein fehlender Zaehler. Dieser Test haelt fest,
    dass das so bleibt: der Vermieter liest, welche Masse wo steht, und
    dass der Mieter 15 % kuerzen darf, solange er es nicht aufraeumt.
    """
    gemischt = (
        _zaehler(1, 1, 1200.0, WAERME),
        _zaehler(2, 2, 800.0, WAERME),
        _zaehler(3, 1, 30.0, WARMWASSER),
        _zaehler(4, 2, 6000.0, WARMWASSER, einheit='kWh'),
    )
    texte = ' | '.join(
        w if isinstance(w, str) else (w.get('text') or str(w))
        for w in (rechne(haus(gemischt)).get('warnings') or ()))

    assert 'verschiedene Maßeinheiten an den Zählern: kWh und m³' in texte
    assert 'ganz nach Wohnfläche verteilt' in texte
    assert '§ 12 Abs. 1 HeizkostenV' in texte
