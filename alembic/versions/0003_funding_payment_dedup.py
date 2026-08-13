"""deduplicate simulated funding payments

Revision ID: 0003_funding_payment_dedup
Revises: 0002_paper_execution
Create Date: 2026-08-13 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0003_funding_payment_dedup"
down_revision: str | None = "0002_paper_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_funding_payment_position_ts",
        "funding_payments",
        ["position_id", "paid_at"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_funding_payment_position_ts", table_name="funding_payments")
