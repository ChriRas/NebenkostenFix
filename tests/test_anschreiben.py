"""Das Anschreiben mit Zahlungsaufforderung als editierbare Vorlage (NK-064).

Das Deckblatt trug einen festen Gruß; der Vermieter konnte den Ton
seines Anschreibens nicht bestimmen. Die Vorlage lebt je Objekt in der
Tabelle ``anschreiben_vorlagen``, ohne Eintrag spricht der Vorgabetext
aus ``anschreiben.py``. Die Platzhalter füllt ``text_fuer`` aus dem
Ergebnis der Abrechnung -- Geld in der Sprache des Dokuments, Komma
statt Punkt. Die Zahlungsaufforderung ist Teil der Vorlage; der
Platzhalter ``{aufforderung}`` bleibt bei einem Guthaben gewollt leer,
denn es gäbe nichts zu fordern.

Das Auslesen des PDF arbeitet wie in ``test_pdf_fuss.py``: Seiten
unkomprimiert, Textströme direkt gelesen, Umbrüche wieder
zusammengeklebt.
"""

from __future__ import annotations

import os
import re
import zlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import reportlab.rl_config

from nebenkostenfix.anschreiben import VORGABE, PLATZHALTER, fuelle, text_fuer, absaetze
from nebenkostenfix.pdf_cover_page import build_cover_page_elements

ZEITRAUM = {'start_date': '2025-01-01', 'end_date': '2025-12-31'}


@pytest.fixture
def unkomprimiert(monkeypatch):
    """Seiten ohne Kompression, damit der Text lesbar im Strom steht."""
    monkeypatch.setattr(reportlab.rl_config, 'pageCompression', 0)


def _entschluesselt(stueck: str) -> str:
    """Löst die Escapes eines PDF-Textstücks auf (Umlaute als Oktal)."""
    ausgabe = []
    i = 0
    while i < len(stueck):
        zeichen = stueck[i]
        if zeichen == '\\' and i + 1 < len(stueck):
            if stueck[i + 1] in '01234567':
                ziffern = ''
                j = i + 1
                while j < len(stueck) and len(ziffern) < 3 \
                        and stueck[j] in '01234567':
                    ziffern += stueck[j]
                    j += 1
                ausgabe.append(chr(int(ziffern, 8)))
                i = j
                continue
            ausgabe.append(stueck[i + 1])
            i += 2
            continue
        ausgabe.append(zeichen)
        i += 1
    return ''.join(ausgabe).replace(chr(0x80), '€')


def _blaetter(pdf: bytes) -> list[str]:
    """Der geklebte Text jedes Blatts, in der Reihenfolge des Zeichnens."""
    blaetter = []
    for roh in pdf.split(b'stream')[1:]:
        roh = roh.split(b'endstream')[0]
        try:
            roh = zlib.decompress(roh.strip())
        except zlib.error:
            # Unkomprimierter Inhalt (pageCompression 0) oder Bildstrom:
            # der rohe Inhalt bleibt, Klammern findet der Ausdruck dort
            # genauso.
            pass
        stuecke = [_entschluesselt(m) for m in re.findall(
            r'\(((?:\\.|[^\\)])*)\)', roh.decode('latin-1', 'replace'))]
        blaetter.append(re.sub(r'\s+', '', ''.join(stuecke)))
    return blaetter


def _geklebt(pdf: bytes) -> str:
    """Der Text des ganzen Dokuments, alle Stroeme zusammengeklebt.

    Der QR-Code zeichnet seinen Bildstrom vor den Inhalt des Deckblatts
    -- auf Position im Strom ist also kein Verlass; gezählt wird der
    Text, nicht der Ort.
    """
    return ''.join(_blaetter(pdf))


# --- Die Renderfunktion -------------------------------------------------------


def test_die_renderfunktion_fuellt_bekannte_platzhalter():
    """Bekannte Platzhalter bekommen ihren Wert, Geld in Dokumentsprache."""
    text = text_fuer(
        'Hallo {mieter_name}, Wohnung {wohnung_name}.',
        mieter_name='Anna Mieterin', wohnung_name='EG links',
        objekt_name='Haus am Anger', zeitraum='01.01.2025 bis 31.12.2025',
        gesamtsumme=Decimal('1200.00'), vorauszahlungen=Decimal('300.00'),
        saldo=Decimal('900.00'))
    assert text == 'Hallo Anna Mieterin, Wohnung EG links.'


