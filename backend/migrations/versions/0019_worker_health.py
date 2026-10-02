"""Add durable worker health state."""
from alembic import op
import sqlalchemy as sa
revision="0019_worker_health"
down_revision="0018_delivery_offers"
branch_labels=None
depends_on=None

def upgrade()->None:
    op.create_table(
        "worker_health",
        sa.Column("worker_name",sa.String(80),primary_key=True),
        sa.Column("status",sa.String(20),nullable=False),
        sa.Column("last_started_at",sa.DateTime(timezone=True)),
        sa.Column("last_heartbeat_at",sa.DateTime(timezone=True)),
        sa.Column("last_success_at",sa.DateTime(timezone=True)),
        sa.Column("last_failure_at",sa.DateTime(timezone=True)),
        sa.Column("last_duration_ms",sa.Integer()),
        sa.Column("last_processed",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("last_scanned",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("last_candidates",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("last_deleted",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("last_skipped",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("last_failed",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("last_error",sa.String(1000)),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('STARTING','RUNNING','HEALTHY','FAILING','STOPPED')",name="ck_worker_health_status"),
        sa.CheckConstraint("last_duration_ms IS NULL OR last_duration_ms >= 0",name="ck_worker_health_duration"),
        sa.CheckConstraint("last_processed >= 0 AND last_scanned >= 0 AND last_candidates >= 0 AND last_deleted >= 0 AND last_skipped >= 0 AND last_failed >= 0",name="ck_worker_health_counts"),
    )

def downgrade()->None:
    op.drop_table("worker_health")
