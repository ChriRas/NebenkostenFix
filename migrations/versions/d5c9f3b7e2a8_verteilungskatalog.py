"""Verteilungskatalog der Kostenarten (Re-Review Phase 54)

Revision ID: d5c9f3b7e2a8
Revises: f7c2e9a4b6d1
Create Date: 2026-10-18

Die neunundreißigste Wanderung: der Seed schrieb seit je die Katalog-Namen
(``PER_SQM``, ``METER_READING``) in ``cost_categories.allocation_method`` --
Werte, die keine der fuenf Abrechnungsarten (``abrechnungsart.ARTEN``) kennt.
Funktional harmlos: das Abrechnungsblatt liest das Kostenprofil des Mieters,
nicht die Spalte der Kostenart. Sichtbar wurde es mit Phase 54: die neue
Kostenarten-Tabelle zeigt die Spalte, und das Bearbeiten-Formular kennt die
fuenf deutschen Werte -- ein ``PER_SQM`` liess sich dort nicht mehr
darstellen.

Die Wanderung setzt die Spalte auf die echten Kodes:

* ``PER_SQM`` -> ``qm``
* ``METER_READING`` mit eigenem Zaehler -> ``direkt``
* ``METER_READING`` ohne Zaehler -> ``qm`` (wie bisher gerechnet: ohne
  Profil zaehlt die VORGABE ``qm``; die Abrechnung aendert sich nicht)

Jeder andere Wert bleibt, wie er ist -- der Fremdanbieter-Bestand soll
nicht still angetastet werden.
"""

from alembic import op

revision = 'd5c9f3b7e2a8'
down_revision = 'f7c2e9a4b6d1'
branch_labels = None
depends_on = None

#: Die Katalog-Namen, deren ``qm`` im Rueckweg wieder ``PER_SQM`` wird.
#: Eigene Kostenarten mit demselben Namen gibt es nicht (Namen sind
#: eindeutig, der Seed heisst so) -- der Rueckweg trifft sie nicht.
_QM_NAMEN = (
    'Grundsteuer', 'Entwässerung', 'Niederschlagswasser', 'Heizung',
    'Warmwasser', 'Heizung und Warmwasser (verbundene Anlage)', 'Aufzug',
    'Straßenreinigung und Müllbeseitigung',
    'Gebäudereinigung und Ungezieferbekämpfung', 'Gartenpflege',
    'Allgemeinstrom', 'Schornsteinreinigung',
    'Sach- und Haftpflichtversicherung', 'Hauswart',
    'Antenne, Breitband oder Glasfaser', 'Wäschepflege',
    'Sonstige Betriebskosten',
)


def upgrade() -> None:
    # Erst der Zaehler-Fall, dann der Rest: METER_READING mit eigenem
    # Zaehler ist "nach Verbrauch", alles uebrige rechnet weiter nach
    # Flaeche, wie es die VORGABE bisher tat.
    op.execute(
        "UPDATE cost_categories SET allocation_method = 'direkt' "
        "WHERE allocation_method = 'METER_READING' AND requires_meter = 1")
    op.execute(
        "UPDATE cost_categories SET allocation_method = 'qm' "
        "WHERE allocation_method = 'METER_READING'")
    op.execute(
        "UPDATE cost_categories SET allocation_method = 'qm' "
        "WHERE allocation_method = 'PER_SQM'")


def downgrade() -> None:
    # Der Rueckweg stellt die Katalog-Namen wieder her, soweit sie sich
    # eindeutig zuruecksetzen lassen; der Rest bleibt auf dem Kode.
    op.execute(
        "UPDATE cost_categories SET allocation_method = 'PER_SQM' "
        "WHERE allocation_method = 'qm' AND name IN "
        "('" + "','".join(_QM_NAMEN) + "')")
    op.execute(
        "UPDATE cost_categories SET allocation_method = 'METER_READING' "
        "WHERE allocation_method = 'direkt'")
