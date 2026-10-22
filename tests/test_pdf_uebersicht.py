"""Phase 59 (Issue #35, Punkt 2): das Übersichtsblatt vor dem Detailteil.

Der Melder hat eine Musterabrechnung angehängt und dazu geschrieben:
*„Nach dieser Aufstellung könnte dann noch die Einzelne Berechnung folgen,
wie sie bereits ausgegeben wird."* Also ein Blatt **davor**, das alles auf
einen Blick zeigt -- und der Detailteil bleibt, wie er ist.

**Der Kern dieser Tests ist die Summenprobe.** Ein Übersichtsblatt, das
1.200,00 € nennt, während der Detailteil dahinter auf 1.198,37 € kommt, ist
schlimmer als kein Übersichtsblatt: Der Mieter liest zwei Forderungen für
dieselbe Abrechnung und weiß nicht, welche gilt. Dieselbe Klasse wie der
gemischte Nenner aus Phase 55 -- zwei Wege zur selben Zahl, die
auseinanderlaufen können. Deshalb prüft hier nicht nur, *dass* die Summen
stimmen, sondern auch, dass ein Auseinanderlaufen **laut** wird.

Die zweite Hälfte ist der Wortvorrat: Der Verteilerschlüssel muss aus
``abrechnungsart.ARTEN`` kommen und die Heizkostentrennung aus
``heizung.BETRKV_NR``. Eine zweite Liste im Satzmodul würde irgendwann von
der ersten abweichen, und niemand würde es merken.
"""

from __future__ import annotations

import re
import zlib
from decimal import Decimal

import pytest
import reportlab

from nebenkostenfix import abrechnungsart, heizung
from nebenkostenfix import pdf_uebersicht as uebersichtsblatt
from nebenkostenfix.pdf_generator import PDFGenerator
from nebenkostenfix.rechenkern import Schritt


# --- PDF-Text lesen (wie tests/test_pdf_rechenweg.py) -------------------

def _entschluesselt(stueck: str) -> str:
    ausgabe = []
    i = 0
    while i < len(stueck):
        zeichen = stueck[i]
        if zeichen == '\\' and i + 1 < len(stueck):
            if stueck[i + 1] in '01234567':
                ziffern = ''
                j = i + 1
                while j < len(stueck) and len(ziffern) < 3 \
                        and stueck[j] in '01234567':
                    ziffern += stueck[j]
                    j += 1
                ausgabe.append(chr(int(ziffern, 8)))
                i = j
                continue
            ausgabe.append(stueck[i + 1])
            i += 2
            continue
        ausgabe.append(zeichen)
        i += 1
    return ''.join(ausgabe).replace(chr(0x80), '€')


def _blaetter(pdf: bytes) -> list[str]:
    blaetter = []
    for roh in pdf.split(b'stream')[1:]:
        roh = roh.split(b'endstream')[0]
        try:
            roh = zlib.decompress(roh.strip())
        except zlib.error:
            pass
        stuecke = [_entschluesselt(m) for m in re.findall(
            r'\(((?:\\.|[^\\)])*)\)', roh.decode('latin-1', 'replace'))]
        blaetter.append(re.sub(r'\s+', '', ''.join(stuecke)))
    return blaetter


def _geklebt(pdf: bytes) -> str:
    return ''.join(_blaetter(pdf))


# --- Die Posten, wie der Kern sie liefert -------------------------------

