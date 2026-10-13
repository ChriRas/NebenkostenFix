"""Das Anschreiben mit Zahlungsaufforderung als editierbare Vorlage (NK-064).

Das Deckblatt der Abrechnung trug einen festen Gruß; der Vermieter
konnte den Ton seines Anschreibens nicht bestimmen. Hier steht die
Vorlage: ein Vorgabetext mit Platzhaltern, den der Vermieter je Objekt
über die Route ändern kann. Die Renderfunktion füllt die Platzhalter
aus dem Ergebnis der Abrechnung -- Geld in der Sprache des Dokuments
(Komma statt Punkt, über ``euro_text`` aus dem Kern).

Platzhalter, die keine Werte haben (etwa die Einwendungsfrist, solange
das Zustelldatum fehlt), bleiben sichtbar stehen: ein sichtbares Loch
schreit, ein leeres schweigt. Der Platzhalter ``{aufforderung}`` ist der
einzige mit absichtlich leerem Wert -- bei einem Guthaben gäbe es keine
Zahlungsaufforderung, und die Lücke ist hier der Inhalt.
"""

from datetime import date
from decimal import Decimal
# Bandit-Ausnahme: maskiert Text fuer reportlab, parst kein XML
from xml.sax.saxutils import escape  # nosec B406

from nebenkostenfix.rechenkern import euro_text

# NK-247: neutrale Anrede statt „Sehr geehrte/r“ -- eine Stelle für die
# Vorlage und den festen Gruß des Deckblatts. NK-264: eine eigene Anrede
# je Mieter geht vor; der neutrale Gruß bleibt der Rückfall.
ANREDE = 'Guten Tag {mieter_name},'


def anrede(mieter_name: str, eigene: str | None = None) -> str:
    eigene = (eigene or '').strip()
    if not eigene:
        return ANREDE.format(mieter_name=mieter_name)
    return eigene if eigene[-1] in ',!' else eigene + ','


# NK-264: ich/wir nach der Art des Vermieters (Einstellungen); ohne Angabe
# die neutralen Sätze aus NK-248. Anschreiben und PDF lesen von hier.
ARTEN = ('privat', 'firma')
_SAETZE = {
    None: {
        'belege': 'Die Belege können Sie auf Verlangen einsehen.',
        'konto': 'das Konto',
        'bekanntes_konto': 'das bekannte Konto',
        'rueckfragen': 'Rückfragen zur Abrechnung werden gern beantwortet.',
    },
    'privat': {
        'belege': 'Die Belege können Sie auf Verlangen bei mir einsehen.',
        'konto': 'mein Konto',
        'bekanntes_konto': 'mein bekanntes Konto',
        'rueckfragen': 'Rückfragen zur Abrechnung beantworte ich gern.',
    },
    'firma': {
        'belege': 'Die Belege können Sie auf Verlangen bei uns einsehen.',
        'konto': 'unser Konto',
        'bekanntes_konto': 'unser bekanntes Konto',
        'rueckfragen': 'Rückfragen zur Abrechnung beantworten wir gern.',
    },
}


def saetze(art: str | None) -> dict:
    return _SAETZE.get(art, _SAETZE[None])


def vorgabe(art: str | None = None) -> str:
    """Die Vorlage, solange der Vermieter nichts Eigenes hinterlegt hat."""
    return (
        '{anrede}\n\n'
        'anbei erhalten Sie die Nebenkostenabrechnung für die Wohnung '
        '{wohnung_name} für den Zeitraum {zeitraum}.\n\n'
        'Die Abrechnung ergibt bei Gesamtkosten von {gesamtsumme} und '
        'Vorauszahlungen von {vorauszahlungen} einen Saldo in Höhe von '
        '{saldo_betrag} ({saldo_art}).\n\n'
        '{aufforderung}\n\n'
        'Sie können Einwendungen gegen diese Abrechnung innerhalb von zwölf '
        'Monaten nach ihrem Zugang geltend machen. ' + saetze(art)['belege'] + '\n\n'
        'Mit freundlichen Grüßen\n'
        '{vermieter_name}'
    )


VORGABE = vorgabe()

# Was es zu füllen gibt -- die Route nennt dem Vermieter dieselbe Liste.
PLATZHALTER = {
    'anrede': ('Anrede des Mieters -- die eigene aus dem Mieterdialog, '
               'sonst „Guten Tag <Name>,“'),
    'mieter_name': 'Name des Mieters',
    'wohnung_name': 'Name der Wohnung',
    'objekt_name': 'Name des Objekts',
    'vermieter_name': ('Name des Vermieters aus den Einstellungen -- leer, '
                       'solange keiner hinterlegt ist'),
    'zeitraum': 'Abrechnungszeitraum, etwa „01.01.2025 bis 31.12.2025“',
    'gesamtsumme': 'Summe aller Kostenpositionen',
    'vorauszahlungen': 'Summe der geleisteten Vorauszahlungen',
    'saldo_betrag': 'Gesamtsumme abzüglich Vorauszahlungen',
    'saldo_art': '„Nachzahlung“, „Guthaben“ oder „Ausgleich“',
    'aufforderung': ('Die Zahlungsaufforderung -- nur bei einer Nachzahlung '
                     'gefüllt, sonst leer'),
    'einwendungsfrist': ('Ende der Einwendungsfrist des Mieters -- nur '
                         'gefüllt, wenn das Zustelldatum vorliegt, sonst '
                         'sichtbarer Platzhalter'),
    'vorauszahlung_anpassung': ('Die neue monatliche Vorauszahlung ab ihrem '
                                'Wirksamwerden (R-VZ-01) -- leer, wenn sich '
                                'nichts ändert'),
}


