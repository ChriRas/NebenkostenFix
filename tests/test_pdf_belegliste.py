"""Die Belegliste je Position (R-DOC-01 Punkt 8, NK-058).

Der BGH verlangt den Belegverweis nicht im Dokument (§ 556 Abs. 4 BGB gibt
nur ein Einsichtsrecht auf Verlangen) -- die Software liefert ihn trotzdem,
weil eine Abrechnung, die der Mieter nachpruefen kann, weniger Rueckfragen
erzeugt (Produktentscheidung, R-DOC-01). Je Position stehen Rechnungsnummer,
Anbieter, Ausstellungsdatum und Dokument mit Seitenzahl auf dem Blatt.

Das Auslesen des erzeugten PDF arbeitet wie in ``test_pdf_tageskonvention.py``:
die Seiten werden unkomprimiert erzeugt und die Textstroeme direkt gelesen.
"""

from __future__ import annotations

import re
import zlib
from datetime import date
from decimal import Decimal

import pytest
import reportlab.rl_config

from nebenkostenfix.pdf_generator import PDFGenerator


@pytest.fixture
def unkomprimiert(monkeypatch):
    """Seiten ohne Kompression, damit der Text lesbar im Strom steht."""
    monkeypatch.setattr(reportlab.rl_config, 'pageCompression', 0)


def _text(pdf: bytes) -> str:
    stuecke = []
    for roh in pdf.split(b'stream')[1:]:
        roh = roh.split(b'endstream')[0]
        try:
            roh = zlib.decompress(roh.strip())
        except zlib.error:
            pass
        stuecke.append(roh.decode('latin-1', 'replace'))
    return ' '.join(stuecke)


def _entschluesselt(stueck: str) -> str:
    """Loest die Escapes eines PDF-Textstuecks auf.

    Der Strom schreibt Klammern als \\( und Umlaute als Oktalzahlen
    (\"a ist \\344). Ohne Aufloesung wuerde "Wärmemenge" als "W44rmemenge"
    ankommen und die Suche würde sie verfehlen.
    """
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
    return ''.join(ausgabe)


def _geklebt(pdf: bytes) -> str:
    """Der Text ohne Zeilenumbrueche, in der Reihenfolge des Zeichnens.

    Der Zellensatz bricht Woerter um (wordWrap CJK); ein Satz wie
    "Rechnung Nr. R-2024-041 vom 15.04.2024" steht im Strom darum in
    Stuecken. Wer sie im Zeichenvertrag wieder zusammensetzt, erkennt
    den Satz trotzdem -- und unterscheidet ihn vom Beleglistenfeld,
    das die Rechnung ohne das Wort "Rechnung" nennt.
    """
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


def _posten(*, mit_nummer=True, mit_datum=True) -> dict:
    """Ein Kostenposten mit den Belegangaben einer echten Rechnung."""
    posten = {
        'category': 'Wasserversorgung',
        'period': '01.01.2024 - 31.12.2024',
        'description': 'Umlage nach Wohnflaeche',
        'tenant_cost': Decimal('600.00'),
        'invoice_days': 366,
        'overlap_days': 366,
        'provider_name': 'Stadtwerke Musterstadt',
        'invoice_total_amount': Decimal('1200.00'),
        'prorated_amount': Decimal('600.00'),
        'doc_name': 'rechnung-wasser.pdf, Seiten 3',
        'doc_path': 'belege/rechnung-wasser.pdf',
    }
    if mit_nummer:
        posten['invoice_number'] = 'R-2024-041'
    if mit_datum:
        posten['rechnungsdatum'] = '2024-04-15'
    return posten


def _erzeuge(detailliert: bool, posten: list[dict]) -> str:
    return _text(_pdf(detailliert, posten))


def _pdf(detailliert: bool, posten: list[dict]) -> bytes:
    erzeuger = PDFGenerator(
        property_name='Haus am Anger',
        apartment_name='Wohnung 1',
        tenant_name='Mustermann',
        start_date='2024-01-01',
        end_date='2024-12-31',
        detailliert=detailliert,
    )
    return erzeuger.generate(posten, _summe(posten), Decimal('0.00'))