def _posten() -> list[dict]:
    """Vier Positionen: Fläche, Zähler, Heizkosten und eine mit 0,00 €."""
    return [
        {
            'category': 'Wasserversorgung',
            'period': '01.01.2025 - 31.12.2025',
            'description': 'Umlage nach Wohnfläche (50 von 100 m²)',
            'tenant_cost': Decimal('300.00'),
            'prorated_amount': Decimal('600.00'),
            'invoice_total_amount': Decimal('600.00'),
            'billing_type': 'qm', 'invoice_days': 365, 'overlap_days': 365,
            'provider_name': 'Stadtwerke Musterstadt',
            'sub_items': [], 'rechenweg': [
                Schritt('Rechnungsbetrag', Decimal('600.00')),
                Schritt('nach Wohnfläche 50 von 100 m²', Decimal('300.00'))],
        },
        {
            'category': 'Allgemeinstrom',
            'period': '01.01.2025 - 31.12.2025',
            'description': 'Nach Verbrauch (eigener Zähler)',
            'tenant_cost': Decimal('80.00'),
            'prorated_amount': Decimal('240.00'),
            'invoice_total_amount': Decimal('240.00'),
            'billing_type': 'direkt', 'invoice_days': 365, 'overlap_days': 365,
            'provider_name': 'Stromanbieter',
            'sub_items': [], 'rechenweg': [],
        },
        {
            'category': 'Heizung und Warmwasser (Wärmepumpe)',
            'period': '01.01.2025 - 31.12.2025',
            'description': 'Heizkosten nach HeizkostenV',
            'tenant_cost': Decimal('500.00'),
            'prorated_amount': Decimal('1000.00'),
            'invoice_total_amount': Decimal('1000.00'),
            'billing_type': 'heizkosten', 'invoice_days': 365, 'overlap_days': 365,
            'provider_name': 'Energieversorger',
            'sub_items': [], 'rechenweg': [],
        },
        {
            'category': 'Gartenpflege',
            'period': '01.01.2025 - 31.12.2025',
            'description': 'Umlage nach Wohnfläche (50 von 100 m²)',
            'tenant_cost': Decimal('0.00'),
            'prorated_amount': Decimal('0.00'),
            'invoice_total_amount': Decimal('0.00'),
            'billing_type': 'qm', 'invoice_days': 365, 'overlap_days': 365,
            'provider_name': 'Gartenbau Muster',
            'sub_items': [], 'rechenweg': [],
        },
    ]


GESAMT = Decimal('880.00')      # 300 + 80 + 500 + 0
VORAUS = Decimal('700.00')


# --- Der Kern: die Zuordnung -------------------------------------------

def test_die_heizkostentrennung_kommt_aus_dem_kern():
    """Nr. 4, 5 und 6 des § 2 BetrKV -- keine eigene Liste im Satzmodul."""
    assert uebersichtsblatt.HEIZKOSTENNUMMERN == frozenset(heizung.BETRKV_NR.values())


def test_eine_heizkostenzeile_zaehlt_als_heizkosten():
    assert uebersichtsblatt.ist_heizkosten(
        {'category': 'Heizung', 'billing_type': 'heizkosten'})


def test_eine_heizkostenrechnung_ohne_anlage_zaehlt_auch():
    """Ohne zugeordnete Anlage rechnet der Kern nach Fläche -- die Nummer
    sagt trotzdem, dass es Heizkosten sind (W-HEIZKOSTEN-OHNE-ZUORDNUNG)."""
    assert uebersichtsblatt.ist_heizkosten(
        {'category': 'Heizung', 'billing_type': 'qm'})


def test_wasser_ist_keine_heizkostenposition():
    assert not uebersichtsblatt.ist_heizkosten(
        {'category': 'Wasserversorgung', 'billing_type': 'qm'})


def test_der_verteilerschluessel_kommt_aus_abrechnungsart():
    """Ein zweiter Wortvorrat würde irgendwann abweichen, unbemerkt."""
    for art, text in abrechnungsart.ARTEN.items():
        assert uebersichtsblatt.schluessel_text({'billing_type': art}) == text


def test_der_anteil_rechnet_gegen_die_verteilte_masse():
    """Gegen den Rechnungsbetrag gerechnet ginge die Zeile nicht auf."""
    zeile = {'billing_type': 'qm', 'tenant_cost': Decimal('300.00'),
             'prorated_amount': Decimal('600.00')}

    assert uebersichtsblatt.anteil_text(zeile) == '50,0 %'


def test_beim_eigenen_zaehler_steht_kein_prozentsatz():
    """Der Betrag kommt vom Zähler, nicht aus einem Anteil."""
    zeile = {'billing_type': 'direkt', 'tenant_cost': Decimal('80.00'),
             'prorated_amount': Decimal('240.00')}

    assert uebersichtsblatt.anteil_text(zeile) == uebersichtsblatt.OHNE_ANTEIL


