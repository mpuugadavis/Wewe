"""Technical controls for consuming retailer payable ledger entries.

This module does not determine settlement eligibility or calculate what a
retailer is owed. It only protects the integrity of an explicitly created
settlement and its links to payable ledger entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import RetailerPayableEntry, RetailerSettlement, RetailerSettlementLine


class RetailerSettlementControlError(ValueError):
    """Base error for invalid settlement control operations."""


class SettlementEntryConflictError(RetailerSettlementControlError):
    """A payable entry cannot be consumed by the requested settlement."""


@dataclass(frozen=True, slots=True)
class SettlementAudit:
    settlement_id: UUID
    retailer_id: UUID
    line_count: int
    line_total_ugx: int
    settlement_amount_ugx: int

    @property
    def is_balanced(self) -> bool:
        return self.line_total_ugx == self.settlement_amount_ugx


def attach_payable_entry_to_draft_settlement(
    session: Session,
    *,
    settlement_id: UUID,
    payable_entry_id: UUID,
    amount_ugx: int,
) -> RetailerSettlementLine:
    """Attach an explicit payable amount to a draft settlement.

    The caller remains responsible for deciding that the entry is eligible
    for settlement. This function only enforces ownership, lifecycle,
    positive amount, and single-consumption invariants.
    """

    if amount_ugx <= 0:
        raise RetailerSettlementControlError("amount_ugx must be greater than zero")

    settlement = session.scalar(
        select(RetailerSettlement)
        .where(RetailerSettlement.id == settlement_id)
        .with_for_update()
    )
    if settlement is None:
        raise RetailerSettlementControlError("settlement_id does not exist")
    if settlement.status != "DRAFT":
        raise RetailerSettlementControlError(
            "payable entries can only be attached to a DRAFT settlement"
        )

    entry = session.scalar(
        select(RetailerPayableEntry)
        .where(RetailerPayableEntry.id == payable_entry_id)
        .with_for_update()
    )
    if entry is None:
        raise RetailerSettlementControlError("payable_entry_id does not exist")

    if entry.retailer_id != settlement.retailer_id:
        raise SettlementEntryConflictError(
            "payable entry belongs to a different retailer"
        )
    if entry.currency != settlement.currency:
        raise SettlementEntryConflictError(
            "payable entry currency does not match settlement currency"
        )
    if entry.entry_type != "CREDIT":
        raise SettlementEntryConflictError(
            "only CREDIT payable entries can be attached to a settlement"
        )
    if amount_ugx != entry.amount_ugx:
        raise SettlementEntryConflictError(
            "settlement line must consume the full payable entry amount"
        )

    existing_total = session.scalar(
        select(func.coalesce(func.sum(RetailerSettlementLine.amount_ugx), 0)).where(
            RetailerSettlementLine.settlement_id == settlement_id
        )
    )
    if int(existing_total or 0) + amount_ugx > settlement.amount_ugx:
        raise SettlementEntryConflictError(
            "settlement lines cannot exceed the settlement amount"
        )

    existing = session.scalar(
        select(RetailerSettlementLine)
        .join(
            RetailerSettlement,
            RetailerSettlement.id == RetailerSettlementLine.settlement_id,
        )
        .where(
            RetailerSettlementLine.payable_entry_id == payable_entry_id,
            RetailerSettlement.status.in_(("DRAFT", "SUBMITTED", "SETTLED")),
        )
    )
    if existing is not None:
        raise SettlementEntryConflictError(
            "payable entry is already consumed by an active or settled settlement"
        )

    line = RetailerSettlementLine(
        settlement_id=settlement_id,
        payable_entry_id=payable_entry_id,
        amount_ugx=amount_ugx,
        currency=settlement.currency,
    )
    session.add(line)
    session.flush()
    return line


def audit_retailer_settlement(
    session: Session,
    settlement_id: UUID,
) -> SettlementAudit:
    """Return an auditable comparison of settlement amount and linked lines."""

    settlement = session.scalar(
        select(RetailerSettlement).where(RetailerSettlement.id == settlement_id)
    )
    if settlement is None:
        raise RetailerSettlementControlError("settlement_id does not exist")

    line_count, line_total = session.execute(
        select(
            func.count(RetailerSettlementLine.payable_entry_id),
            func.coalesce(func.sum(RetailerSettlementLine.amount_ugx), 0),
        ).where(RetailerSettlementLine.settlement_id == settlement_id)
    ).one()

    return SettlementAudit(
        settlement_id=settlement.id,
        retailer_id=settlement.retailer_id,
        line_count=int(line_count),
        line_total_ugx=int(line_total),
        settlement_amount_ugx=settlement.amount_ugx,
    )
