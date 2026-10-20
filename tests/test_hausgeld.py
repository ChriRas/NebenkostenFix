"""Phase 50: die Hausgeld-Einzelabrechnung als Quelle (Live-Issue #30).

Der Vermieter einer Eigentumswohnung bekommt vom Verwalter eine
Einzelabrechnung und muss daraus die Betriebskostenabrechnung fuer seinen
Mieter machen. Zwei Dinge gehen dabei regelmaessig schief:

1. **Er gibt Positionen weiter, die er nicht weitergeben darf.** Die
   Hausgeldabrechnung enthaelt Verwaltervergütung, Erhaltungsrücklage und
   Instandhaltung -- nach § 1 Abs. 2 BetrKV gehoeren die dem Eigentuemer,
   nicht dem Mieter. Wer sie mit umlegt, hat eine angreifbare Abrechnung.
2. **Er uebernimmt den eigenen Betrag ungeprueft.** Ein Verwalterfehler
   wandert dann unbemerkt in die Mieterabrechnung weiter.

Dieses Modul rechnet beides nach. Es entscheidet nichts allein: der
Vermieter bestaetigt jede Position (R-KAT-01, Plan Phase 50).

Die Positionsnamen sind die echten aus Issue #30. Die Zahlen sind mit der
Hand nachgerechnet und stehen in den Docstrings. Ohne Datenbank.
"""

from decimal import Decimal

import pytest

from nebenkostenfix import hausgeld


# --- Die Prueffrage: stimmt der eigene Betrag? -----------------------------


def test_der_eigene_betrag_wird_nachgerechnet():
    """2.400,00 € Müll, mein Anteil 125 von 1.000 MEA → 300,00 €."""
    probe = hausgeld.pruefe_position(
        gesamtbetrag='2400.00', eigener_anteil='125', gesamtanteile='1000',
        eigener_betrag='300.00')

    assert probe.erwartet == Decimal('300.00')
    assert probe.abweichung == Decimal('0.00')
    assert probe.stimmt is True


def test_eine_abweichung_unter_einem_euro_bleibt_still():
    """Rundung des Verwalters: 300,49 statt 300,00 — kein Hinweis.

    Jeder Verwalter rundet anders, und die Summe muss am Ende aufgehen.
    Unter einem Euro ist das Rundung und kein Fehler (Plan Phase 50).
    """
    probe = hausgeld.pruefe_position(
        gesamtbetrag='2400.00', eigener_anteil='125', gesamtanteile='1000',
        eigener_betrag='300.49')

    assert probe.abweichung == Decimal('0.49')
    assert probe.stimmt is True
    assert probe.hinweis is None


def test_eine_abweichung_ueber_einem_euro_wird_gezeigt():
    """312,00 statt 300,00 — zwölf Euro sind keine Rundung."""
    probe = hausgeld.pruefe_position(
        gesamtbetrag='2400.00', eigener_anteil='125', gesamtanteile='1000',
        eigener_betrag='312.00')

    assert probe.abweichung == Decimal('12.00')
    assert probe.stimmt is False
    assert '300,00' in probe.hinweis and '312,00' in probe.hinweis


def test_die_grenze_selbst_gilt_als_rundung():
    """Genau 1,00 € ist noch still, 1,01 € nicht mehr."""
    gleich = hausgeld.pruefe_position(
        gesamtbetrag='2400.00', eigener_anteil='125', gesamtanteile='1000',
        eigener_betrag='301.00')
    darueber = hausgeld.pruefe_position(
        gesamtbetrag='2400.00', eigener_anteil='125', gesamtanteile='1000',
        eigener_betrag='301.01')

    assert gleich.stimmt is True
    assert darueber.stimmt is False


def test_ein_anteil_von_null_ist_keine_rechnung():
    """Ohne Gesamtanteile gibt es keinen Anteil -- und keine stille Null."""
    with pytest.raises(hausgeld.HausgeldFehler) as fehler:
        hausgeld.pruefe_position(
            gesamtbetrag='2400.00', eigener_anteil='125', gesamtanteile='0',
            eigener_betrag='300.00')

    assert 'Gesamtanteile' in str(fehler.value)


def test_ein_eigener_anteil_ueber_den_gesamtanteilen_wird_abgewiesen():
    """Wer mehr Anteile hat als die Gemeinschaft, hat sich verlesen."""
    with pytest.raises(hausgeld.HausgeldFehler):
        hausgeld.pruefe_position(
            gesamtbetrag='2400.00', eigener_anteil='1200',
            gesamtanteile='1000', eigener_betrag='300.00')