def test_ohne_masse_gibt_es_keinen_anteil():
    """Nicht durch Null teilen und keine erfundene Null-Prozent-Angabe."""
    zeile = {'billing_type': 'qm', 'tenant_cost': Decimal('0.00'),
             'prorated_amount': Decimal('0.00')}

    assert uebersichtsblatt.anteil_text(zeile) == uebersichtsblatt.OHNE_ANTEIL


# --- Der Kern: die Summen ----------------------------------------------

def test_bei_einem_zaehler_steht_keine_gesamtsumme():
    """Der lineare Tagesanteil darf nicht aufs Blatt.

    ``prorated_amount`` ist bei einer Zählerposition der Rechnungsbetrag
    linear auf die Tage gerechnet. Ein Zähler verbraucht aber nicht linear,
    und neben dem Zählerbetrag gelesen sähe die Zahl wie eine Quote aus,
    die niemand gerechnet hat. Die Belegliste zeigt sie aus demselben Grund
    nicht (``tests/test_praxisbestand.py``).
    """
    zeile = {'billing_type': 'direkt', 'tenant_cost': Decimal('477.66'),
             'prorated_amount': Decimal('2953.42')}

    assert uebersichtsblatt.gesamtkosten(zeile) is None


def test_bei_einem_anteil_steht_die_verteilte_masse():
    """Die Gegenrichtung: wo verteilt wurde, gehört die Masse hin."""
    zeile = {'billing_type': 'qm', 'tenant_cost': Decimal('300.00'),
             'prorated_amount': Decimal('600.00')}

    assert uebersichtsblatt.gesamtkosten(zeile) == Decimal('600.00')


def test_die_drei_summen_des_musters():
    stand = uebersichtsblatt.uebersicht(_posten(), vorauszahlungen=VORAUS)

    assert stand['betriebskosten'] == Decimal('380.00')   # 300 + 80 + 0
    assert stand['heizkosten'] == Decimal('500.00')
    assert stand['nebenkosten'] == GESAMT
    assert stand['saldo'] == GESAMT - VORAUS


def test_die_teilsummen_ergeben_die_gesamtsumme():
    """Die Probe, die auf dem Blatt jeder nachrechnen kann."""
    stand = uebersichtsblatt.uebersicht(_posten())

    assert stand['betriebskosten'] + stand['heizkosten'] == stand['nebenkosten']


def test_eine_null_euro_zeile_bleibt_stehen():
    """Für den Mieter ist „geprüft, trifft mich nicht" eine Information."""
    stand = uebersichtsblatt.uebersicht(_posten())

    positionen = [z['position'] for z in stand['zeilen']]
    assert 'Gartenpflege' in positionen
    assert len(stand['zeilen']) == 4


def test_die_summe_wird_nicht_nachgerechnet_sondern_uebernommen():
    """Der Zeilenbetrag des Kerns gilt, auch wenn Masse × Anteil anders fällt.

    Wer die Übersicht selbst rechnen lässt, bekommt irgendwann eine
    Rundung anders als der Detailteil -- und genau das darf nicht sein.
    """
    posten = [{'category': 'Wasserversorgung', 'billing_type': 'qm',
               'tenant_cost': Decimal('123.45'),
               'prorated_amount': Decimal('1000.00')}]

    stand = uebersichtsblatt.uebersicht(posten)

    assert stand['nebenkosten'] == Decimal('123.45')


def test_abweichende_summen_brechen_ab(app_ctx):
    """Zwei Zahlen für eine Forderung gehen nicht raus.

    Ein Schutznetz: im Betrieb kommt die Gesamtsumme aus denselben Posten,
    die Abweichung entsteht nur durch einen künftigen Fehler im Rechenkern.
    Darum über den Generator, nicht über ``pruefe_summe`` allein (Review
    0.17.0): Geprüft ist, dass das PDF dann wirklich nicht entsteht -- ein
    Cent Abweichung reicht."""
    erzeuger = PDFGenerator(property_name='Haus am Anger', apartment_name='EG links',
                            tenant_name='Anna Mieterin', start_date='2025-01-01',
                            end_date='2025-12-31')

    with pytest.raises(uebersichtsblatt.UebersichtFehler) as fehler:
        erzeuger.generate(_posten(), GESAMT + Decimal('0.01'), VORAUS)

    assert '880,00' in str(fehler.value) and '880,01' in str(fehler.value)


