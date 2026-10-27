"""Was nach dem Loeschen von Wohnung oder Immobilie uebrig blieb.

Zaehler und wohnungsbezogene Rechnungen haengen ohne Kaskade an der
Wohnung, die Anschreiben-Vorlage ohne Kaskade an der Immobilie. Beim
Loeschen blieben sie liegen: der Zaehler wurde still zum Unterzaehler ohne
Wohnung, die Rechnung und die Vorlage zeigten auf eine ID, die SQLite der
naechsten neuen Wohnung bzw. Immobilie wieder gibt -- und die erbte sie.
"""

from datetime import date

from billing_factories import apt, category, house


def _zaehler(haus, wohnung=None, nummer='WZ-1'):
    from nebenkostenfix.models import Meter, MeterReading, db
    m = Meter(category_id=category('Wasserversorgung').id, property_id=haus.id,
              apartment_id=wohnung.id if wohnung else None,
              is_main_meter=wohnung is None, meter_number=nummer)
    db.session.add(m)
    db.session.flush()
    db.session.add(MeterReading(meter_id=m.id, reading_date=date(2025, 1, 1), value=100))
    db.session.commit()
    return m


def _rechnung(haus, wohnung):
    from nebenkostenfix.models import CostInvoice, db
    r = CostInvoice(category_id=category('Grundsteuer').id, property_id=haus.id,
                    apartment_id=wohnung.id, start_date=date(2024, 1, 1),
                    end_date=date(2024, 12, 31), amount=300)
    db.session.add(r)
    db.session.commit()
    return r


def test_wohnung_mit_zaehler_wird_nicht_geloescht(auth_client):
    """Zaehler und Lesungen sind Messhistorie (D-82): kein stiller Zweckwechsel."""
    from nebenkostenfix.models import Apartment, Meter, MeterReading, db
    haus = house('Zaehlerhaus')
    eg = apt(haus, 'EG', 50.0)
    zaehler = _zaehler(haus, eg)
    antwort = auth_client.delete(f'/api/apartments/{eg.id}')
    assert antwort.status_code == 409
    assert antwort.get_json()['error'] == (
        'Die Wohnung „EG“ kann nicht gelöscht werden, solange noch Folgendes '
        'zu ihr gehört: 1 Zähler.')
    db.session.expire_all()
    assert db.session.get(Apartment, eg.id) is not None
    assert db.session.get(Meter, zaehler.id).apartment_id == eg.id
    assert MeterReading.query.count() == 1


def test_wohnung_mit_eigener_rechnung_wird_nicht_geloescht(auth_client):
    """Sonst erbt die naechste neue Wohnung die Rechnung ueber die ID."""
    from nebenkostenfix.models import Apartment, CostInvoice, db
    haus = house('Rechnungshaus')
    apt(haus, 'EG', 50.0)
    og = apt(haus, 'OG', 60.0)
    rechnung = _rechnung(haus, og)
    antwort = auth_client.delete(f'/api/apartments/{og.id}')
    assert antwort.status_code == 409
    assert antwort.get_json()['error'].endswith(': 1 Rechnung.')
    db.session.expire_all()
    assert db.session.get(Apartment, og.id) is not None
    assert db.session.get(CostInvoice, rechnung.id).apartment_id == og.id


def test_die_meldung_der_wohnung_zaehlt_alles_auf(auth_client):
    haus = house('Volle Wohnung')
    eg = apt(haus, 'EG', 50.0)
    _rechnung(haus, eg)
    _rechnung(haus, eg)
    _zaehler(haus, eg)
    meldung = auth_client.delete(f'/api/apartments/{eg.id}').get_json()['error']
    assert meldung.endswith(': 2 Rechnungen und 1 Zähler.')


def test_zaehler_und_rechnungen_anderer_haelt_die_wohnung_nicht(auth_client):
    """Hauszaehler, Hausrechnung und alles der Nachbarwohnung bleiben unberuehrt."""
    from nebenkostenfix.models import Apartment, CostInvoice, Meter, db
    haus = house('Nachbarhaus')
    eg = apt(haus, 'EG', 50.0)
    og = apt(haus, 'OG', 60.0)
    _zaehler(haus, None, 'HZ-1')
    _zaehler(haus, eg, 'WZ-EG')
    _rechnung(haus, eg)
    db.session.add(CostInvoice(category_id=category('Grundsteuer').id, property_id=haus.id,
                               start_date=date(2024, 1, 1), end_date=date(2024, 12, 31),
                               amount=500))
    db.session.commit()
    assert auth_client.delete(f'/api/apartments/{og.id}').status_code == 200
    db.session.expire_all()
    assert db.session.get(Apartment, og.id) is None
    assert Meter.query.count() == 2
    assert CostInvoice.query.count() == 2
    assert Meter.query.filter_by(meter_number='WZ-EG').one().apartment_id == eg.id


def test_die_immobilie_nimmt_ihr_anschreiben_mit(auth_client):
    """Die Vorlage ist Text, kein Beleg -- sie geht mit, statt vererbt zu werden."""
    from nebenkostenfix.models import AnschreibenVorlage, db
    andere = house('Anderes Haus')
    alt = house('Altes Haus')  # zuletzt angelegt: SQLite gibt seine ID neu her
    for haus in (alt, andere):
        db.session.add(AnschreibenVorlage(property_id=haus.id, text=f'Brief für {haus.name}'))
    db.session.commit()
    alte_id = alt.id
    assert auth_client.delete(f'/api/properties/{alte_id}').status_code == 200
    assert [v.text for v in AnschreibenVorlage.query.all()] == ['Brief für Anderes Haus']

    neu = auth_client.post('/api/properties', json={'name': 'Neues Haus'}).get_json()['id']
    assert neu == alte_id
    assert auth_client.get(f'/api/properties/{neu}/anschreiben').get_json()['ist_vorgabe']


def test_im_beispielhaus_haelt_der_zaehler_die_wohnung(auth_client):
    """Die Zaehlerpruefung gilt auch im Beispiel; „Beispiel löschen“ nimmt das Haus."""
    from nebenkostenfix import beispielimmobilie
    from nebenkostenfix.models import Apartment
    beispielimmobilie.anlegen()
    eg = Apartment.query.filter_by(name='EG links').one()
    antwort = auth_client.delete(f'/api/apartments/{eg.id}')
    assert antwort.status_code == 409
    assert antwort.get_json()['error'].endswith(': 1 Zähler.')
    beispielimmobilie.entfernen()


def test_die_frist_steht_vor_zaehler_und_rechnung_der_wohnung(auth_client):
    """Review R2-2: erst die Sperre, die niemand beheben kann -- sonst loescht
    der Vermieter Rechnung und Zaehler und scheitert danach doch an der Frist."""
    from billing_factories import tenant
    from nebenkostenfix.models import Payment, db
    haus = house('Fristhaus')
    eg = apt(haus, 'EG', 50.0)
    m = tenant(eg, 'Mira Muster', move_in=date(2024, 1, 1))
    db.session.add(Payment(tenant_id=m.id, amount=100, payment_date=date(2025, 3, 1),
                           type='Nebenkostenvorauszahlung'))
    db.session.commit()
    _zaehler(haus, eg)
    _rechnung(haus, eg)
    meldung = auth_client.delete(f'/api/apartments/{eg.id}').get_json()['error']
    assert '31.12.2035' in meldung
    assert 'Zähler' not in meldung and 'Rechnung' not in meldung
