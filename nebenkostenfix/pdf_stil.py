"""Ein Satz Marken und Bausteine für das ganze PDF (Phase 60).

Bis 0.16.0 hatte dasselbe Dokument **zwei Designsprachen**: Deckblatt und
Übersichtsblatt hell mit grauen Tabellenköpfen, der Detailteil mit violetten
Vollbalken als Rubriküberschriften. Wer beides sieht, hält es für zwei
Dokumente. Dazu kamen Abstände, die jede Datei für sich erfunden hat -- 30 pt
hier, 40 dort, 10 dazwischen -- und die sich als Löcher lesen, nicht als Ruhe.

Hier steht deshalb **alles einmal**: Farben, Schriftgrade, ein Abstandsraster
und die Bausteine, aus denen die drei Teile gebaut werden. Wer einen Abstand
ändert, ändert ihn für das ganze Dokument; wer eine Farbe sucht, findet sie
an einer Stelle.

**Die Vorlage** ist der Anhang aus Live-Issue #35. Sie ist radikal schlicht:
keine Kästen, keine Farbbalken, die Summen rechtsbündig. Genau das meint
der Melder mit „Verschlankung" -- und es ist auch das, was ein Brief an
einen Mieter sein soll: lesbar, nicht dekoriert.

Gebaut waren drei Entwürfe, zur Auswahl. Der Herausgeber hat am 2026-10-21 den
ruhigsten genommen: **nur Haarlinien und Fettung, keine Flächen.** Die
beiden anderen sind gelöscht -- eine Wahl, die niemand mehr trifft, ist
keine Wahl, sondern toter Code mit einem Schalter davor.
"""

from __future__ import annotations

from dataclasses import dataclass

from nebenkostenfix.geld import text as _geld_text
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle
# Bandit-Ausnahme: maskiert Text fuer reportlab, parst kein XML
from xml.sax.saxutils import escape  # nosec B406

#: Das Abstandsraster. Jeder senkrechte Abstand im Dokument ist einer davon.
#: Ohne Raster wählt jede Stelle ihren eigenen Wert, und das Blatt bekommt
#: Löcher an Stellen, an denen niemand eine Pause gemeint hat.
XS, S, M, L, XL, XXL = 4, 8, 12, 18, 24, 36

#: Die Breite des Satzspiegels: A4 (595,28) minus zweimal Rand (56,7)
#: minus zweimal Rahmenpolster (6). Die sechs Punkte Polster sind der Grund,
#: warum eine 482 pt breite Tabelle 6 pt **links aus dem Satz ragte** und
#: nicht mehr unter ihrer Ueberschrift stand -- reportlab zentriert eine zu
#: breite Tabelle im Rahmen, statt sie zu beschneiden. Die Summe der
#: Spaltenbreiten jeder Tabelle muss hier hineinpassen.
SATZBREITE = 470


@dataclass(frozen=True)
class Stil:
    """Die Werte eines Erscheinungsbilds. Struktur steckt nie hier drin."""

    name: str
    #: Hintergrund der Tabellenkopfzeile; None heißt „keine Fläche".
    kopf_flaeche: colors.Color | None
    kopf_schrift: colors.Color
    #: Tönung jeder zweiten Zeile; None heißt „kein Zebra".
    zebra: colors.Color | None
    #: Hintergrund des Summenblocks; None heißt „keine Fläche".
    summen_flaeche: colors.Color | None
    #: Die Fläche eines echten Kastens -- GiroCode, Zählernachweis. Das ist
    #: kein Schmuck: Beide sind abgesetzte Blöcke mit eigener Aufgabe, und
    #: ohne Fläche verlieren sie ihre Grenze. Deshalb bleibt sie, auch wo
    #: Tabellen keine Flächen tragen.
    flaeche: colors.Color
    linie: colors.Color
    text: colors.Color
    leise: colors.Color
    guthaben: colors.Color
    nachzahlung: colors.Color


#: Das Erscheinungsbild des Dokuments. Der Herausgeber hat am 2026-10-21 aus drei
#: gebauten Entwürfen -- Vorlage (dunkler Tabellenkopf), Marke (Hausfarbe)
#: und diesem -- den ruhigen gewählt: **keine Flächen, nur Haarlinien und
#: Fettung.** Die beiden anderen sind deshalb gelöscht und nicht als
#: ungenutzte Wahlmöglichkeit stehen geblieben; ein Dokument hat ein
#: Erscheinungsbild, und wer es ändert, ändert es hier.
#:
#: Keine Farbe ist erfunden: jede steht als Token in `static/style.css`
#: (`tests/test_design_einheit.py` hält das fest).
STIL = Stil(
    name='ruhig',
    kopf_flaeche=None,
    kopf_schrift=colors.HexColor('#17182B'),      # --text-main
    zebra=None,
    summen_flaeche=None,
    flaeche=colors.HexColor('#FAFAFB'),           # --surface-alt
    linie=colors.HexColor('#D4D5E0'),             # --control-border
    text=colors.HexColor('#17182B'),              # --text-main
    leise=colors.HexColor('#5B5D72'),             # --text-muted
    guthaben=colors.HexColor('#2F7D5B'),          # --success-color
    nachzahlung=colors.HexColor('#A3312A'),       # --danger-color
)