def test_unbekannte_platzhalter_bleiben_sichtbar_stehen():
    """Ein Platzhalter ohne Wert wird nicht still gelöscht: die Lücke schreit."""
    text = fuelle('Gruß an {mieter_name}, Frist {einwendungsfrist}.',
                  {'mieter_name': 'Anna Mieterin'})
    assert '{einwendungsfrist}' in text
    assert 'Anna Mieterin' in text


def test_die_aufforderung_steht_nur_bei_nachzahlung():
    """Bei einer Nachzahlung fordert der Satz den Betrag, beim Guthaben schweigt er."""
    kwargs = dict(
        mieter_name='Anna', wohnung_name='EG links', objekt_name='Haus',
        zeitraum='2025', gesamtsumme=Decimal('1200.00'),
        vorauszahlungen=Decimal('300.00'))
    nachzahlung = text_fuer(VORGABE, saldo=Decimal('900.00'), **kwargs)
    assert 'Bitte gleichen Sie den ausstehenden Betrag in Höhe von 900,00 € aus.' in nachzahlung

    guthaben = text_fuer(VORGABE, saldo=Decimal('-150.00'), **kwargs)
    assert 'Bitte gleichen' not in guthaben

    ausgeglichen = text_fuer(VORGABE, saldo=Decimal('0.00'), **kwargs)
    assert 'Bitte gleichen' not in ausgeglichen


def test_saldo_art_und_betrag_stehen_jedem_zur_verfuegung():
    """Die Platzhalter bleiben -- auch wenn die Vorgabe sie nicht mehr setzt.

    Phase 60: Der Vorgabetext nennt die drei Zahlen nicht mehr; der Block
    „Ihr Anteil an den Nebenkosten" auf demselben Blatt tut es, einmal und
    untereinander. Wer sie in einer **eigenen** Vorlage im Flusstext haben
    will, kann das weiter -- und genau das wird hier geprüft, damit das
    Streichen aus der Vorgabe die Platzhalter nicht stillschweigend
    mitnimmt.
    """
    eigene = '{saldo_art}: {saldo_betrag} von {gesamtsumme} minus {vorauszahlungen}'
    kwargs = dict(
        mieter_name='Anna', wohnung_name='EG links', objekt_name='Haus',
        zeitraum='2025', gesamtsumme=Decimal('1200.00'),
        vorauszahlungen=Decimal('300.00'))

    assert (text_fuer(eigene, saldo=Decimal('900.00'), **kwargs)
            == 'Nachzahlung: 900,00 € von 1.200,00 € minus 300,00 €')
    # Der Platzhalter traegt das Vorzeichen: ein Guthaben ist negativ.
    assert text_fuer(eigene, saldo=Decimal('-150.00'), **kwargs).startswith(
        'Guthaben: -150,00 €')
    assert text_fuer(eigene, saldo=Decimal('0.00'), **kwargs).startswith(
        'Ausgleich: 0,00 €')


def test_die_vorgabe_benutzt_nur_bekannte_platzhalter():
    """Der Vorgabetext kann nur Platzhalter tragen, die die Renderfunktion füllt."""
    assert re.findall(r'\{(\w+)\}', VORGABE), 'Der Vorgabetext trägt Platzhalter'
    for name in set(re.findall(r'\{(\w+)\}', VORGABE)):
        assert name in PLATZHALTER


def test_die_absaetze_bleiben_getrennt_und_werden_maskiert():
    """Leere Zeilen trennen Absätze; ``&`` stirbt nicht als XML-Stück."""
    stuecke = absaetze('Erster Absatz.\n\nZweiter & letzter.')
    assert stuecke == ['Erster Absatz.', 'Zweiter &amp; letzter.']
    # Eine gewollt leere Aufforderung hinterlässt keinen leeren Absatz.
    stuecke = absaetze('Vor der Lücke.\n\n\n\nNach der Lücke.')
    assert stuecke == ['Vor der Lücke.', 'Nach der Lücke.']


# --- Die Routen der Vorlage ---------------------------------------------------


def test_ohne_eigenen_text_antwortet_die_vorgabe(auth_client, app_ctx):
    """GET ohne Eintrag liefert den Vorgabetext samt Platzhalterliste."""
    from billing_factories import house

    objekt = house()
    from nebenkostenfix.models import db
    db.session.commit()

    antwort = auth_client.get(f'/api/properties/{objekt.id}/anschreiben')
    assert antwort.status_code == 200
    koerper = antwort.get_json()
    assert koerper['ist_vorgabe'] is True
    assert koerper['text'] == VORGABE
    assert koerper['platzhalter'] == PLATZHALTER


