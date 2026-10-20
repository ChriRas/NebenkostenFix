"""Phase 50: die Heizkostenrechnung, die niemand zugeordnet hat.

Der Fall kommt aus der Hausgeld-Runde (Live-Issue #30): der Vermieter einer
Eigentumswohnung bekommt vom Messdienst einen festen Betrag **fuer seine
Wohnung**. Traegt er ihn als Rechnung ein, ohne sie der Wohnung zuzuordnen,
teilt die App ihn nach Wohnflaeche auf alle Wohnungen des Objekts -- und
sagt nichts. Der Mieter zahlt dann einen Bruchteil dessen, was auf ihn
entfaellt, und der Vermieter bleibt auf dem Rest sitzen.

**Das ist derselbe stille Rechenfehler wie bei der Zahlungsart und den
gemischten Masseinheiten:** eine plausible Eingabe, ein falsches Ergebnis,
keine Fehlermeldung.

Der groesste Teil dieser Datei prueft, wann die Warnung **nicht** kommt.
Eine Warnung, die bei jedem erscheint, liest nach zwei Wochen niemand mehr
-- und dann hilft sie auch dem nicht, der sie braucht.

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
    rechne,
)

JAHR_BEGINN = date(2024, 1, 1)
JAHR_ENDE = date(2024, 12, 31)

#: Die drei Heizkostenarten des Katalogs: Nr. 4 Heizung, Nr. 5 Warmwasser,
#: Nr. 6 verbundene Anlage. Nur sie loesen die Warnung aus.
HEIZUNG = Kategorie(id=9, name='Heizung', braucht_zaehler=False, betrkv_nr=4)
WARMWASSER = Kategorie(id=10, name='Warmwasser', braucht_zaehler=False,
                       betrkv_nr=5)
VERBUNDEN = Kategorie(id=11, name='Heizung und Warmwasser',
                      braucht_zaehler=False, betrkv_nr=6)
#: Keine Heizkostenart -- eine ganz normale Rechnung fuers Haus.
HAUSWART = Kategorie(id=14, name='Hauswart', braucht_zaehler=False,
                     betrkv_nr=14)

LINKS = Wohnung(id=1, name='Whg. 3 OG', qm=72.0)
RECHTS = Wohnung(id=2, name='Whg. 1 OG', qm=48.0)
ANNA = Mieter(id=1, name='Anna Mieterin', einzug=date(2020, 1, 1),
              auszug=None, wohnung_id=1)
BERT = Mieter(id=2, name='Bert Nachbar', einzug=date(2020, 1, 1),
              auszug=None, wohnung_id=2)


def rechnung(kategorie=HEIZUNG, betrag='1686.50', wohnung_id=None,
             anlage_id=None, id=1):
    return Rechnung(
        id=id, kategorie=kategorie, betrag=Decimal(betrag),
        beginn=JAHR_BEGINN, ende=JAHR_ENDE,
        wohnung_id=wohnung_id, heizungsanlage_id=anlage_id)


def warnungen(rechnungen=None, wohnungen=(LINKS, RECHTS), mieter=(ANNA, BERT),
              anlagen=(), zaehler=()):
    """Die Warnungen der Abrechnung fuer Anna."""
    ergebnis = rechne(Vorgang(
        mieter=mieter[0], wohnung=wohnungen[0],
        immobilie_id=1, immobilie_name='Beispielweg 7',
        beginn=JAHR_BEGINN, ende=JAHR_ENDE,
        wohnungen=tuple(wohnungen), mieter_der_immobilie=tuple(mieter),
        profile={},
        rechnungen=tuple(rechnungen if rechnungen is not None
                         else (rechnung(),)),
        zaehler=tuple(zaehler), heizungsanlagen=tuple(anlagen)))
    return [w if isinstance(w, str) else (w.get('text') or str(w))
            for w in (ergebnis.get('warnings') or ())]


def hat_warnung(texte):
    return any('W-HEIZKOSTEN-OHNE-ZUORDNUNG' in t for t in texte)


# --- Der Fall, fuer den die Warnung da ist --------------------------------


def test_heizkostenrechnung_ohne_zuordnung_im_mehrfamilienhaus():
    """1.686,50 € Heizkosten, zwei Wohnungen, keine Zuordnung, keine Anlage.

    Die App teilt nach Wohnflaeche: Anna 72 von 120 qm = 1.011,90 €. Wenn
    der Betrag aber fuer **ihre** Wohnung galt, fehlen 674,60 €.
    """
    texte = warnungen()

    assert hat_warnung(texte)
    treffer = next(t for t in texte if 'W-HEIZKOSTEN-OHNE-ZUORDNUNG' in t)
    assert 'Heizung' in treffer
    assert 'Wohnfläche' in treffer
    # Der Weg hinaus steht dabei, nicht nur der Befund.
    assert 'Wohnung zu' in treffer or 'zuordnen' in treffer


def test_die_warnung_nennt_jede_betroffene_rechnung():
    """Zwei Rechnungen ohne Zuordnung -- zwei Warnungen, nicht eine pauschale."""
    texte = warnungen([
        rechnung(id=1, kategorie=HEIZUNG, betrag='1686.50'),
        rechnung(id=2, kategorie=WARMWASSER, betrag='420.00'),
    ])

    treffer = [t for t in texte if 'W-HEIZKOSTEN-OHNE-ZUORDNUNG' in t]
    assert len(treffer) == 2
    assert any('Heizung' in t for t in treffer)
    assert any('Warmwasser' in t for t in treffer)


def test_auch_die_verbundene_anlage_nach_nummer_6():
    texte = warnungen([rechnung(kategorie=VERBUNDEN)])

    assert hat_warnung(texte)


# --- Und jetzt: wann sie NICHT kommt --------------------------------------
# Das ist der wichtigere Teil. Eine Warnung, die bei jedem erscheint, liest
# nach zwei Wochen niemand mehr.


def test_nicht_wenn_die_rechnung_der_wohnung_zugeordnet_ist():
    """Der richtige Weg loest keine Warnung aus -- das ist der Normalfall."""
    texte = warnungen([rechnung(wohnung_id=1)])

    assert not hat_warnung(texte)


def test_nicht_wenn_das_objekt_nur_eine_wohnung_hat():
    """Bei einer Wohnung ist die Flaechenverteilung 100 % -- also richtig.

    Der Vermieter einer einzelnen Eigentumswohnung ist der haeufigste
    Nutzer dieses Wegs. Ihn zu warnen, wo nichts schiefgeht, waere genau
    die pauschale Warnung, die keiner mehr liest.
    """
    texte = warnungen(wohnungen=(LINKS,), mieter=(ANNA,))

    assert not hat_warnung(texte)


def test_nicht_wenn_die_rechnung_an_einer_heizungsanlage_haengt():
    """Mit Anlage gilt die HeizkostenV -- dafuer ist die App gebaut.

    Dann verteilt der Kern nach § 7 und § 8 und warnt mit seinen eigenen
    Meldungen, wenn die Erfassung unvollstaendig ist. Eine zweite Warnung
    daneben waere Laerm.
    """
    anlage = Heizungsanlage(
        id=1, name='Kessel', versorgt=heizung.HEIZUNG,
        verbrauchsanteil_prozent=70, warmwasser_weg=None,
        warmwasser_kwh=None, brennstoff_menge=None)
    zaehler = tuple(
        Zaehler(id=i, nummer=f'Z-{i}', kategorie_id=9,
                kategorie_name='Heizung', kategorie_betrkv_nr=4,
                ist_hauptzaehler=False, immobilie_id=1, wohnung_id=i,
                heizungsanlage_id=1,
                staende=(Stand(datum=JAHR_BEGINN, wert=0.0),
                         Stand(datum=date(2025, 1, 1), wert=1000.0 * i)))
        for i in (1, 2))
    texte = warnungen([rechnung(anlage_id=1)], anlagen=(anlage,),
                      zaehler=zaehler)

    assert not hat_warnung(texte)


def test_nicht_bei_einer_kostenart_ausserhalb_der_heizkosten():
    """Hauswart (Nr. 14) wird nach Flaeche verteilt, und das ist richtig so.

    Das ist die Probe gegen die pauschale Warnung: fast jede Abrechnung
    hat Rechnungen ohne Wohnungszuordnung. Nur bei den Heizkosten ist das
    ein Verdacht, weil der Messdienst je Wohnung abrechnet.
    """
    texte = warnungen([rechnung(kategorie=HAUSWART, betrag='2400.00')])

    assert not hat_warnung(texte)


def test_eine_gewoehnliche_abrechnung_bleibt_still():
    """Der Alltagsfall: Hauswart, Müll, Versicherung -- keine Warnung.

    Wenn dieser Test faellt, warnt die App zu viel.
    """
    texte = warnungen([
        rechnung(id=1, kategorie=HAUSWART, betrag='2400.00'),
        rechnung(id=2, kategorie=Kategorie(id=8, name='Müllbeseitigung',
                                           braucht_zaehler=False, betrkv_nr=8),
                 betrag='800.00'),
        rechnung(id=3, kategorie=Kategorie(id=13, name='Versicherung',
                                           braucht_zaehler=False,
                                           betrkv_nr=13),
                 betrag='1200.00'),
    ])

    assert texte == [] or not hat_warnung(texte)


def test_der_zugeordnete_und_der_offene_fall_nebeneinander():
    """Zwei Heizkostenrechnungen, eine zugeordnet -- nur eine Warnung.

    Genau der Stand, in dem ein Vermieter mitten in der Erfassung steckt:
    die eine Wohnung hat er schon, die andere noch nicht.
    """
    texte = warnungen([
        rechnung(id=1, betrag='1284.50', wohnung_id=1),
        rechnung(id=2, betrag='402.00'),
    ])

    treffer = [t for t in texte if 'W-HEIZKOSTEN-OHNE-ZUORDNUNG' in t]
    assert len(treffer) == 1
    assert '402,00' in treffer[0]
