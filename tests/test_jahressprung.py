"""NK-228: Sprünge einer Kostenart gegenüber dem Vorjahr.

Schritt 2 des Assistenten zeigt je Kostenart die Änderung zum Vorjahr und
markiert sie als Sprung, wenn sie mehr als 20 % beträgt -- nach oben wie
nach unten. Ohne Rechnungen in beiden Jahren gibt es keine Änderung, also
auch keinen Sprung. Blockiert wird nichts.
"""

from __future__ import annotations

from datetime import date

from billing_factories import category, house, invoice
from nebenkostenfix.jahresabrechnung import stand

JAHR = 2025


def _art(app_ctx, diesjahr, vorjahr, name='Grundsteuer'):
    haus = house('Sprunghaus')
    kat = category(name)
    if diesjahr is not None:
        invoice(haus, kat, diesjahr, date(JAHR, 1, 1), date(JAHR, 12, 31))
    if vorjahr is not None:
        invoice(haus, kat, vorjahr, date(JAHR - 1, 1, 1), date(JAHR - 1, 12, 31),
                invoice_number='INV-0')
    arten = stand(haus.id, JAHR, heute=date(2026, 3, 1))['kostenarten']
    return next(k for k in arten if k['id'] == kat.id)


def test_mehr_als_zwanzig_prozent_ist_ein_sprung(app_ctx):
    k = _art(app_ctx, 1450.0, 1000.0)
    assert (k['aenderung'], k['sprung']) == (45, True)


def test_genau_zwanzig_prozent_ist_noch_keiner(app_ctx):
    k = _art(app_ctx, 1200.0, 1000.0)
    assert (k['aenderung'], k['sprung']) == (20, False)


def test_knapp_darueber_zaehlt_nach_der_gerundeten_anzeige(app_ctx):
    # 20,4 % zeigt der Assistent als „+20 %“ -- markiert wird, was man sieht.
    assert _art(app_ctx, 1204.0, 1000.0)['sprung'] is False
    k = _art(app_ctx, 1205.0, 1000.0)
    assert (k['aenderung'], k['sprung']) == (21, True)


def test_ein_rueckgang_ist_auch_ein_sprung(app_ctx):
    k = _art(app_ctx, 700.0, 1000.0)
    assert (k['aenderung'], k['sprung']) == (-30, True)


def test_ohne_vorjahr_kein_sprung(app_ctx):
    k = _art(app_ctx, 1450.0, None)
    assert (k['aenderung'], k['sprung']) == (None, False)


def test_ohne_rechnung_im_jahr_kein_sprung(app_ctx):
    # Fehlt die Rechnung, sagt das schon „fehlt“ -- minus 100 % wäre Lärm.
    k = _art(app_ctx, None, 1000.0)
    assert k['zustand'] == 'fehlt'
    assert (k['aenderung'], k['sprung']) == (None, False)


# --- NK-242: das Abrechnungsjahr des Hauses, Beträge zeitanteilig -----------------

def _april_haus(preis_ab_oktober_2025):
    """Abrechnungsjahr 01.04.–31.03., Rechnungen jeweils 01.10.–30.09."""
    haus = house('Aprilhaus')
    haus.abrechnungsjahr_beginn = '04-01'
    kat = category('Grundsteuer')
    for nummer, (jahr, betrag) in enumerate(((2023, 1200.0), (2024, 1200.0),
                                             (2025, preis_ab_oktober_2025))):
        invoice(haus, kat, betrag, date(jahr, 10, 1), date(jahr + 1, 9, 30),
                invoice_number=f'INV-{nummer}')
    ergebnis = stand(haus.id, JAHR, heute=date(2026, 6, 1))
    return ergebnis, next(k for k in ergebnis['kostenarten'] if k['id'] == kat.id)


def test_abweichendes_abrechnungsjahr_rechnet_zeitanteilig(app_ctx):
    # 183/365 von 1.200 + 182/365 von 1.800; Vorjahr 183/366 + 182/365 von 1.200.
    ergebnis, k = _april_haus(1800.0)

    assert (ergebnis['von'], ergebnis['bis']) == ('2025-04-01', '2026-03-31')
    assert (k['anzahl'], k['summe'], k['summe_vorjahr']) == (2, 1499.17, 1198.36)
    assert (k['aenderung'], k['sprung']) == (25, True)


def test_gleicher_preis_ueber_die_jahresgrenze_ist_kein_sprung(app_ctx):
    _, k = _april_haus(1200.0)

    assert (k['summe'], k['summe_vorjahr']) == (1200.0, 1198.36)
    assert (k['aenderung'], k['sprung']) == (0, False)
