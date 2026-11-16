"""Der Wechseltag eines Nachfolgezählers (NK-258).

Beim Zählerwechsel stehen Endstand des alten und Anfangsstand des neuen
Zählers am selben Tag. Der Rechenkern hängt den neuen Zähler an seinem
frühesten Stand an den alten. Ein Stand am Nachfolger vor dem Wechseltag
verschöbe diesen Anschluss, und der Verbrauch des alten Zählers ginge
verloren. Formular, Berichtigung und Tabellenimport weisen ihn deshalb ab.

Das Modul hängt nur an ``models``, damit ``app`` und ``tabellenimport`` es
ohne Zirkelimport nutzen können.
"""

from __future__ import annotations

from datetime import date


def wechseltag(zaehler) -> date | None:
    """Der Tag des letzten Stands am Vorgänger, also der Endstand aus dem Wechsel.

    None, wenn der Zähler keinen ersetzt oder der Vorgänger keinen Stand hat.
    """
    if not zaehler.ersetzt_id:
        return None
    from nebenkostenfix.models import MeterReading
    letzter = (MeterReading.query.filter_by(meter_id=zaehler.ersetzt_id)
               .order_by(MeterReading.reading_date.desc()).first())
    return letzter.reading_date if letzter else None


def vor_dem_wechseltag(zaehler, datum: date) -> str | None:
    """Der Text der Absage, wenn ``datum`` vor dem Wechseltag liegt, sonst None.

    Der Wechseltag selbst gilt nicht als „davor“: dort steht der Anfangsstand.
    """
    tag = wechseltag(zaehler)
    if tag is None or datum >= tag:
        return None
    return (f'Der Zähler ersetzt seit dem {tag:%d.%m.%Y} einen alten Zähler. '
            'Stände davor gehören an den alten Zähler.')
