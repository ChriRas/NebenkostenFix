"""Export: die Mieter-Auskunft ließ das Kaltmiete-Soll weg.

``GET /api/tenants/<id>/export`` ist die Auskunft nach Art. 15 DSGVO
(R-DSGVO-02: „Datenexport je Mieter“; Docstring der Route: „die JSON-Auskunft
mit allen Zeilen zum Mieter“). ``mieter_daten.export_erstellen`` nahm
Kostenprofile, Haushaltsgrößen, Vorauszahlungs-Soll und Zahlungen mit --
die vereinbarte Kaltmiete ab Stichtag (``kaltmiete_soll``, Phase 49) hängt
genauso am Mieter (``Tenant.kaltmiete_soll``, Kaskade beim Löschen), fehlte
in der Auskunft aber ganz. Der Mieter erfuhr so nicht, welche Miethöhen und
Indexanpassungen über ihn gespeichert sind.

Alle Daten fiktiv.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date

from tests import billing_factories as f


def _auskunft(client, mieter_id):
    antwort = client.get(f'/api/tenants/{mieter_id}/export')
    assert antwort.status_code == 200, antwort.get_data(as_text=True)
    with zipfile.ZipFile(io.BytesIO(antwort.data)) as archiv:
        return json.loads(archiv.read('mieter-auskunft.json'))


def test_auskunft_enthaelt_das_kaltmiete_soll(auth_client, app_ctx):
    mieter = f.tenant(f.apt(f.house('Testhaus Auskunft'), 'OG', 55),
                      'Mia Beispiel', date(2023, 1, 1))
    for tag, betrag, index in (('2023-01-01', '610', 'false'), ('2024-04-01', '640', 'true')):
        antwort = auth_client.post(f'/api/tenants/{mieter.id}/kaltmiete_soll',
                                   data={'gueltig_ab': tag, 'betrag': betrag,
                                         'indexmiete': index})
        assert antwort.status_code == 201, antwort.get_data(as_text=True)
    assert len(mieter.kaltmiete_soll) == 2

    auskunft = _auskunft(auth_client, mieter.id)

    assert 'kaltmiete_soll' in auskunft, sorted(auskunft)
    assert [(s['gueltig_ab'], s['betrag']) for s in auskunft['kaltmiete_soll']] == [
        ('2023-01-01', '610.00'), ('2024-04-01', '640.00')]


def test_gegenprobe_vorauszahlung_soll_steht_drin(auth_client, app_ctx):
    """Das Schwesterfeld ist da -- der Unterschied liegt nur am Kaltmiete-Soll."""
    mieter = f.tenant(f.apt(f.house('Testhaus Auskunft 2'), 'EG', 48),
                      'Ole Beispiel', date(2023, 1, 1))
    auth_client.post(f'/api/tenants/{mieter.id}/vorauszahlung_soll',
                     data={'gueltig_ab': '2023-01-01', 'betrag': '120'})
    auskunft = _auskunft(auth_client, mieter.id)
    assert [s['betrag'] for s in auskunft['vorauszahlung_soll']] == ['120.00']


# --- Zwei Mieter im selben Haus ------------------------------------------------


def _kaltmiete(client, mieter_id, tag, betrag, index):
    antwort = client.post(f'/api/tenants/{mieter_id}/kaltmiete_soll',
                          data={'gueltig_ab': tag, 'betrag': betrag,
                                'indexmiete': index})
    assert antwort.status_code == 201, antwort.get_data(as_text=True)
    return antwort.get_json()['id']


def _haus_mit_zwei_mietern():
    haus = f.house('Testhaus Auskunft')
    mieter = f.tenant(f.apt(haus, 'W1', 48), 'Mieter Auskunft', date(2024, 1, 1))
    fremd = f.tenant(f.apt(haus, 'W2', 55), 'Mieter Fremd', date(2024, 1, 1))
    return mieter, fremd


def test_kaltmiete_soll_vollstaendig_und_nach_stichtag(auth_client, app_ctx):
    """Alle Spalten jeder Zeile, sortiert nach gueltig_ab -- auch wenn der
    spätere Stichtag zuerst erfasst wurde."""
    mieter, fremd = _haus_mit_zwei_mietern()
    spaeter = _kaltmiete(auth_client, mieter.id, '2025-01-01', '545,50', 'true')
    frueher = _kaltmiete(auth_client, mieter.id, '2024-01-01', '520,00', 'false')
    _kaltmiete(auth_client, fremd.id, '2024-01-01', '610,00', 'false')

    auskunft = _auskunft(auth_client, mieter.id)

    assert auskunft['kaltmiete_soll'] == [
        {'id': frueher, 'tenant_id': mieter.id, 'gueltig_ab': '2024-01-01',
         'betrag': '520.00', 'indexmiete': False},
        {'id': spaeter, 'tenant_id': mieter.id, 'gueltig_ab': '2025-01-01',
         'betrag': '545.50', 'indexmiete': True},
    ]


def test_kaltmiete_soll_anderer_mieter_bleibt_draussen(auth_client, app_ctx):
    mieter, fremd = _haus_mit_zwei_mietern()
    _kaltmiete(auth_client, mieter.id, '2024-01-01', '520,00', 'false')
    _kaltmiete(auth_client, mieter.id, '2025-01-01', '545,50', 'true')
    _kaltmiete(auth_client, fremd.id, '2024-01-01', '610,00', 'false')

    eigene = _auskunft(auth_client, mieter.id)['kaltmiete_soll']
    assert len(eigene) == 2
    assert {s['tenant_id'] for s in eigene} == {mieter.id}
    assert '610.00' not in [s['betrag'] for s in eigene]

    # Und umgekehrt: die Auskunft des anderen Mieters hat nur seine Zeile.
    fremde = _auskunft(auth_client, fremd.id)['kaltmiete_soll']
    assert [(s['tenant_id'], s['betrag']) for s in fremde] == [(fremd.id, '610.00')]


def test_ohne_kaltmiete_soll_eine_leere_liste(auth_client, app_ctx):
    mieter, fremd = _haus_mit_zwei_mietern()
    _kaltmiete(auth_client, fremd.id, '2024-01-01', '610,00', 'false')

    auskunft = _auskunft(auth_client, mieter.id)

    assert auskunft['kaltmiete_soll'] == []


def test_vorauszahlung_soll_bleibt_unveraendert_neben_der_kaltmiete(auth_client, app_ctx):
    """Gegenprobe: das Vorauszahlungs-Soll steht weiter so
    drin wie bisher, getrennt vom Kaltmiete-Soll, und die übrigen Schlüssel
    der Auskunft sind dieselben -- der neue kommt direkt nach
    'vorauszahlung_soll'."""
    mieter, _fremd = _haus_mit_zwei_mietern()
    antwort = auth_client.post(f'/api/tenants/{mieter.id}/vorauszahlung_soll',
                               data={'gueltig_ab': '2024-01-01', 'betrag': '150,00'})
    assert antwort.status_code == 201, antwort.get_data(as_text=True)
    vz_id = antwort.get_json()['id']
    _kaltmiete(auth_client, mieter.id, '2024-01-01', '520,00', 'false')

    auskunft = _auskunft(auth_client, mieter.id)

    assert auskunft['vorauszahlung_soll'] == [
        {'id': vz_id, 'tenant_id': mieter.id, 'gueltig_ab': '2024-01-01',
         'betrag': '150.00'}]
    assert [s['betrag'] for s in auskunft['kaltmiete_soll']] == ['520.00']
    assert list(auskunft) == [
        'format', 'erstellt_am', 'mieter', 'kostenprofile', 'haushaltsgroessen',
        'vorauszahlung_soll', 'kaltmiete_soll', 'zahlungen', 'abrechnungsberichte',
        'ablesungen', 'dateien', 'hinweis']
