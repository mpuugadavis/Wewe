# WEWE Phase 5 Economics Model

## Commercial decision

WEWE uses a **marketplace commission model**, not a delivery-markup-only model.

- Customer pays: merchandise subtotal + committed delivery fee.
- Retailer payable: merchandise value less WEWE marketplace commission.
- Rider earning: funded from the committed delivery fee.
- WEWE gross marketplace revenue: commission on merchandise.
- Payment processing: modeled conservatively as a WEWE cost at the current Uganda mobile-money collection rate.
- No cash payments.
- No Flutterwave LIVE transition in this phase.

### Initial commission

**8% of merchandise subtotal** is the launch baseline.

The rate is configurable by an administrator from 0% to 30%, but the rate and resulting UGX commission are snapshotted on each new order. Changing the setting therefore affects only future orders.

### Why 8%

The model needs to remain affordable for a campus customer while producing positive gross contribution on ordinary baskets.

At the current delivery configuration, the minimum delivery charge is UGX 2,500. Flutterwave currently lists Uganda mobile-money collection at 3%; its Uganda pricing page also lists mobile-money payouts below UGX 125,000 at UGX 1,000 and payouts at or above UGX 125,001 at 1.2%. These processor costs are **not** added to the customer's checkout total by WEWE in this implementation; they are treated as a conservative platform-cost assumption for economics planning.

Illustrative gross contribution before hosting, support, taxes and other overhead:

| Merchandise | Delivery | Customer total | 8% commission | 3% collection cost | Gross contribution |
|---:|---:|---:|---:|---:|---:|
| UGX 10,000 | 2,500 | 12,500 | 800 | 375 | 425 |
| UGX 25,000 | 2,500 | 27,500 | 2,000 | 825 | 1,175 |
| UGX 50,000 | 4,500 | 54,500 | 4,000 | 1,635 | 2,365 |

This deliberately excludes retailer payout fees and operating overhead. Retailer settlement should therefore be **batched**, rather than paying out every small order individually.

### Multi-retailer orders

The existing delivery model remains:

raw fee = max(minimum fee, base fee + route distance × price/km)

with a 15% consolidation discount for orders containing at least two retailer fulfillments.

The commission is calculated only on merchandise, never on delivery. This prevents WEWE from taking commission from rider compensation.

### Accounting flow

On successful payment:

1. The order's snapshotted commission is used.
2. Merchandise value is allocated to each retailer fulfillment.
3. The retailer allocation is net of commission.
4. The allocation is posted to the retailer payable ledger.
5. Delivery money remains available for delivery earnings.
6. Every allocation is idempotent and auditable.

Historical orders are left at 0% commission by the migration so the launch does not rewrite past economics.

## Important business-policy follow-up

Before live launch, the remaining commercial controls should define:

- retailer settlement cadence/threshold;
- who bears payment processing fees in the Flutterwave dashboard;
- treatment of refunds after retailer settlement;
- taxes and statutory reporting;
- whether a future premium/advertising revenue stream is added.

These are deliberately not guessed in code.
