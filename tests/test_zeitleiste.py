"""NK-144: Die Zeitleiste der Rechnungen, auf Basis des Rechnungsdatums.

Der Rechnungszeitraum sagt, wofuer ein Beleg gilt; das Rechnungsdatum sagt,
wann er ausgestellt wurde. Die Zeitleiste gruendet auf dem Ausstellungsdatum
und zeigt Jahre/Monate absteigend. Altbestand ohne Datum kommt in eine
eigene Gruppe am Ende -- aus einem NULL wird nichts geraten (D-57).
"""

from __future__ import annotations

import re

from datetime import date
from decimal import Decimal

import pytest

from nebenkostenfix.models import (Apartment, CostCategory, CostInvoice, Property, db)

KATEGORIE = 'Strom (Zeitleiste)'


def kategorie_name() -> str:
    """Der Eintrag-Test gleicht mit der Seed-Kategorie ab, ohne ihren
    Namen hier zu raten."""
    return CostCategory.query.first().name


def _vorbereitung() -> tuple[Property, Apartment, CostCategory]:
    immobilie = Property(name='Zeitleistenhof')
    db.session.add(immobilie)
    db.session.flush()
    wohnung = Apartment(name='Whg. 1', property_id=immobilie.id, sqm=60)
    db.session.add(wohnung)
    # Die Kostenart kommt aus dem Seed-Katalog (BetrKV); eine eigene
    # anzulegen muesste die BetrKV-Nummer und die Rueckfragen mitschleppen.
    kategorie = CostCategory.query.first()
    db.session.flush()
    return immobilie, wohnung, kategorie


def _rechnung(wohnung, kategorie, start, ende, datum, betrag) -> None:
    db.session.add(CostInvoice(
        property_id=wohnung.property_id, apartment_id=wohnung.id,
        category_id=kategorie.id,
        start_date=date.fromisoformat(start),
        end_date=date.fromisoformat(ende),
        rechnungsdatum=(date.fromisoformat(datum) if datum else None),
        amount=Decimal(betrag)))
    db.session.commit()


@pytest.fixture
def zwei_rechnungen(app_ctx):
    """Eine Rechnung im April 2025, eine im Maerz 2024 -- jeweils mit
    Ausstellungsdatum; die Zeitraeume sind bewusst andersherum."""
    _, wohnung, kategorie = _vorbereitung()
    _rechnung(wohnung, kategorie, '2024-03-01', '2024-03-31',
              '2025-04-10', '150.00')
    _rechnung(wohnung, kategorie, '2025-01-01', '2025-01-31',
              '2024-03-05', '300.00')


def test_leerer_bestand_gibt_eine_leere_zeitleiste(app_ctx, auth_client):
    antwort = auth_client.get('/api/invoices/zeitleiste')
    assert antwort.status_code == 200
    koerper = antwort.get_json()
    assert koerper['jahre'] == []
    assert koerper['ohne_datum'] is None
    assert koerper['gesamt'] == 0


def test_zeitraum_zaehlt_nicht_ausstellung_sortiert(app_ctx, auth_client,
                                                    zwei_rechnungen):
    """Die Maerz-2024-Rechnung (ausgestellt 2025) steht unter 2025, die
    Januar-2025-Rechnung (ausgestellt 2024) unter 2024."""
    koerper = auth_client.get('/api/invoices/zeitleiste').get_json()
    jahre = [j['jahr'] for j in koerper['jahre']]
    assert jahre == [2025, 2024]
    monate_2025 = koerper['jahre'][0]['monate']
    assert [m['monat'] for m in monate_2025] == [4]
    assert monate_2025[0]['label'] == 'April'
    assert monate_2025[0]['summe'] == 150.0


def test_monate_stehen_absteigend_und_summen_stimmen(app_ctx, auth_client,
                                                     zwei_rechnungen):
    _, wohnung, kategorie = _vorbereitung()
    _rechnung(wohnung, kategorie, '2025-02-01', '2025-02-28',
              '2025-02-20', '49.50')
    _rechnung(wohnung, kategorie, '2025-04-01', '2025-04-30',
              '2025-04-01', '10.00')

    koerper = auth_client.get('/api/invoices/zeitleiste').get_json()
    jahr_2025 = next(j for j in koerper['jahre'] if j['jahr'] == 2025)
    assert [m['monat'] for m in jahr_2025['monate']] == [4, 2]
    april = jahr_2025['monate'][0]
    assert april['summe'] == 160.0  # 150.00 (altes) + 10.00 (neues)
    assert jahr_2025['summe'] == 209.5
    assert koerper['gesamt'] == 509.5


