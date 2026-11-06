"""Zahlungen: eine Zahlung für einen Mieter, den es nicht gibt.

POST /api/payments prüfte tenant_id nur auf eine ganze Zahl. SQLite setzt den
Fremdschlüssel nicht durch, also wurde die Zahlung mit 201 gespeichert. Sie
stand in keiner Liste (die Liste verbindet mit tenants) und hängte sich an den
nächsten Mieter, der diese Nummer bekommt. Erwartet: 400 am Feld tenant_id,
nichts gespeichert, weder als Einzelbuchung noch als Serie. Alle Werte sind
erfunden.
"""

from __future__ import annotations

from datetime import date

from nebenkostenfix.models import Payment, VorauszahlungSoll, db
from tests import billing_factories as f


def _mieter_eins():
    haus = f.house('Musterhaus')
    mieter = f.tenant(f.apt(haus, 'W1', 50), 'Mieter Eins', date(2024, 1, 1))
    db.session.commit()
    return mieter


def _buchen(client, tenant_id, **extra):
    daten = {'tenant_id': str(tenant_id), 'amount': '120.00',
             'payment_date': '2024-03-01', 'type': 'Nebenkostenvorauszahlung'}
    daten.update(extra)
    return client.post('/api/payments', data=daten)


def test_zahlung_fuer_unbekannten_mieter_wird_abgewiesen(auth_client, app_ctx):
    haus = f.house('Testhaus Nacht')
    mieter = f.tenant(f.apt(haus, 'OG rechts', 48), 'Mieterin Test', date(2024, 1, 1))
    db.session.commit()
    unbekannt = mieter.id + 1

    antwort = auth_client.post('/api/payments', data={
        'tenant_id': str(unbekannt), 'amount': '120', 'payment_date': '2024-03-01',
        'type': 'Nebenkostenvorauszahlung'})

    assert antwort.status_code in (400, 404), antwort.get_json()
    assert Payment.query.filter_by(tenant_id=unbekannt).count() == 0


def test_verwaiste_zahlung_landet_beim_naechsten_mieter(auth_client, app_ctx):
    """Die Folge: der nächste angelegte Mieter erbt die Zahlung als Vorauszahlung."""
    haus = f.house('Testhaus Nacht')
    wohnung = f.apt(haus, 'EG links', 55)
    erster = f.tenant(wohnung, 'Mieter Eins', date(2024, 1, 1), date(2024, 6, 30))
    db.session.commit()
    auth_client.post('/api/payments', data={
        'tenant_id': str(erster.id + 1), 'amount': '150', 'payment_date': '2024-08-01',
        'type': 'Nebenkostenvorauszahlung'})

    neuer = f.tenant(wohnung, 'Mieter Zwei', date(2024, 7, 1))
    db.session.commit()

    assert Payment.query.filter_by(tenant_id=neuer.id).count() == 0


def test_einzelbuchung_unbekannter_mieter_fehler_am_feld(auth_client, app_ctx):
    mieter = _mieter_eins()
    unbekannt = mieter.id + 1

    antwort = _buchen(auth_client, unbekannt)

    assert antwort.status_code == 400, antwort.get_json()
    rumpf = antwort.get_json()
    assert rumpf['feld'] == 'tenant_id'
    assert rumpf['error'] == 'Diesen Mieter gibt es nicht.'
    assert Payment.query.count() == 0


def test_serie_unbekannter_mieter_legt_nichts_an(auth_client, app_ctx):
    mieter = _mieter_eins()
    unbekannt = mieter.id + 1

    antwort = _buchen(auth_client, unbekannt, is_recurring='true',
                      end_date='2024-12-31')

    assert antwort.status_code == 400, antwort.get_json()
    assert antwort.get_json()['feld'] == 'tenant_id'
    assert Payment.query.count() == 0
    assert VorauszahlungSoll.query.count() == 0


def test_unbekannter_mieter_wird_vor_der_abrechnung_geprueft(auth_client, app_ctx):
    """Mit Abrechnungsnummer nennt der Fehler den Mieter, nicht die Abrechnung."""
    mieter = _mieter_eins()

    antwort = _buchen(auth_client, mieter.id + 1, type='Nebenkostenzahlung',
                      billing_report_id='1')

    assert antwort.status_code == 400, antwort.get_json()
    assert antwort.get_json()['feld'] == 'tenant_id'
    assert Payment.query.count() == 0


def test_nach_abgewiesener_serie_erbt_neuer_mieter_nichts(auth_client, app_ctx):
    mieter = _mieter_eins()
    unbekannt = mieter.id + 1
    _buchen(auth_client, unbekannt)
    _buchen(auth_client, unbekannt, is_recurring='true', end_date='2024-12-31')

    zwei = f.tenant(mieter.apartment, 'Mieter Zwei', date(2024, 7, 1))
    db.session.commit()

    assert zwei.id == unbekannt  # SQLite vergibt die freie Nummer neu
    assert Payment.query.filter_by(tenant_id=zwei.id).count() == 0
    assert VorauszahlungSoll.query.filter_by(tenant_id=zwei.id).count() == 0


def test_gegenprobe_einzelbuchung_existierender_mieter(auth_client, app_ctx):
    """Neben dem abgewiesenen Versuch bucht Mieter Eins wie bisher genau eine Zahlung."""
    mieter = _mieter_eins()
    assert _buchen(auth_client, mieter.id + 1).status_code == 400

    einzeln = _buchen(auth_client, mieter.id)

    assert einzeln.status_code == 201, einzeln.get_json()
    zahlungen = Payment.query.all()
    assert [(z.tenant_id, z.payment_date, f'{z.amount:.2f}') for z in zahlungen] == [
        (mieter.id, date(2024, 3, 1), '120.00')]
    assert VorauszahlungSoll.query.count() == 0


def test_gegenprobe_serie_existierender_mieter(auth_client, app_ctx):
    """Die Serie für Mieter Eins: 10 Zahlungen März bis Dezember, Soll ab März."""
    mieter = _mieter_eins()
    assert _buchen(auth_client, mieter.id + 1, is_recurring='true',
                   end_date='2024-12-31').status_code == 400

    serie = _buchen(auth_client, mieter.id, is_recurring='true',
                    end_date='2024-12-31')

    assert serie.status_code == 201, serie.get_json()
    assert serie.get_json()['message'] == '10 Zahlungen erfolgreich erfasst'
    zahlungen = Payment.query.order_by(Payment.payment_date).all()
    assert {z.tenant_id for z in zahlungen} == {mieter.id}
    assert [z.payment_date for z in zahlungen] == [
        date(2024, monat, 1) for monat in range(3, 13)]
    soll = VorauszahlungSoll.query.all()
    assert [(s.tenant_id, s.gueltig_ab, f'{s.betrag:.2f}') for s in soll] == [
        (mieter.id, date(2024, 3, 1), '120.00')]


def test_gegenprobe_serie_vor_einzug_ohne_soll(auth_client, app_ctx):
    """Wie bisher: eine Serie, die vor dem Einzug beginnt, setzt kein Soll."""
    mieter = _mieter_eins()
    assert _buchen(auth_client, mieter.id + 1, payment_date='2023-11-01',
                   is_recurring='true', end_date='2024-02-29').status_code == 400

    antwort = _buchen(auth_client, mieter.id, payment_date='2023-11-01',
                      is_recurring='true', end_date='2024-02-29')

    assert antwort.status_code == 201, antwort.get_json()
    assert Payment.query.count() == 4
    assert Payment.query.filter_by(tenant_id=mieter.id).count() == 4
    assert VorauszahlungSoll.query.count() == 0
