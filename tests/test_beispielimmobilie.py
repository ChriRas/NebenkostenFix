"""NK-141: Die Beispielimmobilie fuer die Uebersicht „Fehlende Daten".

Die Demo ist keine Sonderbehandlung, sondern echte Daten: Zwei Wohnungen,
zwei Mieter, vier Zaehler in den vier Zustaenden der Aktualitaet und ein
Mietverhaeltnis, das nach Verbrauch abgerechnet wird, ohne Unterzaehler --
genau dafuer warnt die Uebersicht. Getestet wird durch die HTTP-Schicht:
Anlegen, Zweitversuch, und was die data-quality-Route daraus macht.
"""

from __future__ import annotations

import pytest

from app import beispielimmobilie as demo


@pytest.fixture(autouse=True)
def _keine_demo_ueberreste(app_ctx):
    """Die Demo traegt einen festen Namen; Reste aus frueheren Tests weg."""
    yield
    demo.entfernen()


def test_anlegen_legt_ein_komplett_unvollstaendiges_haus_an(app_ctx, auth_client):
    res = auth_client.post('/api/analytics/beispiel-immobilie')
    assert res.status_code == 201, res.get_data(as_text=True)
    bericht = res.get_json()
    assert bericht['wohnungen'] == 2
    assert bericht['mieter'] == 2
    assert bericht['zaehler'] == 4
    assert 'Beispielhaus' in demo.NAME

    from nebenkostenfix.models import (Apartment, Meter, MeterReading, Property, Tenant,
                        TenantCostProfile)
    haus = Property.query.filter_by(name=demo.NAME).one()
    wohnungen = Apartment.query.filter_by(property_id=haus.id).all()
    assert len(wohnungen) == 2
    mieter = [Tenant.query.filter_by(apartment_id=w.id).all()
              for w in wohnungen]
    assert sum(len(m) for m in mieter) == 2
    zaehler = Meter.query.filter_by(property_id=haus.id).all()
    assert len(zaehler) == 4
    assert MeterReading.query.count() == 3  # einer bleibt absichtlich ohne Stand
    assert TenantCostProfile.query.count() == 2


def test_uebersicht_zeigt_alle_vier_zustaende_und_eine_warnung(app_ctx, auth_client):
    res = auth_client.post('/api/analytics/beispiel-immobilie')
    property_id = res.get_json()['property_id']

    res = auth_client.get(f'/api/analytics/data-quality/{property_id}')
    assert res.status_code == 200
    qualitaet = res.get_json()

    zustaende = {m['status'] for m in qualitaet['meters']}
    # frisch, veraltet, dringend und nie gelesen -- jede Ampelstufe ist einmal da
    assert zustaende == {'green', 'yellow', 'red', 'none'}

    arten = {(w['type'], w['severity']) for w in qualitaet['warnings']}
    assert ('missing_submeter', 'error') in arten


def test_zweiter_aufruf_wird_gemeldet_nicht_doppelt_angelegt(app_ctx, auth_client):
    erste = auth_client.post('/api/analytics/beispiel-immobilie')
    property_id = erste.get_json()['property_id']

    zweite = auth_client.post('/api/analytics/beispiel-immobilie')
    assert zweite.status_code == 409
    assert zweite.get_json()['property_id'] == property_id

    from nebenkostenfix.models import Property
    assert Property.query.filter_by(name=demo.NAME).count() == 1


def test_anlegen_braucht_anmeldung(app_ctx, anon_client):
    assert anon_client.post(
        '/api/analytics/beispiel-immobilie').status_code == 401


# --- NK-159: vollständiges Beispiel ---------------------------------------------

def test_beispiel_bringt_rechnungen_zahlungen_und_eine_fertige_abrechnung(app_ctx, auth_client):
    from nebenkostenfix.models import CostInvoice, Payment, Property, TenantBillingReport
    from nebenkostenfix import datenordner
    res = auth_client.post('/api/analytics/beispiel-immobilie')
    bericht = res.get_json()
    assert bericht['abrechnung'] is True and bericht['rechnungen'] == len(demo.RECHNUNGEN)
    haus = Property.query.filter_by(name=demo.NAME).one()
    assert CostInvoice.query.filter_by(property_id=haus.id).count() == len(demo.RECHNUNGEN)
    abrechnung = TenantBillingReport.query.one()
    von, bis = demo.vorjahr()
    assert Payment.query.filter(Payment.tenant_id == abrechnung.tenant_id,
                                Payment.payment_date.between(von, bis)).count() == 12
    assert (abrechnung.start_date, abrechnung.end_date) == (von, bis)
    assert abrechnung.document_path_detailed
    assert (datenordner.belegordner() / abrechnung.document_path_detailed).is_file()


def test_beispiel_zaehlt_in_keiner_kennzahl(app_ctx, auth_client):
    auth_client.post('/api/analytics/beispiel-immobilie')
    haeuser = auth_client.get('/api/properties').get_json()
    assert [h['ist_beispiel'] for h in haeuser] == [True]
    assert all(m['ist_beispiel'] for m in auth_client.get('/api/tenants').get_json())
    assert all(z['ist_beispiel'] for z in auth_client.get('/api/payments').get_json())