#: Ein Betrag in deutscher Schreibweise. Kein eigener Formatierer mehr:
#: ``geld.text`` ist der eine Ort, an dem ein Euro-Betrag zu Text wird --
#: auch für die Sätze, die der Kern schreibt (``rechenkern.euro_text``).
geld = _geld_text


def stile(s: Stil) -> dict:
    """Die Absatzstile des Dokuments -- einmal für alle drei Teile."""
    def absatz(name, **werte):
        grund = dict(fontName='Helvetica', fontSize=9, leading=12.5,
                     textColor=s.text)
        grund.update(werte)
        return ParagraphStyle(f'NK{name}', **grund)

    return {
        # Der eine große Titel je Blatt.
        'Titel': absatz('Titel', fontName='Helvetica-Bold', fontSize=16,
                        leading=20),
        # Die Zeilen direkt unter dem Titel: eng gesetzt, damit sie als
        # Block zum Titel gehoeren und nicht als eigener Absatz wirken.
        'Titelzeile': absatz('Titelzeile', fontSize=9.5, leading=13,
                             textColor=s.leise),
        # Der Betreff eines Briefs: fett, aber nicht so gross wie der Titel
        # eines Tabellenblatts. Ein Brief schreit nicht.
        'Betreff': absatz('Betreff', fontName='Helvetica-Bold', fontSize=12,
                          leading=16),
        'Zwischentitel': absatz('Zwischentitel', fontName='Helvetica-Bold',
                                fontSize=10, leading=14),
        'Text': absatz('Text', fontSize=9.5, leading=14),
        'Anschrift': absatz('Anschrift', fontSize=9.5, leading=13),
        'Klein': absatz('Klein', fontSize=8.5, leading=11.5, textColor=s.leise),
        'Zelle': absatz('Zelle', fontSize=8.5, leading=11),
        'ZelleRechts': absatz('ZelleRechts', fontSize=8.5, leading=11, alignment=2),
        'ZelleFett': absatz('ZelleFett', fontName='Helvetica-Bold', fontSize=8.5,
                            leading=11),
        'ZelleFettRechts': absatz('ZelleFettRechts', fontName='Helvetica-Bold',
                                  fontSize=8.5, leading=11, alignment=2),
        # Die Rubrik ueber einer Gruppe von Positionen. Klein, leise und in
        # Versalien: Sie ordnet, sie konkurriert nicht. Vorher stand sie im
        # selben Fett und derselben Groesse wie die Positionen darunter --
        # das Auge fand keine Stufen und las eine Liste aus lauter Gleichen.
        'Rubrik': absatz('Rubrik', fontName='Helvetica-Bold', fontSize=7.5,
                         leading=10, textColor=s.leise),
        'Kopf': absatz('Kopf', fontName='Helvetica-Bold', fontSize=8.5,
                       leading=11, textColor=s.kopf_schrift),
        'KopfRechts': absatz('KopfRechts', fontName='Helvetica-Bold', fontSize=8.5,
                             leading=11, textColor=s.kopf_schrift, alignment=2),
        'Fuss': absatz('Fuss', fontSize=7.5, leading=10, textColor=s.leise),
    }


def rechenweg(schritte, s: Stil, saetze: dict, *, breite: int = 374) -> Table:
    """Die Schritte einer Zeile: links die Rechnung, rechts ihr Ergebnis.

    Phase 61. Vorher war jeder Schritt ein Satz mit Gleichheitszeichen, und
    weil der nächste Schritt wieder mit dem Zwischenergebnis anfing, stand
    jede Zahl zweimal. Rechtsbündig untereinander braucht es kein „="
    mehr: Die Spalte **ist** die Gleichheit, und die unterste Zahl ist das
    Ergebnis.

    Jeder Schritt ist ein Paar (Text, Betrag) -- ein
    ``rechenkern.Schritt``, oder was davon nach einer Runde durch JSON
    uebrig ist: eine zweielementige Liste. Deshalb wird **entpackt** und
    nicht nach Feldnamen gefragt; ein NamedTuple verspricht genau das.
    """
    rechts = 70
    daten = []
    for schritt in schritte:
        text, betrag = schritt
        daten.append([Paragraph(escape(text), saetze['Zelle']),
                      Paragraph(geld(betrag), saetze['ZelleRechts'])])
    tabelle = Table(daten, colWidths=[breite - rechts, rechts])
    tabelle.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    return tabelle


