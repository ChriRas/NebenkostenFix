"""Die Gutschrift nach Fläche steht im PDF, mit negativem Betrag.

Gehört zu ``tests/test_gutschrift_umlage.py``: Der Rechenkern gibt eine
Gutschrift nach Fläche oder Personen jetzt als Zeile mit negativem
Mieteranteil aus. Hier wird geprüft, dass das Blatt sie trägt -- im
Übersichtsblatt mit Anteil und Summe, in der Aufstellung mit Rechenweg --
und dass die Summenprobe des Übersichtsblatts (``pruefe_summe``) aufgeht.

Alle Daten sind erfunden.
"""

from __future__ import annotations

import re
import zlib
from datetime import date
from decimal import Decimal

import pytest
import reportlab.rl_config

from nebenkostenfix import pdf_uebersicht
from nebenkostenfix.pdf_generator import PDFGenerator
from nebenkostenfix.rechenkern import (Kategorie, Mieter, Rechnung, Vorgang,
                                       Wohnung, Zahlung, rechne)

JAHR_BEGINN = date(2025, 1, 1)
JAHR_ENDE = date(2025, 12, 31)
MUELL = Kategorie(id=1, name='Müllabfuhr', braucht_zaehler=False)


@pytest.fixture
def unkomprimiert(monkeypatch):
    """Seiten ohne Kompression, damit der Text lesbar im Strom steht."""
    monkeypatch.setattr(reportlab.rl_config, 'pageCompression', 0)


def _ergebnis():
    """60 von 100 qm, 500,00 EUR Rechnung und 100,00 EUR Gutschrift."""
    wohnungen = (Wohnung(id=1, name='Wohnung 1', qm=60.0),
                 Wohnung(id=2, name='Wohnung 2', qm=40.0))
    mieter = (
        Mieter(id=1, name='Mieter 1', einzug=JAHR_BEGINN, auszug=None, wohnung_id=1),
        Mieter(id=2, name='Mieter 2', einzug=JAHR_BEGINN, auszug=None, wohnung_id=2),
    )
    return rechne(Vorgang(
        mieter=mieter[0], wohnung=wohnungen[0], immobilie_id=1,
        immobilie_name='Musterweg 1', beginn=JAHR_BEGINN, ende=JAHR_ENDE,
        wohnungen=wohnungen, mieter_der_immobilie=mieter,
        profile={MUELL.id: 'qm'},
        rechnungen=(
            Rechnung(id=1, kategorie=MUELL, betrag=Decimal('500.00'),
                     beginn=JAHR_BEGINN, ende=JAHR_ENDE, nummer='R-1'),
            Rechnung(id=2, kategorie=MUELL, betrag=Decimal('-100.00'),
                     beginn=JAHR_BEGINN, ende=JAHR_ENDE, nummer='GS-1'),
        ),
        zahlungen=(Zahlung(datum=date(2025, 6, 1), betrag=Decimal('200.00')),),
    ))


def _entschluesselt(stueck: str) -> str:
    """Oktal-Escapes eines PDF-Textstücks auflösen, \\200 ist das Eurozeichen."""
    ausgabe = []
    i = 0
    while i < len(stueck):
        if stueck[i] == '\\' and i + 1 < len(stueck):
            if stueck[i + 1] in '01234567':
                j = i + 1
                while j < len(stueck) and j - i <= 3 and stueck[j] in '01234567':
                    j += 1
                ausgabe.append(chr(int(stueck[i + 1:j], 8)))
                i = j
                continue
            ausgabe.append(stueck[i + 1])
            i += 2
            continue
        ausgabe.append(stueck[i])
        i += 1
    return ''.join(ausgabe).replace(chr(0x80), '€')


def _geklebt(pdf: bytes) -> str:
    """Der Text des Blatts ohne Leerraum, in der Reihenfolge des Zeichnens."""
    stuecke = []
    for roh in pdf.split(b'stream')[1:]:
        roh = roh.split(b'endstream')[0]
        try:
            roh = zlib.decompress(roh.strip())
        except zlib.error:
            pass
        stuecke.extend(_entschluesselt(m) for m in re.findall(
            r'\(((?:\\.|[^\\)])*)\)', roh.decode('latin-1', 'replace')))
    return re.sub(r'\s+', '', ''.join(stuecke))


def test_uebersicht_fuehrt_die_gutschrift_mit_anteil():
    """Die Gutschrift-Zeile trägt ihren Anteil, die Summe ist 240,00 EUR."""
    ergebnis = _ergebnis()
    stand = pdf_uebersicht.uebersicht(
        ergebnis['line_items'], vorauszahlungen=ergebnis['prepaid_amount'])

    gutschrift = [z for z in stand['zeilen'] if z['kosten'] < 0]
    assert len(gutschrift) == 1
    assert gutschrift[0]['kosten'] == Decimal('-60.00')
    assert gutschrift[0]['gesamtkosten'] == Decimal('-100.00')
    assert gutschrift[0]['anteil'] == '60,0 %'
    assert stand['nebenkosten'] == Decimal('240.00')
    assert stand['saldo'] == Decimal('40.00')
    pdf_uebersicht.pruefe_summe(stand, ergebnis['total_amount'])


def test_das_pdf_zeigt_die_gutschrift_negativ(unkomprimiert):
    """Im Blatt stehen -60,00 EUR für die Gutschrift und 240,00 EUR gesamt."""
    ergebnis = _ergebnis()
    pdf = PDFGenerator(
        property_name='Musterweg 1', apartment_name='Wohnung 1',
        tenant_name='Mieter 1', start_date='2025-01-01', end_date='2025-12-31',
    ).generate(ergebnis['line_items'], ergebnis['total_amount'],
               ergebnis['prepaid_amount'])
    text = _geklebt(pdf)

    assert 'Rechnungsbetrag-100,00€' in text
    assert 'nachWohnfläche60von100m²-60,00€' in text
    assert '240,00€' in text