def test_altbestand_ohne_datum_landet_am_ende(app_ctx, auth_client):
    _, wohnung, kategorie = _vorbereitung()
    wohnung.name = 'Whg. Alt'
    _rechnung(wohnung, kategorie, '2019-01-01', '2019-12-31',
              None, '120.00')

    koerper = auth_client.get('/api/invoices/zeitleiste').get_json()
    assert koerper['jahre'] == []
    rest = koerper['ohne_datum']
    assert rest['summe'] == 120.0
    assert rest['rechnungen'][0]['rechnungsdatum'] is None
    assert koerper['gesamt'] == 120.0


def test_eintraege_tragen_die_ansichtsfelder(app_ctx, auth_client,
                                             zwei_rechnungen):
    koerper = auth_client.get('/api/invoices/zeitleiste').get_json()
    eintrag = koerper['jahre'][0]['monate'][0]['rechnungen'][0]
    assert eintrag['rechnungsdatum'] == '2025-04-10'
    assert eintrag['kategorie_name'] == kategorie_name()
    assert eintrag['property_name'] == 'Zeitleistenhof'
    assert eintrag['hat_beleg'] is False
    # Phase 67: die Seite im Sammelbeleg, damit der Link dort aufschlägt.
    assert 'seiten' in eintrag


def test_ohne_anmeldung_gesperrt(app_ctx, anon_client):
    assert anon_client.get('/api/invoices/zeitleiste').status_code == 401


def test_umschalter_und_container_sind_verdrahtet():
    """Die Zeitleiste ist eine zweite Ansicht im Rechnungen-Tab: Umschalter
    (Auswahlpillen ohne Verb), verdeckter Container, Kennungen springen."""
    with open('static/index.html', encoding='utf-8') as datei:
        seite = datei.read()
    assert 'id="pills-invoice-zeitleiste"' in seite
    assert 'zeigeInvoiceZeitleiste()' in seite
    assert 'id="invoices-zeitleiste"' in seite
    # Der Cache-Buster muss da sein und darf nicht zurueckfallen -- aber
    # nicht auf einer festen Nummer stehen. Vorher stand hier `?v=14`
    # woertlich; damit fiel dieser Test bei jeder spaeteren Stilaenderung,
    # obwohl mit der Zeitleiste nichts geschehen war. Ein Test, den man
    # durch Hochzaehlen einer Zahl gruen macht, erzieht zum Hochzaehlen.
    stil = re.search(r'style\.css\?v=(\d+)', seite)
    skript_version = re.search(r'app\.js\?v=(\d+)', seite)
    assert stil and int(stil.group(1)) >= 14, (
        'style.css hat keinen Cache-Buster oder faellt hinter v14 zurueck '
        '(den Stand, mit dem die Zeitleiste kam).')
    assert skript_version and int(skript_version.group(1)) >= 39, (
        'app.js hat keinen Cache-Buster oder faellt hinter v39 zurueck.')
    with open('static/app.js', encoding='utf-8') as datei:
        skript = datei.read()
    assert 'fetch(zeitleisteAdresse())' in skript
    assert 'renderInvoiceZeitleiste' in skript


# --- Phase 62 (Issue #35, Nachtrag): die Zeitleiste folgt den Filtern ---
#
# Befund: „Der Filter oben macht auf dieser Zeitleistenansicht keinen
# Unterschied." Die Zeitleiste holte immer den ganzen Bestand, und ihre
# Umschaltung blendete die Filterleiste aus. Bei gewaehlter Immobilie
# standen unter „Ohne Rechnungsdatum" Rechnungen einer anderen.


def _zweites_haus() -> Apartment:
    anderes = Property(name='Nachbarhaus')
    db.session.add(anderes)
    db.session.flush()
    wohnung = Apartment(name='Whg. N', property_id=anderes.id, sqm=40)
    db.session.add(wohnung)
    db.session.flush()
    return wohnung


def _alle_eintraege(koerper) -> list[dict]:
    eintraege = [r for j in koerper['jahre'] for m in j['monate']
                 for r in m['rechnungen']]
    if koerper['ohne_datum']:
        eintraege += koerper['ohne_datum']['rechnungen']
    return eintraege


