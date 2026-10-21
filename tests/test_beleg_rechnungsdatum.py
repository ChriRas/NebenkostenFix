"""Phase 64: Das Rechnungsdatum für alle Rechnungen eines Sammelbelegs.

Aus der Durchsicht vor 0.17.0: Mehrere Rechnungen hängen an derselben PDF,
jede mit ihren Seiten. Das Ausstellungsdatum steht einmal auf dem Beleg,
musste aber bei jeder Rechnung einzeln eingetragen werden. „Das muss keine
Pflicht sein, aber ich möchte die Option haben."

Wer beim Speichern ``rechnungsdatum_fuer_beleg`` setzt, schreibt das Datum
in alle Rechnungen, die an demselben Beleg hängen. Ohne den Haken ändert
sich nur die eine Rechnung -- wie bisher.
"""

from __future__ import annotations

from datetime import date

from nebenkostenfix.models import CostInvoice, InvoiceDocument, db
from tests import billing_factories as f


def _sammelbeleg():
    haus = f.house()
    kat = f.category("Wasser")
    beleg = InvoiceDocument(property_id=haus.id, filename="sammel.pdf",
                            document_path="sammel.pdf", is_collective=True)
    anderer = InvoiceDocument(property_id=haus.id, filename="einzeln.pdf",
                              document_path="einzeln.pdf")
    db.session.add_all([beleg, anderer])
    db.session.flush()
    rechnungen = []
    for nummer, dok in (("A", beleg), ("B", beleg), ("C", beleg), ("D", anderer)):
        inv = f.invoice(haus, kat, 100, invoice_number=nummer)
        inv.invoice_document_id = dok.id
        rechnungen.append(inv)
    rechnungen[1].rechnungsdatum = date(2025, 1, 5)  # ein altes Datum wird überschrieben
    db.session.commit()
    return haus, kat, beleg, [r.id for r in rechnungen]


def _felder(haus, kat, beleg, **mehr):
    return {'category_id': kat.id, 'property_id': haus.id, 'amount': '100.00',
            'start_date': '2025-01-01', 'end_date': '2025-12-31',
            'invoice_document_id': beleg.id, 'rechnungsdatum': '2026-02-14', **mehr}


def _daten(ids):
    db.session.expire_all()
    return [CostInvoice.query.get(i).rechnungsdatum for i in ids]


def test_mit_haken_bekommen_alle_rechnungen_des_belegs_das_datum(auth_client):
    haus, kat, beleg, ids = _sammelbeleg()
    antwort = auth_client.put(f'/api/invoices/{ids[0]}', json=_felder(
        haus, kat, beleg, invoice_number='A', rechnungsdatum_fuer_beleg=True))
    assert antwort.status_code == 200, antwort.get_data(as_text=True)
    assert antwort.get_json()['beleg_datum_gesetzt'] == 2
    assert _daten(ids) == [date(2026, 2, 14)] * 3 + [None]


def test_ohne_haken_aendert_sich_nur_die_eine_rechnung(auth_client):
    haus, kat, beleg, ids = _sammelbeleg()
    antwort = auth_client.put(f'/api/invoices/{ids[0]}', json=_felder(
        haus, kat, beleg, invoice_number='A'))
    assert antwort.status_code == 200
    assert 'beleg_datum_gesetzt' not in antwort.get_json()
    assert _daten(ids) == [date(2026, 2, 14), date(2025, 1, 5), None, None]


def test_auch_beim_erfassen_einer_neuen_rechnung(auth_client):
    haus, kat, beleg, ids = _sammelbeleg()
    antwort = auth_client.post('/api/invoices', json=_felder(
        haus, kat, beleg, invoice_number='E', document_pages='6',
        rechnungsdatum_fuer_beleg=True))
    assert antwort.status_code == 201, antwort.get_data(as_text=True)
    assert antwort.get_json()['beleg_datum_gesetzt'] == 3
    assert _daten(ids) == [date(2026, 2, 14)] * 3 + [None]


def test_ohne_datum_wird_nichts_geloescht(auth_client):
    """Ein leeres Datum mit Haken darf die Daten der anderen nicht leeren."""
    haus, kat, beleg, ids = _sammelbeleg()
    antwort = auth_client.put(f'/api/invoices/{ids[0]}', json=_felder(
        haus, kat, beleg, invoice_number='A', rechnungsdatum='',
        rechnungsdatum_fuer_beleg=True))
    assert antwort.status_code == 200
    assert _daten(ids) == [None, date(2025, 1, 5), None, None]
