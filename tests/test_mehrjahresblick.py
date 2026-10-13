"""NK-263: Mehrjahresblick je Wohnung.

Euro je m² und Jahr je Kostenart und die Vorauszahlungen, je Abrechnungsjahr
des Hauses, aus den festgesetzten Abrechnungen. Alle Werte sind erfunden.
"""

from __future__ import annotations

from datetime import date

import pytest

from nebenkostenfix import mehrjahresblick as mj
from nebenkostenfix.models import BillingReportVersion, TenantBillingReport, db
from tests import billing_factories as f

D = date


def _je_jahr(liste):
    return {j['jahr']: j for j in liste}


# --- Kern ----------------------------------------------------------------------

def test_abweichendes_abrechnungsjahr_traegt_den_schalttag_und_heisst_2023_24():
    liste = mj.verlauf([
        (D(2023, 7, 1), D(2024, 6, 30), 50, [('Wasser', 600)], 700),
        (D(2024, 7, 1), D(2025, 6, 30), 50, [('Wasser', '547.50')], 720),
    ], 7, 1)
    assert [(j['jahr'], j['von'], j['bis'], j['jahrestage'], j['belegte_tage']) for j in liste] == [
        ('2023/24', '2023-07-01', '2024-06-30', 366, 366),
        ('2024/25', '2024-07-01', '2025-06-30', 365, 365)]
    assert liste[0]['je_qm'] == {'Wasser': '12.00'}
    assert liste[1]['je_qm'] == {'Wasser': '10.95'}
    assert [j['vorauszahlung'] for j in liste] == ['700.00', '720.00']


def test_eine_abrechnung_ab_maerz_gehoert_zum_jahr_das_im_juli_davor_begann():
    assert mj.jahresanfang(D(2024, 3, 1), 7, 1) == D(2023, 7, 1)
    assert mj.jahresanfang(D(2024, 7, 1), 7, 1) == D(2024, 7, 1)
    assert mj.jahresanfang(D(2024, 12, 31), 1, 1) == D(2024, 1, 1)


def test_leerstand_im_jahr_verduennt_den_wert_je_qm_nicht():
    # 182 Tage belegt, der Rest leer: hochgerechnet auf 366 Tage.
    liste = mj.verlauf([(D(2024, 1, 1), D(2024, 6, 30), 60, [('Wasser', 300)], 400)], 1, 1)
    assert liste[0]['jahr'] == '2024' and liste[0]['belegte_tage'] == 182
    assert liste[0]['je_qm'] == {'Wasser': '10.05'}  # 300 * 366 / (60 * 182)


def test_ein_ganz_leeres_jahr_steht_als_luecke_da():
    liste = mj.verlauf([
        (D(2023, 1, 1), D(2023, 12, 31), 60, [('Wasser', 600)], 500),
        (D(2025, 1, 1), D(2025, 12, 31), 60, [('Wasser', 660)], 550),
    ], 1, 1)
    assert [j['jahr'] for j in liste] == ['2023', '2024', '2025']
    leer = liste[1]
    assert (leer['belegte_tage'], leer['je_qm'], leer['je_qm_gesamt'], leer['vorauszahlung']) == \
        (0, {}, None, '0.00')


def test_geaenderte_wohnflaeche_zaehlt_mit_der_flaeche_jeder_abrechnung():
    # Halbjahr auf 50 m², Halbjahr auf 60 m²: Nenner sind die Flaechentage.
    liste = mj.verlauf([
        (D(2024, 1, 1), D(2024, 6, 30), 50, [('Wasser', 500)], 0),
        (D(2024, 7, 1), D(2024, 12, 31), 60, [('Wasser', 600)], 0),
    ], 1, 1)
    assert liste[0]['belegte_tage'] == 366
    assert liste[0]['je_qm'] == {'Wasser': '19.99'}  # 1100 * 366 / (50*182 + 60*184)


def test_kostenarten_getrennt_gesamt_und_ohne_flaeche_kein_wert():
    liste = mj.verlauf([(D(2024, 1, 1), D(2024, 12, 31), 40,
                         [('Wasser', 200), ('Heizung', 800), ('Wasser', 40)], '1000.10')], 1, 1)
    assert liste[0]['je_qm'] == {'Heizung': '20.00', 'Wasser': '6.00'}
    assert liste[0]['je_qm_gesamt'] == '26.00'
    assert liste[0]['vorauszahlung'] == '1000.10'
    ohne = mj.verlauf([(D(2024, 1, 1), D(2024, 12, 31), None, [('Wasser', 200)], 0)], 1, 1)
    assert ohne[0]['je_qm'] == {'Wasser': None} and ohne[0]['je_qm_gesamt'] is None


