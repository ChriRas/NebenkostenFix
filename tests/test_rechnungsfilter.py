"""Phase 57 (Issue #35, Punkt 3): Rechnungen nach Jahr ansehen.

Der Melder wollte „ein Auswahlfeld um sich die Rechnungen für verschiedene
Jahre anzugucken". Die Zeitleiste (NK-144) gruppierte schon nach Jahr und
Monat, aber die Filterleiste kannte nur Suche und Kategorie -- und die
Jahressumme rechnete der Server (``zeitleiste.erstellen``) bereits, ohne
dass die Oberflaeche sie zeigte.

Was hier gegen die Oberflaeche geprueft wird, sind die **Anker**: die
Felder, an denen das Verhalten haengt, und der Weg der Summe. Das Verhalten
selbst -- filtern, zaehlen, summieren, zuruecksetzen -- faehrt der
Rauchtest (``scripts/rauchtest_design.js``, acht Pruefpunkte „Phase 57")
gegen einen DOM-Stub.

Der Teil, der am ehesten still kaputtgeht, ist die Summe: Eine Zeile, die
immer die Gesamtsumme nennt, sieht aus wie eine Antwort auf die gestellte
Frage und ist doch keine. Deshalb steht hier ausdruecklich, dass sie aus
``filtered`` kommt und nicht aus ``invoices``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
OBERFLAECHE = WURZEL / 'static' / 'index.html'
SKRIPT = WURZEL / 'static' / 'app.js'
STIL = WURZEL / 'static' / 'style.css'


@pytest.fixture(scope='module')
def html() -> str:
    return OBERFLAECHE.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def js() -> str:
    return SKRIPT.read_text(encoding='utf-8')


def test_die_filterleiste_hat_ein_auswahlfeld_fuer_das_jahr(html):
    """Neben Suche und Kategorie, in derselben Leiste."""
    leiste = re.search(r'id="invoice-filter"(.*?)</div>\s*</div>', html, re.S)
    assert leiste, 'Die Filterleiste der Rechnungen ist nicht auffindbar.'

    assert 'id="invoice-jahr-filter"' in leiste.group(1), (
        'Das Auswahlfeld für das Jahr steht nicht in der Filterleiste.')
    assert 'Alle Jahre' in leiste.group(1), (
        'Dem Auswahlfeld fehlt der Vorgabeeintrag „Alle Jahre".')


def test_das_auswahlfeld_zeichnet_die_liste_neu(html):
    """Ohne ``onchange`` waere das Feld eine Zierde."""
    feld = re.search(r'<select id="invoice-jahr-filter"[^>]*>', html)

    assert feld and 'onchange="renderInvoices()"' in feld.group(0), (
        'Das Jahr-Auswahlfeld löst kein Neuzeichnen aus.')


def test_die_summenzeile_steht_ueber_der_liste(html):
    """Sie ist anfangs verborgen -- zu leerem Bestand gehoert keine Summe."""
    zeile = re.search(r'<p class="rechnungen-summe" id="invoice-summe"[^>]*>',
                      html)

    assert zeile, 'Die Summenzeile über der Rechnungsliste fehlt.'
    assert 'hidden' in zeile.group(0), (
        'Die Summenzeile ist nicht verborgen vorbelegt; bei leerem Bestand '
        'stünde dort eine Null ohne Zusammenhang.')


def test_das_jahr_kommt_aus_dem_rechnungsdatum(js):
    """D-57: das Ausstellungsdatum des Belegs, nicht der Tag der Erfassung."""
    funktion = re.search(r'function rechnungsJahr\(rechnung\)\s*\{.*?\n\}',
                         js, re.S)
    assert funktion, 'rechnungsJahr() fehlt.'

    assert 'rechnung.rechnungsdatum' in funktion.group(0), (
        'rechnungsJahr() liest nicht das Rechnungsdatum.')
    for falsch in ('created_at', 'start_date', 'end_date'):
        assert falsch not in funktion.group(0), (
            f'rechnungsJahr() nimmt „{falsch}" statt des Rechnungsdatums.')


def test_die_summe_folgt_dem_filter_und_nicht_dem_bestand(js):
    """Der Fehler, der hier wehtut: die Zeile nennt immer alles."""
    render = re.search(r'function renderInvoices\(\)\s*\{.*?\n\}', js, re.S)
    assert render, 'renderInvoices() ist nicht auffindbar.'
    text = render.group(0)

    assert 'filtered.reduce' in text, (
        'Die Summenzeile rechnet nicht über die gefilterte Liste.')
    assert 'invoices.reduce' not in text, (
        'Die Summenzeile rechnet über den ganzen Bestand. Dann beantwortet '
        'sie eine andere Frage als die, die der Nutzer gestellt hat.')


def test_das_zuruecksetzen_raeumt_auch_das_jahr(js):
    """Ein Filter, den „zuruecksetzen" stehen laesst, ist eine Falle."""
    funktion = re.search(
        r'function rechnungsfilterZuruecksetzen\(\)\s*\{.*?\n\}', js, re.S)
    assert funktion, 'rechnungsfilterZuruecksetzen() fehlt.'

    assert "invoice-jahr-filter" in funktion.group(0), (
        '„Filter zurücksetzen" räumt das Jahr nicht mit. Der Nutzer sieht '
        'dann eine gefilterte Liste und keinen Grund dafür.')


def test_die_zeitleiste_zeigt_die_summe_die_der_server_rechnet(js):
    """Nicht nachrechnen: ``zeitleiste.erstellen`` liefert sie fertig."""
    funktion = re.search(
        r'function renderInvoiceZeitleiste\(.*?\n\}', js, re.S)
    assert funktion, 'renderInvoiceZeitleiste() ist nicht auffindbar.'

    assert 'jahr.summe' in funktion.group(0), (
        'Die Zeitleiste zeigt die Jahressumme des Servers nicht.')
    assert 'zeitleiste-jahressumme' in funktion.group(0), (
        'Der Jahressumme fehlt ihre Klasse.')


def test_die_neuen_klassen_sind_im_stylesheet():
    """Sonst steht die Summe ohne Form in der Zeile."""
    css = STIL.read_text(encoding='utf-8')

    for klasse in ('.zeitleiste-jahressumme', '.rechnungen-summe'):
        assert klasse in css, f'{klasse} fehlt im Stylesheet.'


def test_der_cache_buster_steigt_mit_der_aenderung(html):
    """Wer app.js aendert und die Nummer vergisst, liefert den alten Stand."""
    js_version = re.search(r'/static/app\.js\?v=(\d+)', html)
    css_version = re.search(r'/static/style\.css\?v=(\d+)', html)

    assert js_version and int(js_version.group(1)) >= 40, (
        'Der Cache-Buster von app.js steht noch unter 40 (Phase 57).')
    assert css_version and int(css_version.group(1)) >= 15, (
        'Der Cache-Buster von style.css steht noch unter 15 (Phase 57).')
