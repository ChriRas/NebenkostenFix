"""Die Hausgeld-Einzelabrechnung als Quelle (Phase 50, Live-Issue #30).

Der Vermieter einer Eigentumswohnung bekommt vom Verwalter eine
Einzelabrechnung und macht daraus die Betriebskostenabrechnung fuer seinen
Mieter. Dieses Modul nimmt ihm die zwei Pruefungen ab, die dabei zaehlen:

1. **Darf ich das weitergeben?** Die Hausgeldabrechnung enthaelt Positionen,
   die nach § 1 Abs. 2 BetrKV beim Eigentuemer bleiben -- Verwaltervergütung,
   Erhaltungsrücklage, Instandsetzung. Wer sie mit umlegt, hat eine
   angreifbare Abrechnung (R-KAT-01).
2. **Stimmt mein Anteil?** Der eigene Betrag muss Gesamtbetrag · eigener
   Anteil / Gesamtanteile sein. Ein Verwalterfehler wandert sonst unbemerkt
   in die Mieterabrechnung weiter.

**Was dieses Modul nicht tut.** Es prueft keine WEG-Abrechnung nach § 28 WEG
-- kein Wirtschaftsplan, keine Rücklagen, keine Untergemeinschaften, keine
Abgrenzung gegen das Abflussprinzip der Gesamtabrechnung. Das liegt
ausserhalb dessen, was diese Anwendung leisten will. Hier geht es nur um
den Ausschnitt, den der Vermieter fuer seinen Mieter braucht.

Und es entscheidet nichts allein: ``einschaetzung`` ist ein Vorschlag, den
der Vermieter bestaetigt. Eine Position, die weder im Katalog noch auf der
Sperrliste steht, bleibt ausdruecklich **offen** -- nicht umlagefaehig und
nicht gesperrt, sondern eine Frage an den Mietvertrag (R-KAT-02).

Geld ist ``Decimal``, wie im ganzen Kern. Ohne Datenbank.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Sequence

from nebenkostenfix import betrkv
from nebenkostenfix.geld import NULL, dec, runde, summe

__all__ = [
    'HausgeldFehler',
    'Probe',
    'Rat',
    'Position',
    'Bericht',
    'RUNDUNGSGRENZE',
    'HEIZKOSTEN_HINWEIS',
    'ZEITRAUM_HINWEIS',
    'pruefe_position',
    'pruefe_summe',
    'einschaetzung',
    'uebernahme',
]


class HausgeldFehler(ValueError):
    """Eine Angabe aus der Einzelabrechnung, mit der nicht zu rechnen ist."""


#: Bis hierher ist eine Abweichung Rundung des Verwalters und kein Fehler.
#: Jeder Verwalter rundet anders, und seine Summe muss am Ende aufgehen --
#: ein Cent-Hinweis je Position waere nur Laerm. Ein Euro ist die Grenze,
#: ab der es nicht mehr Rundung sein kann (Plan Phase 50).
RUNDUNGSGRENZE = Decimal('1.00')


#: Der Hinweis zum Abrechnungszeitraum. Die WEG rechnet nach dem
#: Abflussprinzip ueber das Kalenderjahr -- sie verteilt, was im Jahr
#: bezahlt wurde, nicht was im Jahr verbraucht wurde. Fuer die
#: Betriebskostenabrechnung ist das nach BGH VIII ZR 27/07 zulaessig.
#: Offen bleibt es beim Mieterwechsel: dann traegt ein Mieter eine
#: Rechnung, die in die Zeit des anderen gehoerte. Darauf weist die App
#: hin, statt es stillschweigend zu uebernehmen.
#: Wohin die Heizkosten gehoeren. Der Messdienst rechnet sie getrennt ab
#: und nennt einen festen Betrag je Wohnung -- in der Hausgeldabrechnung
#: stehen sie oft nur als Sammelposten. Der Weg dafuer ist in der App
#: vorhanden: eine Rechnung, die **einer Wohnung zugeordnet** ist, geht
#: ungeteilt an deren Mieter ("Direkt zugewiesen"). Ohne die Zuordnung
#: verteilt der Kern sie nach Wohnflaeche auf alle Wohnungen des Objekts
#: -- rechnerisch sauber und fachlich falsch, und ohne Fehlermeldung.
#: Deshalb steht der Satz hier und nicht nur in der Hilfe.
HEIZKOSTEN_HINWEIS = (
    'Die Heizkosten aus der Abrechnung Ihres Messdienstes gehören nicht in '
    'diese Liste. Tragen Sie sie als eigene Rechnung ein und ordnen Sie '
    'diese Rechnung der Wohnung zu — dann geht der Betrag ungeteilt an '
    'Ihren Mieter. Ohne die Zuordnung wird er nach Wohnfläche auf alle '
    'Wohnungen des Objekts verteilt.')


ZEITRAUM_HINWEIS = (
    'Die Hausgeldabrechnung verteilt, was im Kalenderjahr bezahlt wurde, '
    'nicht was in ihm verbraucht wurde (Abflussprinzip). Für die '
    'Betriebskostenabrechnung ist das zulässig (BGH, Urteil vom 20.02.2008, '
    'VIII ZR 27/07). Prüfen Sie es aber, wenn in diesem Zeitraum ein '
    'Mieterwechsel lag: dann kann eine Rechnung in die Zeit des anderen '
    'Mieters gehören.')


#: Positionen, die nach § 1 Abs. 2 BetrKV beim Eigentuemer bleiben, als
#: Wortmuster auf dem Positionsnamen. Die Liste ist bewusst breit: sie
#: findet "Verwaltervergütung", "Verwaltergebühr" und "Kosten der
#: Verwaltung", und sie **schlaegt den Katalog** -- eine Reparatur bleibt
#: Instandsetzung, auch wenn der Hausmeister sie macht.
#:
#: Jeder Eintrag nennt seinen Grund, denn der Vermieter soll nicht lesen
#: "unbekannt", sondern warum er das nicht weitergeben darf.
EIGENTUEMERPOSITIONEN = (
    (r'verwalt(er|ung)', 'Verwaltungskosten'),
    (r'(erhaltungs|instandhaltungs)r(ü|ue)cklage', 'Zuführung zur Rücklage'),
    (r'r(ü|ue)cklage', 'Zuführung zur Rücklage'),
    (r'instand(haltung|setzung|halten)', 'Instandhaltung und Instandsetzung'),
    (r'reparatur', 'Instandhaltung und Instandsetzung'),
    (r'sanierung', 'Instandhaltung und Instandsetzung'),
    (r'kontof(ü|ue)hrung', 'Kosten der Kontoführung'),
    (r'(eigent(ü|ue)mer)?versammlung', 'Kosten der Eigentümerversammlung'),
    (r'rechts(beratung|anwalt|verfolgung)|gerichts', 'Rechtsverfolgungskosten'),
    (r'beirat', 'Vergütung des Verwaltungsbeirats'),
)

_GESPERRT = tuple((re.compile(muster, re.I), grund)
                  for muster, grund in EIGENTUEMERPOSITIONEN)

_GRUND_SPERRE = (
    '{was} gehören nach § 1 Abs. 2 BetrKV nicht zu den Betriebskosten — '
    'sie bleiben beim Eigentümer und dürfen nicht auf den Mieter umgelegt '
    'werden.')
_GRUND_KATALOG = (
    'Betriebskosten nach § 2 Nr. {nr} BetrKV ({bezeichnung}) — umlagefähig, '
    'wenn der Mietvertrag die Umlage vorsieht.')
_GRUND_OFFEN = (
    'Diese Position steht in keiner Nummer des Katalogs nach § 2 BetrKV. '
    'Umlagefähig ist sie nur, wenn der Mietvertrag sie ausdrücklich nennt; '
    'dann gehört sie unter „Sonstige Betriebskosten" (Nr. 17). Prüfen Sie '
    'den Mietvertrag, bevor Sie sie übernehmen.')


def _geld(wert, feld: str) -> Decimal:
    """Ein Geldbetrag aus der Abrechnung, oder ein verstaendlicher Fehler."""
    try:
        return dec(wert)
    except Exception as fehler:          # noqa: BLE001 -- jede Ursache gleich
        raise HausgeldFehler(
            f'{feld}: „{wert}" ist kein Betrag.') from fehler


def _anteil(wert, feld: str) -> Decimal:
    """Eine Anteilszahl -- MEA, Quadratmeter, Einheiten, Verbrauch."""
    zahl = _geld(wert, feld)
    if zahl < NULL:
        raise HausgeldFehler(f'{feld} kann nicht negativ sein.')
    return zahl


@dataclass(frozen=True)
class Probe:
    """Das Ergebnis einer Nachrechnung: erwartet, angesetzt, Abweichung."""

    erwartet: Decimal
    angesetzt: Decimal
    abweichung: Decimal
    stimmt: bool
    hinweis: Optional[str] = None


def _zahl(betrag: Decimal) -> str:
    """Ein Betrag, wie er in der Abrechnung steht: 1.234,56."""
    return f'{betrag:,.2f}'.replace(',', '\x00').replace(
        '.', ',').replace('\x00', '.')


def _probe(erwartet: Decimal, angesetzt: Decimal, satz: str) -> Probe:
    abweichung = abs(erwartet - angesetzt)
    stimmt = abweichung <= RUNDUNGSGRENZE
    return Probe(
        erwartet=erwartet, angesetzt=angesetzt, abweichung=abweichung,
        stimmt=stimmt,
        hinweis=None if stimmt else satz.format(
            erwartet=_zahl(erwartet), angesetzt=_zahl(angesetzt),
            abweichung=_zahl(abweichung)))


def pruefe_position(*, gesamtbetrag, eigener_anteil, gesamtanteile,
                    eigener_betrag) -> Probe:
    """Rechnet den eigenen Betrag einer Position nach.

    Gesamtbetrag · eigener Anteil / Gesamtanteile, kaufmaennisch auf den
    Cent gerundet wie im ganzen Kern. Welcher Schluessel dahintersteht --
    Miteigentumsanteile, Quadratmeter, Einheiten, Verbrauch -- ist dafuer
    gleichgueltig: gerechnet wird immer dasselbe Verhaeltnis.

    >>> pruefe_position(gesamtbetrag='2400.00', eigener_anteil='125',
    ...                 gesamtanteile='1000', eigener_betrag='300.00').stimmt
    True
    """
    gesamt = _geld(gesamtbetrag, 'Gesamtbetrag')
    mein = _anteil(eigener_anteil, 'Eigener Anteil')
    alle = _anteil(gesamtanteile, 'Gesamtanteile')
    angesetzt = _geld(eigener_betrag, 'Eigener Betrag')

    if alle == NULL:
        raise HausgeldFehler(
            'Gesamtanteile: ohne Gesamtanteile lässt sich kein Anteil '
            'bilden. Tragen Sie ein, auf wie viele Anteile der '
            'Gesamtbetrag verteilt wurde.')
    if mein > alle:
        raise HausgeldFehler(
            f'Eigener Anteil: {_zahl(mein)} ist mehr als die Gesamtanteile '
            f'({_zahl(alle)}). Vermutlich sind die beiden vertauscht.')

    return _probe(
        runde(gesamt * mein / alle), angesetzt,
        'Erwartet waren {erwartet} €, angesetzt sind {angesetzt} € — '
        'eine Abweichung von {abweichung} €. Prüfen Sie den Anteil und '
        'den Gesamtbetrag dieser Position.')


def pruefe_summe(eigene_betraege: Sequence, abrechnungssumme) -> Probe:
    """Prueft, ob die uebernommenen Positionen die Endsumme ergeben.

    Der haeufigste Uebertragungsfehler ist die vergessene Zeile, und den
    findet keine Einzelprobe -- nur diese.
    """
    erwartet = _geld(abrechnungssumme, 'Abrechnungssumme')
    gezaehlt = summe(_geld(b, 'Eigener Betrag') for b in eigene_betraege)
    return _probe(
        erwartet, gezaehlt,
        'Die Einzelabrechnung endet auf {erwartet} €, übernommen sind '
        '{angesetzt} € — es fehlen oder stehen {abweichung} € zu viel. '
        'Vergleichen Sie, ob jede Position erfasst ist.')


@dataclass(frozen=True)
class Rat:
    """Ein Vorschlag zur Umlagefaehigkeit -- der Vermieter bestaetigt ihn.

    ``umlagefaehig`` ist absichtlich dreiwertig: ``True`` (im Katalog),
    ``False`` (§ 1 Abs. 2 BetrKV) und ``None`` (weder noch -- eine Frage an
    den Mietvertrag, nicht an die App).
    """

    name: str
    umlagefaehig: Optional[bool]
    betrkv_nr: Optional[int]
    begruendung: str


def einschaetzung(name) -> Rat:
    """Schaetzt ein, ob eine Position der Hausgeldabrechnung umlagefaehig ist.

    Die Sperrliste kommt **vor** dem Katalog: "Hausmeister-Reparaturen"
    deutet auf Nr. 14, bleibt aber Instandsetzung. Umgekehrt waere der
    Fehler teuer -- eine gesperrte Position, die unter einer Katalognummer
    durchrutscht, steht am Ende in der Mieterabrechnung.
    """
    wort = (name or '').strip()
    if not wort:
        return Rat(name=wort, umlagefaehig=None, betrkv_nr=None,
                   begruendung=_GRUND_OFFEN)

    for muster, grund in _GESPERRT:
        if muster.search(wort):
            return Rat(name=wort, umlagefaehig=False, betrkv_nr=None,
                       begruendung=_GRUND_SPERRE.format(was=grund))

    nummer = betrkv.nummernvorschlag(wort)
    if nummer is None:
        return Rat(name=wort, umlagefaehig=None, betrkv_nr=None,
                   begruendung=_GRUND_OFFEN)
    return Rat(name=wort, umlagefaehig=True, betrkv_nr=nummer,
               begruendung=_GRUND_KATALOG.format(
                   nr=nummer, bezeichnung=betrkv.bezeichnung(nummer)))


@dataclass(frozen=True)
class Position:
    """Eine Zeile der Einzelabrechnung mit Einschaetzung und Nachrechnung."""

    name: str
    gesamtbetrag: Decimal
    eigener_betrag: Decimal
    rat: Rat
    probe: Probe


@dataclass(frozen=True)
class Bericht:
    """Was aus einer Einzelabrechnung fuer den Mieter uebrig bleibt."""

    positionen: list = field(default_factory=list)
    umlagefaehig: list = field(default_factory=list)
    beim_eigentuemer: list = field(default_factory=list)
    offen: list = field(default_factory=list)
    summe_umlagefaehig: Decimal = NULL
    summe_eigentuemer: Decimal = NULL
    summe_offen: Decimal = NULL
    summenprobe: Optional[Probe] = None


def uebernahme(positionen: Sequence[dict], *, eigener_anteil, gesamtanteile,
               abrechnungssumme=None) -> Bericht:
    """Rechnet eine ganze Einzelabrechnung durch.

    Jede Position bekommt ihre Einschaetzung und ihre Nachrechnung; die
    Summen sind nach den drei Faellen getrennt. Eine offene Position zaehlt
    in **keine** der beiden Summen -- sie wartet auf den Vermieter, und
    stillschweigend einsortiert wird nichts.

    ``abrechnungssumme`` ist die Endsumme der Einzelabrechnung. Ohne sie
    entfaellt die Summenprobe; nicht jede Abrechnung nennt eine.
    """
    gezaehlt: list = []
    for zeile in positionen:
        name = zeile.get('name') or ''
        gesamt = _geld(zeile.get('gesamtbetrag'), f'Gesamtbetrag ({name})')
        mein = _geld(zeile.get('eigener_betrag'), f'Eigener Betrag ({name})')
        gezaehlt.append(Position(
            name=name, gesamtbetrag=gesamt, eigener_betrag=mein,
            rat=einschaetzung(name),
            probe=pruefe_position(
                gesamtbetrag=gesamt, eigener_anteil=eigener_anteil,
                gesamtanteile=gesamtanteile, eigener_betrag=mein)))

    nach_fall = {True: [], False: [], None: []}
    for posten in gezaehlt:
        nach_fall[posten.rat.umlagefaehig].append(posten)

    return Bericht(
        positionen=gezaehlt,
        umlagefaehig=nach_fall[True],
        beim_eigentuemer=nach_fall[False],
        offen=nach_fall[None],
        summe_umlagefaehig=summe(p.eigener_betrag for p in nach_fall[True]),
        summe_eigentuemer=summe(p.eigener_betrag for p in nach_fall[False]),
        summe_offen=summe(p.eigener_betrag for p in nach_fall[None]),
        summenprobe=(
            None if abrechnungssumme is None else pruefe_summe(
                [p.eigener_betrag for p in gezaehlt], abrechnungssumme)))