def test_gleiche_summen_gehen_durch():
    stand = uebersichtsblatt.uebersicht(_posten())

    assert uebersichtsblatt.pruefe_summe(stand, GESAMT) is None


# --- Das Blatt im PDF --------------------------------------------------

def _pdf(detailliert: bool = False, anschrift: str | None = None) -> bytes:
    erzeuger = PDFGenerator(
        property_name='Haus am Anger',
        apartment_name='EG links',
        tenant_name='Anna Mieterin',
        start_date='2025-01-01',
        end_date='2025-12-31',
        detailliert=detailliert,
        tenant_anschrift=anschrift,
    )
    return erzeuger.generate(_posten(), GESAMT, VORAUS)


@pytest.fixture
def unkomprimiert(monkeypatch):
    """Seiten ohne Kompression, damit der Text lesbar im Strom steht.

    Ohne das setzt reportlab ASCII85 über Flate, und aus dem Strom kommt
    Rauschen statt Text -- ein Test, der dann grün ist, prüft nichts.
    """
    monkeypatch.setattr(reportlab.rl_config, 'pageCompression', 0)


@pytest.fixture
def pdf(app_ctx, unkomprimiert) -> bytes:
    """Ein PDF je Test: ``app_ctx`` lebt pro Test, nicht pro Modul."""
    return _pdf()


def test_das_blatt_traegt_die_spalten_des_musters(pdf):
    text = _geklebt(pdf)

    for spalte in ('Kostenposition', 'Gesamtkosten', 'Verteilerschlüssel',
                   'Anteil', 'KostenMieter'):
        assert spalte in text, f'Die Spalte „{spalte}" fehlt im Übersichtsblatt.'


def test_das_blatt_nennt_jede_position_auch_die_mit_null_euro(pdf):
    text = _geklebt(pdf)

    for position in ('Wasserversorgung', 'Allgemeinstrom', 'Gartenpflege'):
        assert position in text, position


def test_das_blatt_nennt_die_drei_summen(pdf):
    text = _geklebt(pdf)

    # Phase 60: die Worte der Vorlage („Betriebskosten gesamt") statt
    # „Summe Betriebskosten". Geprüft ist, dass alle drei Summen dastehen.
    assert 'Betriebskostengesamt' in text
    assert 'Heizkostengesamt' in text
    assert 'Nebenkostengesamt' in text


def test_das_blatt_nennt_dieselbe_summe_wie_die_abrechnung(pdf):
    """Die Zahl auf dem Übersichtsblatt ist die der Abrechnung."""
    text = _geklebt(pdf)

    assert '880,00€' in text
    assert '180,00€' in text          # Saldo: 880,00 - 700,00


def test_das_ergebnis_steht_weiter_nur_einmal(pdf):
    """NK-249: Das Ergebnis steht einmal, auf dem Deckblatt.

    Das Übersichtsblatt schließt seine Tabelle mit „Saldo" ab statt die
    Worte des Deckblatts zu wiederholen. Zwei Stellen, die dasselbe
    fordern, lassen den Mieter nach dem Unterschied suchen -- und genau
    diese Wiederholung hatte NK-249 schon einmal entfernt.
    """
    text = _geklebt(pdf)

    assert text.count('IhreNachzahlung') + text.count('IhrGuthaben') <= 1
    assert 'Saldo' in text


def test_das_blatt_steht_vor_dem_detailteil(pdf):
    """Eine Übersicht hinter der Aufstellung wäre keine Übersicht."""
    blaetter = [b for b in _blaetter(pdf) if b]
    mit_uebersicht = next(i for i, b in enumerate(blaetter)
                          if 'Kostenposition' in b)
    # Phase 61: Die Aufstellung hat zwei Spalten -- „Kostenart und Umlage"
    # und den Betrag. Drei Spalten waren zu eng: Jeder Rechenschritt brach
    # um. (Phase 60 hieß der Kopf noch „Umlage und Rechenweg".)
    mit_detail = next(i for i, b in enumerate(blaetter)
                      if 'KostenartundUmlage' in b)

    assert mit_uebersicht < mit_detail


