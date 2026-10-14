"""add new chapter counter

Revision ID: e12faf9d735f
Revises: cc451636df5e
Create Date: 2026-10-15 01:35:12.319012
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e12faf9d735f"
down_revision: str | None = "cc451636df5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("novel", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "new_chapters",
                sa.Integer(),
                nullable=False,
                # Needed for existing rows: the column is NOT NULL, and an
                # existing library has novels with no value to copy in.
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("novel", schema=None) as batch_op:
        batch_op.drop_column("new_chapters")
