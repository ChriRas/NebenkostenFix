"""Soll der Kaltmieten (Phase 49)

Revision ID: f7c2e9a4b6d1
Revises: b4e7c1d92a58
Create Date: 2026-10-18

Die neunundzwanzigste Wanderung: eine neue Tabelle ``kaltmiete_soll``.
Je Mietverhaeltnis die vereinbarte Kaltmiete ab einem Stichtag, nach dem
Muster von ``vorauszahlung_soll``. Der Betrag stand bisher nirgends, und
die Erinnerung an die naechste Mieterhoehung (§ 558: 15 Monate, Indexmiete
§ 557b: 12 Monate) hatte kein Datum, von dem sie zaehlen koennte. Kein
Backfill: ohne Eintrag bleibt es beim bisherigen Stand ohne Erinnerung.
"""

from alembic import op
import sqlalchemy as sa

revision = 'f7c2e9a4b6d1'
down_revision = 'b4e7c1d92a58'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'kaltmiete_soll',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('gueltig_ab', sa.Date(), nullable=False),
        sa.Column('betrag', sa.Numeric(12, 2), nullable=False),
        sa.Column('indexmiete', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'gueltig_ab',
                            name='uq_kaltmiete_soll_tenant_gueltig_ab'),
        sa.CheckConstraint('betrag >= 0', name='ck_kaltmiete_soll_betrag'),
    )


def downgrade() -> None:
    op.drop_table('kaltmiete_soll')