def test_der_detailteil_bleibt_unberuehrt(app_ctx, unkomprimiert):
    """Der Melder wollte nichts wegnehmen, und die Regeln erlauben es nicht.

    R-DOC-01 Punkt 6–8: Rechenweg je Zeile und Belegliste bleiben stehen.
    """
    text = _geklebt(_pdf(detailliert=True))

    # Phase 61: Text links, Betrag rechtsbündig -- das „=" ist weg,
    # die Spalte sagt es.
    assert 'nachWohnfläche50von100m²300,00€' in text.replace(' ', '')
    assert 'StadtwerkeMusterstadt' in text


def test_der_briefkopf_traegt_die_anschrift_des_mieters(app_ctx, unkomprimiert):
    """Phase 58 liefert sie, Phase 59 setzt sie -- Blatt 1 des Musters."""
    text = _geklebt(_pdf(anschrift='Musterweg 1\n12345 Musterstadt'))

    assert 'Musterweg1' in text
    assert '12345Musterstadt' in text


def test_die_route_nimmt_nach_dem_auszug_die_zustellanschrift(app_ctx):
    """Der ganze Weg: Datenbank -> Auswahlregel -> Briefkopf.

    Die Regel selbst prüft ``tests/test_anschriften.py``. Hier geht es um
    die Verdrahtung: Nimmt die Route, die das PDF erzeugt, wirklich die
    Zustelladresse -- oder liest sie stillschweigend das falsche Feld?
    Die Frist des § 556 Abs. 3 BGB läuft über den Zugang; ein Brief an die
    alte Wohnung lässt sie ablaufen, ohne jemanden zu erreichen.
    """
    from datetime import date

    import app as anwendung
    from nebenkostenfix.models import Tenant

    mieter = Tenant(apartment_id=1, name='Anna Mieterin',
                    move_in_date=date(2024, 1, 1),
                    move_out_date=date(2025, 6, 30),
                    anschrift='Musterweg 1\n12345 Musterstadt',
                    zustellanschrift='Neue Straße 9\n54321 Anderswo')

    # Lange nach dem Auszug: die neue Adresse gilt.
    assert anwendung._zustellanschrift(mieter, date(2025, 8, 1)) \
        == 'Neue Straße 9\n54321 Anderswo'
    # Noch im Mietverhältnis: die Wohnung gilt, auch wenn die neue
    # Anschrift schon bekannt ist.
    assert anwendung._zustellanschrift(mieter, date(2025, 3, 1)) \
        == 'Musterweg 1\n12345 Musterstadt'
    # Am letzten Miettag wohnt er noch dort.
    assert anwendung._zustellanschrift(mieter, date(2025, 6, 30)) \
        == 'Musterweg 1\n12345 Musterstadt'


def test_ohne_anschrift_bleibt_das_blatt_wie_bisher(pdf):
    """Kein leerer Briefkopf und keine erfundene Adresse."""
    text = _geklebt(pdf)

    # Phase 60: Der Briefkopf ist der der Vorlage -- zwei Anschriften
    # nebeneinander, ohne Beschriftung. Ohne hinterlegte Anschrift steht
    # nur der Name da: keine leere Zeile, keine erfundene Adresse.
    assert 'AnnaMieterin' in text
    assert 'Empfänger' not in text


# --- Review 0.17.0 (A6): der Umbruch bei vielen Positionen ---------------

def _viele_posten(anzahl: int) -> list[dict]:
    vorlage = _posten()[0]
    return [dict(vorlage, category=f'Position{nummer:02d}',
                 tenant_cost=Decimal('10.00'), prorated_amount=Decimal('20.00'))
            for nummer in range(anzahl)]


