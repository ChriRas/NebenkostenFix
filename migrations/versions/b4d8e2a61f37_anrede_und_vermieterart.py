"""Anrede je Mieter und Art des Vermieters (NK-264)

Revision ID: b4d8e2a61f37
Revises: 670627ef0699
Create Date: 2026-10-12

Die sechsundzwanzigste Wanderung: zwei nullbare Spalten.
``tenants.anrede`` haelt eine eigene Anrede je Mieter („Sehr geehrte Frau
Muster“); leer heisst der neutrale Gruss aus NK-247. ``vermieterdaten.art``
ist „privat“ oder „firma“ und schaltet ich/wir in Anschreiben und PDF;
leer heisst die neutralen Saetze aus NK-248. Kein Backfill: leer ist
genau der bisherige Stand.
"""

from alembic import op
import sqlalchemy as sa

revision = 'b4d8e2a61f37'
down_revision = '670627ef0699'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tenants') as batch:
        batch.add_column(sa.Column('anrede', sa.String(200), nullable=True))
    with op.batch_alter_table('vermieterdaten') as batch:
        batch.add_column(sa.Column('art', sa.String(10), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('vermieterdaten') as batch:
        batch.drop_column('art')
    with op.batch_alter_table('tenants') as batch:
        batch.drop_column('anrede')