def fuelle(vorlage: str, platzhalter: dict) -> str:
    """Füllt die bekannten Platzhalter; was ohne Wert bleibt, bleibt sichtbar.

    Ein Platzhalter ohne Eintrag wird nicht still gelöscht: der
    Vermieter soll die Lücke im Anschreiben sehen und schließen, nicht
    dem Mieter einen unvollständigen Satz geben. ``None`` im Werte-Dict
    gilt als "kein Wert", ``''`` als gewollt leer.
    """
    text = vorlage
    for name, wert in platzhalter.items():
        marke = '{' + name + '}'
        if marke in text:
            text = text.replace(marke, '' if wert is None else str(wert))
    return text


def _saldo_art(saldo: Decimal) -> str:
    if saldo > 0:
        return 'Nachzahlung'
    if saldo < 0:
        return 'Guthaben'
    return 'Ausgleich'


def _aufforderung(saldo: Decimal) -> str:
    """Die Zahlungsaufforderung -- nur wo etwas zu zahlen ist.

    Bei einem Guthaben wäre der Satz eine unbezahlbare Forderung; die
    Lücke ist gewollt (siehe Modul-Dokumentation).
    """
    if saldo > 0:
        # NK-248: ohne ich/wir -- der Satz passt für Privatperson und Firma.
        return (f'Bitte gleichen Sie den ausstehenden Betrag in Höhe von '
                f'{euro_text(saldo)} aus.')
    return ''


def text_fuer(vorlage: str, *, mieter_name: str, wohnung_name: str,
              objekt_name: str, zeitraum: str, gesamtsumme: Decimal,
              vorauszahlungen: Decimal, saldo: Decimal,
              einwendungsfrist: str | None = None,
              vermieter_name: str = '',
              vorauszahlung: dict | None = None,
              mieter_anrede: str | None = None) -> str:
    """Füllt die Vorlage aus dem Ergebnis einer Abrechnung.

    ``vermieter_name`` unterschreibt den Gruß (NK-210). Ohne Namen bleibt
    er leer: ein Gruß ohne Unterschrift ist ehrlicher als der Name des
    Hauses an ihrer Stelle.

    ``einwendungsfrist`` ist das Ende der Einwendungsfrist des Mieters --
    bekannt erst mit dem Zustelldatum; ohne es bleibt der Platzhalter
    sichtbar stehen.

    ``vorauszahlung`` ist der Vorschlag aus ``vorauszahlung.vorschlag``
    (NK-226). Ohne Änderung bleibt der Satz gewollt leer.

    ``mieter_anrede`` ist die eigene Anrede des Mieters (NK-264).
    """
    return fuelle(vorlage, {
        'anrede': anrede(mieter_name, mieter_anrede),
        'mieter_name': mieter_name,
        'wohnung_name': wohnung_name,
        'objekt_name': objekt_name,
        'vermieter_name': vermieter_name,
        'zeitraum': zeitraum,
        'gesamtsumme': euro_text(gesamtsumme),
        'vorauszahlungen': euro_text(vorauszahlungen),
        'saldo_betrag': euro_text(saldo),
        'saldo_art': _saldo_art(saldo),
        'aufforderung': _aufforderung(saldo),
        'einwendungsfrist': einwendungsfrist,
        'vorauszahlung_anpassung': _anpassung(vorauszahlung),
    })


def _anpassung(v: dict | None) -> str:
    if not v or not v.get('aenderung'):
        return ''
    ab = date.fromisoformat(v['ab'])
    return (f"Ab dem {ab:%d.%m.%Y} beträgt Ihre monatliche Vorauszahlung "
            f"{euro_text(Decimal(v['neu']))} (bisher {euro_text(Decimal(v['bisher']))}).")


def absaetze(text: str) -> list[str]:
    """Der Anschreiben-Text in Absätze geteilt, wie das Blatt ihn setzt.

    Leere Zeilen trennen; innerhalb eines Absatzes bleiben Zeilenumbrüche
    erhalten (das Blatt setzt sie als Umbruch). Die Werte sind bereits
    ausgefüllt -- hier wird nur noch for XML-maskiert, denn ein
    ``Paragraph`` des Satzers liest seinen Text als XML-Stück und wäre an
    einem einzigen ``&`` im Anschreiben gestorben.
    """
    stuecke = []
    for stueck in text.split('\n\n'):
        stueck = stueck.strip('\n')
        if stueck:
            stuecke.append(escape(stueck).replace('\n', '<br/>'))
    return stuecke
