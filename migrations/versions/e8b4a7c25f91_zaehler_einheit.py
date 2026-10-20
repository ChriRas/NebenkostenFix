"""Die Einheit steht am Zaehler (Phase 55)

Revision ID: e8b4a7c25f91
Revises: d5c9f3b7e2a8
Create Date: 2026-10-20

Die einunddreissigste Wanderung: ``meters.einheit``.

Bisher leitete der Kern aus der BetrKV-Nummer der Kostenart ab, was ein
Zaehler misst -- Nr. 5 Warmwasser hiess "m3", also Wasserzaehler. Ein
Warmwasser-Waermemengenzaehler (kWh) hatte damit keinen Platz, obwohl
§ 9 Abs. 2 Satz 1 HeizkostenV ihn ausdruecklich vorsieht und er bei
Waermepumpen der uebliche Aufbau ist (Nachfrage zu Live-Issue #32).

**Diese Wanderung aendert kein Verhalten.** Sie schreibt fuer jeden
vorhandenen Zaehler genau die Einheit fest, die der Kern heute ableiten
wuerde. Danach entscheidet dasselbe Ergebnis aus einem Feld statt aus
einer Ableitung -- fuer den Bestand ist das ein Nullwechsel. Erst wer
die Einheit kuenftig von Hand aendert, bekommt ein anderes Verhalten.

Die Ableitung ist hier als Schnappschuss nachgebildet und importiert
bewusst nichts aus ``nebenkostenfix``: eine Wanderung muss in fuenf
Jahren noch dasselbe tun, auch wenn der Katalog sich weiterdreht.
"""

from alembic import op
import sqlalchemy as sa

revision = 'e8b4a7c25f91'
down_revision = 'd5c9f3b7e2a8'
branch_labels = None
depends_on = None

#: Schnappschuss von ``betrkv.EINHEITEN`` am 2026-10-20.
EINHEITEN_NACH_NUMMER = {
    1: 'Einheiten',
    2: 'm³', 3: 'm³',
    4: 'kWh', 5: 'm³', 6: 'kWh',
    7: 'Einheiten', 8: 'Einheiten', 9: 'Einheiten', 10: 'Einheiten',
    11: 'kWh',
    12: 'Einheiten', 13: 'Einheiten', 14: 'Einheiten', 15: 'Einheiten',
    16: 'Einheiten', 17: 'Einheiten',
}

#: Die Vorgabe, wenn weder Nummer noch Name etwas hergeben.
VORGABE = 'Einheiten'


def _abgeleitet(name, nummer):
    """Was ``rechenkern.einheit_fuer`` am 2026-10-20 geantwortet haette."""
    if nummer is not None:
        return EINHEITEN_NACH_NUMMER.get(nummer, VORGABE)
    wort = (name or '').lower()
    if 'strom' in wort:
        return 'kWh'
    if any(x in wort for x in ('wasser', 'gas', 'entwäss')):
        return 'm³'
    if any(x in wort for x in ('wärme', 'waerme', 'heiz')):
        return 'kWh'
    return VORGABE


def upgrade() -> None:
    with op.batch_alter_table('meters') as partie:
        partie.add_column(sa.Column('einheit', sa.String(10), nullable=True))

    verbindung = op.get_bind()
    zeilen = verbindung.execute(sa.text(
        'SELECT m.id, c.name, c.betrkv_nr '
        'FROM meters m JOIN cost_categories c ON c.id = m.category_id'
    )).fetchall()
    for zaehler_id, name, nummer in zeilen:
        verbindung.execute(
            sa.text('UPDATE meters SET einheit = :einheit WHERE id = :id'),
            {'einheit': _abgeleitet(name, nummer), 'id': zaehler_id},
        )
    # Ein Zaehler ohne Kostenart kann es nicht geben (category_id ist
    # nullable=False), aber ein verwaister Fremdschluessel in einem alten
    # Bestand soll die Wanderung nicht anhalten.
    verbindung.execute(sa.text(
        "UPDATE meters SET einheit = :vorgabe WHERE einheit IS NULL"
    ), {'vorgabe': VORGABE})


def downgrade() -> None:
    # Der Rueckweg nimmt die Spalte weg; der Kern leitet dann wieder aus
    # der Nummer ab. Eine von Hand gesetzte Einheit geht dabei verloren --
    # das ist der Preis des Rueckwegs und steht so in der SPEC.
    with op.batch_alter_table('meters') as partie:
        partie.drop_column('einheit')