def _summe(posten: list[dict]):
    """Die Gesamtsumme der Abrechnung: die Summe der Zeilenbetraege.

    So rechnet der Kern (``total_amount += runde(tenant_cost)``), und seit
    Phase 59 verlaesst sich das Uebersichtsblatt darauf: Es bricht ab, wenn
    seine Summe von der uebergebenen abweicht. Eine erfundene Gesamtsumme
    im Pruefstand wuerde genau diesen Waechter ausloesen.
    """
    return sum((p['tenant_cost'] for p in posten), start=Decimal('0.00'))


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_die_belegliste_zeigt_alle_vier_angaben(unkomprimiert, detailliert):
    """R-DOC-01 Punkt 8: Nummer, Anbieter, Datum, Dokumentseite.

    Der Vermieter sendet nur eine der beiden Fassungen -- darum traegt
    jede fuer sich die Belegliste.
    """
    pdf = _pdf(detailliert, [_posten()])
    text = _text(pdf)
    geklebt = _geklebt(pdf)
    assert 'Belegliste' in text, (
        f'{"Detaillierte" if detailliert else "Einfache"} Variante nennt '
        'keine Belege (R-DOC-01 Punkt 8)'
    )
    assert 'Nr.' in text
    assert 'R-2024-041' in text
    assert 'vom15.04.2024' in geklebt
    assert 'Stadtwerke' in text
    assert 'Musterstadt' in text
    assert 'Seiten' in text
    assert 'rechnung-wasser.pdf,Seiten3' in geklebt


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_der_verweis_steht_an_der_position_selbst(unkomprimiert, detailliert):
    """Eine Position aus einer Rechnung traegt den Verweis direkt in der Zeile."""
    text = _erzeuge(detailliert, [_posten()])
    geklebt = _geklebt(_pdf(detailliert, [_posten()]))
    # Das Beleglistenfeld nennt dieselbe Rechnung ohne den Zusatz
    # "Rechnung" -- nur der Verweis an der Position faehrt ihn.
    assert 'RechnungNr.R-2024-041vom15.04.2024' in geklebt, text[-400:]


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_ohne_rechnungsdatum_wird_kein_datum_erfunden(unkomprimiert, detailliert):
    """NULL bleibt NULL: der Zeitraum ist kein Ausstellungsdatum (D-57).

    Eine Rechnung ueber Januar bis Maerz kann im April ausgestellt sein;
    ein erfundenes Datum waere schlimmer als keines.
    """
    text = _erzeuge(detailliert, [_posten(mit_datum=False)])
    assert 'vom' not in text


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_ohne_rechnungsnummer_keine_belegzeile(unkomprimiert, detailliert):
    """Was kein Beleg hat, kann die Liste nicht belegen."""
    text = _erzeuge(detailliert, [_posten(mit_nummer=False)])
    assert 'Nr.' not in text
    assert 'Belegliste' not in text


