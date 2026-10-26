"""NK-153: Loeschung gegen Aufbewahrungsfristen (E-11 → D-89).

Festgesetzte Abrechnungen und Zahlungen sind Buchungsbelege des Vermieters
(§ 147 AO, § 257 HGB). Die DSGVO-Loeschung sperrt sie bis Fristende statt sie
zu vernichten, blendet das Mietverhaeltnis ueberall aus und loescht es nach
Ablauf beim Start.
"""

from datetime import date
from pathlib import Path

import pytest

from nebenkostenfix import mieter_daten

PDF = b'%PDF-1.4\n%%EOF\n'


def _datei(relativ):
    from app import nas_handler
    voll = Path(nas_handler.nas_mount_path) / relativ
    voll.parent.mkdir(parents=True, exist_ok=True)
    voll.write_bytes(PDF)
    return relativ


@pytest.fixture
def mieter(app_ctx):
    from billing_factories import apt, category, house, profile, tenant
    from nebenkostenfix.models import Haushaltsgroesse, Payment, TenantBillingReport, db
    haus = house('Aufbewahrungshaus')
    wohnung = apt(haus, 'EG', 50.0)
    m = tenant(wohnung, 'Anna Mieterin', move_in=date(2022, 1, 1))
    m.move_out_date = date(2024, 12, 31)
    m.contract_path = _datei('2022/' + 'a' * 32 + '.pdf')
    profile(m, category('Grundsteuer'), 'qm')
    db.session.add(Haushaltsgroesse(tenant_id=m.id, gueltig_ab=date(2022, 1, 1),
                                    personenanzahl=2))
    db.session.add(Payment(tenant_id=m.id, amount=100, payment_date=date(2024, 3, 1),
                           type='Nebenkostenvorauszahlung'))
    db.session.add(TenantBillingReport(
        tenant_id=m.id, start_date=date(2024, 1, 1), end_date=date(2024, 12, 31),
        created_at=date(2025, 5, 1), frist_ende=date(2025, 12, 31),
        document_path=_datei('2025/' + 'b' * 32 + '.pdf')))
    db.session.commit()
    return m


def test_frist_zehn_jahre_nach_dem_letzten_jahr(mieter):
    # letzte Abrechnung 2025 -> Frist bis 31.12.2035
    assert mieter_daten.aufbewahrung_bis(mieter) == date(2035, 12, 31)


def test_ohne_abrechnung_und_zahlung_keine_frist(app_ctx):
    from billing_factories import apt, house, tenant
    m = tenant(apt(house('Leer'), 'EG', 40.0), 'Neu')
    assert mieter_daten.aufbewahrung_bis(m) is None


def test_loeschung_sperrt_statt_zu_loeschen(mieter, auth_client):
    from app import nas_handler
    from nebenkostenfix.models import (Haushaltsgroesse, Payment, Tenant, TenantBillingReport,
                        TenantCostProfile, db)
    vertrag = mieter.contract_path
    antwort = auth_client.delete(f'/api/tenants/{mieter.id}')
    assert antwort.status_code == 200
    bericht = antwort.get_json()
    assert bericht['gesperrt_bis'] == '2035-12-31'
    assert '31.12.2035' in bericht['message']
    assert '§ 147 AO' in bericht['message']
    # sofort weg: Mietvertrag (Datei und Verweis), Kostenprofile
    assert vertrag in bericht['geloeschte_dateien']
    assert not (Path(nas_handler.nas_mount_path) / vertrag).exists()
    zeile = db.session.get(Tenant, mieter.id)
    assert zeile is not None and zeile.contract_path is None
    assert TenantCostProfile.query.count() == 0
    # bleibt: Abrechnung samt PDF, Zahlungen, Haushaltsgroessen
    assert TenantBillingReport.query.count() == 1
    assert (Path(nas_handler.nas_mount_path) /
            TenantBillingReport.query.one().document_path).exists()
    assert Payment.query.count() == 1
    assert Haushaltsgroesse.query.count() == 1


def test_die_zustellanschrift_geht_mit_der_sperre(mieter, auth_client):
    """Review 0.17.0: die neue Adresse nach dem Auszug ist kein Aufbewahrungsgut."""
    from nebenkostenfix.models import Tenant, db
    mieter.zustellanschrift = 'Neue Strasse 1\n12345 Neustadt'
    db.session.commit()
    assert auth_client.delete(f'/api/tenants/{mieter.id}').status_code == 200
    zeile = db.session.get(Tenant, mieter.id)
    assert zeile.gesperrt_bis is not None
    assert zeile.zustellanschrift is None


def test_gesperrte_sind_ueberall_ausgeblendet(mieter, auth_client):
    auth_client.delete(f'/api/tenants/{mieter.id}')
    assert auth_client.get('/api/tenants').get_json() == []
    assert auth_client.get('/api/billing/reports').get_json() == []
    assert auth_client.get('/api/payments').get_json() == []
    vorschlaege = auth_client.get('/api/billing/suggestions').get_json()
    assert all(v.get('tenant_id') != mieter.id for v in vorschlaege)
    gesperrt = auth_client.get('/api/tenants?gesperrte=1').get_json()
    assert [t['id'] for t in gesperrt] == [mieter.id]
    assert gesperrt[0]['gesperrt_bis'] == '2035-12-31'


