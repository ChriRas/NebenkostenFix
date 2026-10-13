"""NK-261 (R-VZ-02): Soll und Ist der Vorauszahlungen je Monat.

Vorher sah der Vermieter nur die Liste der erfassten Zahlungen. Ob ein Mieter
im Rückstand ist, musste er Monat für Monat selbst gegen den vereinbarten
Betrag halten -- und eine Serienbuchung legte die Zahlungen im Voraus an,
der vereinbarte Betrag stand danach nirgends mehr. Alle Werte sind erfunden.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date

import pytest

from nebenkostenfix import vorauszahlung as vz
from nebenkostenfix.models import Payment, Tenant, VorauszahlungSoll, db
from tests import billing_factories as f

D = date


def _monate(ergebnis):
    return {m['monat']: m for m in ergebnis['monate']}


# --- Kern ----------------------------------------------------------------------

def test_teilzahlung_ist_ein_rueckstand():
    e = vz.soll_ist([(D(2024, 1, 1), 100)], [(D(2024, 1, 3), 100), (D(2024, 2, 3), 60)],
                    D(2024, 1, 1), None, D(2024, 3, 15))
    m = _monate(e)
    assert (m['2024-01']['rueckstand'], m['2024-02']['rueckstand']) == (False, True)
    assert m['2024-02']['differenz'] == '-40.00'
    # Der laufende Monat steht da, ist aber noch nicht fällig.
    assert m['2024-03']['laufend'] is True and m['2024-03']['rueckstand'] is False
    assert (e['offen'], e['ueberzahlt'], e['saldo']) == ('40.00', '0.00', '40.00')


def test_zwei_teilzahlungen_ergeben_den_monat():
    e = vz.soll_ist([(D(2024, 1, 1), 100)], [(D(2024, 1, 3), 60), (D(2024, 1, 20), 40)],
                    D(2024, 1, 1), D(2024, 1, 31), D(2024, 6, 1))
    assert _monate(e)['2024-01']['rueckstand'] is False and e['saldo'] == '0.00'


def test_ueberzahlung_wird_gegengerechnet():
    e = vz.soll_ist([(D(2024, 1, 1), 100)], [(D(2024, 1, 3), 50), (D(2024, 2, 3), 150)],
                    D(2024, 1, 1), D(2024, 2, 29), D(2024, 6, 1))
    assert _monate(e)['2024-01']['rueckstand'] is True
    assert (e['offen'], e['ueberzahlt'], e['saldo']) == ('50.00', '50.00', '0.00')
    assert vz.erinnerung(e, 'Guten Tag A,', 'EG', 'das Konto', None) is None


def test_einzug_im_monat_rechnet_anteilig():
    """16 von 31 Tagen: 124 € × 16/31 = 64 €."""
    e = vz.soll_ist([(D(2024, 1, 16), 124)], [(D(2024, 1, 20), 64)],
                    D(2024, 1, 16), None, D(2024, 2, 10))
    jan = _monate(e)['2024-01']
    assert (jan['soll'], jan['rueckstand']) == ('64.00', False)


def test_auszug_im_monat_rechnet_anteilig_und_endet_dort():
    """15 von 29 Tagen (Schaltjahr): 116 € × 15/29 = 60 €; danach kein Monat mehr."""
    e = vz.soll_ist([(D(2024, 1, 1), 116)], [(D(2024, 1, 3), 116), (D(2024, 2, 3), 50)],
                    D(2024, 1, 1), D(2024, 2, 15), D(2024, 9, 1))
    assert [m['monat'] for m in e['monate']] == ['2024-01', '2024-02']
    feb = _monate(e)['2024-02']
    assert (feb['soll'], feb['differenz'], feb['laufend']) == ('60.00', '-10.00', False)


def test_eine_anpassung_zur_monatsmitte_gilt_ab_ihrem_tag():
    """April hat 30 Tage: 14 × 90 € und 16 × 120 € → (1260 + 1920) / 30 = 106 €."""
    e = vz.soll_ist([(D(2024, 4, 15), 120), (D(2024, 1, 1), 90)], [],
                    D(2024, 1, 1), D(2024, 5, 31), D(2024, 9, 1))
    m = _monate(e)
    assert (m['2024-03']['soll'], m['2024-04']['soll'], m['2024-05']['soll']) == \
        ('90.00', '106.00', '120.00')


def test_ohne_soll_gibt_es_keinen_rueckstand():
    e = vz.soll_ist([(D(2024, 3, 1), 100)], [(D(2024, 1, 3), 80)],
                    D(2024, 1, 1), D(2024, 3, 31), D(2024, 9, 1))
    jan = _monate(e)['2024-01']
    assert (jan['soll'], jan['ist'], jan['rueckstand']) == (None, '80.00', False)
    assert e['offen'] == '100.00'  # nur der März


def test_vor_dem_einzug_gibt_es_keine_monate():
    assert vz.soll_ist([], [], D(2025, 1, 1), None, D(2024, 12, 1))['monate'] == []


def test_die_erinnerung_nennt_monate_summe_und_konto():
    e = vz.soll_ist([(D(2024, 1, 1), 100)],
                    [(D(2024, 1, 3), 60), (D(2024, 2, 3), 110), (D(2024, 3, 3), 70)],
                    D(2024, 1, 1), D(2024, 3, 31), D(2024, 9, 1))
    text = vz.erinnerung(e, 'Sehr geehrte Frau Muster,', 'EG links', 'mein bekanntes Konto',
                         'Vermieter V')
    assert text.startswith('Sehr geehrte Frau Muster,\n\nfür die Wohnung EG links ')
    assert '  01/2024: fällig 100,00 €, gezahlt 60,00 €, offen 40,00 €' in text
    assert '  03/2024: fällig 100,00 €, gezahlt 70,00 €, offen 30,00 €' in text
    assert '02/2024' not in text.split('abzüglich')[0]
    assert 'abzüglich Überzahlungen anderer Monate: 10,00 €' in text
    assert 'Offen sind insgesamt 60,00 €.' in text
    assert 'auf mein bekanntes Konto.' in text
    assert text.endswith('Mit freundlichen Grüßen\nVermieter V')


# --- Über die API --------------------------------------------------------------

@pytest.fixture
def mieter(app_ctx):
    haus = f.house()
    return f.tenant(f.apt(haus, 'EG', 50), 'Mieter A', D(2024, 1, 1), D(2024, 3, 31))


def _zahlung(m, tag, betrag, art='Nebenkostenvorauszahlung'):
    db.session.add(Payment(tenant_id=m.id, amount=betrag, payment_date=tag, type=art))
    db.session.commit()


def test_das_soll_anlegen_berichtigen_und_loeschen(auth_client, mieter):
    url = f'/api/tenants/{mieter.id}/vorauszahlung_soll'
    assert auth_client.post(url, data={'gueltig_ab': '2024-01-01', 'betrag': '90'}).status_code == 201
    berichtigt = auth_client.post(url, data={'gueltig_ab': '2024-01-01', 'betrag': '100'})
    assert berichtigt.status_code == 200
    assert [(s.gueltig_ab, str(s.betrag)) for s in mieter.vorauszahlung_soll] == \
        [(D(2024, 1, 1), '100.00')]
    vorher = auth_client.post(url, data={'gueltig_ab': '2023-12-31', 'betrag': '90'})
    assert vorher.status_code == 400 and vorher.get_json()['feld'] == 'gueltig_ab'
    negativ = auth_client.post(url, data={'gueltig_ab': '2024-02-01', 'betrag': '-1'})
    assert negativ.status_code == 400 and negativ.get_json()['feld'] == 'betrag'
    id_ = mieter.vorauszahlung_soll[0].id
    assert auth_client.delete(f'/api/vorauszahlung_soll/{id_}').status_code == 200
    assert VorauszahlungSoll.query.count() == 0
    assert auth_client.post('/api/tenants/99999/vorauszahlung_soll',
                            data={'gueltig_ab': '2024-01-01', 'betrag': '1'}).status_code == 404


def test_ein_soll_nach_dem_auszug_wird_abgelehnt(auth_client, mieter):
    # NK-269: Nach dem Auszug am 31.03. ist kein Monat mehr zu zahlen.
    url = f'/api/tenants/{mieter.id}/vorauszahlung_soll'
    danach = auth_client.post(url, data={'gueltig_ab': '2024-04-01', 'betrag': '90'})
    assert danach.status_code == 400 and danach.get_json()['feld'] == 'gueltig_ab'
    assert auth_client.post(url, data={'gueltig_ab': '2024-03-31', 'betrag': '90'}).status_code == 201
    assert [s.gueltig_ab for s in mieter.vorauszahlung_soll] == [D(2024, 3, 31)]

def test_die_ansicht_zeigt_soll_ist_und_die_erinnerung(auth_client, mieter):
    auth_client.post(f'/api/tenants/{mieter.id}/vorauszahlung_soll',
                     data={'gueltig_ab': '2024-01-01', 'betrag': '100'})
    _zahlung(mieter, D(2024, 1, 3), 100)
    _zahlung(mieter, D(2024, 2, 3), 60)
    _zahlung(mieter, D(2024, 3, 3), 100)
    _zahlung(mieter, D(2024, 2, 3), 999, art='Miete')  # zählt nicht
    d = auth_client.get(f'/api/tenants/{mieter.id}/vorauszahlungen').get_json()
    assert [s['betrag'] for s in d['soll']] == ['100.00']
    assert [(m['monat'], m['rueckstand']) for m in d['monate']] == \
        [('2024-01', False), ('2024-02', True), ('2024-03', False)]
    assert d['saldo'] == '40.00'
    assert 'Guten Tag Mieter A,' in d['erinnerung']
    assert '02/2024: fällig 100,00 €, gezahlt 60,00 €, offen 40,00 €' in d['erinnerung']
    assert auth_client.get('/api/tenants/99999/vorauszahlungen').status_code == 404


def test_die_serienbuchung_hinterlegt_das_soll(auth_client, mieter):
    """Die Serie legt Zahlungen im Voraus an; der vereinbarte Betrag bleibt jetzt stehen."""
    daten = {'tenant_id': mieter.id, 'amount': '95', 'payment_date': '2024-02-01',
             'end_date': '2024-03-01', 'is_recurring': 'true'}
    assert auth_client.post('/api/payments', data={**daten, 'type': 'Miete'}).status_code == 201
    assert VorauszahlungSoll.query.count() == 0
    assert auth_client.post('/api/payments', data={
        **daten, 'type': 'Nebenkostenvorauszahlung'}).status_code == 201
    assert [(s.gueltig_ab, str(s.betrag)) for s in mieter.vorauszahlung_soll] == \
        [(D(2024, 2, 1), '95.00')]
    # Eine zweite Serie ab demselben Tag berichtigt, statt doppelt zu hinterlegen.
    auth_client.post('/api/payments', data={**daten, 'amount': '97',
                                            'type': 'Nebenkostenvorauszahlung'})
    assert [str(s.betrag) for s in mieter.vorauszahlung_soll] == ['97.00']


def test_die_auskunft_enthaelt_das_soll(auth_client, mieter):
    auth_client.post(f'/api/tenants/{mieter.id}/vorauszahlung_soll',
                     data={'gueltig_ab': '2024-01-01', 'betrag': '100'})
    antwort = auth_client.get(f'/api/tenants/{mieter.id}/export')
    with zipfile.ZipFile(io.BytesIO(antwort.data)) as archiv:
        auskunft = json.loads(archiv.read('mieter-auskunft.json'))
    assert [s['betrag'] for s in auskunft['vorauszahlung_soll']] == ['100.00']


def test_das_soll_geht_mit_dem_mieter(auth_client, mieter):
    """Ohne Zahlung und Abrechnung wird der Mieter ganz gelöscht -- das Soll mit."""
    auth_client.post(f'/api/tenants/{mieter.id}/vorauszahlung_soll',
                     data={'gueltig_ab': '2024-01-01', 'betrag': '100'})
    assert auth_client.delete(f'/api/tenants/{mieter.id}').status_code == 200
    assert Tenant.query.count() == 0 and VorauszahlungSoll.query.count() == 0