def test_der_dritte_cent_wird_nicht_verschluckt():
    """100,00 € auf 3 von 7 Anteilen = 42,857… → 42,86 € kaufmännisch."""
    probe = hausgeld.pruefe_position(
        gesamtbetrag='100.00', eigener_anteil='3', gesamtanteile='7',
        eigener_betrag='42.86')

    assert probe.erwartet == Decimal('42.86')
    assert probe.stimmt is True


# --- Die Summenprobe ------------------------------------------------------


def test_die_summe_der_positionen_muss_die_abrechnung_ergeben():
    """Die Einzelabrechnung nennt eine Endsumme -- die muss aufgehen."""
    probe = hausgeld.pruefe_summe(
        ['300.00', '120.50', '80.00'], abrechnungssumme='500.50')

    assert probe.erwartet == Decimal('500.50')
    assert probe.stimmt is True


def test_eine_fehlende_position_fliegt_in_der_summenprobe_auf():
    """Der haeufigste Uebertragungsfehler: eine Zeile vergessen."""
    probe = hausgeld.pruefe_summe(
        ['300.00', '120.50'], abrechnungssumme='500.50')

    assert probe.abweichung == Decimal('80.00')
    assert probe.stimmt is False
    assert '80,00' in probe.hinweis


# --- Die Umlagefaehigkeit je Position -------------------------------------


@pytest.mark.parametrize('name, nummer', [
    ('Müllentsorgung', 8),
    ('Straßenreinigungsgeb.', 8),
    ('Frischwasser', 2),
    ('Hausstrom', 11),
    ('Versicherungen', 13),
    ('Kaminkehrer', 12),
    ('Hausmeister/-reinigung', 14),
    ('Pflege d. Außenanlage', 10),
])
def test_die_echten_positionen_sind_umlagefaehig(name, nummer):
    """Die acht Positionen aus Issue #30 -- jede mit ihrer Nummer."""
    rat = hausgeld.einschaetzung(name)

    assert rat.umlagefaehig is True
    assert rat.betrkv_nr == nummer


@pytest.mark.parametrize('name, wort', [
    ('Verwaltervergütung', '§ 1 Abs. 2'),
    ('Verwaltergebühr', '§ 1 Abs. 2'),
    ('Zuführung Erhaltungsrücklage', '§ 1 Abs. 2'),
    ('Instandhaltungsrücklage', '§ 1 Abs. 2'),
    ('Instandsetzung Dach', '§ 1 Abs. 2'),
    ('Reparatur Aufzugstür', '§ 1 Abs. 2'),
    ('Kontoführungsgebühren', '§ 1 Abs. 2'),
    ('Kosten der Eigentümerversammlung', '§ 1 Abs. 2'),
    ('Rechtsberatung', '§ 1 Abs. 2'),
    ('Bankgebühren', '§ 1 Abs. 2'),
    ('Mahngebühren', '§ 1 Abs. 2'),
    ('Jahresabschlussprüfung', '§ 1 Abs. 2'),
])
def test_die_eigentuemerpositionen_sind_nicht_umlagefaehig(name, wort):
    """§ 1 Abs. 2 BetrKV: das traegt der Eigentuemer, nicht der Mieter.

    Diese Positionen stehen in jeder Hausgeldabrechnung und in keiner
    Betriebskostenabrechnung. Die App sagt nicht nur "unbekannt", sondern
    nennt den Grund -- sonst legt der Vermieter sie unter Nr. 17 an.
    """
    rat = hausgeld.einschaetzung(name)

    assert rat.umlagefaehig is False
    assert rat.betrkv_nr is None
    assert wort in rat.begruendung


@pytest.mark.parametrize('name', [
    'Bankgebühren',
    'Bankspesen',
    'Mahnkosten',
    'Mahngebühren Hausgeld',
    'Jahresabschlussprüfung',
    'Abschlussprüfung WEG',
])
def test_verwaltungsnahe_posten_raten_nicht_zur_nummer_17(name):
    """Bank-, Mahn- und Abschlusskosten sind gesperrt, nicht offen.

    Der Unterschied ist der Rat, den der Vermieter bekommt. Eine **offene**
    Position heisst "umlagefaehig nur, wenn der Mietvertrag sie nennt --
    dann unter Nr. 17". Fuer diese drei waere das falsch: sie sind nach
    § 1 Abs. 2 BetrKV Verwaltungs- bzw. Rechtsverfolgungskosten und bleiben
    auch mit Mietvertrag beim Eigentuemer. Der Vermieter wuerde sonst auf
    einen Weg geschickt, der nicht traegt.
    """
    rat = hausgeld.einschaetzung(name)

    assert rat.umlagefaehig is False
    assert rat.betrkv_nr is None
    assert 'Nr. 17' not in rat.begruendung


