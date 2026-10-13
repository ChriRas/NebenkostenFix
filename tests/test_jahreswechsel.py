"""NK-267: Neues Jahr beginnen.

Der Ablauf selbst ist Oberfläche und steht im Rauchtest
(``jahreswechselPruefen``). Vom Server braucht er nur, die Abrechnungen
einer Immobilie zu finden: die Liste trägt dafür ``property_id``.
"""

from __future__ import annotations

from datetime import date

from nebenkostenfix.models import TenantBillingReport, db
from tests import billing_factories as f


def test_die_abrechnungsliste_nennt_die_immobilie(auth_client, app_ctx):
    haus_a, haus_b = f.house('Haus A'), f.house('Haus B')
    for haus in (haus_a, haus_b):
        mieter = f.tenant(f.apt(haus, 'EG', 50), 'Mieter', date(2025, 1, 1))
        db.session.add(TenantBillingReport(tenant_id=mieter.id, start_date=date(2025, 1, 1),
                                           end_date=date(2025, 12, 31), frist_ende=date(2026, 12, 31)))
    db.session.commit()
    liste = auth_client.get('/api/billing/reports').get_json()
    assert sorted(r['property_id'] for r in liste) == sorted([haus_a.id, haus_b.id])
