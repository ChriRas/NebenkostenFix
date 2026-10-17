"""Fristenkalender (NK-262, R-FRIST-05).

Der Kalender erfindet keine Frist. Er sammelt Daten, die andere Regeln
schon festlegen, und gibt sie als Liste oder als ``.ics``-Datei nach
RFC 5545 heraus. Die Eingaben sind schlichte Tupel; die Abfragen macht
``app.py``, damit dieses Modul ohne Datenbank pruefbar bleibt.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from nebenkostenfix.frist import einwendungsfrist
from nebenkostenfix.zeitraum import ein_jahr_nach

PRODID = '-//NebenkostenFix//Fristenkalender//DE'


def naechste_ablesung(letztes_ende: date) -> date:
    """Ende des Zeitraums, der auf den zuletzt abgerechneten folgt.

    Er beginnt am Tag nach ``letztes_ende`` und dauert ein Jahr; der
    Schalttag zaehlt mit (``ein_jahr_nach``): auf den 28.02.2023 folgt der
    29.02.2024, nicht der 28.02.
    """
    return ein_jahr_nach(letztes_ende + timedelta(days=1)) - timedelta(days=1)


def _monate_weiter(d: date, monate: int) -> date:
    """``d`` um Kalendermonate weiter; ein fehlender Tag klemmt ans Monatsende.

    Auf den 31.01. folgt 15 Monate spaeter der 30.04.: der Monat hat keinen
    31., und die Frist rutscht deshalb nicht in den Folgemonat.
    """
    gesamt = d.month - 1 + monate
    jahr, monat = d.year + gesamt // 12, gesamt % 12 + 1
    letzter = calendar.monthrange(jahr, monat)[1]
    return date(jahr, monat, min(d.day, letzter))


def mietanpassung(letzte: date, indexmiete: bool = False) -> date:
    """Der frueheste Tag, an dem die naechste Erhoehung verlangt werden darf.

    § 558 BGB: mindestens 15 Monate muessen seit der letzten Erhoehung
    vergangen sein -- am 15-Monats-Tag selbst ist es so weit. Bei der
    Indexmiete nach § 557b BGB reicht ein Jahr seit der letzten Aenderung.
    """
    return _monate_weiter(letzte, 12 if indexmiete else 15)


def termine(berichte, letzte_zeitraeume, soll, zaehler, heute: date,
            kaltmiete=None) -> list[dict]:
    """Alle Termine ab ``heute``, nach Datum sortiert.

    ``berichte``: (id, wer, frist_ende, zugestellt_am) je Abrechnung.
    ``letzte_zeitraeume``: (haus_id, haus, Ende des letzten Zeitraums).
    ``soll``: (id, wer, gueltig_ab, betrag) je Vorauszahlungs-Soll.
    ``zaehler``: (id, was, geeicht_bis) je Zaehler, der nicht abgeloest ist.
    ``kaltmiete``: (id, wer, gueltig_ab, indexmiete) je Kaltmiete-Soll --
    nur der juengste Stichtag je Mieter, er ist die letzte Erhoehung.
    """
    liste = []

    def neu(art, schluessel, datum, titel):
        if datum >= heute:
            liste.append({'datum': datum.isoformat(), 'art': art, 'titel': titel,
                          'uid': f'{art}-{schluessel}@nebenkostenfix'})

    for rid, wer, frist_ende, zugestellt_am in berichte:
        if zugestellt_am is None:
            # Ohne Zugang zaehlt die Abrechnungsfrist; die Einwendungsfrist
            # gibt es erst mit Zugang -- geschaetzt wird nicht (R-FRIST-05).
            neu('abrechnungsfrist', rid, frist_ende, f'Ende der Abrechnungsfrist: {wer}')
        else:
            neu('einwendungsfrist', rid, einwendungsfrist(zugestellt_am),
                f'Ende der Einwendungsfrist: {wer}')
    for hid, haus, ende in letzte_zeitraeume:
        tag = naechste_ablesung(ende)
        while tag < heute:  # ein Jahr nicht abgerechnet: der Stichtag laeuft weiter
            tag = naechste_ablesung(tag)
        neu('ablesung', f'{hid}-{tag:%Y%m%d}', tag,
            f'Zähler ablesen: {haus} (Ende des Abrechnungszeitraums)')
    for sid, wer, ab, betrag in soll:
        euro = f'{betrag:.2f}'.replace('.', ',')
        neu('vorauszahlung', sid, ab, f'Neue Vorauszahlung: {wer}, {euro} € je Monat')
    for zid, was, bis in zaehler:
        neu('eichfrist', zid, bis, f'Eichfrist endet: {was}')
    for kid, wer, ab, indexmiete in (kaltmiete or []):
        tag = mietanpassung(ab, indexmiete)
        neu('mietanpassung', kid, tag, f'Früheste Mieterhöhung: {wer}')
    return sorted(liste, key=lambda t: (t['datum'], t['titel']))


def _text(wert: str) -> str:
    """TEXT nach RFC 5545 3.3.11: Backslash, Semikolon, Komma, Zeilenumbruch."""
    return (wert.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
            .replace('\n', '\\n'))


def _falten(zeile: str) -> str:
    """Zeilen ueber 75 Oktette falten (RFC 5545 3.1), ohne UTF-8 zu teilen."""
    teile, aktuell = [], ''
    for zeichen in zeile:
        grenze = 74 if teile else 75  # die Folgezeile beginnt mit einem Leerzeichen
        if len((aktuell + zeichen).encode('utf-8')) > grenze:
            teile.append(aktuell)
            aktuell = zeichen
        else:
            aktuell += zeichen
    teile.append(aktuell)
    return '\r\n '.join(teile)


def ics(liste: list[dict], jetzt_utc: datetime) -> str:
    """Die Termine als VCALENDAR mit ganztaegigen VEVENTs.

    ``DTSTART;VALUE=DATE`` ohne Uhrzeit: ein Fristende rutscht durch keine
    Zeitzone auf den Vortag. Ohne DTEND dauert der Termin einen Tag.
    """
    stempel = jetzt_utc.strftime('%Y%m%dT%H%M%SZ')
    zeilen = ['BEGIN:VCALENDAR', 'VERSION:2.0', f'PRODID:{PRODID}', 'CALSCALE:GREGORIAN',
              'METHOD:PUBLISH']
    for t in liste:
        zeilen += ['BEGIN:VEVENT', f'UID:{t["uid"]}', f'DTSTAMP:{stempel}',
                   f'DTSTART;VALUE=DATE:{t["datum"].replace("-", "")}',
                   f'SUMMARY:{_text(t["titel"])}', 'TRANSP:TRANSPARENT', 'END:VEVENT']
    zeilen.append('END:VCALENDAR')
    return ''.join(_falten(z) + '\r\n' for z in zeilen)