def _heizposten() -> dict:
    """Eine Heizzeile nach § 7: mehrere Rechnungen in einer Position (D-47)."""
    return {
        'category': 'Heizung (Gas-Zentrale)',
        'period': '01.01.2024 - 31.12.2024',
        'description': '50/50 nach § 7 HeizkostenV',
        'tenant_cost': Decimal('900.00'),
        'invoice_days': 366,
        'overlap_days': 366,
        'billing_type': 'heizkosten',
        'invoice_total_amount': Decimal('1800.00'),
        'prorated_amount': Decimal('900.00'),
        'heizung_details': {
            'rechnungen': [
                {
                    'invoice_id': 1,
                    'invoice_number': 'W-2024-100',
                    'rechnungsdatum': '2024-04-15',
                    'kostenart_text': 'Wärmemenge',
                    'provider_name': 'Fernwaerme Sued',
                    'period': '01.01.2024 - 30.06.2024',
                    'doc_name': 'fernwaerme-1.pdf, Seiten 2',
                    'amount': Decimal('700.00'),
                    'rechnungsbetrag': Decimal('1400.00'),
                    'prorated_amount': Decimal('700.00'),
                },
                {
                    'invoice_id': 2,
                    'invoice_number': 'W-2024-201',
                    'rechnungsdatum': None,
                    'kostenart_text': 'Wartung',
                    'provider_name': 'Heizungsbaumeister Krause',
                    'period': '01.07.2024 - 31.12.2024',
                    'doc_name': None,
                    'amount': Decimal('200.00'),
                    'rechnungsbetrag': Decimal('400.00'),
                    'prorated_amount': Decimal('200.00'),
                },
            ],
        },
    }


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_eine_heizzeile_listet_jede_ihrer_rechnungen(unkomprimiert, detailliert):
    """Zwei Rechnungen in einer Position: die Liste fuehrt beide einzeln."""
    text = _erzeuge(detailliert, [_heizposten()])
    geklebt = _geklebt(_pdf(detailliert, [_heizposten()]))
    assert 'W-2024-100' in text
    assert 'vom15.04.2024' in geklebt
    assert 'W-2024-201' in text
    assert 'Wärmemenge' in geklebt
    assert 'Wartung' in geklebt
    assert 'Fernwaerme' in geklebt
    assert 'Krause' in geklebt


def test_heizung_nach_verbrauch_zeigt_keinen_tagesanteil(unkomprimiert):
    """Nach Verbrauch verteilt passt der Tagesanteil nicht zum angesetzten
    Betrag. Die Spalte sagt dann den Weg statt einer falschen Zahl."""
    posten = _heizposten()
    erste, zweite = posten['heizung_details']['rechnungen']
    erste['prorated_amount'] = Decimal('123.45')
    erste['nach_verbrauch'] = True
    geklebt = _geklebt(_pdf(True, [posten]))
    assert '123,45' not in geklebt
    assert 'nachZähler' in geklebt
    # Ohne erfassten Verbrauch (ganz nach Flaeche) bleibt der Tagesanteil.
    assert '200,00' in geklebt


def test_eine_heizzeile_mit_mehreren_rechnungen_verweist_nicht_in_der_zeile():
    """Der Verweis in der Zeile gilt nur fuer Positionen aus einer Rechnung.

    Sonst wuerde er so tun, als gehoerte eine von ihnen der ganzen Zeile.
    """
    text = _erzeuge(False, [_heizposten()])
    assert 'RechnungW-2024-100' not in _geklebt(_pdf(False, [_heizposten()])), text[-400:]


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_ein_wort_fuer_die_liste(unkomprimiert, detailliert):
    """Zwei Woerter fuer dieselbe Liste waeren eine Ungereimtheit (glossar)."""
    text = _erzeuge(detailliert, [_posten()])
    assert 'Verwendete Rechnungen' not in text


def test_die_ausfuehrliche_variante_weist_die_rechnungsbetraege(unkomprimiert):
    """Die Betragsspalten der frueheren Tabelle bleiben erhalten -- je Rechnung."""
    geklebt = _geklebt(_pdf(True, [_posten()]))
    # Phase 60: mit Tausenderpunkt, wie jeder andere Betrag im Dokument
    # (``pdf_stil.geld``). Vorher stand hier „1200,00" neben „1.200,00"
    # auf demselben Blatt.
    assert '1.200,00' in geklebt
    assert '600,00' in geklebt


def test_die_einfache_variante_fuehrt_keine_rechnungsbetraege(unkomprimiert):
    """Der Verweis zeigt auf den Beleg; der Betrag steht an der Position."""
    text = _erzeuge(False, [_posten()])
    assert '1.200,00' not in text and '1200,00' not in text


def test_rechnungsdatum_angabe_gibt_iso_oder_nichts():
    """Der Kern liefert die Rohangabe JSON-sicher (D-57)."""
    from nebenkostenfix.rechenkern import rechnungsdatum_angabe

    assert rechnungsdatum_angabe(date(2024, 4, 15)) == '2024-04-15'
    assert rechnungsdatum_angabe(None) is None


# --- Die Route: vom Eingabefeld bis zur Ausgabe ----------------------------

from billing_factories import apt, house  # noqa: E402


