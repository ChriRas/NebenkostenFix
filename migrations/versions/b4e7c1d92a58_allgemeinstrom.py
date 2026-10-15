"""Kostenart Nr. 11 heisst Allgemeinstrom

Revision ID: b4e7c1d92a58
Revises: a8c4e2f61d93
Create Date: 2026-10-15

Die dreissigste Wanderung, reine Daten: der Katalog nennt Nr. 11 jetzt
"Allgemeinstrom" statt "Beleuchtung (Allgemeinstrom)". Das Seed gleicht
ueber die Nummer ab und benennt nichts um, darum zieht diese Wanderung
den Bestand nach -- aber nur den unveraenderten Standardnamen. Wer seine
Kostenart selbst benannt hat, behaelt den Namen. Gibt es "Allgemeinstrom"
schon (name ist UNIQUE), bleibt alles, wie es ist.
"""

from alembic import op
import sqlalchemy as sa

revision = 'b4e7c1d92a58'
down_revision = 'a8c4e2f61d93'
branch_labels = None
depends_on = None

ALT = 'Beleuchtung (Allgemeinstrom)'
NEU = 'Allgemeinstrom'


def _umbenennen(von: str, nach: str) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE cost_categories SET name = :nach"
            " WHERE betrkv_nr = 11 AND name = :von"
            " AND NOT EXISTS (SELECT 1 FROM cost_categories WHERE name = :nach)"
        ),
        {"von": von, "nach": nach},
    )


def upgrade() -> None:
    _umbenennen(ALT, NEU)


def downgrade() -> None:
    _umbenennen(NEU, ALT)