def test_beispiel_loeschen_nimmt_alles_mit(app_ctx, auth_client):
    from nebenkostenfix.models import (Apartment, CostInvoice, Meter, MeterReading, Payment, Property,
                        Tenant, TenantBillingReport)
    from nebenkostenfix import datenordner
    auth_client.post('/api/analytics/beispiel-immobilie')
    pdf = datenordner.belegordner() / TenantBillingReport.query.one().document_path_detailed
    # Eine echte Immobilie daneben bleibt unberührt.
    from nebenkostenfix.models import db
    db.session.add(Property(name='Musterhaus Lindenstraße'))
    db.session.commit()

    antwort = auth_client.delete('/api/analytics/beispiel-immobilie')
    assert antwort.status_code == 200 and antwort.get_json() == {'entfernt': True, 'dateien': 1}
    assert [p.name for p in Property.query.all()] == ['Musterhaus Lindenstraße']
    for modell in (Apartment, Tenant, CostInvoice, Meter, MeterReading, Payment,
                   TenantBillingReport):
        assert modell.query.count() == 0, modell.__name__
    assert not pdf.exists()
    assert auth_client.delete('/api/analytics/beispiel-immobilie').get_json() == {'entfernt': False}


def test_beispiel_loeschen_braucht_anmeldung(app_ctx, anon_client):
    assert anon_client.delete('/api/analytics/beispiel-immobilie').status_code == 401



def test_vorauszahlungen_reichen_bis_heute(app_ctx):
    """NK-243: jeder Mieter zahlt monatlich bis zum Monat von „heute“, nie danach."""
    from datetime import date

    from nebenkostenfix.models import Payment, Tenant
    heute = date(2026, 5, 20)
    demo.anlegen(heute=heute)
    for name in demo.MIETER:
        mieter = Tenant.query.filter_by(name=name).one()
        tage = sorted(z.payment_date for z in Payment.query.filter_by(tenant_id=mieter.id))
        assert tage, name
        assert tage[-1] == date(2026, 5, 3), name
        assert tage[0] >= mieter.move_in_date, name
        monate = [(t.year, t.month) for t in tage]
        assert len(monate) == len(set(monate)) == (2026 - tage[0].year) * 12 + 5 - tage[0].month + 1, name
    # Ben zog 200 Tage vor „heute“ ein (14.10.2025): erste Zahlung im November.
    ben = Tenant.query.filter_by(name=demo.MIETER[1]).one()
    assert min(z.payment_date for z in Payment.query.filter_by(tenant_id=ben.id)) == date(2025, 11, 3)


def test_keine_vorauszahlung_vor_dem_faelligkeitstag(app_ctx):
    """NK-243: am 2. des Monats ist die Zahlung vom 3. noch Zukunft."""
    from datetime import date

    from nebenkostenfix.models import Payment
    demo.anlegen(heute=date(2026, 5, 2))
    assert max(z.payment_date for z in Payment.query) == date(2026, 4, 3)


# Das Beispielhaus wird am Namen erkannt (``ist_beispiel``) und ist von der
# Aufbewahrungssperre ausgenommen. Ein echtes Haus darf den Namen darum nicht
# bekommen -- weder beim Anlegen noch beim Umbenennen noch über den Import.

def test_ein_neues_haus_bekommt_den_beispielnamen_nicht(app_ctx, auth_client):
    from nebenkostenfix.models import Property
    res = auth_client.post('/api/properties', json={'name': demo.NAME})
    assert res.status_code == 400
    assert demo.NAME in res.get_json()['error']
    assert Property.query.filter_by(name=demo.NAME).count() == 0


def test_ein_echtes_haus_wird_nicht_zum_beispiel_umbenannt(app_ctx, auth_client):
    from billing_factories import house
    from nebenkostenfix.models import Property, db
    haus = house('Echtes Haus')
    res = auth_client.put(f'/api/properties/{haus.id}', json={'name': demo.NAME})
    assert res.status_code == 400
    db.session.expire_all()
    assert db.session.get(Property, haus.id).name == 'Echtes Haus'


def test_das_beispiel_selbst_bleibt_bearbeitbar(app_ctx, auth_client):
    from nebenkostenfix.models import Property
    assert auth_client.post('/api/analytics/beispiel-immobilie').status_code == 201
    haus = Property.query.filter_by(name=demo.NAME).one()
    res = auth_client.put(f'/api/properties/{haus.id}',
                          json={'name': demo.NAME, 'is_standalone': True})
    assert res.status_code == 200, res.get_json()


def test_der_import_legt_kein_haus_mit_dem_beispielnamen_an(app_ctx):
    from nebenkostenfix.tabellenimport import ZeilenFehler, _Aufloeser
    with pytest.raises(ZeilenFehler, match='Beispielhaus'):
        _Aufloeser().haus(demo.NAME, anlegen=True)