def test_der_vermieter_hinterlegt_und_ändert_seinen_text(auth_client, app_ctx):
    """PUT speichert je Objekt; GET liefert den eigenen Text zurück."""
    from billing_factories import house

    objekt = house()
    from nebenkostenfix.models import db
    db.session.commit()

    antwort = auth_client.put(
        f'/api/properties/{objekt.id}/anschreiben',
        json={'text': 'Liebe Anna, hier ist Ihre Abrechnung.'})
    assert antwort.status_code == 200
    assert antwort.get_json()['ist_vorgabe'] is False

    antwort = auth_client.get(f'/api/properties/{objekt.id}/anschreiben')
    koerper = antwort.get_json()
    assert koerper['ist_vorgabe'] is False
    assert koerper['text'] == 'Liebe Anna, hier ist Ihre Abrechnung.'

    # Ein zweites PUT ändert, statt zu verdoppeln: die Paarung ist einzigartig.
    auth_client.put(f'/api/properties/{objekt.id}/anschreiben',
                    json={'text': 'Und noch einmal.'})
    from nebenkostenfix.models import AnschreibenVorlage
    zeilen = AnschreibenVorlage.query.filter_by(property_id=objekt.id).all()
    assert len(zeilen) == 1
    assert zeilen[0].text == 'Und noch einmal.'


def test_die_leere_vorlage_wird_abgelehnt(auth_client, app_ctx):
    """Ohne Text gibt es nichts zu sagen: die Route lehnt ab."""
    from billing_factories import house

    objekt = house()
    from nebenkostenfix.models import db
    db.session.commit()

    for text in ('', '   '):
        antwort = auth_client.put(
            f'/api/properties/{objekt.id}/anschreiben', json={'text': text})
        assert antwort.status_code == 400


def test_loeschen_fuehrt_zurueck_zur_vorgabe(auth_client, app_ctx):
    """DELETE wirft den eigenen Text weg; danach spricht wieder die Vorgabe."""
    from billing_factories import house

    objekt = house()
    from nebenkostenfix.models import db
    db.session.commit()

    auth_client.put(f'/api/properties/{objekt.id}/anschreiben',
                    json={'text': 'Mein Text.'})
    antwort = auth_client.delete(f'/api/properties/{objekt.id}/anschreiben')
    assert antwort.status_code == 200
    koerper = antwort.get_json()
    assert koerper['ist_vorgabe'] is True
    assert koerper['text'] == VORGABE


def test_ein_unbekanntes_objekt_wird_abgewiesen(auth_client):
    antwort = auth_client.get('/api/properties/424242/anschreiben')
    assert antwort.status_code == 404


# --- Die Einbindung ins PDF ---------------------------------------------------


def _deckblatt(unkomprimiert, anschreiben=None) -> str:
    """Das Deckblatt als geklebten Text, wie der Leser es sieht."""
    elemente = build_cover_page_elements(
        property_name='Haus am Anger', apartment_name='EG links',
        tenant_name='Anna Mieterin', start_date='2025-01-01',
        end_date='2025-12-31', total_amount=Decimal('1200.00'),
        prepaid_amount=Decimal('300.00'), balance=Decimal('900.00'),
        anschreiben=anschreiben)
    from reportlab.platypus import SimpleDocTemplate
    from reportlab.lib.pagesizes import A4
    from io import BytesIO

    puffer = BytesIO()
    doc = SimpleDocTemplate(puffer, pagesize=A4)
    doc.build(elemente)
    pdf = puffer.getvalue()
    # NK-249: das Deckblatt bleibt ein Blatt, auch mit dem Vorgabetext; der
    # Umbruch am Ende zählt nicht als eigene Seite.
    assert len(re.findall(rb'/Type /Page(?![sA-Za-z])', pdf)) == 1
    return _blaetter(pdf)[0]