def test_auskunft_bleibt_moeglich(mieter, auth_client):
    auth_client.delete(f'/api/tenants/{mieter.id}')
    antwort = auth_client.get(f'/api/tenants/{mieter.id}/export')
    assert antwort.status_code == 200


def test_nach_fristablauf_loescht_der_start_alles(mieter, auth_client):
    from app import nas_handler
    from nebenkostenfix.models import Payment, Tenant, TenantBillingReport, db
    auth_client.delete(f'/api/tenants/{mieter.id}')
    pdf = TenantBillingReport.query.one().document_path
    assert mieter_daten.abgelaufene_loeschen(date(2035, 12, 31)) == 0
    assert mieter_daten.abgelaufene_loeschen(date(2036, 1, 1)) == 1
    assert db.session.get(Tenant, mieter.id) is None
    assert TenantBillingReport.query.count() == 0
    assert Payment.query.count() == 0
    assert not (Path(nas_handler.nas_mount_path) / pdf).exists()


def test_die_oberflaeche_nennt_frist_und_pruefung():
    root = Path(__file__).resolve().parents[1]
    js = (root / 'static' / 'app.js').read_text(encoding='utf-8')
    html = (root / 'static' / 'index.html').read_text(encoding='utf-8')
    assert '§ 147 AO' in js and 'fachlich prüfen' in js
    assert 'id="gesperrte-mieter"' in html
    assert '/api/tenants?gesperrte=1' in js


# --- Wohnung und Immobilie loeschen: dieselbe Frist wie beim Mieter -----------
#
# Bis hierher galt die Sperre nur fuer DELETE /api/tenants. Wer die Wohnung
# oder das Haus loeschte, nahm Mieter, Abrechnungen und Zahlungen ueber die
# Kaskade mit -- auch die schon gesperrten, die nirgends mehr zu sehen sind.


def _bestand():
    from nebenkostenfix.models import Payment, Tenant, TenantBillingReport
    return {'mieter': Tenant.query.count(),
            'abrechnungen': TenantBillingReport.query.count(),
            'zahlungen': Payment.query.count()}


def test_wohnung_mit_frist_wird_nicht_geloescht(mieter, auth_client):
    from app import nas_handler
    from nebenkostenfix.models import Apartment, TenantBillingReport, db
    vorher = _bestand()
    antwort = auth_client.delete(f'/api/apartments/{mieter.apartment_id}')
    assert antwort.status_code == 409
    meldung = antwort.get_json()['error']
    assert '„EG“' in meldung and '31.12.2035' in meldung and '§ 147 AO' in meldung
    # Der Mieter ist sichtbar -- kein Verweis auf die gesperrten noetig.
    assert 'Datenschutz' not in meldung
    db.session.expire_all()
    assert db.session.get(Apartment, mieter.apartment_id) is not None
    assert _bestand() == vorher
    assert (Path(nas_handler.nas_mount_path) /
            TenantBillingReport.query.one().document_path).exists()


def test_immobilie_mit_frist_wird_nicht_geloescht(mieter, auth_client):
    from nebenkostenfix.models import Property, db
    haus_id = mieter.apartment.property_id
    vorher = _bestand()
    antwort = auth_client.delete(f'/api/properties/{haus_id}')
    assert antwort.status_code == 409
    meldung = antwort.get_json()['error']
    assert '„Aufbewahrungshaus“' in meldung and '31.12.2035' in meldung
    db.session.expire_all()
    assert db.session.get(Property, haus_id) is not None
    assert _bestand() == vorher


def test_auch_gesperrte_mieter_halten_wohnung_und_haus(mieter, auth_client):
    """Der gesperrte Mieter ist unsichtbar -- seine Frist laeuft trotzdem."""
    wohnung_id, haus_id = mieter.apartment_id, mieter.apartment.property_id
    assert auth_client.delete(f'/api/tenants/{mieter.id}').get_json()['gesperrt_bis']
    assert auth_client.get('/api/tenants').get_json() == []
    vorher = _bestand()
    for url in (f'/api/apartments/{wohnung_id}', f'/api/properties/{haus_id}'):
        antwort = auth_client.delete(url)
        assert antwort.status_code == 409
        # Review R1-5: die Wohnung zeigt keinen Mieter -- die Meldung sagt, wo er steht.
        assert 'Einstellungen → Datenschutz' in antwort.get_json()['error']
    assert _bestand() == vorher