def test_ein_unbekannter_name_bleibt_offen():
    """Weder Katalog noch Sperrliste: der Vermieter entscheidet.

    "Fußmatten" ist der Grenzfall aus Issue #30 -- umlagefaehig nur, wenn
    der Mietvertrag es hergibt (R-KAT-02, Nr. 17).
    """
    rat = hausgeld.einschaetzung('Fußmatten')

    assert rat.umlagefaehig is None
    assert rat.betrkv_nr is None
    assert 'Mietvertrag' in rat.begruendung


def test_die_sperrliste_schlaegt_den_katalog():
    """"Hausmeister-Reparaturen" ist beides -- die Sperre gewinnt.

    Ein Name, der auf eine umlagefaehige Nummer deutet und zugleich eine
    Eigentuemerposition nennt, ist nicht umlagefaehig: die Reparatur bleibt
    Instandsetzung, auch wenn der Hausmeister sie macht.
    """
    rat = hausgeld.einschaetzung('Hausmeister-Reparaturen')

    assert rat.umlagefaehig is False
    assert '§ 1 Abs. 2' in rat.begruendung


def test_ein_leerer_name_bleibt_offen():
    """Kein Name, keine Einschaetzung -- und kein Absturz."""
    for leer in (None, '', '   '):
        rat = hausgeld.einschaetzung(leer)
        assert rat.umlagefaehig is None


# --- Der ganze Weg: eine Abrechnung durchrechnen --------------------------


#: Eine Hausgeldabrechnung, wie sie ankommt: die acht umlagefaehigen
#: Positionen aus Issue #30 plus drei, die beim Eigentuemer bleiben.
#: MEA 125 von 1.000. Die eigenen Betraege sind Gesamtbetrag · 0,125.
ABRECHNUNG = [
    ('Müllentsorgung', '2400.00', '300.00'),
    ('Straßenreinigungsgeb.', '800.00', '100.00'),
    ('Frischwasser', '4800.00', '600.00'),
    ('Hausstrom', '1600.00', '200.00'),
    ('Versicherungen', '3200.00', '400.00'),
    ('Kaminkehrer', '480.00', '60.00'),
    ('Hausmeister/-reinigung', '7200.00', '900.00'),
    ('Pflege d. Außenanlage', '2000.00', '250.00'),
    ('Verwaltervergütung', '6000.00', '750.00'),
    ('Zuführung Erhaltungsrücklage', '12000.00', '1500.00'),
    ('Instandsetzung Dach', '4000.00', '500.00'),
]


def test_die_abrechnung_trennt_sich_in_zwei_summen():
    """Umlagefähig 2.810,00 €, beim Eigentümer 2.750,00 €.

    Die acht: 300 + 100 + 600 + 200 + 400 + 60 + 900 + 250 = 2.810,00.
    Die drei: 750 + 1.500 + 500 = 2.750,00. Zusammen 5.560,00 — die
    Endsumme der Einzelabrechnung.

    **Das ist der Wert dieser Phase in einer Zahl:** wer die Abrechnung
    ungeprüft übernimmt, legt 2.750,00 € um, die er nicht umlegen darf.
    """
    bericht = hausgeld.uebernahme(
        [{'name': n, 'gesamtbetrag': g, 'eigener_betrag': e}
         for n, g, e in ABRECHNUNG],
        eigener_anteil='125', gesamtanteile='1000',
        abrechnungssumme='5560.00')

    assert bericht.summe_umlagefaehig == Decimal('2810.00')
    assert bericht.summe_eigentuemer == Decimal('2750.00')
    assert bericht.summenprobe.stimmt is True
    assert len(bericht.umlagefaehig) == 8
    assert len(bericht.beim_eigentuemer) == 3
    assert bericht.offen == []


def test_jede_position_wird_dabei_nachgerechnet():
    """Ein Verwalterfehler in einer Zeile faellt auf, die anderen bleiben still."""
    mit_fehler = [dict(name=n, gesamtbetrag=g, eigener_betrag=e)
                  for n, g, e in ABRECHNUNG]
    mit_fehler[2]['eigener_betrag'] = '660.00'   # 600,00 wäre richtig

    bericht = hausgeld.uebernahme(
        mit_fehler, eigener_anteil='125', gesamtanteile='1000')

    falsch = [p for p in bericht.positionen if not p.probe.stimmt]
    assert [p.name for p in falsch] == ['Frischwasser']
    assert falsch[0].probe.abweichung == Decimal('60.00')


