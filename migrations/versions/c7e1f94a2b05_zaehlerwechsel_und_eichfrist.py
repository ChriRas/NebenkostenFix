"""Zaehlerwechsel, Eichfrist und Einbauort (NK-258)

Revision ID: c7e1f94a2b05
Revises: b4d8e2a61f37
Create Date: 2026-10-12

Die siebenundzwanzigste Wanderung: drei nullbare Spalten an ``meters``.
``ersetzt_id`` zeigt auf den Zaehler, den dieser beim Wechsel abgeloest hat;
der Rechenkern haengt beide zu einer Kette zusammen. ``geeicht_bis`` und
``ort`` sind Auskunft fuer den Vermieter (R-EICH-01) und aendern keine
Berechnung. Kein Backfill: leer ist genau der bisherige Stand -- jeder
Zaehler steht fuer sich.
"""

from alembic import op
import sqlalchemy as sa

revision = 'c7e1f94a2b05'
down_revision = 'b4d8e2a61f37'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('meters') as batch:
        batch.add_column(sa.Column('ersetzt_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('geeicht_bis', sa.Date(), nullable=True))
        batch.add_column(sa.Column('ort', sa.String(100), nullable=True))
        batch.create_foreign_key(
            'fk_meters_ersetzt', 'meters', ['ersetzt_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('meters') as batch:
        batch.drop_constraint('fk_meters_ersetzt', type_='foreignkey')
        batch.drop_column('ort')
        batch.drop_column('geeicht_bis')
        batch.drop_column('ersetzt_id')
