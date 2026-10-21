"""Die Anschriften von Mieter und Vermieter (Phase 58, Issue #35 Punkt 1).

Bis 0.16.0 kannte die Anwendung keine Adresse. Der Brief an den Mieter
hatte einen Betreff, eine Anrede und einen Gruß -- aber keinen Kopf, in
dem steht, an wen er geht und von wem er kommt.

Hier steht nur die **Auswahl**, nicht die Form: Welche der beiden
Anschriften eines Mietverhältnisses gilt für diese Zustellung? Das ist
keine Darstellungsfrage, sondern eine Rechtsfrage. Die Frist des
§ 556 Abs. 3 Satz 1 BGB läuft über den **Zugang** der Abrechnung beim
Mieter. Eine Abrechnung, die an die alte Wohnung geht, erreicht ihn
nicht -- die Frist läuft trotzdem ab, und danach ist eine Nachforderung
ausgeschlossen. Darum entscheidet das der Kern und nicht die Oberfläche,
und darum sagt ``zustellhinweis`` dem Vermieter etwas, bevor es zu spät
ist.

Die Regel in einem Satz: **Die Zustellanschrift gilt erst ab dem Auszug.**
Solange der Mieter noch wohnt, ist seine Wohnung die richtige Adresse,
auch wenn die neue längst bekannt ist. Das Feld in der Oberfläche heißt
deshalb „Zustelladresse ab Auszug“ und nicht „zweite Adresse“.

Der Auszugstag selbst zählt noch als Wohnen: Er ist der letzte Miettag
(so steht es im Mieterdialog und so rechnet der Kern die Anteile).
"""

from __future__ import annotations

from datetime import date

#: Der Hinweis, wenn nach dem Auszug keine Zustellanschrift bekannt ist.
HINWEIS_OHNE_ZUSTELLUNG = (
    'Der Mieter ist ausgezogen und es ist keine Zustelladresse hinterlegt. '
    'Die Abrechnungsfrist des § 556 Abs. 3 BGB läuft über den Zugang beim '
    'Mieter — eine Abrechnung an die alte Wohnung erreicht ihn nicht.'
)


def saeubern(text: str | None) -> str:
    """Eine Anschrift aus einem Textfeld, ohne Rand und ohne Leerzeilen.

    Was aus einem ``<textarea>`` kommt, hat Leerzeichen an den Rändern und
    gern eine Leerzeile am Ende. Für den Briefkopf zählen nur die Zeilen
    mit Inhalt; sonst klafft im Kopf eine Lücke, die niemand getippt hat.
    """
    if not text:
        return ''
    zeilen_mit_inhalt = [zeile.strip() for zeile in str(text).splitlines()]
    return '\n'.join(zeile for zeile in zeilen_mit_inhalt if zeile)


def zeilen(text: str | None) -> list[str]:
    """Die Anschrift als Liste -- das Blatt setzt sie Zeile für Zeile."""
    gesaeubert = saeubern(text)
    return gesaeubert.split('\n') if gesaeubert else []


def ist_ausgezogen(auszug: date | None, stichtag: date) -> bool:
    """Ist das Mietverhältnis am Stichtag beendet?

    Ohne Auszugsdatum wohnt der Mieter noch. Am Auszugstag selbst auch:
    Er ist der letzte Miettag, der Nachmieter zieht am Tag danach ein.
    """
    return auszug is not None and auszug < stichtag


def fuer_zustellung(anschrift: str | None, zustellanschrift: str | None, *,
                    ausgezogen: bool) -> str:
    """Die Anschrift, an die diese Abrechnung geht.

    Nach dem Auszug die Zustellanschrift, sonst die der Wohnung. Fehlt
    die Zustellanschrift, bleibt es bei der alten: Eine Adresse, bei der
    ein Nachsendeauftrag greifen kann, ist mehr als keine. Ist auch die
    leer, bleibt der Briefkopf leer -- erfunden wird hier nichts.
    """
    wohnung = saeubern(anschrift)
    neu = saeubern(zustellanschrift)
    if ausgezogen and neu:
        return neu
    return wohnung


def zustellhinweis(anschrift: str | None, zustellanschrift: str | None, *,
                   ausgezogen: bool) -> str | None:
    """Der Satz für den Vermieter, oder ``None``, wenn alles passt.

    Nur ein Fall ist gefährlich: ausgezogen und keine Zustelladresse. Dann
    geht die Abrechnung an eine Wohnung, in der der Mieter nicht mehr
    wohnt, und die Frist läuft, ohne dass es jemand merkt.
    """
    if ausgezogen and not saeubern(zustellanschrift):
        return HINWEIS_OHNE_ZUSTELLUNG
    return None
