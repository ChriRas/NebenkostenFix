"""Vorschlag zur Anpassung der Vorauszahlung nach einer Abrechnung (R-VZ-01, NK-226).

§ 560 Abs. 4 BGB: nach einer Abrechnung darf jede Seite die vereinbarte
Vorauszahlung auf eine angemessene Höhe anpassen. Angemessen ist hier der
Kostenanteil der Abrechnung je Monat, auf volle Euro gerundet, ohne
Zuschlag. Die Software schlägt vor, sie bucht nichts. Wo sie nichts
Belastbares sagen kann, nennt sie den Grund statt einer Zahl.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from nebenkostenfix.geld import CENT


def _heute() -> date:
    return date.today()


def monate(beginn: date, ende: date) -> Decimal:
    """Kalendermonate im Zeitraum, angebrochene tagesgenau."""
    summe = Decimal(0)
    jahr, monat = beginn.year, beginn.month
    while (jahr, monat) <= (ende.year, ende.month):
        tage = calendar.monthrange(jahr, monat)[1]
        von = beginn.day if (jahr, monat) == (beginn.year, beginn.month) else 1
        bis = ende.day if (jahr, monat) == (ende.year, ende.month) else tage
        summe += Decimal(bis - von + 1) / tage
        jahr, monat = (jahr + 1, 1) if monat == 12 else (jahr, monat + 1)
    return summe


def ab_datum(stichtag: date) -> date:
    """Der Erste des übernächsten Monats: der Zugang liegt sicher davor."""
    m = stichtag.month + 2
    return date(stichtag.year + (m - 1) // 12, (m - 1) % 12 + 1, 1)


def bisherige_hoehe(zahlungen) -> Decimal:
    """Die bisherige monatliche Vorauszahlung aus den gebuchten Zahlungen.

    Je Monat summiert, so sind zwei Teilzahlungen ein Monatsbetrag. Von den
    letzten drei Monaten mit Zahlung zählt der häufigste Betrag, bei
    Gleichstand der jüngste: eine einzelne Sammel- oder Teilzahlung
    verfälscht die Höhe nicht (NK-237).
    """
    # Eine Erhöhung zählt hier erst ab dem zweiten Monat; mit laufender
    # Serienbuchung gilt vorher laufende_hoehe (NK-259).
    je_monat = {}
    for tag, betrag in zahlungen:
        monat = (tag.year, tag.month)
        je_monat[monat] = je_monat.get(monat, Decimal(0)) + Decimal(betrag)
    letzte = [je_monat[m] for m in sorted(je_monat)[-3:]]
    return max(reversed(letzte), key=letzte.count)


def laufende_hoehe(zahlungen, stichtag: date) -> Decimal | None:
    """Die Höhe der laufenden Serienbuchung, oder None ohne eine (NK-259).

    Was für den Monat nach dem Stichtag schon gebucht ist, kommt aus einer
    Serienbuchung; erfasst wird sonst nur, was gezahlt ist. Deren Monatsbetrag
    gilt sofort, auch wenn die Erhöhung erst in diesem Monat begann.
    """
    naechster = ab_datum(stichtag) - timedelta(days=1)
    gebucht = [Decimal(b) for d, b in zahlungen
               if (d.year, d.month) == (naechster.year, naechster.month)]
    return sum(gebucht) if gebucht else None


def vorschlag(kosten, beginn: date, ende: date, auszug: date | None,
              zahlungen, stichtag: date | None = None,
              teilauswahl: bool = False) -> dict:
    """Der Vorschlag, oder ``{'grund': ...}``, wenn es keinen gibt.

    ``zahlungen`` sind die gebuchten Nebenkostenvorauszahlungen des Mieters
    als (Datum, Betrag); die bis zum Stichtag ergeben die bisherige Höhe.
    Ohne Stichtag gilt heute.
    """
    if stichtag is None:
        stichtag = _heute()
    if teilauswahl:
        return {'grund': 'Die Abrechnung umfasst nicht alle Kostenarten mit '
                         'Rechnungen im Zeitraum, ein Monatsbetrag daraus wäre '
                         'zu niedrig.'}
    bisherige = sorted((d, b) for d, b in zahlungen if d <= stichtag)
    if not bisherige:
        return {'grund': 'Keine Nebenkostenvorauszahlung gebucht. Anpassen lässt '
                         'sich nur eine vereinbarte Vorauszahlung (§ 560 Abs. 4 BGB).'}
    ab = ab_datum(stichtag)
    if auszug is not None and auszug < ab:
        return {'grund': f'Der Auszug liegt vor dem {ab:%d.%m.%Y}.'}
    anzahl = monate(beginn, ende)
    bisher = laufende_hoehe(zahlungen, stichtag) or bisherige_hoehe(bisherige)
    neu = (Decimal(kosten) / anzahl).quantize(Decimal('1'), ROUND_HALF_UP)
    return {
        'ab': ab.isoformat(),
        'bisher': f'{bisher:.2f}',
        'neu': f'{neu:.2f}',
        'kosten': f'{Decimal(kosten):.2f}',
        'monate': f'{anzahl:.2f}',
        'kuenftige': sum(1 for d, _ in zahlungen if d >= ab),
        'aenderung': neu != bisher,
    }


# --- Soll und Ist je Monat (R-VZ-02, NK-261) -----------------------------------

def _soll_im_monat(soll, jahr: int, monat: int, einzug: date,
                   auszug: date | None) -> Decimal | None:
    """Das Soll des Monats tagesgenau, oder None ohne gültigen Eintrag.

    Jeder Tag im Mietverhältnis trägt den Monatsbetrag, der an ihm gilt,
    geteilt durch die Tage des Monats: Ein- und Auszug im Monat und eine
    Änderung zur Monatsmitte rechnen anteilig (wie ``monate``).
    """
    tage = calendar.monthrange(jahr, monat)[1]
    summe, gilt = Decimal(0), False
    for tag in range(1, tage + 1):
        d = date(jahr, monat, tag)
        if d < einzug or (auszug is not None and d > auszug):
            continue
        betrag = next((b for ab, b in reversed(soll) if ab <= d), None)
        if betrag is not None:
            summe += Decimal(betrag)
            gilt = True
    return (summe / tage).quantize(CENT, ROUND_HALF_UP) if gilt else None


def soll_ist(soll, zahlungen, einzug: date, auszug: date | None,
             heute: date) -> dict:
    """Je Monat vom Einzug bis heute (oder Auszug): Soll gegen Ist.

    ``soll`` sind die hinterlegten Monatsbeträge als (gültig ab, Betrag),
    ``zahlungen`` die erfassten Nebenkostenvorauszahlungen als (Datum,
    Betrag). Gezählt wird nur, was erfasst ist -- keine Bankdaten. Der
    laufende Monat steht da, ist aber noch nicht fällig und zählt nicht.
    Monate ohne Soll zählen auch nicht: ohne Soll gibt es keinen Rückstand.
    """
    soll = sorted(soll)
    ist_je_monat = {}
    for tag, betrag in zahlungen:
        monat = (tag.year, tag.month)
        ist_je_monat[monat] = ist_je_monat.get(monat, Decimal(0)) + Decimal(betrag)
    ende = min(auszug, heute) if auszug is not None else heute
    zeilen, offen, ueber = [], Decimal(0), Decimal(0)
    jahr, monat = einzug.year, einzug.month
    while (jahr, monat) <= (ende.year, ende.month):
        s = _soll_im_monat(soll, jahr, monat, einzug, auszug)
        i = ist_je_monat.get((jahr, monat), Decimal(0))
        laufend = (jahr, monat) == (heute.year, heute.month)
        zeile = {'monat': f'{jahr:04d}-{monat:02d}', 'soll': None, 'ist': f'{i:.2f}',
                 'differenz': None, 'rueckstand': False, 'laufend': laufend}
        if s is not None:
            zeile['soll'], zeile['differenz'] = f'{s:.2f}', f'{i - s:.2f}'
            if not laufend and i < s:
                offen += s - i
                zeile['rueckstand'] = True
            elif not laufend:
                ueber += i - s
        zeilen.append(zeile)
        jahr, monat = (jahr + 1, 1) if monat == 12 else (jahr, monat + 1)
    return {'monate': zeilen, 'offen': f'{offen:.2f}',
            'ueberzahlt': f'{ueber:.2f}', 'saldo': f'{offen - ueber:.2f}'}


def _euro(betrag) -> str:
    return f'{Decimal(betrag):.2f}'.replace('.', ',') + ' €'


def erinnerung(ergebnis: dict, anrede: str, wohnung: str, konto: str,
               vermieter: str | None) -> str | None:
    """Die Vorlage „Zahlungserinnerung“ als Text, oder None ohne Rückstand.

    Ein Vorschlag zum Kopieren: der Vermieter liest und ändert ihn, bevor er
    ihn verschickt. Überzahlte Monate werden gegengerechnet.
    """
    saldo = Decimal(ergebnis['saldo'])
    if saldo <= 0:
        return None
    zeilen = [
        f"  {m['monat'][5:]}/{m['monat'][:4]}: fällig {_euro(m['soll'])}, "
        f"gezahlt {_euro(m['ist'])}, offen {_euro(-Decimal(m['differenz']))}"
        for m in ergebnis['monate'] if m['rueckstand']]
    if Decimal(ergebnis['ueberzahlt']) > 0:
        zeilen.append(f"  abzüglich Überzahlungen anderer Monate: "
                      f"{_euro(ergebnis['ueberzahlt'])}")
    gruss = f'\n\nMit freundlichen Grüßen\n{vermieter}' if vermieter else \
        '\n\nMit freundlichen Grüßen'
    return (
        f'{anrede}\n\n'
        f'für die Wohnung {wohnung} sind folgende Nebenkostenvorauszahlungen '
        f'noch nicht vollständig eingegangen:\n\n'
        + '\n'.join(zeilen) +
        f'\n\nOffen sind insgesamt {_euro(saldo)}. Bitte überweisen Sie den '
        f'Betrag innerhalb von 14 Tagen auf {konto}. Hat sich Ihre Zahlung '
        f'mit diesem Schreiben überschnitten, betrachten Sie es bitte als '
        f'gegenstandslos.'
        + gruss
    )