@pytest.mark.parametrize('anzahl', [*range(8, 17), 25, 40])
def test_bei_vielen_positionen_bleibt_das_blatt_beieinander(
        app_ctx, unkomprimiert, anzahl):
    """Tabelle, Summen und Fußnote steckten in einem ``KeepTogether``: Ab
    rund zehn Positionen passte das nicht mehr unter die Kopfdaten, und das
    Blatt trug nur Titel und Mieterdaten, die Tabelle stand eine Seite
    weiter. Bei neun Positionen stand die Fußnote allein auf einer Seite."""
    posten = _viele_posten(anzahl)
    pdf = PDFGenerator(
        property_name='Haus am Anger', apartment_name='EG links',
        tenant_name='Anna Mieterin', start_date='2025-01-01',
        end_date='2025-12-31',
    ).generate(posten, Decimal('10.00') * anzahl, Decimal('0'))
    blaetter = [b for b in _blaetter(pdf) if b]

    def blatt(text):
        # Das erste Vorkommen: Die Positionen stehen danach auch im Detailteil.
        return min(i for i, b in enumerate(blaetter) if text in b)

    assert blatt('Mieterdaten') == blatt('Position00'), \
        'Die Tabelle beginnt nicht auf dem Blatt mit den Kopfdaten.'
    letzte = blatt(f'Position{anzahl - 1:02d}')
    assert blatt('Nebenkostengesamt') == letzte, \
        'Die Summen stehen getrennt von den letzten Zeilen.'
    assert blatt('WiesichjedePosition') == letzte, \
        'Die Fußnote steht allein.'


# --- Review 0.17.0: Direktzuweisung, Katalognummer, Spaltenbreiten ------

def _direkt(beschreibung, kosten):
    return dict(_posten()[1], description=beschreibung,
                tenant_cost=Decimal(kosten), prorated_amount=Decimal('240.00'))


def test_eine_direkt_zugewiesene_rechnung_heisst_auch_so():
    """B4: Der Detailteil sagt „Direkt zugewiesen", das Blatt sagte „eigener
    Zähler" und ließ Gesamtkosten und Anteil leer -- obwohl die ganze
    Rechnung dieser Wohnung gehört."""
    posten = _direkt('Direkt zugewiesen (100 % der Rechnung für diese Wohnung)',
                     '240.00')

    assert uebersichtsblatt.schluessel_text(posten) == 'Direkt zugewiesen'
    assert uebersichtsblatt.gesamtkosten(posten) == Decimal('240.00')
    assert uebersichtsblatt.anteil_text(posten) == '100,0 %'


def test_eine_direktrechnung_nach_zaehler_nennt_keine_quote():
    """Teilt der Zähler eine überstehende Rechnung, kommt der Betrag aus der
    Ablesung -- dann wie beim eigenen Zähler keine Gesamtsumme."""
    posten = _direkt('Direkt zugewiesen, nach Verbrauch: 80 von 240 kWh der '
                     'Rechnung', '80.00')

    assert uebersichtsblatt.schluessel_text(posten) == 'Direkt zugewiesen'
    assert uebersichtsblatt.gesamtkosten(posten) is None
    assert uebersichtsblatt.anteil_text(posten) == uebersichtsblatt.OHNE_ANTEIL


def test_die_heizkostentrennung_liest_die_nummer_aus_dem_bestand(app_ctx):
    """C: „Nahwärme" mit Nr. 4 ist eine Heizkostenposition, auch wenn der
    Name allein nach Nr. 17 klingt."""
    from nebenkostenfix.models import CostCategory, db

    db.session.add(CostCategory(name='Nahwärme', allocation_method='qm',
                                betrkv_nr=4))
    db.session.commit()
    posten = dict(_posten()[0], category='Nahwärme')

    assert uebersichtsblatt.ist_heizkosten(posten)


def test_die_spalten_fassen_ihre_laengsten_werte():
    """C: „100,0 %" brach in der Spalte Anteil um, der Heizkostenschlüssel
    in jeder Zeile. Gemessen an der Tabelle, die das Blatt wirklich setzt."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.platypus import Table
    from nebenkostenfix import pdf_stil

    elemente = uebersichtsblatt.build_uebersicht_elements(
        _posten(), gesamtsumme=GESAMT, end_date='2025-12-31')
    [tabelle] = [e for e in elemente
                 if isinstance(e, Table) and len(e._colWidths) == 5]
    zelle = pdf_stil.stile(pdf_stil.STIL)['Zelle']
    polster = 16

    def breite(text):
        return stringWidth(text, zelle.fontName, zelle.fontSize) + polster

    schluessel = [*abrechnungsart.ARTEN.values(),
                  uebersichtsblatt.SCHLUESSEL_HEIZKOSTEN, 'Direkt zugewiesen']
    assert max(map(breite, schluessel)) <= tabelle._colWidths[2]
    assert breite('100,0 %') <= tabelle._colWidths[3]
    assert sum(tabelle._colWidths) == 470