def test_die_route_nimmt_das_rechnungsdatum_an(auth_client, app_ctx):
    """Das Ausstellungsdatum wandert von der Eingabe bis zur Ausgabe."""
    from nebenkostenfix.models import CostCategory, CostInvoice

    prop = house('Belegshaus')
    apt(prop, 'Beleg-EG', 50.0)
    kat = CostCategory.query.filter_by(name='Wasserversorgung').first()

    antwort = auth_client.post('/api/invoices', json={
        'category_id': kat.id,
        'property_id': prop.id,
        'amount': '460.00',
        'start_date': '2026-01-01',
        'end_date': '2026-12-31',
        'invoice_number': 'R-2026-001',
        'rechnungsdatum': '2026-04-15',
    })
    assert antwort.status_code == 201, antwort.get_data(as_text=True)

    rechnung = CostInvoice.query.get(antwort.get_json()['id'])
    assert rechnung.rechnungsdatum == date(2026, 4, 15)

    liste = auth_client.get('/api/invoices').get_json()
    zeile = next(z for z in liste if z['id'] == rechnung.id)
    assert zeile['rechnungsdatum'] == '2026-04-15'


def test_die_route_vertraegt_ein_fehlendes_rechnungsdatum(auth_client, app_ctx):
    """Der Altbestand traegt kein Datum -- die Route verlangt es nicht."""
    from nebenkostenfix.models import CostCategory, CostInvoice

    prop = house('Belegshaus Alt')
    apt(prop, 'Beleg-OG', 50.0)
    kat = CostCategory.query.filter_by(name='Wasserversorgung').first()

    antwort = auth_client.post('/api/invoices', json={
        'category_id': kat.id,
        'property_id': prop.id,
        'amount': '460.00',
        'start_date': '2026-01-01',
        'end_date': '2026-12-31',
    })
    assert antwort.status_code == 201, antwort.get_data(as_text=True)

    rechnung = CostInvoice.query.get(antwort.get_json()['id'])
    assert rechnung.rechnungsdatum is None


def test_die_zeile_des_kerns_traegt_die_belegangaben():
    """Der Kern uebermittelt Nummer, Datum (ISO), Anbieter und Beleg je Zeile."""
    from nebenkostenfix.rechenkern import (
        Beleg, Kategorie, Mieter, Rechnung, Wohnung, Vorgang, rechne,
    )

    meine = Wohnung(id=1, name='EG links', qm=50.0)
    andere = Wohnung(id=2, name='EG rechts', qm=50.0)
    ich = Mieter(id=1, name='Anna Mieterin', einzug=date(2020, 1, 1),
                 auszug=None, wohnung_id=1)
    r = Rechnung(
        id=1,
        kategorie=Kategorie(id=1, name='Wasserversorgung',
                            braucht_zaehler=False),
        betrag=Decimal('1200.00'),
        beginn=date(2024, 1, 1),
        ende=date(2024, 12, 31),
        nummer='R-2024-041',
        versorger_name='Stadtwerke Musterstadt',
        rechnungsdatum=date(2024, 4, 15),
        beleg=Beleg(dateiname='rechnung-wasser.pdf',
                    pfad='belege/x.pdf', seiten='3'),
    )
    v = Vorgang(
        mieter=ich,
        wohnung=meine,
        immobilie_id=1,
        immobilie_name='Hauptstrasse 1',
        beginn=date(2024, 1, 1),
        ende=date(2024, 12, 31),
        wohnungen=(meine, andere),
        mieter_der_immobilie=(ich,),
        profile={},
        rechnungen=(r,),
    )
    zeile = rechne(v)['line_items'][0]
    assert zeile['invoice_number'] == 'R-2024-041'
    assert zeile['rechnungsdatum'] == '2024-04-15'
    assert zeile['provider_name'] == 'Stadtwerke Musterstadt'
    assert zeile['doc_name'] == 'rechnung-wasser.pdf, Seiten 3'


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_die_belegliste_steht_genau_einmal_da(unkomprimiert, detailliert):
    """NK-244: die ausführliche Fassung hängte die Liste zweimal an."""
    pdf = _pdf(detailliert, [_posten()])
    assert _text(pdf).count('Belegliste') == 1
    assert ('Zeitanteilig' in _geklebt(pdf)) is detailliert


