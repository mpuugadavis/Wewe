"""WEWE income and settlement policy.

This module exposes participant-facing accounting views and the initial retailer
settlement eligibility rule. Ledger entries remain immutable accounting facts;
settlements consume eligible credits without turning the ledger into a wallet.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    PlatformSetting,
    RetailerPayableEntry,
    RetailerSettlement,
    RetailerSettlementLine,
)

RETAILER_SETTLEMENT_POLICY_KEY = "retailer_settlement_policy"
DEFAULT_RETAILER_SETTLEMENT_THRESHOLD_UGX = 20_000


class RetailerIncomeError(ValueError):
    """Invalid retailer income policy or accounting state."""


@dataclass(frozen=True, slots=True)
class RetailerIncomeSnapshot:
    retailer_id: UUID
    gross_credits_ugx: int
    debit_adjustments_ugx: int
    ledger_balance_ugx: int
    paid_out_ugx: int
    pending_payout_ugx: int
    available_to_settle_ugx: int
    recovery_due_ugx: int
    minimum_settlement_ugx: int

    @property
    def owed_by_wewe_ugx(self) -> int:
        return max(0, self.ledger_balance_ugx - self.paid_out_ugx)

    @property
    def eligible_for_settlement(self) -> bool:
        return (
            self.recovery_due_ugx == 0
            and self.available_to_settle_ugx >= self.minimum_settlement_ugx
        )


def resolve_retailer_settlement_threshold(session: Session) -> int:
    setting = session.get(PlatformSetting, RETAILER_SETTLEMENT_POLICY_KEY)
    if setting is None:
        return DEFAULT_RETAILER_SETTLEMENT_THRESHOLD_UGX
    value = setting.value.get("minimum_ugx") if isinstance(setting.value, dict) else None
    if value is None:
        raise RetailerIncomeError("Retailer settlement policy is incomplete.")
    try:
        threshold = int(value)
    except (TypeError, ValueError):
        raise RetailerIncomeError("Retailer settlement threshold is invalid.") from None
    if threshold <= 0:
        raise RetailerIncomeError("Retailer settlement threshold must be positive.")
    return threshold


def _settlement_totals(session: Session, retailer_id: UUID) -> tuple[int, int]:
    settled = session.scalar(
        select(func.coalesce(func.sum(RetailerSettlement.amount_ugx), 0)).where(
            RetailerSettlement.retailer_id == retailer_id,
            RetailerSettlement.status == "SETTLED",
        )
    )
    pending = session.scalar(
        select(func.coalesce(func.sum(RetailerSettlement.amount_ugx), 0)).where(
            RetailerSettlement.retailer_id == retailer_id,
            RetailerSettlement.status.in_(( "DRAFT", "SUBMITTED")),
        )
    )
    return int(settled or 0), int(pending or 0)


def get_retailer_income_snapshot(
    session: Session,
    retailer_id: UUID,
) -> RetailerIncomeSnapshot:
    totals = dict(
        session.execute(
            select(
                RetailerPayableEntry.entry_type,
                func.coalesce(func.sum(RetailerPayableEntry.amount_ugx), 0),
            )
            .where(RetailerPayableEntry.retailer_id == retailer_id)
            .group_by(RetailerPayableEntry.entry_type)
        ).all()
    )
    credits = int(totals.get("CREDIT", 0))
    debits = int(totals.get("DEBIT", 0))
    ledger_balance = credits - debits
    paid_out, pending_payout = _settlement_totals(session, retailer_id)

    # Settlements are obligations already consumed by a payout instruction.
    # Failed/review settlements are deliberately excluded and therefore release
    # their linked credits back into the available pool.
    owed = ledger_balance - paid_out
    recovery_due = max(0, -owed)
    available = max(0, owed - pending_payout)

    return RetailerIncomeSnapshot(
        retailer_id=retailer_id,
        gross_credits_ugx=credits,
        debit_adjustments_ugx=debits,
        ledger_balance_ugx=ledger_balance,
        paid_out_ugx=paid_out,
        pending_payout_ugx=pending_payout,
        available_to_settle_ugx=available,
        recovery_due_ugx=recovery_due,
        minimum_settlement_ugx=resolve_retailer_settlement_threshold(session),
    )


def list_retailer_income_entries(
    session: Session,
    retailer_id: UUID,
    *,
    limit: int = 100,
) -> list[dict]:
    rows = session.scalars(
        select(RetailerPayableEntry)
        .where(RetailerPayableEntry.retailer_id == retailer_id)
        .order_by(RetailerPayableEntry.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": row.id,
            "order_id": row.order_id,
            "fulfillment_id": row.fulfillment_id,
            "entry_type": row.entry_type,
            "amount_ugx": row.amount_ugx,
            "reason": row.reason,
            "source_reference": row.source_reference,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def list_retailer_income_settlements(
    session: Session,
    retailer_id: UUID,
    *,
    limit: int = 50,
) -> list[dict]:
    rows = session.scalars(
        select(RetailerSettlement)
        .where(RetailerSettlement.retailer_id == retailer_id)
        .order_by(RetailerSettlement.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": row.id,
            "amount_ugx": row.amount_ugx,
            "status": row.status,
            "settlement_reference": row.settlement_reference,
            "payout_reference": row.payout_reference,
            "created_at": row.created_at,
            "submitted_at": row.submitted_at,
            "settled_at": row.settled_at,
        }
        for row in rows
    ]


def retailer_income_payload(session: Session, retailer_id: UUID) -> dict:
    snapshot = get_retailer_income_snapshot(session, retailer_id)
    return {
        "currency": "UGX",
        "gross_credits_ugx": snapshot.gross_credits_ugx,
        "debit_adjustments_ugx": snapshot.debit_adjustments_ugx,
        "ledger_balance_ugx": snapshot.ledger_balance_ugx,
        "owed_by_wewe_ugx": snapshot.owed_by_wewe_ugx,
        "paid_out_ugx": snapshot.paid_out_ugx,
        "pending_payout_ugx": snapshot.pending_payout_ugx,
        "available_to_settle_ugx": snapshot.available_to_settle_ugx,
        "recovery_due_ugx": snapshot.recovery_due_ugx,
        "minimum_settlement_ugx": snapshot.minimum_settlement_ugx,
        "eligible_for_settlement": snapshot.eligible_for_settlement,
        "entries": list_retailer_income_entries(session, retailer_id),
        "settlements": list_retailer_income_settlements(session, retailer_id),
    }
