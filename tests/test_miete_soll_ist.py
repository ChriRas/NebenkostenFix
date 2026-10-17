"""Phase 53 (Issue #31): Erwartete gegen tatsächliche Kaltmiete.

Der Vermieter hat die Kaltmiete-Soll-Stufen (Phase 49) und die gebuchten
Mietzahlungen. Diese Tests zählen je Monat Soll gegen Ist -- getrennt von
den Nebenkostenvorauszahlungen, damit sich beide nicht mischen -- und
halten die parametrisierte Erinnerung fest. Alle Werte sind erfunden.
"""

from __future__ import annotations

from datetime import date

import pytest

from nebenkostenfix import vorauszahlung as vz
from nebenkostenfix.models import Payment, db
from tests import billing_factories as f
from tests.test_migrations import WURZEL

D = date


def _monate(ergebnis):
    return {m['monat']: m for m in ergebnis['monate']}


# --- Kern: Tagesgenauigkeit und parametrisierte Erinnerung ---------------------

def test_monatsmitte_einzug_und_erhöhung_zählen_tagesgenau():
    e = vz.soll_ist(
        [(D(2025, 3, 15), 700), (D(2025, 8, 1), 750)],
        [(D(2025, 3, 20), '383.87'), (D(2025, 4, 3), 700), (D(2025, 5, 3), 700),
         (D(2025, 6, 3), 700), (D(2025, 7, 3), 700), (D(2025, 8, 3), 750),
         (D(2025, 9, 3), 750)],
        D(2025, 3, 15), None, D(2025, 10, 15))
    m = _monate(e)
    # Einzug am 15.: 17 von 31 Tagen im März.
    assert m['2025-03']['soll'] == '383.87'
    assert [m[f'2025-0{n}']['soll'] for n in (4, 5, 6, 7)] == ['700.00'] * 4
    # Die Erhöhung gilt ab dem 01.08. voll.
    assert (m['2025-08']['soll'], m['2025-09']['soll']) == ('750.00', '750.00')
    assert e['saldo'] == '0.00'
    assert m['2025-10']['laufend'] is True and m['2025-10']['rueckstand'] is False


def test_eine_erhöhung_zur_monatsmitte_wird_anteilig_gerechnet():
    e = vz.soll_ist([(D(2025, 1, 1), 700), (D(2025, 6, 15), 800)], [],
                    D(2025, 1, 1), None, D(2025, 7, 1))
    m = _monate(e)
    # 14 Tage à 700 und 16 Tage à 800, durch 30 Tage im Juni.
    assert m['2025-06']['soll'] == '753.33'
    assert m['2025-06']['rueckstand'] is True
    assert e['offen'] == '4253.33'


def test_die_erinnerung_wird_parametrisiert():
    e = vz.soll_ist([(D(2024, 1, 1), 100)], [(D(2024, 2, 3), 60)],
                    D(2024, 1, 1), None, D(2024, 3, 1))
    miete = vz.erinnerung(e, 'Guten Tag A,', 'EG', 'das Konto', None,
                          art='Mietzahlungen')
    assert 'sind folgende Mietzahlungen noch nicht vollständig eingegangen' in miete
    assert 'Nebenkostenvorauszahlungen' not in miete
    # Der bisherige Text bleibt Wort für Wort gleich.
    voraus = vz.erinnerung(e, 'Guten Tag A,', 'EG', 'das Konto', None)
    assert 'sind folgende Nebenkostenvorauszahlungen noch nicht vollständig ' \
           'eingegangen' in voraus
    assert miete.replace('Mietzahlungen', 'Nebenkostenvorauszahlungen') == voraus


# --- Über die API ---------------------------------------------------------------

@pytest.fixture
def mieter(app_ctx):
    haus = f.house()
    return f.tenant(f.apt(haus, 'EG', 50), 'Mieter A', D(2024, 1, 1), D(2024, 3, 31))


def _zahlung(m, tag, betrag, art='Miete'):
    db.session.add(Payment(tenant_id=m.id, amount=betrag, payment_date=tag, type=art))
    db.session.commit()