def test_ohne_anbieter_liefert_der_kern_keinen():
    """NK-246: der Kern setzte „Unbekannt“ ein; jetzt bleibt es None."""
    from nebenkostenfix.rechenkern import Kategorie, Mieter, Rechnung, Vorgang, Wohnung, rechne
    meine = Wohnung(id=1, name='EG links', qm=50.0)
    ich = Mieter(id=1, name='Anna Mieterin', einzug=date(2020, 1, 1), auszug=None, wohnung_id=1)
    r = Rechnung(id=1, kategorie=Kategorie(id=1, name='Wasserversorgung', braucht_zaehler=False),
                 betrag=Decimal('1200.00'), beginn=date(2024, 1, 1), ende=date(2024, 12, 31))
    v = Vorgang(mieter=ich, wohnung=meine, immobilie_id=1, immobilie_name='Hauptstrasse 1',
                beginn=date(2024, 1, 1), ende=date(2024, 12, 31), wohnungen=(meine,),
                mieter_der_immobilie=(ich,), profile={}, rechnungen=(r,))
    assert rechne(v)['line_items'][0]['provider_name'] is None


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_ohne_anbieter_keine_anbieterzeile(unkomprimiert, detailliert):
    """NK-246: ohne Anbieter steht weder „Unbekannt“ noch „Anbieter:“ da."""
    ohne = _posten()
    ohne['provider_name'] = None
    geklebt = _geklebt(_pdf(detailliert, [ohne]))
    assert 'Unbekannt' not in geklebt and 'Anbieter:' not in geklebt
    # Phase 60: Zeitraum, Anbieter und Beleg stehen als **eine** Zeile unter
    # der Kostenart, mit Mittelpunkten getrennt und ohne Beschriftung -- der
    # Name braucht keine. Geprüft bleibt die Sache: Mit Anbieter steht er da,
    # ohne steht nichts da, auch kein leerer Trenner.
    mit = _geklebt(_pdf(detailliert, [_posten()]))
    assert 'StadtwerkeMusterstadt' in mit
    assert '··' not in geklebt


# --- Die Schlusssätze (NK-248) ---------------------------------------------


def test_der_schluss_nennt_die_hinterlegte_iban(unkomprimiert, monkeypatch):
    """NK-248: mit IBAN steht sie im Zahlungssatz, nicht „das bekannte Konto“."""
    monkeypatch.setenv('VERMIETER_IBAN', 'DE89370400440532013000')
    geklebt = _geklebt(_pdf(False, [_posten()]))
    assert ('Bitteüberweisen' in geklebt
            and 'aufdasKontomitderIBANDE89370400440532013000.' in geklebt)
    assert 'bekannteKonto' not in geklebt
    assert 'stehenwir' not in geklebt
    assert 'RückfragenzurAbrechnungwerdengernbeantwortet.' in geklebt


def test_der_schluss_ohne_iban_bleibt_beim_bekannten_konto(unkomprimiert, monkeypatch):
    """Ohne hinterlegte IBAN bleibt der bisherige Zahlungssatz; ohne ich/wir."""
    monkeypatch.delenv('VERMIETER_IBAN', raising=False)
    geklebt = _geklebt(_pdf(False, [_posten()]))
    assert 'innerhalbvon14TagenaufdasbekannteKonto.' in geklebt
    assert 'IBAN' not in geklebt
    assert 'stehenwir' not in geklebt


# --- Umbruch an Wortgrenzen (NK-250) -----------------------------------------