def test_eine_unbekannte_position_landet_bei_den_offenen():
    """Nichts wird stillschweigend einsortiert -- der Vermieter entscheidet."""
    bericht = hausgeld.uebernahme(
        [{'name': 'Fußmatten', 'gesamtbetrag': '400.00',
          'eigener_betrag': '50.00'}],
        eigener_anteil='125', gesamtanteile='1000')

    assert [p.name for p in bericht.offen] == ['Fußmatten']
    assert bericht.summe_umlagefaehig == Decimal('0.00')
    assert bericht.summe_eigentuemer == Decimal('0.00')


def test_ohne_endsumme_gibt_es_keine_summenprobe():
    """Nicht jede Abrechnung nennt eine Endsumme -- dann entfaellt die Probe."""
    bericht = hausgeld.uebernahme(
        [{'name': 'Müllentsorgung', 'gesamtbetrag': '2400.00',
          'eigener_betrag': '300.00'}],
        eigener_anteil='125', gesamtanteile='1000')

    assert bericht.summenprobe is None


def test_eine_leere_abrechnung_ist_kein_absturz():
    bericht = hausgeld.uebernahme([], eigener_anteil='1', gesamtanteile='1')

    assert bericht.positionen == []
    assert bericht.summe_umlagefaehig == Decimal('0.00')


# --- Die Route ------------------------------------------------------------


def test_die_route_rechnet_die_abrechnung_durch(auth_client):
    """POST /api/hausgeld/pruefen -- rechnet und speichert nichts."""
    antwort = auth_client.post('/api/hausgeld/pruefen', json={
        'positionen': [{'name': n, 'gesamtbetrag': g, 'eigener_betrag': e}
                       for n, g, e in ABRECHNUNG],
        'eigener_anteil': '125', 'gesamtanteile': '1000',
        'abrechnungssumme': '5560.00'})

    assert antwort.status_code == 200
    daten = antwort.get_json()
    assert daten['summe_umlagefaehig'] == '2810.00'
    assert daten['summe_eigentuemer'] == '2750.00'
    assert daten['anzahl_umlagefaehig'] == 8
    assert daten['anzahl_eigentuemer'] == 3
    assert daten['summenprobe']['stimmt'] is True
    assert 'VIII ZR 27/07' in daten['zeitraum_hinweis']
    # Der Weg fuer die Heizkosten steht dabei: eine Rechnung, die der
    # Wohnung zugeordnet ist. Ohne die Zuordnung verteilt der Kern sie
    # nach Flaeche auf alle Wohnungen -- ohne Fehlermeldung.
    assert 'ordnen Sie' in daten['heizkosten_hinweis']
    assert 'Wohnfläche' in daten['heizkosten_hinweis']

    # Jede Zeile traegt ihre Begruendung mit -- die Oberflaeche erfindet
    # keine Texte dazu.
    verwaltung = next(p for p in daten['positionen']
                      if p['name'] == 'Verwaltervergütung')
    assert verwaltung['umlagefaehig'] is False
    assert '§ 1 Abs. 2 BetrKV' in verwaltung['begruendung']


def test_die_route_weist_eine_unbrauchbare_angabe_ab(auth_client):
    """Gesamtanteile 0 -- kein stilles Ergebnis, sondern 400 mit Grund."""
    antwort = auth_client.post('/api/hausgeld/pruefen', json={
        'positionen': [{'name': 'Müllentsorgung', 'gesamtbetrag': '2400.00',
                        'eigener_betrag': '300.00'}],
        'eigener_anteil': '125', 'gesamtanteile': '0'})

    assert antwort.status_code == 400
    assert 'Gesamtanteile' in antwort.get_json()['error']


def test_die_route_braucht_positionen(auth_client):
    antwort = auth_client.post('/api/hausgeld/pruefen', json={
        'eigener_anteil': '125', 'gesamtanteile': '1000'})

    assert antwort.status_code == 400
    assert antwort.get_json()['feld'] == 'positionen'


def test_die_route_aendert_nichts_am_bestand(auth_client):
    """Die Pruefung ist eine Rechnung, keine Uebernahme.

    Haette sie Kostenarten oder Rechnungen angelegt, waere der Bestand
    nach zwei Proben voller Dubletten -- der Vermieter uebernimmt von Hand,
    was er bestaetigt hat.
    """
    vorher = auth_client.get('/api/categories').get_json()
    auth_client.post('/api/hausgeld/pruefen', json={
        'positionen': [{'name': 'Fußmatten', 'gesamtbetrag': '400.00',
                        'eigener_betrag': '50.00'}],
        'eigener_anteil': '125', 'gesamtanteile': '1000'})

    assert auth_client.get('/api/categories').get_json() == vorher
