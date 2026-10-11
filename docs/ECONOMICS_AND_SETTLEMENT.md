# WEWE Economics & Settlement Model

## Participant income tracking

WEWE records retailer and rider earnings as accounting obligations. The dashboards show those obligations continuously; they are not stored-value wallets.

### Retailers

The retailer dashboard exposes:

- **WEWE owes you** — net unpaid retailer earnings.
- **Available to settle** — the amount not already reserved in a draft/submitted payout.
- **Pending payout** — payout instructions already created/submitted but not yet settled.
- **Paid out** — historical settled payouts.
- **Recovery due** — an amount the retailer owes WEWE when a post-payout reversal/refund exceeds the unpaid balance.
- Income ledger entries and settlement history.

The initial retailer settlement threshold is **UGX 20,000**. The threshold is configurable through the "retailer_settlement_policy" platform setting and defaults to UGX 20,000 when no setting exists.

## Retailer settlement lifecycle

ELIGIBLE PAYABLE -> DRAFT -> SUBMITTED -> SETTLED

Exception states:

- FAILED
- REVIEW_REQUIRED

A payable entry linked to a failed or review-required settlement is released for re-queuing. A payable entry linked to an active or settled settlement remains protected against double payout.

## Rider income tracking

A rider's dashboard shows:

- **WEWE owes you** — unpaid delivery earnings.
- **Paid** — earnings already paid.
- payout status indicating whether the rider is awaiting the scheduled payout run.

Rider earnings remain separate from retailer payables.

## Accounting principles

1. Ledger entries are immutable facts.
2. A settlement is a payout instruction, not proof that funds were paid.
3. Only a confirmed SETTLED payout reduces the amount shown as owed.
4. Failed/review-required payout attempts do not reduce the participant's amount owed.
5. Refunds/cancellations are represented by new debit/reversal entries rather than rewriting history.
6. WEWE does not expose participant balances as withdrawable wallets.
7. Scheduled/batched payouts reduce unnecessary accumulation of third-party balances.

## Current commercial defaults

| Policy | Default |
|---|---:|
| Merchandise commission | 8% |
| Retailer settlement minimum | UGX 20,000 |
| Payment mode | Online payment only |
| Retailer payout | Scheduled/batched |
| Rider payout | Scheduled/batched |
| Flutterwave live transition | Deferred |

The actual payout rail and payout-day operations remain an administrative/payment-provider concern; the accounting layer records the obligation and settlement result independently.
