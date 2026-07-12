"""add paper execution fields

Revision ID: 0002_paper_execution
Revises: 0001_initial
Create Date: 2026-07-12 00:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0002_paper_execution"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("simulated_orders", sa.Column("position_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_simulated_orders_position_id",
        "simulated_orders",
        "positions",
        ["position_id"],
        ["id"],
    )
    op.add_column("positions", sa.Column("exit_spot_price", sa.Numeric(38, 18), nullable=True))
    op.add_column("positions", sa.Column("exit_perp_price", sa.Numeric(38, 18), nullable=True))
    op.add_column("positions", sa.Column("realized_pnl", sa.Numeric(38, 18), nullable=True))
    op.add_column(
        "positions",
        sa.Column("total_fees", sa.Numeric(38, 18), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("positions", "total_fees")
    op.drop_column("positions", "realized_pnl")
    op.drop_column("positions", "exit_perp_price")
    op.drop_column("positions", "exit_spot_price")
    op.drop_constraint("fk_simulated_orders_position_id", "simulated_orders", type_="foreignkey")
    op.drop_column("simulated_orders", "position_id")