def test_die_vorlage_spricht_auf_dem_deckblatt(unkomprimiert):
    """Mit Vorlage steht das Anschreiben statt des festen Grußes."""
    anschreiben = text_fuer(
        VORGABE, mieter_name='Anna Mieterin', wohnung_name='EG links',
        objekt_name='Haus am Anger', zeitraum='01.01.2025 bis 31.12.2025',
        gesamtsumme=Decimal('1200.00'), vorauszahlungen=Decimal('300.00'),
        saldo=Decimal('900.00'))
    blatt = _deckblatt(unkomprimiert, anschreiben)

    assert 'GutenTagAnnaMieterin,' in blatt and 'geehrte' not in blatt
    assert 'fürdieWohnungEGlinksfürdenZeitraum01.01.2025bis31.12.2025' in blatt
    assert 'BittegleichenSiedenausstehendenBetraginHöhevon900,00€aus.' in blatt
    # Phase 60: Die drei Zahlen stehen im Block, nicht noch einmal im Satz
    # darüber. „Zweimal dasselbe hintereinander" (Durchsicht, 2026-10-21).
    assert 'DieAbrechnungergibtbeiGesamtkosten' not in blatt
    assert 'IhreNebenkosten:1.200,00€' in blatt
    assert 'IhreVorauszahlungen:-300,00€' in blatt
    # Der feste Gruß der Software ist verdrängt. Phase 60: Er lautet jetzt
    # „Die Einzelheiten entnehmen Sie bitte den folgenden Seiten" (Wortlaut
    # der Vorlage aus Issue #35); geprüft ist weiter, dass er schweigt,
    # wenn der Vermieter selbst schreibt.
    assert 'Einzelheiten' not in blatt
    # NK-249: das Ergebnis steht einmal. Phase 60: Der Block der Vorlage
    # beschriftet es „Nachzahlung:" (vorher „Ihre Nachzahlung"). Dass das
    # Anschreiben des Vermieters das Wort in seinem eigenen Satz nochmal
    # verwendet, ist seine Sache -- gezählt wird **unser** Block.
    assert blatt.count('Nachzahlung:') == 1


def test_ohne_vorlage_bleibt_es_beim_festen_gruß(unkomprimiert):
    """Kein Anschreiben hinterlegt: der Deckblatt-Gruß wie bisher."""
    blatt = _deckblatt(unkomprimiert)
    assert 'GutenTagAnnaMieterin,' in blatt and 'geehrte' not in blatt
    assert 'Einzelheiten' in blatt


# --- Die Welt: vom Vermieter bis zum Blatt des Mieters ------------------------


def _welt(app_ctx):
    """Zwei Mieter mit Wasserzählern, eine Rechnung, Vorauszahlung für A.

    Dieselbe Welt wie in ``test_versionierung.py``: Annas Abrechnung
    ergibt 1200,00 € bei 300,00 € Vorauszahlung -- eine Nachzahlung von
    900,00 €, genau der Fall, in dem das Anschreiben fordert.
    """
    from nebenkostenfix.models import db
    from billing_factories import (
        apt, category, house, meter, payment, profile, reading, tenant,
    )

    kategorie = category('Wasserversorgung')
    prop = house()
    wohnung_a = apt(prop, 'EG links', 50.0)
    wohnung_b = apt(prop, 'EG rechts', 50.0)
    mieter_a = tenant(wohnung_a, 'Anna Mieterin', move_in=date(2024, 1, 1))
    mieter_b = tenant(wohnung_b, 'Berta Mieterin', move_in=date(2024, 1, 1))
    profile(mieter_a, kategorie, 'direkt')
    profile(mieter_b, kategorie, 'direkt')
    zaehler_a = meter(prop, kategorie, 'WA-A', is_main=False, apartment=wohnung_a)
    zaehler_b = meter(prop, kategorie, 'WA-B', is_main=False, apartment=wohnung_b)
    reading(zaehler_a, date(2025, 1, 1), 0.0)
    lese_ende = reading(zaehler_a, date(2025, 12, 31), 1000.0)
    reading(zaehler_b, date(2025, 1, 1), 0.0)
    reading(zaehler_b, date(2025, 12, 31), 1000.0)
    from billing_factories import invoice
    invoice(prop, kategorie, 2400.0, date(2025, 1, 1), date(2025, 12, 31))
    payment(mieter_a, 300.0, date(2025, 6, 1))
    db.session.commit()
    return mieter_a.id, prop.id, lese_ende.id


def _finalisiere(auth_client, mieter_id):
    """Finalisiert Annas Abrechnung und liefert den Bericht."""
    from nebenkostenfix.models import TenantBillingReport

    antwort = auth_client.post('/api/billing/finalize', json={
        'tenant_id': mieter_id, **ZEITRAUM})
    assert antwort.status_code == 201, antwort.get_data(as_text=True)
    return TenantBillingReport.query.one()


