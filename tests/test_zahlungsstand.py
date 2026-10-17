"""Phase 47: Zahlungsstand je Abrechnung, abgeleitet statt gespeichert.

Das Ergebnis ist positiv bei einer Nachzahlung des Mieters, negativ bei einem
Guthaben. Dagegen zählen die Nebenkostenzahlungen an der Abrechnung; ein
ausgezahltes Guthaben ist eine negative Zahlung. Der Restbetrag trägt das
Vorzeichen: positiv schuldet der Mieter, negativ zahlt der Vermieter aus.

*Hätte die Lücke gefunden:* jeder Test hier (gegen den Stand davor rot).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from nebenkostenfix.zahlungsstand import zahlungsstand

WURZEL = Path(__file__).resolve().parents[1]
QUELLE = (WURZEL / 'static' / 'app.js').read_text(encoding='utf-8')
SEITE = (WURZEL / 'static' / 'index.html').read_text(encoding='utf-8')
GLOSSAR = (WURZEL / 'docs' / 'SPEC' / 'glossar.md').read_text(encoding='utf-8')

braucht_node = pytest.mark.skipif(shutil.which('node') is None, reason='node fehlt')


# --- Die Rechnung -------------------------------------------------------------


def test_ohne_zahlung_ist_die_nachzahlung_offen():
    assert zahlungsstand('840.00', []) == ('offen', Decimal('840.00'))


def test_teilzahlung_laesst_den_rest_offen():
    assert zahlungsstand('840.00', [Decimal('500')]) == ('teilweise', Decimal('340.00'))


def test_volle_zahlung_ist_beglichen():
    assert zahlungsstand('840.00', [Decimal('500'), Decimal('340')]) == \
        ('beglichen', Decimal('0.00'))


def test_ueberzahlung_dreht_das_vorzeichen():
    # 20 € zu viel: der Vermieter zahlt sie zurück.
    assert zahlungsstand('840.00', [Decimal('860')]) == ('ueberzahlt', Decimal('-20.00'))


def test_ergebnis_null_ist_ausgeglichen():
    assert zahlungsstand('0.00', []) == ('ausgeglichen', Decimal('0.00'))


def test_zahlung_auf_ergebnis_null_ist_ueberzahlt():
    assert zahlungsstand('0', [Decimal('5')]) == ('ueberzahlt', Decimal('-5.00'))


def test_guthaben_ist_offen_bis_es_ausgezahlt_ist():
    assert zahlungsstand('-360.00', []) == ('offen', Decimal('-360.00'))
    assert zahlungsstand('-360.00', [Decimal('-100')]) == ('teilweise', Decimal('-260.00'))
    assert zahlungsstand('-360.00', [Decimal('-360')]) == ('beglichen', Decimal('0.00'))
    assert zahlungsstand('-360.00', [Decimal('-400')]) == ('ueberzahlt', Decimal('40.00'))


def test_hin_und_zurueck_gebucht_bleibt_offen():
    assert zahlungsstand('100', [Decimal('50'), Decimal('-50')]) == ('offen', Decimal('100.00'))


def test_rechnet_auf_den_cent_ohne_float_rest():
    # 0.1 + 0.2 als float wäre 0.30000000000000004.
    assert zahlungsstand('0.30', ['0.1', '0.2']) == ('beglichen', Decimal('0.00'))
    assert zahlungsstand('10.005', []) == ('offen', Decimal('10.01'))


# --- Die Routen ---------------------------------------------------------------

from billing_factories import apt, category, house, invoice, payment, tenant  # noqa: E402

ZEITRAUM = {'start_date': '2025-01-01', 'end_date': '2025-12-31'}


def _abrechnung(auth_client, kosten):
    """Ein Mieter allein im Haus, 80 € Vorauszahlung im Monat, festgesetzt."""
    from nebenkostenfix.models import TenantBillingReport
    prop = house('Zahlungshaus')
    mieter = tenant(apt(prop, 'EG', 50.0), 'Zora Zahlerin', move_in=date(2024, 1, 1))
    invoice(prop, category('Grundsteuer'), kosten, date(2025, 1, 1), date(2025, 12, 31))
    for m in range(1, 13):
        payment(mieter, 80.0, date(2025, m, 1))
    assert auth_client.post('/api/billing/finalize', json={
        'tenant_id': mieter.id, **ZEITRAUM}).status_code == 201
    return mieter, TenantBillingReport.query.one()


def _stand(auth_client, report_id):
    details = auth_client.get(f'/api/billing/reports/{report_id}/details').get_json()
    liste = {r['id']: r for r in auth_client.get('/api/billing/reports').get_json()}
    zeile = liste[report_id]
    assert (zeile['zahlungsstand'], zeile['offen_betrag']) == \
        (details['zahlungsstand'], details['offen_betrag'])
    return details['zahlungsstand'], details['offen_betrag']


def _zahle(auth_client, mieter, report_id, betrag):
    antwort = auth_client.post('/api/payments', json={
        'tenant_id': mieter.id, 'amount': betrag, 'payment_date': '2026-03-01',
        'type': 'Nebenkostenzahlung', 'billing_report_id': report_id})
    assert antwort.status_code == 201, antwort.get_data(as_text=True)


def test_nachzahlung_in_details_und_liste(auth_client, app_ctx):
    mieter, report = _abrechnung(auth_client, 1800.0)  # 1800 − 960 = 840
    assert _stand(auth_client, report.id) == ('offen', '840.00')
    _zahle(auth_client, mieter, report.id, '500')
    assert _stand(auth_client, report.id) == ('teilweise', '340.00')
    _zahle(auth_client, mieter, report.id, '340')
    assert _stand(auth_client, report.id) == ('beglichen', '0.00')


def test_guthaben_wird_als_negative_zahlung_ausgezahlt(auth_client, app_ctx):
    mieter, report = _abrechnung(auth_client, 600.0)  # 600 − 960 = −360
    assert _stand(auth_client, report.id) == ('offen', '-360.00')
    _zahle(auth_client, mieter, report.id, '-360')
    assert _stand(auth_client, report.id) == ('beglichen', '0.00')


def test_die_liste_nennt_die_zustellung(auth_client, app_ctx):
    _, report = _abrechnung(auth_client, 1800.0)
    zeile = auth_client.get('/api/billing/reports').get_json()[0]
    assert zeile['zugestellt_am'] is None
    heute = date.today().isoformat()  # frühestens am Tag der Erstellung
    assert auth_client.post(f'/api/billing/reports/{report.id}/zustellung',
                            json={'zugestellt_am': heute}).status_code == 200
    zeile = auth_client.get('/api/billing/reports').get_json()[0]
    assert zeile['zugestellt_am'] == heute


# --- Die Oberfläche -----------------------------------------------------------


def _funktion(name: str) -> str:
    treffer = re.search(rf'^(async )?function {name}\(', QUELLE, re.M)
    assert treffer, f'function {name} fehlt in app.js'
    return QUELLE[treffer.start():QUELLE.index('\n}', treffer.start()) + 2]


def _node(code: str):
    lauf = subprocess.run(['node', '-e', code], capture_output=True, text=True,
                          timeout=30, check=False)
    assert lauf.returncode == 0, lauf.stderr
    return json.loads(lauf.stdout.strip().splitlines()[-1])


HILFEN = (
    "const escapeHtml = s => String(s).replace(/</g, '&lt;');\n"
    "const datumText = d => d;\n"
    "const euroText = b => Number(b).toFixed(2) + ' €';\n"
)


@braucht_node
def test_heute_nennt_offene_zahlungen_zugestellter_abrechnungen():
    code = HILFEN + (
        "const echterBestand = () => ({ properties: [], meters: [], readings: [] });\n"
        "const tenants = [{ id: 7, ist_beispiel: true }];\n"
        "const abrechnungsVorschlaege = []; const currentDocuments = [];\n"
        "const abrechnungsHistorie = [\n"
        " { id: 1, tenant_id: 8, tenant_name: 'Spät', apartment_name: 'OG', zugestellt_am: '2026-03-01', zahlungsstand: 'offen', offen_betrag: '840.00' },\n"
        " { id: 2, tenant_id: 9, tenant_name: 'Früh', apartment_name: 'EG', zugestellt_am: '2026-01-15', zahlungsstand: 'teilweise', offen_betrag: '-60.00' },\n"
        " { id: 3, tenant_id: 8, tenant_name: 'Unzugestellt', apartment_name: 'OG', zugestellt_am: null, zahlungsstand: 'offen', offen_betrag: '10.00' },\n"
        " { id: 4, tenant_id: 8, tenant_name: 'Bezahlt', apartment_name: 'OG', zugestellt_am: '2026-01-01', zahlungsstand: 'beglichen', offen_betrag: '0.00' },\n"
        " { id: 5, tenant_id: 7, tenant_name: 'Beispiel', apartment_name: 'B', zugestellt_am: '2026-01-01', zahlungsstand: 'offen', offen_betrag: '5.00' },\n"
        " { id: 6, tenant_id: 8, tenant_name: 'Altbestand', apartment_name: 'OG', zugestellt_am: '2025-01-01', zahlungsstand: null, offen_betrag: null }];\n"
        + _funktion('heuteAufgaben') +
        "\nconsole.log(JSON.stringify(heuteAufgaben().map(g => [g.name, g.aufgaben.map(a => [a.titel, a.info, a.chip, a.aktion])])));"
    )
    assert _node(code) == [['Zahlungen', [
        ['Früh (EG)', 'Guthaben noch auszahlen: 60.00 € · zugestellt am 2026-01-15',
         'auszahlen', 'Zahlung erfassen'],
        ['Spät (OG)', 'Nachzahlung offen: 840.00 € · zugestellt am 2026-03-01',
         'offen', 'Zahlung erfassen'],
    ]]]


@braucht_node
def test_details_zeigen_den_zahlungsstand_mit_knopf():
    code = HILFEN + _funktion('zahlungsstandPille') + _funktion('zahlungsstandBlock') + (
        "\nconsole.log(JSON.stringify(["
        "zahlungsstandBlock(4, { tenant_id: 8, zahlungsstand: 'teilweise', offen_betrag: '340.00' }),"
        "zahlungsstandBlock(4, { tenant_id: 8, zahlungsstand: 'offen', offen_betrag: '-360.00' }),"
        "zahlungsstandBlock(4, { tenant_id: 8, zahlungsstand: 'beglichen', offen_betrag: '0.00' }),"
        "zahlungsstandBlock(4, { veraltet: false })]));"
    )
    teil, guthaben, bezahlt, alt = _node(code)
    assert 'Zahlungsstand' in teil and 'teilweise beglichen' in teil
    assert 'Der Mieter schuldet noch 340.00 €' in teil
    assert "zahlungZurAbrechnung(4, 8, '340.00')" in teil
    assert 'An den Mieter auszuzahlen: 360.00 €' in guthaben
    assert "zahlungZurAbrechnung(4, 8, '-360.00')" in guthaben
    assert 'beglichen' in bezahlt and 'zahlungZurAbrechnung' not in bezahlt
    assert alt == ''


@braucht_node
def test_negativer_betrag_heisst_guthaben_ausgezahlt():
    code = (
        "const el = { 'label-payment-amount': { textContent: '' }, 'payment-hinweis': { hidden: true } };\n"
        "const document = { getElementById: id => el[id] };\n"
        + _funktion('zahlungsBetragBeschriften') +
        "\nconst stand = [];"
        "zahlungsBetragBeschriften('-360.00'); stand.push([el['label-payment-amount'].textContent, el['payment-hinweis'].hidden]);"
        "zahlungsBetragBeschriften('12'); stand.push([el['label-payment-amount'].textContent, el['payment-hinweis'].hidden]);"
        "console.log(JSON.stringify(stand));"
    )
    assert _node(code) == [['Guthaben ausgezahlt (€)', False], ['Betrag (€)', True]]
    assert 'id="label-payment-amount"' in SEITE and 'id="payment-hinweis"' in SEITE


def test_formular_schlaegt_den_restbetrag_vor():
    rumpf = _funktion('toggleBillingReportField')
    assert 'offen_betrag' in rumpf and 'zahlungsBetragBeschriften' in rumpf
    assert 'zahlungsBetragBeschriften' in _funktion('openAddPaymentModal')


def test_nach_dem_speichern_stimmt_der_stand_wieder():
    assert 'fetchBillingHistory()' in _funktion('savePayment')
    assert 'fetchBillingHistory()' in _funktion('deletePayment')


def test_liste_zeigt_pille_und_filtert_offene():
    rumpf = _funktion('fetchBillingHistory')
    assert 'zahlungsstandPille(' in rumpf and 'historieNurOffen' in rumpf
    assert 'id="historie-nur-offen"' in SEITE


def test_glossar_kennt_die_begriffe():
    for begriff in ('**Zahlungsstand**', '**offen**', '**beglichen**'):
        assert begriff in GLOSSAR


def test_zahlung_nur_an_eine_abrechnung_desselben_mieters(auth_client, app_ctx):
    # Seit Phase 47 zählt jede Zahlung an der Abrechnung in deren Stand: eine
    # fremde oder erfundene Abrechnung würde den Stand verfälschen.
    mieter, report = _abrechnung(auth_client, 1800.0)
    fremd = tenant(apt(house('Nachbarhaus'), 'OG', 40.0), 'Nico Nachbar',
                   move_in=date(2024, 1, 1))
    for tenant_id, report_id in [(fremd.id, report.id), (mieter.id, report.id + 99)]:
        antwort = auth_client.post('/api/payments', json={
            'tenant_id': tenant_id, 'amount': '100', 'payment_date': '2026-03-01',
            'type': 'Nebenkostenzahlung', 'billing_report_id': report_id})
        assert antwort.status_code == 400
        assert antwort.get_json()['feld'] == 'billing_report_id'
    assert _stand(auth_client, report.id) == ('offen', '840.00')


def test_mieterwechsel_laedt_die_abrechnungen_neu():
    # Sonst bleibt die Auswahl des vorigen Mieters stehen.
    assert re.search(r'<select id="payment-tenant"[^>]*onchange="toggleBillingReportField\(\)"', SEITE)