def _ohne_frist(haus, alt=False):
    """Ein Mieter mit Vertrag, aber ohne laufende Frist: gar keine Belege,
    oder nur abgelaufene. Er wohnt in der Wohnung „OG“ von ``haus``."""
    from billing_factories import apt, tenant
    from nebenkostenfix.models import Payment, TenantBillingReport, db
    m = tenant(apt(haus, 'OG', 60.0), 'Bert Mieter', move_in=date(2005, 1, 1))
    m.contract_path = _datei('2005/' + 'c' * 32 + '.pdf')
    if alt:
        # letzter Beleg 2010 -> Frist endete am 31.12.2020
        db.session.add(Payment(tenant_id=m.id, amount=80, payment_date=date(2010, 3, 1),
                               type='Nebenkostenvorauszahlung'))
        db.session.add(TenantBillingReport(
            tenant_id=m.id, start_date=date(2009, 1, 1), end_date=date(2009, 12, 31),
            created_at=date(2010, 5, 1), frist_ende=date(2010, 12, 31),
            document_path=_datei('2010/' + 'd' * 32 + '.pdf')))
    db.session.commit()
    return m


@pytest.mark.parametrize('was', ['wohnung', 'immobilie'])
def test_ohne_frist_geht_alles_samt_dateien(app_ctx, auth_client, was):
    """Ohne Frist wie bisher geloescht -- aber ueber die Mieterloeschung,
    damit Mietvertrag und Abrechnungs-PDF nicht als Waisen liegen bleiben."""
    from app import nas_handler
    from nebenkostenfix.models import Apartment, Property, db
    from billing_factories import house
    m = _ohne_frist(house('Fristloses Haus'), alt=True)
    wohnung_id, haus_id = m.apartment_id, m.apartment.property_id
    dateien = [m.contract_path, m.billing_reports[0].document_path]
    url = (f'/api/apartments/{wohnung_id}' if was == 'wohnung'
           else f'/api/properties/{haus_id}')
    assert auth_client.delete(url).status_code == 200
    db.session.expire_all()
    assert db.session.get(Apartment, wohnung_id) is None
    assert (db.session.get(Property, haus_id) is None) == (was == 'immobilie')
    assert _bestand() == {'mieter': 0, 'abrechnungen': 0, 'zahlungen': 0}
    for pfad in dateien:
        assert not (Path(nas_handler.nas_mount_path) / pfad).exists()


def test_wohnung_im_beispielhaus_bleibt_loeschbar(app_ctx, auth_client):
    """NK-159: Anna und Ben sind erfunden -- keine Sperre fuer das Beispiel."""
    from nebenkostenfix import beispielimmobilie
    from app import nas_handler
    from nebenkostenfix.models import Apartment, Tenant, db
    # Ueber die Route, denn nur sie setzt die Beispielabrechnung samt PDF fest.
    assert auth_client.post('/api/analytics/beispiel-immobilie').status_code == 201
    wohnung = Apartment.query.filter_by(name='EG links').one()
    anna = wohnung.tenants[0]
    assert mieter_daten.aufbewahrung_bis(anna) is not None
    pdfs = [pfad for bericht in anna.billing_reports
            for pfad in (bericht.document_path, bericht.document_path_detailed) if pfad]
    assert pdfs
    assert auth_client.delete(f'/api/apartments/{wohnung.id}').status_code == 200
    db.session.expire_all()
    assert Tenant.query.filter_by(name=beispielimmobilie.MIETER[0]).count() == 0
    assert Tenant.query.filter_by(name=beispielimmobilie.MIETER[1]).count() == 1
    for pfad in pdfs:
        assert not (Path(nas_handler.nas_mount_path) / pfad).exists()
    beispielimmobilie.entfernen()


def test_die_frist_laeuft_bis_einschliesslich_ihres_letzten_tages(mieter):
    """Dieselbe Grenze wie ``loeschen()`` und ``abgelaufene_loeschen()``."""
    assert mieter_daten.laufende_frist([mieter], heute=date(2035, 12, 31)) == date(2035, 12, 31)
    assert mieter_daten.laufende_frist([mieter], heute=date(2036, 1, 1)) is None
    assert mieter_daten.laufende_frist([], heute=date(2035, 1, 1)) is None


def test_eine_frist_haelt_das_haus_aber_nicht_die_nachbarwohnung(mieter, auth_client):
    """Erst wird alles geprueft, dann geloescht: der 409 laesst auch den
    fristlosen Nachbarn samt Vertrag stehen. Dessen Wohnung allein geht."""
    from app import nas_handler
    from nebenkostenfix.models import Apartment, db
    nachbar = _ohne_frist(mieter.apartment.property)
    vertraege = [mieter.contract_path, nachbar.contract_path]
    vorher = _bestand()
    assert auth_client.delete(f'/api/properties/{nachbar.apartment.property_id}').status_code == 409
    assert _bestand() == vorher
    for pfad in vertraege:
        assert (Path(nas_handler.nas_mount_path) / pfad).exists()
    assert auth_client.delete(f'/api/apartments/{nachbar.apartment_id}').status_code == 200
    db.session.expire_all()
    assert db.session.get(Apartment, mieter.apartment_id) is not None
    assert not (Path(nas_handler.nas_mount_path) / vertraege[1]).exists()