def test_die_festsetzung_druckt_das_anschreiben_des_objekts(
        auth_client, app_ctx, unkomprimiert):
    """Das gespeicherte PDF trägt das Anschreiben -- mit den Zahlen dieses Laufs."""
    mieter_id, objekt_id, _ = _welt(app_ctx)

    auth_client.put(
        f'/api/properties/{objekt_id}/anschreiben',
        json={'text': 'Liebe/r {mieter_name},\n\n'
                      'Ihre Abrechnung für {zeitraum} liegt bei. '
                      '{aufforderung}\n\nIhr Vermieter'})
    report = _finalisiere(auth_client, mieter_id)

    pdf = (Path(os.environ['NAS_MOUNT_PATH']) / report.document_path).read_bytes()
    blatt = _geklebt(pdf)
    assert 'Liebe/rAnnaMieterin,' in blatt
    assert 'IhreAbrechnungfür01.01.2025bis31.12.2025liegtbei.' in blatt
    assert 'BittegleichenSiedenausstehendenBetraginHöhevon900,00€aus.' in blatt
    assert 'IhrVermieter' in blatt
    # Der Platzhalter der Aufforderung ist gefüllt, nicht sichtbar stehen
    # geblieben -- bei einer Nachzahlung gibt es etwas zu fordern.
    assert '{aufforderung}' not in blatt


def test_ohne_eigene_vorlage_druckt_die_vorgabe(auth_client, app_ctx, unkomprimiert):
    """Ohne PUT spricht der Vorgabetext -- und die Zahlen stehen einmal.

    Phase 60: Vorher nannte der Vorgabetext Gesamtkosten, Vorauszahlungen
    und Saldo im Flusstext, und der Block „Ihr Anteil an den Nebenkosten"
    direkt darunter dieselben drei noch einmal. Jetzt steht jede Zahl
    genau einmal -- im Block, beschriftet und untereinander.
    """
    mieter_id, _, _ = _welt(app_ctx)
    report = _finalisiere(auth_client, mieter_id)

    pdf = (Path(os.environ['NAS_MOUNT_PATH']) / report.document_path).read_bytes()
    blatt = _geklebt(pdf)
    assert 'GutenTagAnnaMieterin,' in blatt and 'geehrte' not in blatt
    assert 'WohnungEGlinks' in blatt
    assert 'BittegleichenSiedenausstehendenBetraginHöhevon900,00€aus.' in blatt

    assert 'IhreNebenkosten:1.200,00€' in blatt
    assert 'IhreVorauszahlungen:-300,00€' in blatt
    assert 'Nachzahlung:900,00€' in blatt
    assert 'Gesamtkostenvon1.200,00€' not in blatt
    assert 'einenSaldoinHöhevon' not in blatt


def test_die_korrektur_wickelt_dieselbe_vorlage(auth_client, app_ctx, unkomprimiert):
    """Die Korrektur liest die Vorlage neu; der eigene Text steht auch dann."""
    mieter_id, objekt_id, lese_id = _welt(app_ctx)
    report = _finalisiere(auth_client, mieter_id)
    alte_id = report.id

    auth_client.put(
        f'/api/properties/{objekt_id}/anschreiben',
        json={'text': 'Korrigierter Gruß an {mieter_name}.'})

    # Ohne geaenderte Eingaben waere die Korrektur nur eine Kopie (D-59);
    # ein geaenderter Zaehlerstand aendert das Ergebnis und macht den Lauf echt.
    from nebenkostenfix.models import db, MeterReading, TenantBillingReport
    lese_ende = db.session.get(MeterReading, lese_id)
    lese_ende.value = 800.0
    db.session.commit()

    antwort = auth_client.post(f'/api/billing/reports/{alte_id}/korrektur')
    assert antwort.status_code == 201, antwort.get_data(as_text=True)

    frisch = db.session.get(TenantBillingReport, alte_id)
    # Seit NK-131 neutral benannt (belege_export nennt die Fassung).
    assert re.match(r'^\d{4}/[0-9a-f]{32}\.pdf$', frisch.document_path)
    pdf = (Path(os.environ['NAS_MOUNT_PATH']) / frisch.document_path).read_bytes()
    blatt = _geklebt(pdf)
    assert 'KorrigierterGrußanAnnaMieterin.' in blatt


