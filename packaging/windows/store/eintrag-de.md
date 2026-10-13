# Store-Eintrag Deutsch (NK-172)

Texte für das Partner Center, Store listings → Deutsch (Deutschland).
Jeder Abschnitt ist ein Feld. `tests/test_store_eintrag.py` prüft die
Längengrenzen des Partner Centers und dass der Haftungshinweis wörtlich
drinsteht (`nebenkostenfix/haftung.py`).

## Beschreibung

NebenkostenFix erstellt die Nebenkostenabrechnung für private Vermieter mit einer bis fünfzehn Wohnungen. Immobilien, Wohnungen, Mieter, Zählerstände und Rechnungen liegen an einer Stelle. Am Ende steht eine fertige Abrechnung als PDF, mit Deckblatt, Anschreiben und Zahlungs-QR-Code.

Die Regeln folgen der Betriebskostenverordnung (BetrKV), der Heizkostenverordnung (HeizkostenV) und dem Kohlendioxidkostenaufteilungsgesetz (CO2KostAufG). Jede Kostenart und jeder Umlageschlüssel ist in der Abrechnung nachvollziehbar, auch bei Ein- und Auszug im Jahr und bei Leerstand.

Ihre Daten bleiben bei Ihnen: kein Konto beim Herausgeber, kein Server, keine Telemetrie, keine Werbung. Alles liegt in einem Ordner auf Ihrem PC, standardmäßig unter Dokumente\NebenkostenFix. Updates kommen über den Microsoft Store.

Für den Einstieg gibt es eine Beispielimmobilie, den Assistenten „Jahr abrechnen“ und eine Hilfe mit Begriffen von A bis Z. Eine Sicherung oder ein Umzug auf einen anderen Rechner ist eine einzige Datei. Dieselbe Datei nimmt auch die Docker-Fassung für NAS und Heimserver an.

NebenkostenFix ist freie Software unter der GPL-3.0. Der Quelltext liegt auf GitHub.

NebenkostenFix ist kostenlos, quelloffen (GPL-3.0) und wird ohne Gewähr bereitgestellt. Die Anwendung ist keine Rechtsberatung. Prüfen Sie jede Abrechnung selbst, bevor Sie sie verschicken.

## Kurzbeschreibung

Die Nebenkostenabrechnung für private Vermieter. Kostenlos, und Ihre Daten bleiben bei Ihnen.

## Neuerungen in dieser Version

Version 0.14.0: Zählerwechsel und Eichfrist, Soll und Ist der Vorauszahlungen, Fristenkalender, geführter Jahreswechsel und Lohnanteile nach § 35a EStG. Die Rechenregeln bleiben unverändert.

- Zähler lassen sich bearbeiten und tauschen. Beim Zählerwechsel läuft der Verbrauch über beide Zähler weiter, das Ende der Eichfrist wird vorgeschlagen.
- Je Mieter zeigt „Vorauszahlungen“ Soll und Ist für jeden Monat. Bei Rückstand steht eine Zahlungserinnerung als Vorlage bereit.
- Der Fristenkalender sammelt Abrechnungs-, Einwendungs- und Eichfristen und lässt sich als Kalenderdatei (.ics) laden.
- „Neues Jahr beginnen“ führt durch Ablesen, Vorauszahlung und Rechnungen wie im Vorjahr. Vor dem Festsetzen zeigt ein Prüfstand Auffälliges und den Weg zur Behebung.
- Die Wohnungsauswertung zeigt die Kosten je m² über mehrere Jahre.
- Lohnanteile nach § 35a EStG lassen sich je Rechnung erfassen. Die Abrechnung weist sie in einer eigenen Tabelle aus.
- Das Paket zur Belegeinsicht enthält Abrechnung, Rechenweg, Belege und die Ablesefotos der Wohnung.
- Anrede je Mieter, Anschreiben in Ich- oder Wir-Form. Das PDF ist kürzer und trennt Wörter nicht mehr mitten im Wort.
- Am Handy erscheinen Zähler als Karten und die Aktionen eines Bereichs in einem Menü.

## Produktmerkmale

- Immobilien und Wohnungen mit beliebig vielen Einheiten und Umlageschlüsseln
- Mieter mit Ein- und Auszug, anteilige Abrechnung und Leerstand inbegriffen
- Rechnungen einzeln, als Sammelrechnung oder aus einer Tabelle
- Belege als PDF oder Foto
- Zähler mit Beweisfoto, Zwischenablesung und Doppeltarif
- Heizkosten nach HeizkostenV
- CO2-Kostenaufteilung nach dem Stufenmodell
- Abrechnung als PDF mit Deckblatt, Anschreiben und Zahlungs-QR-Code (GiroCode)
- Assistent „Jahr abrechnen“ und Beispielimmobilie
- Hilfe mit Begriffen von A bis Z in der App
- Import aus Excel oder CSV
- Sicherung und Umzug als eine Datei
- Anmeldung mit Benutzername und Passwort
- Keine Telemetrie, keine Werbung, kein Konto beim Herausgeber

## Suchbegriffe

- Nebenkostenabrechnung
- Betriebskosten
- Vermieter
- Heizkostenabrechnung
- Mietverwaltung
- Hausverwaltung
- Nebenkosten

## Copyright

© 2026 NerbrY72. Freie Software unter der GNU General Public License 3.0.

## Zusätzliche Lizenzbedingungen

NebenkostenFix steht unter der GNU General Public License, Version 3 (GPL-3.0): https://github.com/Nerbry72/NebenkostenFix/blob/main/LICENSE
Die Lizenzen der mitgelieferten Software stehen in der App unter Hilfe → Über NebenkostenFix.
