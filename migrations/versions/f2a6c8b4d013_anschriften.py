"""Anschriften fuer Mieter und Vermieter (Phase 58)

Revision ID: f2a6c8b4d013
Revises: e8b4a7c25f91
Create Date: 2026-10-21

Die zweiunddreissigste Wanderung: ``tenants.anschrift``,
``tenants.zustellanschrift`` und ``vermieterdaten.anschrift``.

Bis 0.16.0 hatte niemand eine Anschrift -- weder der Mieter noch der
Vermieter. Der Brief an den Mieter hatte Betreff, Anrede und Gruss, aber
keinen Kopf (Live-Issue #35, Punkt 1).

Drei Spalten, alle ``Text`` und alle ``nullable``:

* ``tenants.anschrift`` -- die Anschrift der Wohnung des Mieters.
* ``tenants.zustellanschrift`` -- die Adresse ab dem Auszug, soweit
  bekannt. Zwei Felder statt einer Adresse mit Gueltigkeitsdatum: so
  steht es wortwoertlich im Issue, und eine Anschrift wechselt nicht
  halbjaehrlich wie ein Sollbetrag.
* ``vermieterdaten.anschrift`` -- die eigene Anschrift fuer den Briefkopf.

``Text`` und nicht ``String(n)``, weil eine Anschrift mehrzeilig ist und
keine sinnvolle Obergrenze hat; die Routen begrenzen die Laenge.

``nullable`` ist keine Bequemlichkeit, sondern Pflicht: Im Bestand hat
**kein** Mietverhaeltnis eine Anschrift. Eine Pflichtspalte haette jeden
vorhandenen Mieter ausgesperrt. Es gibt deshalb auch nichts nachzutragen
-- diese Wanderung legt Spalten an und schreibt keine Zeile.
"""

from alembic import op
import sqlalchemy as sa

revision = 'f2a6c8b4d013'
down_revision = 'e8b4a7c25f91'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tenants') as partie:
        partie.add_column(sa.Column('anschrift', sa.Text(), nullable=True))
        partie.add_column(sa.Column('zustellanschrift', sa.Text(), nullable=True))

    with op.batch_alter_table('vermieterdaten') as partie:
        partie.add_column(sa.Column('anschrift', sa.Text(), nullable=True))


def downgrade() -> None:
    # Der Rueckweg nimmt die Spalten weg, und mit ihnen die eingetragenen
    # Anschriften. Ein Rueckweg, der Daten kostet, muss das sagen: hier
    # kostet er genau das, was der Vermieter von Hand getippt hat.
    with op.batch_alter_table('vermieterdaten') as partie:
        partie.drop_column('anschrift')

    with op.batch_alter_table('tenants') as partie:
        partie.drop_column('zustellanschrift')
        partie.drop_column('anschrift')
