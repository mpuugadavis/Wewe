from app.models import (
    RetailerPaymentAllocation,
    RetailerPayableEntry,
    RetailerSettlement,
    RetailerSettlementLine,
)


def test_retailer_settlement_ledger_tables_exist_with_expected_guards():
    expected = {
        "retailer_payment_allocations",
        "retailer_payable_entries",
        "retailer_settlements",
        "retailer_settlement_lines",
    }
    assert expected.issubset(RetailerPaymentAllocation.metadata.tables)

    assert {
        "ck_retailer_payment_allocation_amount",
        "ck_retailer_payment_allocation_currency",
        "uq_retailer_payment_allocation_payment_fulfillment",
    }.issubset({c.name for c in RetailerPaymentAllocation.__table__.constraints})

    assert {
        "ck_retailer_payable_entry_type",
        "ck_retailer_payable_entry_amount",
        "ck_retailer_payable_entry_currency",
    }.issubset({c.name for c in RetailerPayableEntry.__table__.constraints})
    assert RetailerPayableEntry.__table__.c.source_reference.unique is True

    assert {
        "ck_retailer_settlement_status",
        "ck_retailer_settlement_amount",
        "ck_retailer_settlement_currency",
        "uq_retailer_settlement_reference",
        "uq_retailer_settlement_idempotency",
    }.issubset({c.name for c in RetailerSettlement.__table__.constraints})

    assert {
        "ck_retailer_settlement_line_amount",
        "ck_retailer_settlement_line_currency",
        "uq_retailer_settlement_line_entry",
    }.issubset({c.name for c in RetailerSettlementLine.__table__.constraints})


def test_settlement_ledger_keeps_payment_and_fulfillment_links():
    allocation = RetailerPaymentAllocation.__table__
    payable = RetailerPayableEntry.__table__
    line = RetailerSettlementLine.__table__

    assert {fk.target_fullname for fk in allocation.foreign_keys} >= {
        "payments.id",
        "retailer_fulfillments.id",
        "retailers.id",
    }
    assert {fk.target_fullname for fk in payable.foreign_keys} >= {
        "orders.id",
        "retailer_fulfillments.id",
        "payments.id",
        "retailers.id",
    }
    assert {fk.target_fullname for fk in line.foreign_keys} >= {
        "retailer_settlements.id",
        "retailer_payable_entries.id",
    }