def test_miete_und_vorauszahlung_mischen_sich_nicht(auth_client, mieter):
    auth_client.post(f'/api/tenants/{mieter.id}/kaltmiete_soll',
                     data={'gueltig_ab': '2024-01-01', 'betrag': '700'})
    auth_client.post(f'/api/tenants/{mieter.id}/vorauszahlung_soll',
                     data={'gueltig_ab': '2024-01-01', 'betrag': '300'})
    _zahlung(mieter, D(2024, 1, 3), 700)
    _zahlung(mieter, D(2024, 1, 3), 300, art='Nebenkostenvorauszahlung')
    _zahlung(mieter, D(2024, 2, 3), 300, art='Nebenkostenvorauszahlung')
    _zahlung(mieter, D(2024, 3, 3), 300, art='Nebenkostenvorauszahlung')
    m = auth_client.get(f'/api/tenants/{mieter.id}/miete').get_json()
    v = auth_client.get(f'/api/tenants/{mieter.id}/vorauszahlungen').get_json()
    # Miete: Januar bezahlt, Februar und März (vergangen, ungezahlt) Rückstand.
    assert [(x['monat'], x['rueckstand']) for x in m['monate']] == \
        [('2024-01', False), ('2024-02', True), ('2024-03', True)]
    assert m['saldo'] == '1400.00'
    assert 'Mietzahlungen' in m['erinnerung']
    # Die Vorauszahlung ist vollständig: keine Erinnerung nötig.
    assert v['saldo'] == '0.00' and v['erinnerung'] is None
    assert auth_client.get('/api/tenants/99999/miete').status_code == 404


def test_die_ansicht_zeigt_teilzahlung_und_erinnerung(auth_client, mieter):
    auth_client.post(f'/api/tenants/{mieter.id}/kaltmiete_soll',
                     data={'gueltig_ab': '2024-01-01', 'betrag': '700'})
    _zahlung(mieter, D(2024, 1, 3), 700)
    _zahlung(mieter, D(2024, 2, 3), 70)
    _zahlung(mieter, D(2024, 3, 3), 700)
    d = auth_client.get(f'/api/tenants/{mieter.id}/miete').get_json()
    assert [s['betrag'] for s in d['soll']] == ['700.00']
    assert [(x['monat'], x['rueckstand']) for x in d['monate']] == \
        [('2024-01', False), ('2024-02', True), ('2024-03', False)]
    assert d['saldo'] == '630.00'
    assert '02/2024: fällig 700,00 €, gezahlt 70,00 €, offen 630,00 €' in d['erinnerung']


def test_kuenftige_stufen_sind_geplant(auth_client, app_ctx):
    haus = f.house()
    m = f.tenant(f.apt(haus, 'OG', 60), 'Mieter B', D(2026, 1, 1), None)
    auth_client.post(f'/api/tenants/{m.id}/kaltmiete_soll',
                     data={'gueltig_ab': '2026-01-01', 'betrag': '700'})
    auth_client.post(f'/api/tenants/{m.id}/kaltmiete_soll',
                     data={'gueltig_ab': '2027-01-01', 'betrag': '800'})
    d = auth_client.get(f'/api/tenants/{m.id}/miete').get_json()
    assert [(s['gueltig_ab'], s['geplant']) for s in d['soll']] == \
        [('2026-01-01', False), ('2027-01-01', True)]
    # Gezählt wird nur, was fällig ist: die geplante Stufe steht in keinem Monat.
    assert all(x['soll'] in ('700.00', None) for x in d['monate'])


# --- Oberfläche ------------------------------------------------------------------

def test_die_oberflaeche_hat_die_verdrahtung():
    app = (WURZEL / 'static' / 'app.js').read_text(encoding='utf-8')
    seite = (WURZEL / 'static' / 'index.html').read_text(encoding='utf-8')
    assert 'id="km-monate"' in seite and 'id="km-erinnerung"' in seite
    assert 'data-begriff="kaltmiete"' in seite
    assert '/api/tenants/${tenantId}/miete' in app
    # Eine Monattabelle für beide Arten, nicht doppelt gebaut.
    assert 'function monatsZeilen(' in app
    assert app.count('monatsZeilen(') >= 3
    assert "serienbuchungAnlegen(tenantId, betrag, ab, kuenftige, art = 'Nebenkostenvorauszahlung')" in app
