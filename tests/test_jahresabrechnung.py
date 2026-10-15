"""NK-160: der Stand eines Abrechnungsjahres für den Assistenten.

Am Beispielhaus (NK-159): das Vorjahr ist vollständig erfasst und für Anna
schon festgesetzt. Geprüft wird, was die Schritte 2, 3 und 5 zeigen --
gerechnet wird im Assistenten über die vorhandenen Routen.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from nebenkostenfix import beispielimmobilie as demo


@pytest.fixture
def haus(auth_client):
    antwort = auth_client.post('/api/analytics/beispiel-immobilie')
    assert antwort.status_code == 201
    yield antwort.get_json()['property_id']
    demo.entfernen()


def _stand(client, haus, jahr):
    return client.get(f'/api/jahresabrechnung?property_id={haus}&jahr={jahr}')


def test_kostenarten_mit_vorjahr_und_luecken(auth_client, haus):
    from nebenkostenfix.models import CostCategory, CostInvoice, db
    jahr = date.today().year - 1
    # Im Vorvorjahr gab es eine Hauswart-Rechnung, im Jahr nicht: fehlt.
    hauswart = CostCategory.query.filter_by(name='Hauswart').one()
    db.session.add(CostInvoice(property_id=haus, category_id=hauswart.id, amount=Decimal('300'),
                               start_date=date(jahr - 1, 1, 1), end_date=date(jahr - 1, 12, 31)))
    db.session.commit()
    stand = _stand(auth_client, haus, jahr).get_json()
    arten = {k['name']: k for k in stand['kostenarten']}
    assert arten['Grundsteuer']['zustand'] == 'erfasst' and arten['Grundsteuer']['summe'] == 460.0
    assert arten['Grundsteuer']['summe_vorjahr'] is None
    assert arten['Hauswart']['zustand'] == 'fehlt' and arten['Hauswart']['summe_vorjahr'] == 300.0
    assert arten['Wasserversorgung']['zustand'] == 'offen'  # üblich, aber nie erfasst
    assert 'Aufzug' not in arten


def test_mieter_mit_zeitraum_und_vorhandener_abrechnung(auth_client, haus):
    jahr = date.today().year - 1
    stand = _stand(auth_client, haus, jahr).get_json()
    mieter = {m['name']: m for m in stand['mieter']}
    anna = mieter['Anna Beispiel']
    assert (anna['von'], anna['bis']) == (f'{jahr}-01-01', f'{jahr}-12-31')
    assert anna['abrechnung_id'] and anna['detailliert']
    assert stand['frist_ende'] == f'{jahr + 1}-12-31'


def test_ablesungen_zum_stichtag_und_beim_wechsel(auth_client, haus):
    from nebenkostenfix.models import Apartment, CostCategory, Meter, MeterReading, Tenant, db
    jahr = date.today().year - 1
    ben = Tenant.query.filter_by(name='Ben Beispiel').one()
    ben.move_in_date = date(jahr, 3, 1)          # ein Wechsel im Jahr
    og = Apartment.query.get(ben.apartment_id)
    wasser = CostCategory.query.filter_by(name='Wasserversorgung').one()
    og_zaehler = Meter(property_id=haus, category_id=wasser.id, apartment_id=og.id,
                       meter_number='H-OG-W', is_main_meter=False)
    db.session.add(og_zaehler)
    db.session.commit()

    stand = _stand(auth_client, haus, jahr).get_json()
    zeilen = {z['nummer']: z for z in stand['ablesungen']}
    assert set(zeilen) == {'H-Heiz-1', 'H-EG-1', 'H-WW-1', 'H-W-1', 'H-OG-W'}
    assert zeilen['H-WW-1']['letzte'] is None and not zeilen['H-WW-1']['stichtag_ok']
    assert zeilen['H-OG-W']['wechsel_fehlen'] == [f'{jahr}-03-01']
    assert zeilen['H-EG-1']['wechsel_fehlen'] == []   # andere Wohnung
    assert zeilen['H-OG-W']['wohnung'] == 'OG rechts'

    db.session.add(MeterReading(meter_id=og_zaehler.id, reading_date=date(jahr, 3, 2), value=1.0))
    db.session.add(MeterReading(meter_id=og_zaehler.id, reading_date=date(jahr, 12, 31), value=9.0))
    db.session.commit()
    zeile = {z['nummer']: z for z in _stand(auth_client, haus, jahr).get_json()['ablesungen']}['H-OG-W']
    assert zeile['wechsel_fehlen'] == [] and zeile['stichtag_ok'] is True


def test_ein_zaehlerwechsel_verlangt_keinen_stand_am_alten_oder_vor_dem_neuen(auth_client, haus):
    # NK-258: Der alte Zähler endet mit dem Wechsel, der neue beginnt dort.
    from nebenkostenfix.models import Apartment, CostCategory, Meter, MeterReading, Tenant, db
    jahr = date.today().year - 1
    ben = Tenant.query.filter_by(name='Ben Beispiel').one()
    ben.move_in_date = date(jahr, 3, 1)
    og = Apartment.query.get(ben.apartment_id)
    wasser = CostCategory.query.filter_by(name='Wasserversorgung').one()
    alt = Meter(property_id=haus, category_id=wasser.id, apartment_id=og.id,
                meter_number='H-OG-alt', is_main_meter=False)
    db.session.add(alt)
    db.session.flush()
    neu = Meter(property_id=haus, category_id=wasser.id, apartment_id=og.id,
                meter_number='H-OG-neu', is_main_meter=False, ersetzt_id=alt.id)
    db.session.add(neu)
    db.session.flush()
    for zaehler, tag, wert in ((alt, date(jahr - 1, 12, 31), 10), (alt, date(jahr, 3, 1), 20),
                               (alt, date(jahr, 6, 30), 50), (neu, date(jahr, 6, 30), 0),
                               (neu, date(jahr, 12, 31), 40)):
        db.session.add(MeterReading(meter_id=zaehler.id, reading_date=tag, value=wert))
    db.session.commit()

    zeilen = {z['nummer']: z for z in _stand(auth_client, haus, jahr).get_json()['ablesungen']}
    assert zeilen['H-OG-alt']['stichtag_ok'] and zeilen['H-OG-alt']['wechsel_fehlen'] == []
    assert zeilen['H-OG-neu']['stichtag_ok'] and zeilen['H-OG-neu']['wechsel_fehlen'] == []
    # Im Jahr nach dem Wechsel ist der alte Zähler nicht mehr abzulesen.
    folgejahr = _stand(auth_client, haus, jahr + 1).get_json()['ablesungen']
    assert 'H-OG-alt' not in {z['nummer'] for z in folgejahr}


def test_ungueltige_anfragen(auth_client, haus):
    assert _stand(auth_client, haus, date.today().year + 1).status_code == 400
    assert _stand(auth_client, 99999, 2025).status_code == 400
    assert auth_client.get('/api/jahresabrechnung?jahr=2025').status_code == 400


def test_nur_angemeldet(anon_client):
    assert anon_client.get('/api/jahresabrechnung?property_id=1&jahr=2025').status_code == 401


def test_allgemeinstrom_unter_frueherem_namen_ist_ueblich(auth_client):
    """Review 0.15.0: hat die Migration b4e7c1d92a58 übersprungen (eigene
    Kostenart „Allgemeinstrom“ daneben), heißt Nr. 11 noch wie früher -- der
    Assistent fragt trotzdem nach ihr, nicht nur nach dem neuen Namen."""
    from nebenkostenfix.models import CostCategory, Property, db
    CostCategory.query.filter_by(betrkv_nr=11, name='Allgemeinstrom').one().name = \
        'Beleuchtung (Allgemeinstrom)'
    haus = Property(name='Leeres Haus')
    db.session.add(haus)
    db.session.commit()
    stand = _stand(auth_client, haus.id, date.today().year - 1).get_json()
    arten = {k['name']: k for k in stand['kostenarten']}
    assert arten['Beleuchtung (Allgemeinstrom)']['zustand'] == 'offen'