def test_ohne_abrechnung_kein_verlauf():
    assert mj.verlauf([], 1, 1) == []


# --- Über die API --------------------------------------------------------------

def _abrechnung(mieter, von, bis, qm, zeilen, vorauszahlung, nummer=1, report=None):
    if report is None:
        report = TenantBillingReport(tenant_id=mieter.id, start_date=von, end_date=bis,
                                     frist_ende=D(bis.year + 1, 12, 31))
        db.session.add(report)
        db.session.commit()
    db.session.add(BillingReportVersion(
        report_id=report.id, nummer=nummer, eingangsdaten={'wohnung': {'qm': qm}},
        ergebnis={'line_items': [{'category': k, 'tenant_cost': str(b)} for k, b in zeilen],
                  'prepaid_amount': str(vorauszahlung)},
        software_version='0.0.0', regel_version='2026-01-01'))
    db.session.commit()
    return report


@pytest.fixture
def wohnung(app_ctx):
    haus = f.house('Haus H')
    haus.abrechnungsjahr_beginn = '07-01'
    w = f.apt(haus, 'EG', 50)
    a = f.tenant(w, 'Mieter A', D(2023, 7, 1))
    b = f.tenant(w, 'Mieter B', D(2024, 7, 1))
    bericht = _abrechnung(a, D(2023, 7, 1), D(2024, 6, 30), 40,
                          [('Wasser', 480), ('Heizung', 960)], 1500)
    # Die Korrektur gilt, nicht die erste Fassung.
    _abrechnung(a, None, None, 40, [('Wasser', 400), ('Heizung', 960)], 1500, 2, bericht)
    _abrechnung(b, D(2024, 7, 1), D(2025, 6, 30), 50, [('Wasser', 500)], 1200)
    nachbar = f.tenant(f.apt(haus, 'OG', 70), 'Mieter C', D(2023, 7, 1))
    _abrechnung(nachbar, D(2023, 7, 1), D(2024, 6, 30), 70, [('Wasser', 9999)], 1)
    w.sqm = 80  # spaeter umgemessen: die alten Jahre bleiben, wie sie abgerechnet wurden
    db.session.commit()
    return w


def test_die_wohnungsauswertung_liefert_den_mehrjahresblick(auth_client, wohnung):
    res = auth_client.get(f'/api/analytics/apartment/{wohnung.id}')
    assert res.status_code == 200
    jahre = _je_jahr(res.get_json()['mehrjahresblick'])
    assert list(jahre) == ['2023/24', '2024/25']
    assert jahre['2023/24']['je_qm'] == {'Heizung': '24.00', 'Wasser': '10.00'}
    assert jahre['2023/24']['je_qm_gesamt'] == '34.00'
    assert jahre['2023/24']['vorauszahlung'] == '1500.00'
    assert jahre['2024/25']['je_qm'] == {'Wasser': '10.00'}
    assert jahre['2024/25']['vorauszahlung'] == '1200.00'


def test_altbestand_ohne_version_rechnet_mit_der_heutigen_flaeche(auth_client, app_ctx,
                                                                   monkeypatch):
    import app as app_modul
    haus = f.house('Haus H')
    w = f.apt(haus, 'EG', 50)
    a = f.tenant(w, 'Mieter A', D(2024, 1, 1))
    db.session.add(TenantBillingReport(tenant_id=a.id, start_date=D(2024, 1, 1),
                                       end_date=D(2024, 12, 31), frist_ende=D(2025, 12, 31)))
    db.session.commit()
    monkeypatch.setattr(app_modul, '_bericht_ergebnis', lambda r: (
        {'line_items': [{'category': 'Wasser', 'tenant_cost': 500.0}], 'prepaid_amount': 300.0},
        None))
    jahre = auth_client.get(f'/api/analytics/apartment/{w.id}').get_json()['mehrjahresblick']
    assert [(j['jahr'], j['je_qm'], j['vorauszahlung']) for j in jahre] == \
        [('2024', {'Wasser': '10.00'}, '300.00')]


def test_ohne_abrechnung_ist_der_blick_leer(auth_client, app_ctx):
    w = f.apt(f.house('Haus H'), 'EG', 50)
    assert auth_client.get(f'/api/analytics/apartment/{w.id}').get_json()['mehrjahresblick'] == []
