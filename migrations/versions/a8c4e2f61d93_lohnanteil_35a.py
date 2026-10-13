"""Lohnanteil nach § 35a EStG (NK-268)

Revision ID: a8c4e2f61d93
Revises: d9a3f2c6e1b4
Create Date: 2026-10-13

Die neunundzwanzigste Wanderung: zwei nullbare Spalten an
``cost_invoices`` -- ``art_35a`` (haushaltsnah oder handwerker) und
``lohnanteil`` -- samt CHECKs: eine bekannte Art, beides oder keines,
und der Lohn liegt im Betrag (R-35A-01). Kein Backfill:
leer heisst keine Angabe, dann gibt es keinen Ausweis.
"""

from alembic import op
import sqlalchemy as sa

revision = 'a8c4e2f61d93'
down_revision = 'd9a3f2c6e1b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('cost_invoices') as batch:
        batch.add_column(sa.Column('art_35a', sa.String(20), nullable=True))
        batch.add_column(sa.Column('lohnanteil', sa.Numeric(12, 2), nullable=True))
        batch.create_check_constraint(
            'ck_cost_invoices_art_35a',
            "art_35a IS NULL OR art_35a IN ('handwerker', 'haushaltsnah')")
        batch.create_check_constraint(
            'ck_cost_invoices_35a_vollstaendig',
            '(art_35a IS NULL) = (lohnanteil IS NULL)')
        batch.create_check_constraint(
            'ck_cost_invoices_lohnanteil_im_betrag',
            'lohnanteil IS NULL OR (lohnanteil >= 0 AND lohnanteil <= amount)')


def downgrade() -> None:
    with op.batch_alter_table('cost_invoices') as batch:
        batch.drop_constraint('ck_cost_invoices_lohnanteil_im_betrag', type_='check')
        batch.drop_constraint('ck_cost_invoices_35a_vollstaendig', type_='check')
        batch.drop_constraint('ck_cost_invoices_art_35a', type_='check')
        batch.drop_column('lohnanteil')
        batch.drop_column('art_35a')