def test_die_immobilie_aus_dem_kopf_filtert_auch_den_altbestand(app_ctx, auth_client):
    immobilie, wohnung, kategorie = _vorbereitung()
    nachbar = _zweites_haus()
    _rechnung(wohnung, kategorie, '2024-01-01', '2024-12-31', '2025-02-01', '100.00')
    _rechnung(nachbar, kategorie, '2019-01-01', '2019-12-31', None, '70.00')
    _rechnung(nachbar, kategorie, '2019-01-01', '2019-12-31', None, '30.00')

    koerper = auth_client.get(
        f'/api/invoices/zeitleiste?property_id={immobilie.id}').get_json()
    assert koerper['ohne_datum'] is None, 'Altbestand des Nachbarhauses steht in der Zeitleiste'
    assert {e['property_name'] for e in _alle_eintraege(koerper)} == {'Zeitleistenhof'}
    assert koerper['gesamt'] == 100.0

    nur_nachbar = auth_client.get(
        f'/api/invoices/zeitleiste?property_id={nachbar.property_id}').get_json()
    assert nur_nachbar['jahre'] == []
    assert nur_nachbar['ohne_datum']['summe'] == 100.0


def test_das_jahr_filtert_und_ohne_waehlt_den_altbestand(app_ctx, auth_client,
                                                         zwei_rechnungen):
    _, wohnung, kategorie = _vorbereitung()
    _rechnung(wohnung, kategorie, '2019-01-01', '2019-12-31', None, '5.00')

    nur_2024 = auth_client.get('/api/invoices/zeitleiste?jahr=2024').get_json()
    assert [j['jahr'] for j in nur_2024['jahre']] == [2024]
    assert nur_2024['ohne_datum'] is None
    assert nur_2024['gesamt'] == 300.0

    ohne = auth_client.get('/api/invoices/zeitleiste?jahr=ohne').get_json()
    assert ohne['jahre'] == []
    assert ohne['ohne_datum']['summe'] == 5.0


def test_kostenart_und_suche_filtern_wie_die_liste(app_ctx, auth_client,
                                                   zwei_rechnungen):
    _, wohnung, _ = _vorbereitung()
    andere = CostCategory.query.filter(
        CostCategory.id != CostCategory.query.first().id).first()
    db.session.add(CostInvoice(
        property_id=wohnung.property_id, apartment_id=wohnung.id,
        category_id=andere.id, invoice_number='RE-4711',
        start_date=date(2025, 1, 1), end_date=date(2025, 12, 31),
        rechnungsdatum=date(2025, 6, 1), amount=Decimal('42.00')))
    db.session.commit()

    nach_art = auth_client.get('/api/invoices/zeitleiste',
                               query_string={'kategorie': andere.name}).get_json()
    assert nach_art['gesamt'] == 42.0

    gesucht = auth_client.get('/api/invoices/zeitleiste?suche=re-47').get_json()
    assert [e['kategorie_name'] for e in _alle_eintraege(gesucht)] == [andere.name]

    ohne_filter = auth_client.get('/api/invoices/zeitleiste').get_json()
    assert ohne_filter['gesamt'] == 492.0


def test_die_ansicht_reicht_die_filter_weiter():
    """Die Adresse der Zeitleiste traegt Immobilie und Filter, die Leiste
    bleibt stehen, und jedes Neuzeichnen der Liste zieht sie nach."""
    with open('static/app.js', encoding='utf-8') as datei:
        skript = datei.read()
    adresse = re.search(r'function zeitleisteAdresse\(\) \{[\s\S]*?\n\}', skript)
    assert adresse, 'zeitleisteAdresse() fehlt'
    for teil in ('hausFilter', 'property_id', 'invoice-jahr-filter',
                 'invoice-category-filter', 'invoice-search'):
        assert teil in adresse.group(0), f'{teil} fehlt in der Zeitleisten-Adresse'

    umschalter = re.search(r'async function zeigeInvoiceZeitleiste\(\) \{[\s\S]*?\n\}', skript)
    assert umschalter
    assert "'invoice-filter').style.display = 'none'" not in umschalter.group(0), (
        'Die Zeitleiste blendet die Filterleiste aus.')

    zeichnen = re.search(r'function renderInvoices\(\) \{[\s\S]*?\n\}', skript)
    assert zeichnen and 'zeitleisteNachladen()' in zeichnen.group(0), (
        'renderInvoices laedt die sichtbare Zeitleiste nicht nach.')
