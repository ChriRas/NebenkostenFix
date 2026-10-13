"""Mehrjahresblick je Wohnung (NK-263).

Je Abrechnungsjahr des Hauses: Euro je m² und Jahr je Kostenart und die
Summe der Vorauszahlungen. Die Zahlen kommen aus den festgesetzten
Abrechnungen der Wohnung, nicht aus einer neuen Rechnung -- der Blick zeigt,
was abgerechnet wurde. Die Abfragen macht ``app.py``; dieses Modul rechnet
nur und bleibt ohne Datenbank pruefbar.

Hochgerechnet wird ueber die belegten Flaechentage: ein halbes Jahr Leerstand
halbiert die Kosten, aber nicht den Wert je m² und Jahr. Aendert sich die
Wohnflaeche, zaehlt jede Abrechnung mit der Flaeche, auf der sie stand.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from nebenkostenfix.geld import dec, runde, summe


def jahresanfang(tag: date, monat: int, erster: int) -> date:
    """Beginn des Abrechnungsjahres (Monat, Tag), in dem ``tag`` liegt."""
    start = date(tag.year, monat, erster)
    return start if start <= tag else date(tag.year - 1, monat, erster)


def _bezeichnung(anfang: date) -> str:
    """'2024' beim Kalenderjahr, sonst '2023/24'."""
    if (anfang.month, anfang.day) == (1, 1):
        return str(anfang.year)
    return f'{anfang.year}/{(anfang.year + 1) % 100:02d}'


def _leer():
    return {'tage': 0, 'flaechentage': dec(0), 'kosten': defaultdict(lambda: dec(0)),
            'vorauszahlung': dec(0)}


def verlauf(abrechnungen, monat: int, erster: int) -> list[dict]:
    """Die Jahre vom ersten bis zum letzten abgerechneten, aufsteigend.

    ``abrechnungen``: (beginn, ende, qm, [(kostenart, betrag)], vorauszahlung)
    je Abrechnung der Wohnung, ``ende`` einschliesslich. Ein Jahr ohne
    Abrechnung dazwischen steht mit null Tagen da, damit die Luecke sichtbar
    bleibt. Ohne Flaeche gibt es keinen Wert je m² (``None``).
    """
    jahre = defaultdict(_leer)
    # shortcut: eine Abrechnung zaehlt ganz zum Jahr ihres Beginns; liegt sie
    # ueber einer Jahresgrenze (Jahresbeginn spaeter umgestellt), steht sie
    # nicht anteilig in beiden Jahren -- aufteilen, wenn das vorkommt.
    for beginn, ende, qm, kosten, vorauszahlung in abrechnungen:
        j = jahre[jahresanfang(beginn, monat, erster)]
        tage = (ende - beginn).days + 1
        j['tage'] += tage
        # Fehlt einer Abrechnung die Flaeche, fehlt sie dem Jahr: ihre Kosten
        # zaehlen, ihre Tage nicht -- der Wert je m² waere zu hoch (NK-269).
        if qm and j['flaechentage'] is not None:
            j['flaechentage'] += dec(qm) * tage
        else:
            j['flaechentage'] = None
        for art, betrag in kosten:
            j['kosten'][art] += dec(betrag)
        j['vorauszahlung'] += dec(vorauszahlung or 0)
    if not jahre:
        return []

    anfang, letztes = min(jahre), max(jahre)
    liste = []
    while anfang <= letztes:
        naechstes = date(anfang.year + 1, monat, erster)
        jahrestage = (naechstes - anfang).days
        j = jahre.get(anfang) or _leer()
        flaeche = j['flaechentage']
        liste.append({
            'jahr': _bezeichnung(anfang),
            'von': anfang.isoformat(),
            'bis': (naechstes - timedelta(days=1)).isoformat(),
            'belegte_tage': j['tage'],
            'jahrestage': jahrestage,
            'je_qm': {art: (str(runde(betrag * jahrestage / flaeche)) if flaeche else None)
                      for art, betrag in sorted(j['kosten'].items())},
            'je_qm_gesamt': (str(runde(summe(j['kosten'].values()) * jahrestage / flaeche))
                             if flaeche and j['kosten'] else None),
            'vorauszahlung': str(runde(j['vorauszahlung'])),
        })
        anfang = naechstes
    return liste
