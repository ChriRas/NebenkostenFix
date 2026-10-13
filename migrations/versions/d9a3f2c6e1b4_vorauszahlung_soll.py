"""Soll der Vorauszahlungen (NK-261)

Revision ID: d9a3f2c6e1b4
Revises: c7e1f94a2b05
Create Date: 2026-10-12

Die achtundzwanzigste Wanderung: eine neue Tabelle ``vorauszahlung_soll``.
Je Mietverhaeltnis der vereinbarte Monatsbetrag ab einem Stichtag
(R-VZ-02). Eine Serienbuchung legt die Zahlungen im Voraus an; danach
stand der vereinbarte Betrag nirgends mehr, und Soll und Ist liessen sich
nicht gegeneinander halten. Kein Backfill: ohne Soll gibt es keinen
Rueckstand -- genau der bisherige Stand.
"""

from alembic import op
import sqlalchemy as sa

revision = 'd9a3f2c6e1b4'
down_revision = 'c7e1f94a2b05'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'vorauszahlung_soll',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('gueltig_ab', sa.Date(), nullable=False),
        sa.Column('betrag', sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'gueltig_ab',
                            name='uq_vorauszahlung_soll_tenant_gueltig_ab'),
        sa.CheckConstraint('betrag >= 0', name='ck_vorauszahlung_soll_betrag'),
    )


def downgrade() -> None:
    op.drop_table('vorauszahlung_soll')
