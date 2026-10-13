"""NK-266: Belegeinsicht-Paket je Mieter (R-DSGVO-03).

Ein Haus mit zwei Mietern. Das Paket des einen trägt seine Abrechnung,
den Rechenweg, die Belege seiner Abrechnung und die Ablesefotos der
Zähler seiner Wohnung -- keinen Namen und kein Foto des anderen, und kein
Dateiname im Paket nennt eine Person. Alle Werte sind erfunden.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest

from billing_factories import apt, category, house, invoice, meter, payment, profile, reading, tenant

D = date
NAMEN = ('Anna', 'Mieterin', 'Bert', 'Nachbar')


@pytest.fixture
def welt(app_ctx, monkeypatch, tmp_path):
    from nebenkostenfix.models import InvoiceDocument, db

    nas = tmp_path / 'nas'
    nas.mkdir()
    monkeypatch.setenv('NAS_MOUNT_PATH', str(nas))
    wasser = category('Wasserversorgung')
    haus = house()
    eg, og = apt(haus, 'EG', 50.0), apt(haus, 'OG', 50.0)
    anna = tenant(eg, 'Anna Mieterin', move_in=D(2024, 1, 1))
    bert = tenant(og, 'Bert Nachbar', move_in=D(2024, 1, 1))
    for m in (anna, bert):
        profile(m, wasser, 'direkt')
        payment(m, 300.0, D(2025, 6, 1))

    # Altbestand mit sprechendem Namen: im Paket heißt die Datei neutral.
    beleg = nas / 'wasser_Anna_Mieterin.pdf'
    beleg.write_bytes(b'%PDF-1.4 Wasser 2025')
    rechnung = invoice(haus, wasser, 1200.0, D(2025, 1, 1), D(2025, 12, 31), invoice_number='W-1')
    rechnung.document = InvoiceDocument(property_id=haus.id, filename=beleg.name,
                                        document_path=str(beleg), upload_date=D(2025, 12, 31),
                                        is_collective=True)

    def foto(zaehler, tag, wert, name):
        stand = reading(zaehler, tag, wert)
        datei = nas / name
        datei.write_bytes(b'JPEG ' + name.encode())
        stand.document_path = str(datei)

    eigen = meter(haus, wasser, 'WA-EG', is_main=False, apartment=eg)
    foto(eigen, D(2023, 12, 31), 0.0, 'vorvorjahr.jpg')  # liegt vor dem Stand, ab dem gerechnet wird
    foto(eigen, D(2024, 12, 31), 10.0, 'anna_start.JPG')
    reading(eigen, D(2025, 6, 30), 40.0)  # ohne Foto
    foto(eigen, D(2025, 12, 31), 70.0, 'anna_ende.jpg')
    foto(eigen, D(2026, 3, 1), 80.0, 'anna_danach.jpg')
    fremd = meter(haus, wasser, 'WA-OG', is_main=False, apartment=og)
    foto(fremd, D(2024, 12, 31), 5.0, 'bert_start.jpg')
    foto(fremd, D(2025, 12, 31), 50.0, 'bert_ende.jpg')
    db.session.commit()
    return anna


def _paket(auth_client, mieter):
    from nebenkostenfix.models import TenantBillingReport

    antwort = auth_client.post('/api/billing/finalize', json={
        'tenant_id': mieter.id, 'start_date': '2025-01-01', 'end_date': '2025-12-31'})
    assert antwort.status_code == 201, antwort.get_data(as_text=True)
    report = TenantBillingReport.query.filter_by(tenant_id=mieter.id).one()
    antwort = auth_client.get(f'/api/billing/reports/{report.id}/belege')
    assert antwort.status_code == 200, antwort.get_data(as_text=True)
    with zipfile.ZipFile(io.BytesIO(antwort.data)) as paket:
        return {name: paket.read(name) for name in paket.namelist()}


def test_das_paket_traegt_abrechnung_rechenweg_belege_und_eigene_fotos(auth_client, welt):
    inhalt = _paket(auth_client, welt)
    assert set(inhalt) == {
        'Abrechnung.pdf', 'Rechenweg.csv', 'Belege/01_Wasserversorgung.pdf',
        'Ablesefotos/Zaehler_WA-EG_2024-12-31.jpg',
        'Ablesefotos/Zaehler_WA-EG_2025-12-31.jpg',
        'Ablesefotos/Zaehler_WA-EG_2026-03-01.jpg',
    }, sorted(inhalt)
    assert inhalt['Abrechnung.pdf'].startswith(b'%PDF')
    assert inhalt['Belege/01_Wasserversorgung.pdf'] == b'%PDF-1.4 Wasser 2025'
    assert inhalt['Ablesefotos/Zaehler_WA-EG_2024-12-31.jpg'] == b'JPEG anna_start.JPG'
    rechenweg = inhalt['Rechenweg.csv'].decode('utf-8')
    assert rechenweg.startswith('﻿') and 'Wasserversorgung' in rechenweg


def test_nichts_vom_nachbarn_und_kein_name_im_dateinamen(auth_client, welt):
    inhalt = _paket(auth_client, welt)
    assert not any(teil in name for name in inhalt for teil in NAMEN), sorted(inhalt)
    assert not any(b'bert' in daten for daten in inhalt.values())
    assert not any('WA-OG' in name for name in inhalt)
    for name in ('Rechenweg.csv', 'FEHLENDE_BELEGE.txt'):
        text = inhalt.get(name, b'').decode('utf-8')
        assert 'Bert' not in text and 'Nachbar' not in text and 'WA-OG' not in text


def test_fehlt_das_pdf_steht_es_in_der_liste(auth_client, welt):
    from nebenkostenfix.models import TenantBillingReport, db

    auth_client.post('/api/billing/finalize', json={
        'tenant_id': welt.id, 'start_date': '2025-01-01', 'end_date': '2025-12-31'})
    report = TenantBillingReport.query.filter_by(tenant_id=welt.id).one()
    report.document_path = None
    db.session.commit()
    antwort = auth_client.get(f'/api/billing/reports/{report.id}/belege')
    with zipfile.ZipFile(io.BytesIO(antwort.data)) as paket:
        assert 'Abrechnung.pdf' not in paket.namelist()
        assert 'Abrechnung: das PDF liegt nicht vor.' in paket.read('FEHLENDE_BELEGE.txt').decode('utf-8')