def kopfdaten(paare, s: Stil, saetze: dict, *, breite_links: int = 130) -> Table:
    """Beschriftung und Wert, eng gesetzt -- der Block unter dem Titel.

    Leere Werte fallen weg: Eine Zeile „Vermieter:" ohne Namen sagt nur,
    dass etwas fehlt, und das gehoert in die Oberflaeche, nicht aufs Blatt.
    """
    daten = [[Paragraph(escape(str(bez)), saetze['Klein']),
              Paragraph(escape(str(wert)).replace('\n', '<br/>'), saetze['Klein'])]
             for bez, wert in paare if wert]
    if not daten:
        return None
    tabelle = Table(daten, colWidths=[breite_links, SATZBREITE - breite_links])
    tabelle.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    return tabelle


def tabellenstil(s: Stil, zeilen: int, *, kopfzeilen: int = 1,
                 zebra_ab: int = 1) -> list:
    """Die Befehle für eine Tabelle dieses Stils.

    Senkrechte Linien gibt es nie: Sie zerschneiden die Zeile, die der Leser
    als Einheit lesen soll. Was die Spalten trennt, ist der Abstand.
    """
    befehle = [
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        # Luft nach der zweiten Sichtung: 5,5 pt las sich gedraengt.
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]
    if kopfzeilen:
        letzte_kopfzeile = kopfzeilen - 1
        if s.kopf_flaeche is not None:
            befehle.append(('BACKGROUND', (0, 0), (-1, letzte_kopfzeile),
                            s.kopf_flaeche))
            befehle.append(('TOPPADDING', (0, 0), (-1, letzte_kopfzeile), 9))
            befehle.append(('BOTTOMPADDING', (0, 0), (-1, letzte_kopfzeile), 9))
        else:
            # Ohne Fläche braucht der Kopf eine Kante, sonst schwebt er.
            befehle.append(('LINEABOVE', (0, 0), (-1, 0), 0.8, s.linie))
        befehle.append(('LINEBELOW', (0, letzte_kopfzeile), (-1, letzte_kopfzeile),
                        0.8, s.linie))
    if s.zebra is not None:
        for nummer in range(kopfzeilen + zebra_ab - 1, zeilen, 2):
            befehle.append(('BACKGROUND', (0, nummer), (-1, nummer), s.zebra))
    return befehle


def summenblock(zeilen, s: Stil, saetze: dict, *, breite: int = 240,
                ausrichtung: str = 'RIGHT', schlicht: bool = False) -> Table:
    """Die Summen als rechtsbündiger Block, wie in der Vorlage.

    Nicht über die ganze Breite: Die Summe gehört optisch unter die
    Betragsspalte, der sie folgt. Jede Zeile ist (Beschriftung, Betrag,
    fett?, Farbe oder None).

    ``ausrichtung`` ist ``RIGHT`` unter einer Tabelle und ``LEFT`` im Brief:
    Dort steht der Block unter seiner eigenen Überschrift, und ein Sprung
    nach rechts risse ihn von ihr los.
    """
    daten, befehle = [], [
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]
    if schlicht:
        # Im Brief: nur Text, wie in der Vorlage. Eine Flaeche mitten im
        # Schreiben macht aus dem Brief ein Formular.
        befehle += [('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0)]
    elif s.summen_flaeche is not None:
        befehle.append(('BACKGROUND', (0, 0), (-1, -1), s.summen_flaeche))
    for nummer, (bezeichnung, betrag, fett, farbe) in enumerate(zeilen):
        links = saetze['ZelleFett' if fett else 'Zelle']
        rechts = saetze['ZelleFettRechts' if fett else 'ZelleRechts']
        if farbe is not None:
            links = ParagraphStyle(f'Summe{nummer}L', parent=links, textColor=farbe)
            rechts = ParagraphStyle(f'Summe{nummer}R', parent=rechts, textColor=farbe)
        daten.append([Paragraph(escape(bezeichnung), links),
                      Paragraph(escape(betrag), rechts)])
        if fett and nummer and not schlicht:
            befehle.append(('LINEABOVE', (0, nummer), (-1, nummer), 0.6, s.linie))

    tabelle = Table(daten, colWidths=[breite * 0.62, breite * 0.38],
                    hAlign=ausrichtung)
    tabelle.setStyle(TableStyle(befehle))
    return tabelle