def test_anrede_steht_an_einer_stelle():
    """NK-247: neutral statt „Sehr geehrte/r“, für Vorlage und Deckblatt gleich."""
    from nebenkostenfix import anschreiben, pdf_cover_page
    # NK-264: die Anrede ist ein Platzhalter, gefüllt aus anrede().
    assert anschreiben.VORGABE.startswith('{anrede}')
    assert anschreiben.anrede('Anna Mieterin') == 'Guten Tag Anna Mieterin,'
    quelle = Path(pdf_cover_page.__file__).read_text(encoding='utf-8')
    assert 'geehrte' not in quelle and 'anrede(' in quelle


# ich/wir als ganze Wörter; „Ihnen“/„Sie“ an den Mieter bleiben erlaubt.
ICH_WIR = re.compile(r'\b(ich|mir|mich|mein\w*|wir|uns|unser\w*)\b', re.IGNORECASE)


def test_die_vorgabe_spricht_ohne_ich_und_wir():
    """NK-248: die festen Sätze sagen weder „ich“ noch „wir“ (bis NK-264 wählt)."""
    text = text_fuer(VORGABE, mieter_name='Anna', wohnung_name='EG links',
                     objekt_name='Haus', zeitraum='2025',
                     gesamtsumme=Decimal('1200.00'),
                     vorauszahlungen=Decimal('300.00'), saldo=Decimal('900.00'))
    assert 'Bitte gleichen Sie den ausstehenden Betrag' in text
    assert ICH_WIR.findall(text) == []


# --- Review 0.17.0: Anschriften im Anschreiben, Hinweis ohne Zustelladresse ---


def test_die_anschriften_platzhalter_werden_im_pdf_gefuellt(
        auth_client, app_ctx, unkomprimiert):
    """A5: Die Vorlage bietet {mieter_anschrift} und {vermieter_anschrift}
    an, ``_anschreiben_fuer`` reichte sie nicht durch -- im Brief stand der
    Platzhalter wörtlich."""
    from nebenkostenfix.models import Tenant, Vermieterdaten, db

    mieter_id, objekt_id, _ = _welt(app_ctx)
    db.session.get(Tenant, mieter_id).anschrift = 'Am Anger 1\n12345 Musterstadt'
    db.session.add(Vermieterdaten(anschrift='Vermieterweg 2\n54321 Beispielort'))
    db.session.commit()
    auth_client.put(
        f'/api/properties/{objekt_id}/anschreiben',
        json={'text': 'An {mieter_anschrift}.\n\nVon {vermieter_anschrift}.'})

    report = _finalisiere(auth_client, mieter_id)

    blatt = _geklebt((Path(os.environ['NAS_MOUNT_PATH'])
                      / report.document_path).read_bytes())
    assert '{mieter_anschrift}' not in blatt
    assert '{vermieter_anschrift}' not in blatt
    assert 'AnAmAnger1' in blatt
    assert 'VonVermieterweg2' in blatt


def _vorschau(auth_client, mieter_id):
    antwort = auth_client.post('/api/billing/generate', json={
        'tenant_id': mieter_id, **ZEITRAUM})
    assert antwort.status_code == 200, antwort.get_data(as_text=True)
    return antwort.get_json()['warnings']


def test_ausgezogen_ohne_zustelladresse_warnt_die_vorschau(auth_client, app_ctx):
    """A2: ``zustellhinweis`` war gebaut, aber nirgends verdrahtet. Die
    Release-Notizen versprechen: „die App weist darauf hin“."""
    from nebenkostenfix.anschrift import HINWEIS_OHNE_ZUSTELLUNG
    from nebenkostenfix.models import Tenant, db

    mieter_id, _, _ = _welt(app_ctx)
    mieter = db.session.get(Tenant, mieter_id)
    mieter.move_out_date = date(2025, 12, 31)
    mieter.anschrift = 'Am Anger 1\n12345 Musterstadt'
    db.session.commit()

    assert HINWEIS_OHNE_ZUSTELLUNG in _vorschau(auth_client, mieter_id)

    mieter.zustellanschrift = 'Neue Straße 5\n12345 Musterstadt'
    db.session.commit()
    assert HINWEIS_OHNE_ZUSTELLUNG not in _vorschau(auth_client, mieter_id)


def test_wer_noch_wohnt_bekommt_keinen_zustellhinweis(auth_client, app_ctx):
    from nebenkostenfix.anschrift import HINWEIS_OHNE_ZUSTELLUNG

    mieter_id, _, _ = _welt(app_ctx)
    assert HINWEIS_OHNE_ZUSTELLUNG not in _vorschau(auth_client, mieter_id)
