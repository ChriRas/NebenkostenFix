"""NK-268 (R-35A-01): Lohnanteile nach § 35a EStG ausweisen, nicht berechnen.

Der Vermieter traegt an der Rechnung den Lohnanteil und seine Art ein
(haushaltsnahe Dienstleistung oder Handwerkerleistung). Der Kern legt ihn um
wie die Rechnung -- zeitanteilig, nach dem Schluessel, Leerstand beim
Vermieter -- und das Blatt zeigt je Art eine Tabelle. Keine Steuersaetze,
keine Hoechstbetraege; an den Betraegen der Abrechnung aendert sich nichts.

Alle Zahlen sind erfunden und mit der Hand nachgerechnet.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import reportlab.rl_config
import sqlalchemy

from billing_factories import apt, house, tenant
from nebenkostenfix import heizung, lohnausweis
from nebenkostenfix.pdf_generator import PDFGenerator
from tests.test_pdf_tageskonvention import _posten, _text
from nebenkostenfix.rechenkern import (
    Heizungsanlage, Kategorie, Mieter, Rechnung, Stand, Vorgang, Wohnung,
    Zaehler, rechne,
)

BEGINN = date(2025, 1, 1)
ENDE = date(2025, 12, 31)
GARTEN = Kategorie(id=3, name='Gartenpflege', braucht_zaehler=False)
HAUSWART = Kategorie(id=4, name='Hauswart', braucht_zaehler=False)
WAERME = Kategorie(id=9, name='Heizung', braucht_zaehler=True, betrkv_nr=4)
WARMWASSER = Kategorie(id=10, name='Warmwasser', braucht_zaehler=True, betrkv_nr=5)
WURZEL = Path(__file__).resolve().parents[1]


def rechnung(betrag='1000.00', id=1, kategorie=GARTEN, **kw):
    return Rechnung(id=id, kategorie=kategorie, betrag=Decimal(betrag),
                    beginn=BEGINN, ende=ENDE, **kw)


def haus(rechnungen, einzug=date(2020, 1, 1), qm=(25.0, 75.0), **kw):
    """Mein Mieter in 25 von 100 qm; die grosse Wohnung steht leer."""
    meine = Wohnung(id=1, name='EG', qm=qm[0])
    leer = Wohnung(id=2, name='OG', qm=qm[1])
    ich = Mieter(id=1, name='Anna Mieterin', einzug=einzug, auszug=None, wohnung_id=1)
    grund = dict(
        mieter=ich, wohnung=meine, immobilie_id=1, immobilie_name='Hauptstrasse 1',
        beginn=BEGINN, ende=ENDE, wohnungen=(meine, leer), mieter_der_immobilie=(ich,),
        profile={GARTEN.id: 'qm', HAUSWART.id: 'qm'}, rechnungen=tuple(rechnungen),
        zaehler=(),
    )
    grund.update(kw)
    return Vorgang(**grund)


def zeilen(ergebnis):
    """``{(Art, Kostenart): Betrag}`` aus dem Ausweis."""
    return {(g['art'], z['kostenart']): z['betrag']
            for g in (ergebnis['ausweis_35a'] or {'gruppen': []})['gruppen']
            for z in g['zeilen']}


# --- Umlage wie die Rechnung -------------------------------------------------

def test_lohn_folgt_dem_mieteranteil_der_rechnung():
    """1.000 Euro, davon 400 Lohn; Anna traegt 25 von 100 qm = 250 Euro.

    Ihr Lohnanteil: 400 · 250 / 1.000 = 100,00. Die leere Wohnung (750 Euro,
    300 Euro Lohn) bleibt beim Vermieter und steht nicht in Annas Tabelle.
    """
    ergebnis = rechne(haus([rechnung(art_35a='haushaltsnah', lohnanteil=Decimal('400.00'))]))
    assert ergebnis['line_items'][0]['tenant_cost'] == Decimal('250.00')
    assert zeilen(ergebnis) == {('haushaltsnah', 'Gartenpflege'): Decimal('100.00')}
    gruppe, = ergebnis['ausweis_35a']['gruppen']
    assert gruppe['art_text'] == 'Haushaltsnahe Dienstleistungen'
    assert gruppe['summe'] == Decimal('100.00')
    assert ergebnis['ausweis_35a']['hinweis'] == lohnausweis.HINWEIS


def test_unterjaehrig_nur_die_eigenen_tage():
    """Einzug am 1. Juli: 184 von 365 Tagen. 400 · 0,25 · 184/365 = 50,41."""
    ergebnis = rechne(haus([rechnung(art_35a='handwerker', lohnanteil=Decimal('400.00'))],
                           einzug=date(2025, 7, 1), beginn=date(2025, 7, 1)))
    assert zeilen(ergebnis) == {('handwerker', 'Gartenpflege'): Decimal('50.41')}


def test_getrennt_nach_art_in_der_reihenfolge_des_gesetzes():
    ergebnis = rechne(haus([
        rechnung(id=1, kategorie=HAUSWART, art_35a='handwerker', lohnanteil=Decimal('200.00')),
        rechnung(id=2, art_35a='haushaltsnah', lohnanteil=Decimal('400.00')),
        rechnung(id=3, kategorie=HAUSWART, betrag='500.00'),
    ]))
    arten = [(g['art'], g['summe']) for g in ergebnis['ausweis_35a']['gruppen']]
    assert arten == [('haushaltsnah', Decimal('100.00')), ('handwerker', Decimal('50.00'))]


def test_ohne_angabe_keine_tabelle():
    assert rechne(haus([rechnung()]))['ausweis_35a'] is None


def test_lohn_null_ergibt_keine_zeile():
    ergebnis = rechne(haus([rechnung(art_35a='handwerker', lohnanteil=Decimal('0.00'))]))
    assert ergebnis['ausweis_35a'] is None


def test_betraege_der_abrechnung_bleiben_unveraendert():
    """R-35A-01 Punkt 5: der Ausweis ist eine Zugabe, keine Umlage."""
    ohne = rechne(haus([rechnung()]))
    mit = rechne(haus([rechnung(art_35a='haushaltsnah', lohnanteil=Decimal('400.00'))]))
    ohne.pop('ausweis_35a')
    mit.pop('ausweis_35a')
    assert mit == ohne


def test_summe_ist_die_summe_der_gerundeten_zeilen():
    """R-NUM-02: 1,005 + 1,005 zeigt 1,01 + 1,01 = 2,02, nicht 2,01."""
    ausweis = lohnausweis.ausweis({
        ('Gartenpflege', 'haushaltsnah'): Decimal('1.005'),
        ('Hauswart', 'haushaltsnah'): Decimal('1.005'),
        ('Winterdienst', 'haushaltsnah'): Decimal('0.004'),  # rundet auf 0,00: entfaellt
    })
    gruppe, = ausweis['gruppen']
    assert [z['betrag'] for z in gruppe['zeilen']] == [Decimal('1.01'), Decimal('1.01')]
    assert gruppe['summe'] == Decimal('2.02')


def test_modul_haengt_an_nichts_als_geld():
    """Derselbe Waechter wie fuer ``co2``: ``lohnausweis`` ist ein Baustein des
    Rechenkerns und darf kein Modell hereinziehen (test_kern_importiert_kein_orm)."""
    import ast
    from tests.importwaechter import importierte_module

    baum = ast.parse((WURZEL / 'nebenkostenfix' / 'lohnausweis.py').read_text(encoding='utf-8'))
    importiert = importierte_module(baum)
    assert importiert <= {'__future__', 'decimal', 'typing', 'geld'}, (
        f'lohnausweis.py zieht fremde Module herein: {importiert}')


def test_mieteranteil_ohne_rechnungsbetrag_ist_null():
    assert lohnausweis.mieteranteil(Decimal('10'), Decimal('0'), Decimal('0')) == Decimal('0')


# --- Heizkosten: je Zweck, auf dem Teil ohne CO2 -----------------------------

def _zaehler(id, wohnung_id, verbraucht, kategorie):
    return Zaehler(
        id=id, nummer=f'Z-{id}', kategorie_id=kategorie.id, kategorie_name=kategorie.name,
        ist_hauptzaehler=False, immobilie_id=1, wohnung_id=wohnung_id,
        staende=(Stand(datum=BEGINN, wert=0.0), Stand(datum=date(2026, 1, 1), wert=verbraucht)),
        heizungsanlage_id=1, kategorie_betrkv_nr=kategorie.betrkv_nr)


def _heizhaus(rechnungen, anlage, zaehler):
    meine = Wohnung(id=1, name='EG links', qm=50.0)
    andere = Wohnung(id=2, name='EG rechts', qm=50.0)
    ich = Mieter(id=1, name='Anna Mieterin', einzug=date(2020, 1, 1), auszug=None, wohnung_id=1)
    nachbar = Mieter(id=2, name='Bert Nachbar', einzug=date(2020, 1, 1), auszug=None, wohnung_id=2)
    return Vorgang(
        mieter=ich, wohnung=meine, immobilie_id=1, immobilie_name='Hauptstrasse 1',
        beginn=BEGINN, ende=ENDE, wohnungen=(meine, andere),
        mieter_der_immobilie=(ich, nachbar), profile={}, rechnungen=tuple(rechnungen),
        zaehler=tuple(zaehler), heizungsanlagen=(anlage,))


def _heizrechnung(betrag, id=1, art='brennstoff', **kw):
    return Rechnung(id=id, kategorie=WAERME, betrag=Decimal(betrag), beginn=BEGINN, ende=ENDE,
                    heizungsanlage_id=1, heizkostenart=art, **kw)


def test_heizkosten_je_zweck_der_verbundenen_anlage():
    """Ein Viertel der Waerme geht ans Wasser: 400 Lohn werden 100 und 300.

    Anna traegt 4.275 von 7.500 Heizkosten und 900 von 2.500 Warmwasser
    (die Zahlen aus test_warmwassertrennung): 300 · 0,57 = 171,00 und
    100 · 0,36 = 36,00.
    """
    anlage = Heizungsanlage(
        id=1, name='Kessel', versorgt=heizung.VERBUNDEN, verbrauchsanteil_prozent=70,
        warmwasser_weg=heizung.WW_ZAEHLER, warmwasser_kwh=Decimal('15000'),
        brennstoff_menge=Decimal('60000'))
    zaehler = (_zaehler(1, 1, 1200.0, WAERME), _zaehler(2, 2, 800.0, WAERME),
               _zaehler(3, 1, 30.0, WARMWASSER), _zaehler(4, 2, 70.0, WARMWASSER))
    ergebnis = rechne(_heizhaus(
        [_heizrechnung('10000.00', art='pruefung', art_35a='handwerker',
                       lohnanteil=Decimal('400.00'))], anlage, zaehler))
    assert zeilen(ergebnis) == {
        ('handwerker', 'Heizkosten (Kessel)'): Decimal('171.00'),
        ('handwerker', 'Warmwasserkosten (Kessel)'): Decimal('36.00'),
    }


def test_heizkosten_mit_co2_angabe_rechnen_ohne_den_co2_teil():
    """Brennstoff 10.000 mit 2.000 CO2-Kosten: Masse 8.000, Anna 4.560.

    Die Pruefung (500 Euro, CO2-Angabe 0) laeuft durch denselben Schluessel:
    Anna 285 von 500. Lohn 800 · 4.560/8.000 = 456 plus 300 · 285/500 = 171.
    """
    anlage = Heizungsanlage(id=1, name='Zentralheizung', verbrauchsanteil_prozent=70)
    zaehler = (_zaehler(1, 1, 1200.0, WAERME), _zaehler(2, 2, 800.0, WAERME))
    ergebnis = rechne(_heizhaus([
        _heizrechnung('10000.00', id=1, co2_kosten=Decimal('2000.00'),
                      co2_emission_kg=Decimal('2200.00'), art_35a='haushaltsnah',
                      lohnanteil=Decimal('800.00')),
        _heizrechnung('500.00', id=2, art='pruefung', co2_kosten=Decimal('0.00'),
                      co2_emission_kg=Decimal('0.00'), art_35a='haushaltsnah',
                      lohnanteil=Decimal('300.00')),
    ], anlage, zaehler))
    assert ergebnis['co2']['stufe'] == 4  # die Pruefung mit CO2-Angabe 0 stoert die Einstufung nicht
    assert zeilen(ergebnis) == {('haushaltsnah', 'Heizkosten (Zentralheizung)'): Decimal('627.00')}


# --- Das Blatt ---------------------------------------------------------------

@pytest.fixture
def unkomprimiert(monkeypatch):
    monkeypatch.setattr(reportlab.rl_config, 'pageCompression', 0)


def _pdf_text(ausweis):
    pdf = PDFGenerator(property_name='Haus am Anger', apartment_name='EG', tenant_name='Anna',
                       start_date='2024-01-01', end_date='2024-12-31').generate(
        [_posten(anteilig=False)], Decimal('600.00'), Decimal('0.00'), ausweis_35a=ausweis)
    return _text(pdf)


def test_pdf_zeigt_die_tabelle_mit_hinweis(unkomprimiert):
    text = _pdf_text(lohnausweis.ausweis({
        ('Gartenpflege', 'haushaltsnah'): Decimal('100'),
        ('Hauswart', 'handwerker'): Decimal('50'),
    }))
    assert 'Lohnanteile nach' in text and '35a EStG' in text  # § steht als Oktal-Escape im Strom
    assert 'Haushaltsnahe Dienstleistungen' in text
    assert 'Handwerkerleistungen' in text
    assert '100,00' in text and '50,00' in text
    assert 'Finanzamt' in text  # der Hinweis
    assert '20 %' not in text and 'chstbetrag' not in text  # keine Steuerlogik


def test_pdf_ohne_angabe_ohne_abschnitt(unkomprimiert):
    assert 'Lohnanteile' not in _pdf_text(None)


def test_beide_pdf_wege_reichen_den_ausweis_durch():
    app = (WURZEL / 'app.py').read_text(encoding='utf-8')
    assert app.count('pdf_gen.generate(') == app.count("ausweis_35a=bill_data.get('ausweis_35a')") == 2


# --- Route, Lader, Datenbank -------------------------------------------------

def _garten_rechnung(auth_client, **felder):
    prop = house(name='Lohnhaus')
    wng = apt(prop, 'Lohn-EG', 50.0)
    tenant(wng, 'Lohnmieter', move_in=date(2024, 1, 1))
    from nebenkostenfix.models import CostCategory
    kat = CostCategory.query.filter_by(name='Wasserversorgung').first()
    daten = {'category_id': kat.id, 'property_id': prop.id, 'apartment_id': wng.id,
             'amount': '1200.00', 'start_date': '2025-01-01', 'end_date': '2025-12-31'}
    daten.update(felder)
    return auth_client.post('/api/invoices', json=daten)


def _zeile(auth_client, neu):
    return next(i for i in auth_client.get('/api/invoices').get_json() if i['id'] == neu)


def test_route_speichert_aendert_und_loescht_die_angabe(auth_client, app_ctx):
    antwort = _garten_rechnung(auth_client, art_35a='handwerker', lohnanteil='400,00')
    assert antwort.status_code == 201, antwort.get_data(as_text=True)
    neu = antwort.get_json()['id']
    zeile = _zeile(auth_client, neu)
    assert zeile['art_35a'] == 'handwerker'
    assert Decimal(str(zeile['lohnanteil'])) == Decimal('400.00')

    daten = {k: zeile[k] for k in ('category_id', 'property_id', 'apartment_id', 'start_date',
                                   'end_date')}
    daten['amount'] = '1200.00'
    antwort = auth_client.put(f'/api/invoices/{neu}', json=daten)
    assert antwort.status_code == 200, antwort.get_data(as_text=True)
    zeile = _zeile(auth_client, neu)
    assert zeile['art_35a'] is None and zeile['lohnanteil'] is None


def test_route_ohne_angabe_bleibt_leer(auth_client, app_ctx):
    neu = _garten_rechnung(auth_client, art_35a='').get_json()['id']
    zeile = _zeile(auth_client, neu)
    assert zeile['art_35a'] is None and zeile['lohnanteil'] is None


@pytest.mark.parametrize('felder, feld', [
    ({'art_35a': 'handwerker'}, 'lohnanteil'),
    ({'lohnanteil': '100.00'}, 'art_35a'),
    ({'art_35a': 'steuerfrei', 'lohnanteil': '100.00'}, 'art_35a'),
    ({'art_35a': 'handwerker', 'lohnanteil': '1200.01'}, 'lohnanteil'),
    ({'art_35a': 'handwerker', 'lohnanteil': '-1.00'}, 'lohnanteil'),
])
def test_route_lehnt_falsche_angaben_ab(auth_client, app_ctx, felder, feld):
    antwort = _garten_rechnung(auth_client, **felder)
    assert antwort.status_code == 400
    assert antwort.get_json()['feld'] == feld


def test_lader_reicht_art_und_lohn_durch(auth_client, app_ctx):
    from nebenkostenfix.abrechnungsdaten import _rechnung
    from nebenkostenfix.models import CostInvoice
    neu = _garten_rechnung(auth_client, art_35a='haushaltsnah', lohnanteil='99.90').get_json()['id']
    geladen = _rechnung(CostInvoice.query.get(neu))
    assert (geladen.art_35a, geladen.lohnanteil) == ('haushaltsnah', Decimal('99.90'))


@pytest.mark.parametrize('art, lohn', [
    ('handwerker', None), (None, Decimal('1.00')), ('steuerfrei', Decimal('1.00')),
    ('handwerker', Decimal('1200.01')), ('handwerker', Decimal('-0.01')),
])
def test_datenbank_haelt_die_regel_fest(auth_client, app_ctx, art, lohn):
    from nebenkostenfix.models import CostInvoice, db
    neu = _garten_rechnung(auth_client).get_json()['id']
    rechnung_db = CostInvoice.query.get(neu)
    rechnung_db.art_35a, rechnung_db.lohnanteil = art, lohn
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()