def _zeilen(pdf: bytes) -> list[str]:
    """Jedes Textstück des Stroms für sich -- eine gesetzte Zeile je Stück."""
    stuecke = []
    for roh in pdf.split(b'stream')[1:]:
        roh = roh.split(b'endstream')[0]
        stuecke.extend(_entschluesselt(m) for m in re.findall(
            r'\(((?:\\.|[^\\)])*)\)', roh.decode('latin-1', 'replace')))
    return stuecke


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_kein_wort_bricht_mitten_in_der_zelle(unkomprimiert, detailliert):
    """NK-250: lange Kostenart und Spaltenköpfe brechen an Wortgrenzen."""
    reinigung, heizung = _posten(), _posten()
    reinigung['category'] = 'Gebäudereinigung und Ungezieferbekämpfung'
    reinigung['provider_name'] = 'Abfallwirtschaft Musterstadt'
    heizung['category'] = 'Heizkosten (Zentralheizung)'
    heizung['provider_name'] = 'Stadt Musterstadt'
    zeilen = _zeilen(_pdf(detailliert, [reinigung, heizung]))
    woerter = ['Gebäudereinigung', 'Ungezieferbekämpfung', 'Abfallwirtschaft',
               '(Zentralheizung)', 'Musterstadt', 'Abrechnungszeitraum']
    if detailliert:
        woerter += ['Rechnungsbetrag', 'Zeitanteilig']
    for wort in woerter:
        assert any(wort in z for z in zeilen), (wort, [z for z in zeilen if wort[:5] in z])


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_allgemeinstrom_steht_bei_den_betriebskosten(unkomprimiert, detailliert):
    """NK-251: Nr. 11 (Beleuchtung) ist Betriebskostenart, nicht Heizkosten."""
    strom, gas = _posten(), _posten()
    strom['category'] = 'Allgemeinstrom'
    gas['category'] = 'Heizkosten'
    zeilen = _zeilen(_pdf(detailliert, [strom, gas]))
    # Phase 60: Die Rubrik steht in Versalien -- klein und leise, damit sie
    # ordnet statt mit den Positionen zu konkurrieren. Geprueft ist hier die
    # Zuordnung, nicht die Schreibweise.
    gruppen = [z for z in zeilen if z in ('ENERGIE', 'BETRIEBSKOSTEN')]
    assert gruppen == ['ENERGIE', 'BETRIEBSKOSTEN'], gruppen
    # Phase 59: Die Uebersicht vor der Aufstellung nennt die Position auch,
    # und zwar frueher. Geprueft ist hier die **Aufstellung**: Steht
    # Allgemeinstrom unter der Gruppe „Betriebskosten"?
    aufstellung = zeilen[zeilen.index('BETRIEBSKOSTEN'):]
    assert 'Allgemeinstrom' in aufstellung


@pytest.mark.parametrize('detailliert', [False, True], ids=['einfach', 'detailliert'])
def test_der_zeitraum_der_rechnung_steht_nur_wenn_er_abweicht(
        unkomprimiert, detailliert):
    """Phase 60: derselbe Zeitraum siebenmal ist Rauschen, kein Nachweis.

    R-DOC-01 Punkt 1 will den Zeitraum an der Zeile. Deckt er sich mit dem
    Abrechnungszeitraum -- der Normalfall, und er steht in der Kopfzeile
    des Blattes --, dann wiederholt die Zeile nur, was schon dasteht: bei
    sieben Positionen siebenmal dieselbe Zeitspanne. Nach der zweiten
    Sichtung: „viel zu viel Text".

    Die Richtung, die weh tut, ist die zweite: Eine Rechnung, die **nicht**
    den ganzen Zeitraum deckt, muss ihren Zeitraum nennen. Genau an der
    hängt, ob der Mieter die Kürzung nachvollziehen kann.
    """
    deckt_sich = _geklebt(_pdf(detailliert, [_posten()]))
    assert '01.01.2024-31.12.2024' not in deckt_sich, (
        'Der Zeitraum der Rechnung wiederholt den Abrechnungszeitraum aus '
        'der Kopfzeile.')

    abweichend = _posten()
    abweichend['period'] = '01.03.2024 - 30.11.2024'
    assert '01.03.2024-30.11.2024' in _geklebt(_pdf(detailliert, [abweichend])), (
        'Eine Rechnung über einen kürzeren Zeitraum nennt ihn nicht mehr. '
        'Dann steht der gekürzte Betrag ohne seinen Grund da.')
