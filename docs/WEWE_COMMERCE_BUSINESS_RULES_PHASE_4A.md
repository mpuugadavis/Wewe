# WEWE Commerce Business Rules Specification — Phase 4A

**Document status:** Business specification. Delivery-pricing rules COM-FEE-001 through COM-FEE-011 and the business directions COM-PAY-001, COM-PAY-002, COM-PAY-003, COM-PAY-004, COM-SET-001, COM-CAN-001, and COM-REF-001/002 are approved. WEWE is online-payment-only; cash is out of scope, and the earlier COM-MULTI-001 cash-collection direction is not applicable. Parameters, provider capabilities, and operating procedures explicitly identified as pending still require resolution before affected implementation. Approval of a business direction does not mean that it is implemented.

**Approval key:** Only the decisions expressly identified as **APPROVED** are approved business rules. Every value, threshold, formula detail, timing, fee treatment, SLA, operational default, or capability identified as **PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL** or **PENDING PROVIDER VERIFICATION** remains unapproved. Current implementation findings describe code only; they do not constitute business policy.

**Scope:** Define the commerce behavior needed to guide controlled Phase 4 implementation. This document does not authorize a Mobile Money integration, routing integration, notification worker, infrastructure change, or deployment.

## 1. Preserved technical baseline

Unless a separately approved rule explicitly changes behavior:

- UGX remains the currency and monetary amounts remain integer UGX.
- The Phase 3 cart and checkout behavior is the baseline.
- Existing inventory reservation and conservation behavior is the baseline.
- Customer delivery confirmation-code security remains in force.
- Preserve the existing order, retailer-fulfillment, and delivery-assignment architecture.
- Existing Phase 3 tests must continue to pass.
- Alembic migrations `0001` through `0005` are immutable. Schema changes, if approved, require new migrations.

## 2. Approved initial delivery-pricing rules

The following COM-FEE rules are approved business direction for the initial WEWE model. They do not mean that the implementation already provides distance pricing.

### COM-FEE-001 — Distance-based delivery pricing

Each retailer fulfillment in a delivery order receives its own independently calculated delivery fee from the road-route distance between that retailer's pickup location and the customer's delivery location.

The initial formula is:

```text
raw_delivery_fee =
    max(minimum_fee, base_fee + (route_distance_km × price_per_km))

delivery_fee = raw_delivery_fee rounded to the nearest UGX 500
```

Approved initial parameters:

| Parameter | Initial value |
|---|---:|
| Currency | UGX |
| Minimum delivery fee | UGX 2,500 |
| Base fee | UGX 1,500 |
| Distance rate | UGX 500 per kilometre |
| Final-fee rounding increment | UGX 500 |
| Normal maximum route distance | 15 km per fulfillment leg |
| Pickup delivery fee | UGX 0 |

Example: a 5 km road route gives `UGX 1,500 + (5 × UGX 500) = UGX 4,000`, so the delivery fee is UGX 4,000. If the formula yields less than UGX 2,500, the minimum fee applies before final rounding.

Road-route distance is the customer-pricing basis when a reliable road route is available. The general distance-pricing concept is WEWE's own; this specification does not copy another platform's proprietary formula.

### COM-FEE-002 — Multi-retailer delivery pricing

Price every retailer fulfillment independently. Do not divide one order-level fee equally, assume equal retailer distances, or use an average distance.

```text
order_delivery_fee = sum(fulfillment_delivery_fee for each delivery fulfillment)
```

Example:

| Fulfillment | Road route | Delivery fee |
|---|---:|---:|
| Retailer A → customer | 2 km | UGX 2,500 |
| Retailer B → customer | 5 km | UGX 4,000 |
| **Order delivery fee** | | **UGX 6,500** |

Each fulfillment owns and retains its own delivery-fee amount and quote inputs.

### COM-FEE-003 — Pickup pricing

Customer pickup from a retailer or approved WEWE pickup point has a delivery fee of **UGX 0**. No separate pickup charge is included in the initial model.

If WEWE later transports goods from retailers to a central pickup point, that is a separate logistics service and requires a separate pricing decision.

### COM-FEE-004 — Road-route distance

Prefer road-route distance from a routing service. Straight-line/geodesic distance may be used for internal approximation or preliminary estimation, but it must not be the final customer-pricing distance when a reliable road route is available.

The future implementation should retain, where applicable:

- Retailer pickup location and customer delivery location.
- Coordinates or immutable location references used for the quote.
- Calculated road distance in kilometres, with its precision/units.
- Route calculation timestamp and routing-provider/reference.
- Pricing configuration/version and inputs used.
- Resulting integer-UGX delivery fee.

The routing provider and API are not selected in Phase 4A.

### COM-FEE-005 — Pricing snapshot

Calculate and show the delivery fee before the customer places the order. On checkout, snapshot each fulfillment's calculation and fee. Later pricing-configuration changes must not change an existing order.

A different route taken by the agent or reassignment of an agent does not automatically increase the customer's fee. A route correction after checkout requires an explicit, recorded adjustment; it must not silently overwrite the original quote.

### COM-FEE-006 — Retailer rejection

Each fulfillment owns its own fee. If a retailer rejects its fulfillment, remove that fulfillment's stored delivery-fee allocation in accordance with the applicable order/refund rules. Other retailers' fees remain unchanged and must not be recalculated because of the rejection.

Payment and refund consequences are governed by the separately approved payment/refund rules; this pricing rule does not itself authorize or execute a refund.

### COM-FEE-007 — Customer delivery fee vs courier payout

Customer delivery fees and delivery-agent earnings are separate concepts. The whole customer delivery fee must not automatically become the courier's earning. Do not infer a courier commission or percentage from the customer fee.

Agent earnings are governed separately by COM-PAY-001 and COM-PAY-002. Their model directions are approved; payout parameters and allocation/settlement procedures remain pending.

### COM-FEE-008 — Initial pricing parameters

The table in COM-FEE-001 is the initial approved configuration: minimum UGX 2,500, base UGX 1,500, rate UGX 500/km, nearest-UGX-500 rounding, normal maximum 15 km, and zero delivery fee for pickup. These parameters may be reviewed and changed only through an explicit business decision. When implemented, they are configuration values, not permanent hard-coded constants.

### COM-FEE-009 — Routing failure

If a valid road-route distance cannot be obtained, do not silently invent a distance or present an unsupported delivery price. The preferred initial handling is to prevent delivery checkout until a valid quote is available, or allow pickup if available. Do not implement an automatic fallback distance or price. Any future fallback pricing requires a separate business decision.

### COM-FEE-010 — Future pricing extensions

The initial model excludes surge/demand, time-based, weather-based, category-specific, and other dynamic pricing; automatic delivery-fee discounts; loyalty/free-delivery thresholds; batching or route-optimization discounts; and other promotions. These must not be hidden inside the initial formula. Any later inclusion requires a separate business decision.

### COM-FEE-011 — Pricing philosophy

- Shorter distance uses the affordable minimum fee.
- Longer distance has a progressively higher distance-based charge.
- Multiple retailers have independently priced fulfillment legs.
- Pickup has a UGX 0 delivery fee.
- The customer delivery price is locked at checkout, subject only to explicit recorded adjustment rules.
- Courier payout is a separate business rule.
- Road distance is the preferred basis for customer pricing.

### Pricing clarifications to resolve before implementation

The business has approved the initial values and model. The following details are not specified by that approval and must not be silently invented:

- Tie-breaking behavior when a calculated amount lies exactly halfway between UGX 500 increments.
- Whether the 15 km threshold is applied per fulfillment leg (the interpretation used above) or to another route/order measure.
- What “restricted/quote-based” means operationally beyond 15 km, including who can issue/approve a quote and whether checkout is blocked until approval.
- Coordinate accuracy/validation thresholds and location correction handling.
- The routing provider, API, availability guarantees, and acceptable definition of a “reliable” route.
- Approval and customer-consent process for a post-checkout routing correction that changes the price.

Until these are resolved, do not enable unsupported route cases or silently substitute a different charge.

## 3. Current commerce implementation (observed, not approval)

The following describes the audited Phase 3 implementation only:

- Checkout uses a configurable flat fee, defaulting to UGX 3,500 per retailer fulfillment for delivery; pickup currently has no delivery fee. No road routing is implemented.
- Checkout snapshots item prices and order amounts; it reserves stock, creates one retailer fulfillment per retailer, and creates one delivery assignment per delivery fulfillment.
- Orders and order items have database arithmetic checks for order total and line total. Inventory checks enforce nonnegative quantities and reservations no greater than stock.
- Order idempotency is supported through an optional customer-scoped `Idempotency-Key`; payment creation has no equivalent idempotency key.
- A payment provider registry interface exists, but no Mobile Money provider is registered.
- Payment initiation commits a pending payment before calling the provider. An exception marks it failed even though a provider could have accepted the request before a timeout.
- Payment states currently are `PENDING`, `SUCCESSFUL`, `FAILED`, and `REFUNDED`. There are no explicit expired, uncertain/reconciliation, or refund-pending states.
- Customer cancellation is currently order-wide and allowed only for selected early order states. It is blocked by an accepted/picked-up/out-for-delivery assignment, pending Mobile Money, or successful payment; this conflicts with the approved fulfillment-level pre-pickup cancellation direction and is an implementation gap, not a business rule.
- Retailers can accept/reject a whole pending fulfillment, then move accepted work through preparing and ready.
- Delivery agents can accept, pick up, move out for delivery, and complete with the customer confirmation code. Agent release/reassignment is not supported.
- Cash payments are currently marked successful on the first completed assignment in a multi-fulfillment delivery order. This is legacy implementation behavior and is out of scope under the current online-payment-only decision; do not design or extend cash collection from this observation.
- Admin refund confirmation changes the full payment record to `REFUNDED` using an operator-supplied reference; the route does not execute or independently verify a provider transfer. There is no partial-refund amount ledger.
- Delivery earnings are created on completion and manually marked paid by an admin. Current calculation divides delivery fee by non-cancelled assignments using integer division; customer fees are not thereby approved as agent pay.

## 4. Approved directions and remaining decisions

The business directions below are approved. Each section separately identifies the current implementation and the parameters or operating procedures that remain pending. Approval does not authorize or imply implementation.

### COM-PAY-001 — Agent payout basis

- **APPROVED model:** `courier_payout = base_payout + (eligible_distance_km × courier_rate_per_km)`.
- **Rules:** Courier payout is independent of the customer's delivery fee; it must not simply be a percentage or division of that charge. Customer delivery pricing and courier compensation are separate calculations. Payout inputs must eventually be snapshotted for each earning. Reassignment must not result in double payment for the same work.
- **CURRENT IMPLEMENTATION:** Earning is currently derived by dividing the order delivery fee among non-cancelled assignments using integer division. This can discard a remainder and differs from the approved model.
- **PENDING BUSINESS APPROVAL:** Base payout; courier rate per kilometre; minimum/maximum payout; distance source/method; rounding; qualifying delivery work; payout timing; multiple-agent allocation; reassignment allocation; failed-pickup/cancellation/partial-delivery compensation; return-trip compensation; decline/custody rules.
- **PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL:** Initial Makerere/campus pilot values and operating defaults are set out below. They are proposals only and must not be treated as approved configuration or implemented as policy until explicitly approved.

| Parameter | Proposed initial rule | Reason | Requires explicit approval? |
|---|---|---|---|
| Base payout | UGX 1,000 per completed fulfillment, counted once regardless of agent count | Provides a simple minimum component for a completed pickup-to-customer service without tying compensation to customer price | Yes |
| Courier rate | UGX 300 per eligible road-route kilometre | A modest, linear distance component is simple to explain and grows with service effort on short urban trips | Yes |
| Minimum payout | UGX 1,500 per qualifying completed fulfillment, before multi-agent allocation | Avoids a very low payout for the shortest trips | Yes |
| Maximum payout | No separate monetary cap proposed; cap aggregate eligible distance at 15 km per fulfillment, including any authorized return route, yielding a maximum formula amount of UGX 5,500 before allocation | The distance cap bounds payout exposure without adding an arbitrary monetary ceiling; beyond-normal-distance jobs need an explicit quote/decision | Yes |
| Distance source | Road-route distance from a verified routing provider using the fulfillment's snapshotted retailer pickup and customer destination | Prevents agent-selected GPS traces or detours from inflating payout and uses the same auditable route basis as the customer quote without reusing its fee | Yes, including provider verification |
| Eligible distance | For normal completion, the one-way pickup-to-customer road route snapshotted for that fulfillment; for an approved return, only separately verified route segments actually completed as part of that authorized return, with no duplicate counting. Cap total payable eligible distance at 15 km per fulfillment, including return segments | Makes the payable route reproducible and prevents detours, repeated traversals, or unapproved destinations from increasing it | Yes |
| Distance measurement | Store route distance to 0.1 km for the immutable pickup/destination pair and route/configuration version; use the snapshot for payout | Stable quote inputs are auditable; agent GPS is not the pricing meter | Yes |
| Rounding | Calculate the fulfillment total in UGX; round to nearest UGX 100, with exact ties rounded upward. Allocate rounded whole-UGX components with a deterministic remainder rule so allocations sum exactly to the fulfillment payable | Easy to communicate and avoids fractional-UGX amounts or lost allocations | Yes |
| Delivery eligibility | Create a provisional earning when delivery is completed with required customer confirmation; make it eligible for settlement after a proposed 24-hour exception-review period if no unresolved dispute, fraud flag, or missing evidence exists | Uses the existing confirmation-code control and gives a short review window before settlement; the hold is a proposed operating rule, not a legal requirement | Yes |
| Earning creation timing | Create one fulfillment-level earning record at confirmed delivery; corrections must be auditable adjustments, not duplicate earning rows | Keeps earning tied to an objectively recorded completion event | Yes |
| One-agent fulfillment | Pay that agent the full approved fulfillment amount after eligibility conditions are met | Straightforward default for the ordinary case | Yes |
| Multiple agents/reassignment | Before pickup, an authorized reassignment transfers the complete earning entitlement to the replacement agent; the outgoing agent receives no delivery payout. After pickup, allow only an authorized, event-recorded custody handoff. Split the single base component equally between distinct agents who completed a verified service segment; allocate the distance component in proportion to verified, non-overlapping route segments. Cap aggregate eligible segment distance at 15 km per fulfillment, including any separately authorized return route. | Pays for recorded work, not assignment count; prevents duplicate full payouts and preserves the approved payable | Yes |
| Failed pickup | No delivery earning if the retailer cancels, goods are unavailable, or the agent does not obtain custody. No automatic callout payment is proposed; any exception compensation requires a separately approved reason/evidence rule | Avoids paying a delivery earning for a service that did not reach pickup; recognizes this leaves callout costs uncompensated | Yes |
| Customer cancellation before pickup | No courier earning for the fulfillment; a pre-pickup assignment does not create payable service | No goods were taken into delivery custody and no delivery service was completed | Yes |
| Customer refusal after pickup / failed delivery | Treat refusal as an exception, not a delivered fulfillment. If an authorized return to the retailer is completed and custody is verified, propose one base component plus the rate for verified outbound/return route segments, with total eligible distance capped at 15 km per fulfillment. No completed return, missing custody evidence, or suspected agent fault means hold for review, not automatic payout. | Recognizes verified work while requiring custody and destination evidence; prevents an unverified failed-delivery claim from triggering full payout | Yes |
| Partial delivery | Pay only for a fulfillment the customer has accepted as delivered, once. A partial quantity within one retailer fulfillment is not automatically payable under this proposal; hold for an approved exception decision. | Preserves a clear link between customer acceptance and earning; avoids duplicating the full fulfillment payout | Yes |
| Return-trip compensation | No return mileage is included in an ordinary successful delivery. Count a return route only when an authorized return is required, completed, and evidenced; do not add a second base payout for the same fulfillment. | Does not reward optional detours and pays additional distance only for an approved service obligation | Yes |
| Decline/custody | Declining before accepting, or authorized release before pickup, earns no delivery payout. After pickup, no informal handoff: record authorizing actor, outgoing/incoming agent, time, condition, and custody acceptance. Pay each distinct verified segment at most once; unresolved/lost-custody cases remain on hold for review. | Limits fabricated work and protects goods and payout evidence | Yes |
| Payout settlement timing | Keep the actual settlement cadence and rail unresolved; current admin marking-paid behavior is not a proposed rail or timing commitment | Avoids assuming operational capacity, provider support, or funding terms not established in Phase 4A | Yes |

- **Proposal assumptions:** These UGX values are starting points for a small Makerere/campus pilot, not market-verified wage guidance. The recommendation assumes short urban routes, ordinary single-agent completion, a 15 km normal service limit, reliable route snapshots, and enough order/commission economics to support the proposed courier cost. WEWE has not provided a route-cost survey, agent earnings target, volume forecast, or retailer/platform contribution analysis; validate those before approval.
- **Proposed calculation:** `eligible_distance_km = min(15, verified_eligible_route_distance_km)`; `raw_courier_payout_ugx = max(1500, 1000 + (eligible_distance_km × 300))`; `courier_payout_ugx = raw_courier_payout_ugx rounded to nearest UGX 100 (ties upward)`. For 15 km, the amount is UGX 5,500. Any authorized return distance counts within the same 15 km aggregate cap and is not silently assumed by the ordinary formula.
- **Status:** **APPROVED MODEL; PARAMETERS AND OPERATING RULES PENDING BUSINESS APPROVAL**.

### COM-PAY-002 — Multiple agents and payout settlement

- **APPROVED direction:** Multiple agents and reassignments must be supported without double-paying for the same work. Agent allocations and settlement evidence must be auditable. The approved payable must be fully conserved, with no silently discarded remainder.
- **CURRENT IMPLEMENTATION:** Reassignment is unsupported; an admin can mark a pending earning paid with a reference, without executing or verifying the transfer.
- **PENDING:** Allocation formula; reassignment formula; rounding/remainder treatment; payout authorization; settlement timing; payout evidence; payout rail; dispute/adjustment process.
- **PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL:** Apply the COM-PAY-001 proposal: an authorized pre-pickup reassignment transfers the single payout entitlement to the replacement agent; after pickup, record an authorized custody handoff and allocate the one fulfillment payable by equal shares of the base component, including any top-up required to meet the minimum, among agents completing verified distinct service segments, plus distance-component shares proportional to non-overlapping verified route-segment distances. Cap aggregate eligible distance at 15 km per fulfillment, including any separately authorized return route. Calculate and round the fulfillment amount once, then allocate whole-UGX shares; assign any indivisible remainder to the agent with the final verified segment, with the same rule applied consistently and auditable. The sum of agent allocations must equal the fulfillment payable exactly. More than one handoff, or a segment with missing evidence, is held for manual review rather than generating an additional full payout.
- **Still pending explicit approval:** Whether this proposed split, evidence standard, single-base rule, remainder recipient, and exception handling are acceptable. These defaults do not change the approved requirement for support, auditability, no duplicate payment, and conservation.
- **Status:** **DIRECTION APPROVED; ALLOCATION AND SETTLEMENT RULES PENDING**.

### COM-PAY-003 — Payment lifecycle

- **APPROVED direction:** WEWE must distinguish an `UNKNOWN/UNCERTAIN` payment outcome from `FAILED`. An uncertain payment must not immediately be retried; a new charge attempt is blocked until the original attempt is reconciled or resolved. Every uncertain attempt requires a reconciliation path. Where the selected provider supports an authoritative status query, WEWE should use it where appropriate. Duplicate and late callbacks must be handled idempotently. A late success must not create a duplicate charge or automatically restart a cancelled order.
- **CURRENT IMPLEMENTATION:** Payment records use `PENDING`, `SUCCESSFUL`, `FAILED`, and `REFUNDED`; the schema still cannot persist `UNKNOWN/UNCERTAIN`. Initiation creates and commits a pending record before calling the provider; timeouts and connection errors return an uncertain-result error while leaving the attempt `PENDING`, which blocks another attempt. There is no provider status-query method, expiry process, or reconciliation worker. The webhook requires a signature and registered adapter verification, correlates by provider reference/provider name, and checks amount and currency; it does not separately validate a merchant/account identifier or callback order reference. Exact event-ID replay is acknowledged as duplicate; same-status events do not repeat effects and conflicting terminal transitions are rejected. Late success after local `FAILED` is therefore rejected rather than reconciled. A validated `SUCCESSFUL` callback for a cancelled order updates payment aggregation without reopening the order, but there is no explicit cancelled-order exception/refund handling. Customer cancellation no longer blocks solely because a non-cash payment is `PENDING`. Refund recording is a separate admin/provider callback path; the current admin route records a supplied external reference as refunded without executing or verifying the transfer. No payment expiry behavior exists.
- **Technical implementation choice:** Exact persisted state names and state-transition implementation are for engineering design later; this does not alter the approved behavior.
- **PENDING:** Uncertain-state duration; reconciliation frequency; maximum reconciliation attempts/period; expiry criteria; customer-facing timeout wording; manual resolution procedure.
- **PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL:** Initial payment lifecycle operating parameters are set out below. These are proposals, not approved settings; they do not change the approved COM-PAY-003 direction.

| Parameter | Proposed initial policy | Reason | Requires explicit approval? |
|---|---|---|---|
| Uncertain duration and automatic reconciliation window | Reconcile automatically for up to 30 minutes from the first uncertain result. Do not change the provider outcome to confirmed failure when this window ends. | Balances a bounded support window against delayed provider processing and prolonged customer uncertainty | Yes |
| Reconciliation schedule | Query immediately when uncertainty is detected; then at 1, 3, 5, 10, 15, and 30 minutes after that detection. Stop automated queries after the 30-minute attempt. Use a provider status query only if that provider's authoritative capability is verified. | Gives faster early resolution with a finite schedule, avoids unbounded polling, and does not assume provider query availability | Yes |
| After automatic window | Keep the payment outcome unresolved in a distinct pending/manual-review condition; do not label it `FAILED` or `EXPIRED` as if provider failure were proven. Block further charge attempts until authoritative reconciliation or an explicitly authorized human resolution. | Window expiry is a workflow escalation, not proof of transaction outcome | Yes |
| Customer-facing status | While unresolved: **“Payment confirmation pending. We’re checking your payment. Do not pay again yet.”** After 30 minutes without resolution: **“Payment still needs confirmation. Please contact WEWE support; do not make another payment yet.”** Show “Payment failed” only after authoritative failure or an approved, evidenced manual determination; show “Payment successful” only after validated success. | Avoids falsely reporting failure and reduces accidental duplicate payments | Yes |
| Retry policy | `SUCCESSFUL`: no retry for the same amount/order. `PENDING`: no retry. `UNKNOWN/UNCERTAIN` or manual-review unresolved: no retry. `FAILED`: retry allowed only after an authoritative provider failure or approved/evidenced manual failure resolution, and only if the order remains payable and active. `REFUNDED`: no retry against the refunded attempt; a new attempt may be created only if a remaining amount is legitimately due on an active order under the approved refund/order rules. App/browser closure changes nothing; the attempt remains queryable and blocks retry. | Makes retry depend on resolved transaction evidence, not client behavior or elapsed time alone | Yes |
| Duplicate and matching callbacks | Authenticate and correlate first. An exact repeated event is acknowledged as a duplicate with no financial effect. A different event ID reporting the same transaction and same status is recorded/treated idempotently, with no repeated payment, notification, or order effect. | Event IDs may differ across provider retries; transaction-level idempotency is required too | Yes |
| Conflicting/out-of-order callbacks | Do not accept “last callback wins.” Preserve every authenticated, correlated event for audit. A conflicting status for the same provider transaction is held as a conflict pending an authoritative status query or manual review; do not apply another financial effect until resolved. A refund event may follow a confirmed success only after refund validation; success after confirmed refund does not undo the refund. A failure after confirmed success does not reverse success without authoritative correction and review. | Provider event arrival order alone does not prove transaction chronology or finality | Yes |
| Provider-authoritative override | A provider query may resolve local uncertainty only when the provider, account, transaction, amount, currency, and status semantics are verified as authoritative for the relevant transaction. A query result may resolve an uncertain state to success/failure or confirm refund; it must not silently reverse an already completed contradictory financial outcome. Any conflict with a previously confirmed result is escalated for review. | Prevents unverified or stale status responses from overriding trusted records | Yes |
| Late success after order cancellation | Do not reopen or restart the order. Mark the payment outcome as provider-confirmed success only after normal authenticity/reference/amount validation, then place the captured amount in the cancelled-order exception process. Proposed default: hold for manual reconciliation and refund the confirmed captured amount through COM-REF-001, using provider execution if verified/available or the approved external/manual process. Do not state refund completion until confirmed evidence exists. | Avoids fulfilling a cancelled order while ensuring confirmed customer funds are not silently retained or misreported as failed | Yes |
| Payment expiry | At the end of the 30-minute automated window, expire automated reconciliation only; do not infer provider failure. Keep the outcome distinguishable as unresolved/manual-review (exact persisted label is technical design), and keep retry blocked. If a later provider success arrives, apply the late-success exception path; if authoritative failure is established, resolve to failure and permit retry only under the retry policy. | Distinguishes a local waiting limit from the provider's actual financial outcome | Yes |
| Manual resolution | Trigger after the 30-minute window; on provider/local status conflict; on missing or mismatched reference/amount/currency/account; on callback authentication or event-correlation anomalies; or on a late success after cancellation/refund. Proposed authorized role: designated payments/finance administrator, not an agent or customer. Require provider dashboard/status evidence or independently verified external payment/refund evidence, plus linked WEWE payment/order references, amount/currency, provider transaction reference, timestamps, reason, and reviewer identity. Allowed outcomes: confirmed success, confirmed failure, confirmed refund, or remain unresolved/escalate; never force failure solely to clear a queue. Record decision, evidence references, actor, time, prior/new conceptual outcome, and any refund/adjustment as an auditable event. | Human resolution needs separation from unsupported assumptions and a reviewable record | Yes |
| Callback validation | Before accepting success, verify provider authenticity/signature using the provider's verified mechanism; WEWE payment reference; provider transaction/reference; order reference; expected UGX amount and currency; merchant/account identifier; event ID; provider identity; and consistency with the stored attempt. Missing, invalid, or mismatched data must be rejected/quarantined for review and must not mark payment successful. Provider-specific fields/guarantees remain unverified until COM-PAY-004 verification. | Prevents misapplied or forged callbacks and cross-order/amount credit | Yes |
| Reconciliation/accounting invariants | One provider transaction maps to at most one successful WEWE payment. One payment produces each financial/order effect at most once. Cumulative confirmed refunds never exceed captured UGX. An uncertain attempt cannot be blindly retried. Late success never restarts a cancelled order. Duplicate callbacks produce no duplicate financial effects. | Core loss-prevention and accounting invariants across retries, callbacks, cancellation, and refunds | Yes |

- **Proposed lifecycle (conceptual; not an approved database enum):**

  ```text
  PENDING → SUCCESSFUL
      ├──→ FAILED (only on authoritative/approved resolution)
      └──→ UNKNOWN/UNCERTAIN → scheduled reconciliation
                              ├──→ SUCCESSFUL (validated)
                              ├──→ FAILED (authoritatively resolved)
                              └──→ unresolved/manual review after 30 minutes

  SUCCESSFUL → refund requested → submitted/initiated
                                ├──→ refund confirmed
                                └──→ refund failed / manual review
  ```

  `UNKNOWN/UNCERTAIN` and the post-window manual-review condition must not be treated as confirmed failure. A cancelled order remains cancelled if payment later succeeds; route the captured amount to the exception/refund process.
- **Status:** Approved direction remains unchanged. All timing, retry, customer wording, validation, exception/refund, and manual-operation details above are **PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL**. Provider-specific behavior remains **PENDING PROVIDER VERIFICATION**; persisted state names remain an engineering choice.

### COM-PAY-004 — Mobile Money provider selection and capabilities

- **APPROVED payment scope and target providers:** WEWE is online-payment-only; cash is out of scope. Customer online payment methods target MTN Mobile Money and Airtel Money, using separate provider adapters behind a common WEWE payment contract. Both providers require separate onboarding and qualification/testing.
- **CURRENT IMPLEMENTATION:** A registry interface supports initiation and webhook verification; no Mobile Money provider is registered.
- **PENDING PROVIDER VERIFICATION:** API/integration mechanism; initiation behavior; callback/webhook behavior; status-query capability; refund API; provider idempotency; sandbox availability and limitations; transaction/reference semantics; settlement/reconciliation process; provider fees; production onboarding; credential requirements.
- **Capability constraint:** Do not claim that either provider currently supports any listed capability until it has been verified for WEWE's intended account/product and environment.
- **Status:** **TARGET PROVIDERS APPROVED; CAPABILITIES PENDING PROVIDER VERIFICATION**.

### COM-SET-001 — Retailer settlement

- **APPROVED operating direction:** WEWE intends to collect/hold customer funds and subsequently settle appropriate amounts to retailers.
- **APPROVED separation:** Distinguish customer payment received by WEWE, retailer payable, refunds/adjustments, any separately approved WEWE/platform amount, customer delivery economics, and courier payout. Do not treat the order total or customer delivery fee as retailer payout/revenue by default. Courier payout is separately governed by COM-PAY-001/002.
- **CURRENT IMPLEMENTATION:** No retailer payable ledger, retailer commission calculation, settlement eligibility/cadence/threshold/method, settlement record, or retailer payout route was found. Payments are order-level; the customer payment amount is the order total. Refund handling is status-based rather than a retailer allocation/recovery ledger. Delivery earnings are separate and are not retailer settlement. No code should be inferred to hold or settle retailer funds merely because a customer payment record exists.
- **PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL:** Initial settlement parameters below are a proposed Makerere/campus operating model, not approved amounts, terms, or authority. Illustrative figures in examples are not a commission proposal.
- **Proposed settlement invariants — PENDING EXPLICIT BUSINESS APPROVAL:** WEWE must not settle more than the net value attributable to fulfilled/accepted goods and captured online funds allocated to those goods. Rejected/cancelled/undelivered goods are excluded. Customer delivery fees are not retailer revenue by default; courier payout and online processing fees remain separate ledger amounts. A confirmed customer refund reduces unsettled retailer payable; if the related retailer amount was already settled, record a recoverable retailer balance or authorized future-settlement offset before treating the matter as closed. No recovery is assumed without an approved agreement. A unique settlement instruction/reference and atomic status transition must prevent duplicate transfers. Every settlement and adjustment must reconcile to retailer, order, fulfillment, source payment(s), refund/adjustment evidence, and final payable. Disputed amounts remain explicitly held, not erased or paid twice.

| Parameter | Proposed initial rule | Reason | Requires explicit approval? |
|---|---|---|---|
| Retailer payable calculation | Per fulfillment: `retailer_gross = value of goods actually delivered and accepted, net of retailer-funded discounts`; `retailer_payable = retailer_gross - approved retailer-specific deductions - confirmed refunds/adjustments attributable to those goods`. Do not use order gross/total directly. | Bases payable on fulfilled goods and makes adjustments traceable to a retailer fulfillment | Yes |
| Product/fulfillment value | Use the final checkout-snapshotted line prices for quantities actually accepted as delivered; do not use current listing prices. Exclude rejected, cancelled, undelivered, or unaccepted quantities. | Protects both parties from later catalog-price changes and prevents paying for undelivered goods | Yes |
| Discounts | Attribute each discount to a funding party at checkout. Proposed default: retailer-funded discount reduces retailer gross; WEWE-funded discount does not reduce retailer gross only if WEWE actually funds/credits the discount and the retailer agreement says so. Unattributed discounts remain held/unsettled pending clarification. | Prevents silently charging a discount to the wrong party | Yes |
| Delivery fees | Exclude customer delivery fees from retailer gross/payable unless a separately approved retailer agreement expressly allocates an amount to the retailer. Do not allocate equally by default. | Keeps delivery revenue distinct from merchandise settlement | Yes |
| WEWE/platform fee or commission | No commission percentage is established. Proposed initial treatment: apply no WEWE/platform deduction to retailer payable until a written business/retailer agreement specifies the fee, calculation base, and effective date. | Avoids inventing a commission and prevents undisclosed deductions | Yes |
| Payment-processing fees | Record provider transaction fees as a separate order/payment cost, not as a hidden retailer deduction. Proposed default is WEWE bears them unless an approved retailer agreement expressly allocates them. MTN/Airtel fees remain unverified. | Makes processing cost visible and avoids assuming provider tariffs or pass-through rights | Yes; provider costs also require verification |
| Settlement eligibility | A fulfillment becomes eligible only after its goods are confirmed delivered and accepted, the associated payment funds are confirmed captured and attributable, and no open dispute/refund/cancellation/chargeback hold applies. | Avoids paying against pending funds, undelivered goods, or unresolved liabilities | Yes |
| Hold period | Proposed 7 calendar days after confirmed delivery/acceptance, extended while a dispute, refund, chargeback, or reconciliation is open. This is a proposed risk-control hold, not a legal or statutory period. | Allows initial support/reconciliation while remaining simple to administer | Yes |
| Settlement cadence | Proposed weekly batch on Tuesday for eligible, undisputed balances; balances below threshold or under hold roll forward, with a ledger statement each cycle. | Predictable, operationally simple cadence for an initial campus service | Yes |
| Partial fulfillment | Create payable only for delivered/accepted quantities at their checkout-snapshotted prices. Hold unfulfilled quantities until delivery; exclude them if rejected/cancelled. If the current system cannot record quantity-level acceptance, hold the disputed/partial fulfillment for review rather than assume the full amount is payable. | Aligns retailer payment with actual accepted supply | Yes |
| Retailer rejection | Exclude rejected fulfillment goods and its associated retailer-funded discount/adjustments from payable. If rejected after capture, create a customer refund obligation under COM-REF-001/002; do not settle rejected goods. | Prevents settlement for goods not supplied and links rejection to payment correction | Yes |
| Customer cancellation | Before goods are delivered/accepted, exclude cancelled goods from payable and refund captured amounts attributable to them. After preparation begins, do not invent retailer compensation; hold any requested preparation/cancellation charge until a separate agreement and approval authorizes it. | Separates goods payable from any possible cancellation compensation | Yes |
| Full/partial refunds | Only confirmed refunds reduce captured funds and the attributable retailer payable. Allocate a refund to the originating payment and fulfillment/item/fee component using an approved allocation record. Before settlement, reduce the payable. After settlement, propose recovery by offset against future retailer settlements or a separately recorded retailer receivable; no silent deduction or assumed clawback. | Prevents both customer over-refund and untracked retailer overpayment | Yes |
| Multiple successful payments | Reconcile all successful payment attempts by unique provider transaction/reference and captured amount. Allocate captured funds to order/fulfillment components once; never count payment attempts twice. Settlement availability is limited to funds actually captured and attributable to the relevant delivered goods after confirmed refunds. | Handles split/retried payments while preventing duplicate funding attribution | Yes |
| Threshold | Proposed minimum batch payout: UGX 50,000 per retailer; smaller positive balances roll forward and remain visible as payable, not forfeited. No maximum balance is proposed; held/disputed amounts remain separately identified. | Reduces transfer overhead without extinguishing small retailer balances | Yes |
| Settlement method | Proposed initial operational method: finance-approved manual transfer to a verified retailer-owned destination, with independent confirmation/reference and retailer remittance statement. Do not assume a bank or mobile-money payout API exists; automate only after provider, account, and control verification. | Practical without asserting unverified payout-rail capability | Yes |
| Settlement record and auditability | Each settlement must link retailer, order, fulfillment, relevant successful payment(s), gross merchandise amount, discount source, each deduction/adjustment/refund, final payable, settlement status, unique settlement reference, settlement timestamp, authorized actor, and evidence/statement. Preserve adjustments as linked entries; do not overwrite history. | Provides end-to-end reconciliation and dispute evidence | Yes |
| Disputes and adjustments | Place only the disputed amount on hold; keep undisputed eligible balance payable unless a documented risk reason requires broader hold. Record reason, claimant, evidence, owner, status, decision, and adjustment linkage. No disputed amount may disappear or be settled twice. | Limits unnecessary withholding while preserving a clear audit trail | Yes |
| Taxes/withholding | No tax or withholding treatment is asserted. Obtain appropriate Uganda business/accounting confirmation on invoicing, tax reporting, withholding responsibility/rates, and required settlement records before launch. | Avoids unsupported legal or tax conclusions | Yes; business/accounting confirmation required |
| Idempotency and fund conservation | A settlement instruction/reference is unique and idempotent; a repeated request returns the existing outcome or is rejected without a second transfer. A retailer's cumulative settlements, less recoveries, must not exceed its net eligible payable or captured funds attributable to fulfilled goods. | Prevents duplicate payment and over-settlement | Yes |

- **Settlement lifecycle (conceptual):** `FULFILLMENT_DELIVERED/ACCEPTED → PAYMENT_CAPTURE_CONFIRMED_AND_ALLOCATED → PAYABLE_ACCRUED → HOLD/DISPUTE/REFUND_ADJUSTMENT (if applicable) → ELIGIBLE → SETTLEMENT_SUBMITTED → SETTLED` or `SETTLEMENT_FAILED/RETRY_REVIEW`. A confirmed refund after settlement creates a linked retailer recovery/receivable or future-settlement offset under an approved agreement. Exact persisted states are an engineering choice; a submission is not settlement confirmation.
- **Illustrative example 1 — normal order (figures solely for arithmetic illustration):** customer pays UGX 100,000 for retailer A goods, with no retailer-funded discount. Retailer gross is UGX 100,000. No platform commission is deducted under the proposal pending an agreement; delivery fee and online processing fee are separate and excluded from retailer gross. Final retailer payable before any confirmed refund is UGX 100,000, limited to captured funds attributable to those goods.
- **Illustrative example 2 — rejection/partial fulfillment:** retailer A fulfillment contains two accepted lines totaling UGX 80,000 and one rejected line worth UGX 20,000. Retailer gross/payable is UGX 80,000, not UGX 100,000; rejected goods are excluded. If only UGX 80,000 worth is confirmed delivered in a partial fulfillment, accrue only UGX 80,000 and hold/exclude the remaining UGX 20,000 according to its eventual delivery/rejection outcome. Any captured amount attributable to rejected goods is subject to customer refund, not retailer settlement.
- **Illustrative example 3 — refund:** retailer A has UGX 100,000 eligible gross. A confirmed UGX 10,000 refund attributable to A's goods before settlement reduces payable to UGX 90,000. If UGX 100,000 was already settled, record a UGX 10,000 retailer receivable/approved future-settlement offset; do not silently make a second customer refund or assume unrecoverable amounts vanish.
- **Illustrative example 4 — two retailers:** one online customer order has retailer A delivered goods of UGX 60,000 and retailer B delivered goods of UGX 40,000. Excluding delivery economics and unapproved deductions, A's separate payable is UGX 60,000 and B's is UGX 40,000, each reconciled to the captured payment allocation and their own adjustments. The order's aggregate UGX 100,000 merchandise value is not one retailer's payout; delivery fee, courier payout, and provider fee are separate.
- **UNRESOLVED / REQUIRES BUSINESS OR ACCOUNTING CONFIRMATION:** Discount funding/allocation and contractual treatment; commission existence, base, and rate (no rate is proposed); payment-fee bearer and provider tariffs; settlement eligibility evidence and hold/cadence; partial-quantity support; cancellation-after-preparation compensation; refund allocation and post-settlement recovery authority; multiple-payment allocation; UGX 50,000 threshold; transfer method and destination controls; tax/withholding/invoicing; chargeback/dispute/negative-balance handling; and authorized approval/segregation of duties.
- **Status:** **APPROVED OPERATING DIRECTION; PARAMETERS ARE PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL; tax, provider, and contractual matters remain UNRESOLVED / REQUIRES BUSINESS OR ACCOUNTING CONFIRMATION**.

### COM-CAN-001 — Customer cancellation by stage

- **APPROVED:** A customer may cancel until the relevant fulfillment has been physically picked up by a delivery agent. `PENDING`, `CONFIRMED`, `PREPARING`, and `READY` do not by themselves close the cancellation window. Assignment or agent acceptance is not physical pickup. After verified physical pickup, ordinary customer cancellation is not permitted; use delivery exception/return/refund handling instead.
- **APPROVED multi-retailer principle:** Evaluate each fulfillment independently. A customer may cancel one or more unpicked fulfillments while another already-picked-up or delivered fulfillment continues or enters its exception path. Do not cancel the entire order merely because one fulfillment is no longer cancellable.
- **CURRENT IMPLEMENTATION:** Customer cancellation remains order-wide because the endpoint has no fulfillment selector. It permits order statuses `PENDING`, `CONFIRMED`, `PREPARING`, `READY`, and `PARTIALLY_REJECTED`; acceptance alone does not block it. It blocks the whole order if an assignment is `PICKED_UP`, `OUT_FOR_DELIVERY`, or `DELIVERED`, or has a pickup timestamp. A request that passes the cutoff cancels eligible fulfillments/assignments together, releases each active fulfillment reservation once, and records fulfillment and delivery events. It does not cancel only a subset when another fulfillment has already been picked up; that scope remains unresolved. An accepted agent's availability is not reset because workload-release behavior remains pending approval. Pickup status/timestamp is still agent-recorded and is not independently verified custody evidence.
- **CURRENT INVENTORY BEHAVIOR:** Checkout reserves inventory. `_release_fulfillment_inventory` skips missing, `REJECTED`, `CANCELLED`, and `DELIVERED` fulfillments; otherwise it reduces each associated inventory reservation, bounded at zero. Cancellation invokes this before marking the fulfillment cancelled. The status guard helps prevent repeat release for terminal fulfillments, but reservation provenance is not recorded per cancellation event and concurrent/cross-route protection must be designed and tested.
- **CURRENT PAYMENT/REFUND BEHAVIOR:** Cancellation has no refund execution or refund-obligation ledger and is no longer blocked solely by `PENDING` or `SUCCESSFUL` payment records. A payment that succeeds after cancellation updates payment aggregation but does not reopen the cancelled order; any captured funds remain an unresolved exception because no refund obligation is created automatically. The current schema has no `UNKNOWN/UNCERTAIN` payment state. An initiation timeout remains `PENDING` and blocks another attempt, but no reconciliation workflow exists.
- **CURRENT DELIVERY/RETAILER BEHAVIOR:** Retailer rejection is a separate whole-fulfillment action, currently allowed only while that fulfillment is `PENDING`; it adjusts order totals and releases that fulfillment's reservation. A pre-pickup customer cancellation path does not create retailer payable records because no COM-SET-001 ledger exists. Future settlement must exclude cancelled/rejected/undelivered goods; if a related retailer amount was already settled, any recovery must be a linked, approved COM-SET-001 adjustment rather than a silent deduction.
- **PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL:** Cancellation scope should let the customer select eligible fulfillment(s); if no fulfillment is specified, propose “all currently cancellable fulfillments,” never silently include a picked-up one. Cancel each eligible fulfillment atomically with its reservation and pre-pickup assignment. Continue any non-cancelled fulfillment. Where all remaining active fulfillments are cancelled/rejected, mark the order as cancelled/terminal using the existing status vocabulary and a deterministic derived-status rule; do not invent a new persisted order state in this policy. Mixed delivered/rejected/cancelled outcomes need an explicit aggregation rule before implementation.

| Parameter | Proposed initial rule | Reason | Requires explicit approval? |
|---|---|---|---|
| Eligibility by fulfillment state | `PENDING`, `CONFIRMED`, `PREPARING`, `READY`: eligible if not physically picked up. `OUT_FOR_DELIVERY`: ordinarily not eligible because verified pickup must already have occurred; verify the pickup event, not the label alone. `DELIVERED`, `REJECTED`, `CANCELLED`: not cancellable again. `PARTIALLY_REJECTED` and `PARTIALLY_DELIVERED` are current order-level aggregate statuses, not fulfillment states; decide from each fulfillment. `FAILED` is also an order-level state and requires support review. Unknown/unsupported state: block self-service and route to support. | Status alone can lag physical custody; terminal outcomes must not be reversed | Yes |
| Physical pickup cutoff | The cutoff is the authoritative, timestamped event confirming the agent physically received the goods from the retailer. Agent assignment/acceptance is not pickup. A recorded `PICKED_UP` event is current evidence; disputed/missing pickup evidence is held for review and must not be resolved by request-arrival order alone. | Implements the approved physical-custody test and guards against premature cutoff | Yes |
| Scope and order continuation | Customer selects individual fulfillments, or the proposed default selects all currently cancellable fulfillments. Picked-up/delivered fulfillments are excluded, not used to block cancellation of other eligible fulfillments. Continue all unaffected fulfillments. | Supports orders whose retailers/riders progress independently | Yes |
| Preparation | Cancellation remains available during `PREPARING` until physical pickup. No automatic retailer compensation is proposed. Any documented preparation compensation requires a separate retailer agreement and explicit approval; no amount/formula is proposed here. | Preserves the approved physical cutoff without inventing a merchant charge | Yes |
| Inventory reservation | In the same transaction as cancellation, release the selected fulfillment's reservation once and only once; never decrement on-hand stock for a not-yet-delivered cancellation. Terminal cancellation is idempotent; repeated requests return/identify the existing outcome and do not release stock again. | Prevents overselling and duplicate release | Yes |
| Online payment — no capture / authoritative failure | Cancellation may proceed for eligible fulfillment(s). Do not create a refund for funds not captured. A failed attempt does not imply a refund. | Refund only actual captured funds | Yes |
| Online payment — pending | Proposed: accept eligible fulfillment cancellation as a cancellation intent, leave payment resolution in its own pending state, and block another charge under COM-PAY-003. Do not label the payment failed. If capture later succeeds, keep the cancelled fulfillment/order outcome and create a refund obligation for the attributable cancelled amount. | Allows policy-compliant cancellation without risking duplicate charge or false payment status | Yes |
| Online payment — uncertain | Proposed: record cancellation intent for eligible fulfillment(s), but retain the order/payment in the COM-PAY-003 unresolved financial path and block retries. If success is later confirmed, create the attributable refund obligation; if authoritative failure is confirmed, no refund is due. A timeout alone must not be called failure. | Integrates cancellation with the approved uncertain-payment and late-success rules | Yes |
| Online payment — one or more successful captures | Allow eligible pre-pickup cancellation; calculate the amount attributable to the cancelled goods/approved adjustments and create a refund obligation for captured funds under COM-REF-001/002. Reconcile each successful attempt once; do not cancel a delivered/picked-up fulfillment or refund more than attributable captured funds. Request/submission is not refund completion. | Does not make payment capture an unintended veto over the approved cancellation right | Yes |
| Assignment before pickup | For `UNASSIGNED` or `ACCEPTED` without physical pickup, cancel the selected fulfillment's assignment and record a delivery event. Release an accepted agent's workload/availability consistently; assignment does not remove customer eligibility. | Separates assignment from custody | Yes |
| Assignment after pickup | Do not use ordinary cancellation. Keep custody tracked and route to authorized delivery exception/return/refund process. Agent compensation is governed separately by COM-PAY-001/002 and remains subject to its pending parameters. | Protects goods in custody and avoids inventing courier pay | Yes |
| Customer refusal after pickup | Treat as delivery exception, not cancellation. Record refusal and custody, determine authorized return/disposition, then assess any refund under COM-REF-001/002 and payable adjustment under COM-SET-001. | Does not let a refusal erase custody or financial history | Yes |
| Cancellation fee / retailer compensation | No cancellation fee or automatic retailer preparation compensation is assumed. Proposed default is no automatic charge; any fee/compensation requires an explicit agreement, amount/formula, disclosure, and approval before collection/deduction. | Avoids undisclosed fees or unsupported merchant deductions | Yes |
| Audit record | Record actor, customer/order/fulfillment IDs, time, reason, prior and resulting states, authoritative pickup evidence/timestamp, affected assignment and agent, inventory reservation effect, linked payment(s), refund obligation/reference/status, retailer payable adjustment/recovery, and decision/evidence reference. | Makes cancellation and associated financial/operational effects reviewable | Yes |
| Race resolution | Serialize against fulfillment, assignment, inventory, order, payment/refund records using a consistent lock/transaction design. The winner is determined by authoritative event time/state, not whichever HTTP request arrives first: a retailer confirmation or preparation update before cancellation does not close the window; a retailer rejection that is committed first remains `REJECTED` and must not be cancelled/released twice; verified pickup before the cancellation decision means exception path; accepted cancellation before pickup means later assignment/pickup must be rejected. Payment callbacks/reconciliation update payment/refund only and never reopen cancelled fulfillment/order. Refund processing must remain capped by the outstanding attributable refund obligation and actual provider-confirmed outcomes; a concurrent refund callback cannot erase or duplicate that obligation. | Avoids API arrival-order races and contradictory custody/financial outcomes | Yes |

- **Proposed lifecycle (conceptual):**

  ```text
  Customer requests cancellation
      → identify selected fulfillment(s)
      → inspect authoritative fulfillment and pickup/custody event
          → eligible and no verified pickup:
              record cancellation decision
              → cancel fulfillment and unpicked assignment
              → release its reservation once
              → continue unaffected fulfillments
              → reconcile captured/pending/uncertain online payments
              → create refund obligation for attributable captured funds, if any
              → adjust retailer payable under COM-SET-001
          → verified pickup already occurred:
              reject ordinary cancellation
              → delivery exception / refusal / authorized return / COM-REF refund process
  ```

- **Examples:**
  - **Example 1 — single retailer, before preparation:** Order/fulfillment is `PENDING`, assignment `UNASSIGNED`, stock reserved, and no successful capture exists. Cancellation records the request/reason, marks the fulfillment/order cancelled under the derived-status rule, cancels its assignment, releases its reservation once, and creates no refund unless a capture is later confirmed.
  - **Example 2 — single retailer, during preparation:** Fulfillment is `PREPARING`, assignment is accepted but not picked up. The proposal permits cancellation because preparation and assignment are not physical pickup. Cancel assignment, release reservation once, continue no fulfillment for that retailer; do not invent retailer compensation. If an online capture exists, create a refund obligation for the attributable amount; refund completion follows COM-REF-001/002.
  - **Example 3 — multi-retailer order:** Retailer A is `READY` with no pickup event; retailer B is `OUT_FOR_DELIVERY` and has a verified pickup. A may be cancelled, its unpicked assignment cancelled and stock reservation released. B is not ordinarily cancellable and continues delivery or exception handling. Do not mark the whole order cancelled while B remains active; adjust/refund only the attributable amount for A under approved allocation rules.
  - **Example 4 — assigned but not picked up:** An agent has `ACCEPTED` the assignment but has not physically received goods; there is no authoritative `PICKED_UP` event. Customer cancellation remains eligible. Assignment is cancelled and agent workload released; no agent compensation is assumed.
  - **Example 5 — agent physically picked up:** A verified `PICKED_UP` event predates the cancellation decision. Reject ordinary cancellation; record the attempted request and direct the case to delivery exception. If the customer refuses, record refusal/custody, arrange authorized return/disposition, and determine any captured-fund refund under COM-REF-001/002. Never silently mark the fulfillment cancelled or refund completed.
- **UNRESOLVED / REQUIRES BUSINESS OR ACCOUNTING CONFIRMATION:** Customer selection/default scope; fulfillment-to-order terminal status aggregation (including mixed delivered/cancelled/rejected); operational source and dispute process for pickup evidence; online payment allocation to individual fulfillment/items; behavior when an uncertain payment exists while fulfillment cancellation is requested; refund amount/timing and allocation; preparation compensation agreements; cancellation-fee decision/disclosure; agent workload/availability and any compensation; customer refusal/return logistics; and post-settlement retailer recovery rights under COM-SET-001.
- **Status:** Physical-pickup cutoff and fulfillment-level evaluation are **APPROVED**. All parameter-table rules, examples where they depend on unresolved allocation, and operational/financial defaults are **PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL**. Contract, provider, refund, and retailer-accounting consequences are **UNRESOLVED / REQUIRES BUSINESS OR ACCOUNTING CONFIRMATION**.

### COM-CAN-002 — Retailer rejection/cancellation

- **Business question:** What can a retailer do after confirming or beginning preparation?
- **Current implementation:** Retailer may reject its entire pending fulfillment; rejection adjusts totals and releases reservations. No separate post-confirmation inability workflow exists.
- **Proposed rule:** Permit rejection while pending; treat inability after confirmation as an auditable exception rather than erasing fulfillment history. Fee/payment effects follow COM-FEE-006 and approved refund rules.
- **System behavior/data/tests:** Record reason and actor; make adjustment once; test rejection races against payment, cancellation and other retailer fulfillment progress.
- **Approval:** **REQUIRES USER/BUSINESS APPROVAL**. Merchant obligations and post-confirmation remedies are undecided.

### COM-CAN-003 — Agent release and reassignment

- **APPROVED relationship to other decisions:** Assignment or acceptance does not establish physical custody and does not end customer cancellation eligibility. Under COM-CAN-001, ordinary customer cancellation remains possible for that fulfillment until verified physical pickup; after pickup, ordinary cancellation is blocked and late cancellation/customer refusal must use delivery-exception, authorized return, and COM-REF-001/002 refund handling. Courier payout follows the approved COM-PAY-001 model and COM-PAY-002 multi-agent direction, not customer delivery fees.
- **CURRENT IMPLEMENTATION — delivery state:** One `DeliveryAssignment` row is unique per fulfillment. An agent can accept an `UNASSIGNED` assignment, then the current path is `ACCEPTED → PICKED_UP → OUT_FOR_DELIVERY → DELIVERED`. Acceptance sets `agent_id`, `assigned_at`, and `accepted_at`; it does not set `picked_up_at`. The `PICKED_UP` status update sets `picked_up_at` from the server clock. Moving to `OUT_FOR_DELIVERY` updates fulfillment/order status. `DELIVERED` updates the fulfillment, records `delivered_at`, consumes reserved inventory, recomputes order status, and creates an earning. The API does not record retailer confirmation, pickup code, goods condition, or separate custody-transfer evidence at pickup. A delivery confirmation code may be required at completion when a code hash exists; this is not pickup evidence.
- **CURRENT IMPLEMENTATION — decline/reassignment:** There is no agent decline, agent cancellation, release, or reassignment route. The admin assign route only accepts `UNASSIGNED` assignments and marks them `ACCEPTED`; it cannot transfer an active assignment. There is no first-class record of successive assignment holders or service segments beyond delivery events and the one current `agent_id`.
- **CURRENT IMPLEMENTATION — workload:** Agent acceptance marks the agent `BUSY`; availability cannot be set `OFFLINE` while the agent has an accepted/picked-up/out-for-delivery assignment. Successful delivery marks the current agent `AVAILABLE`. Customer order cancellation now records a delivery cancellation event but does not reset the affected agent to `AVAILABLE`, because cancellation workload-release policy remains pending. Rejection/cancellation workload handling is not consistently implemented; no decline/reassignment workload transition exists.
- **CURRENT IMPLEMENTATION — payout:** At delivery, code divides the order-level customer `delivery_fee_ugx` by the count of non-cancelled assignments on the order and records one earning keyed by assignment. This is not the approved `base_payout + eligible_distance_km × courier_rate_per_km` formula; integer division can discard a remainder, does not allocate by agent work, and uses delivery pricing rather than a payout basis. It creates no earning on decline or failed pickup. Admin payout marking uses a row lock and one pending-to-paid transition with a supplied payout reference, but payout timing, calculation, and allocation remain unimplemented/undecided.
- **PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL — distinctions and actions:**

| Event/state | Business meaning | Proposed rule |
|---|---|---|
| Assignment | Work is offered/assigned to an agent; it does not prove acceptance or custody. | Keep assignment, acceptance, custody, route, and completion as distinct auditable events. |
| `ACCEPTED` | Agent accepts responsibility to attempt the assigned pickup/delivery, without possessing the goods. | Acceptance alone is not pickup, does not trigger a delivery earning, and does not close the COM-CAN-001 cancellation window. |
| Arrival at retailer | Agent reports arrival at pickup location. | Treat as an operational/evidence event only; arrival is not pickup/custody. Exact event and evidence are pending. |
| `PICKED_UP` / custody | Agent physically receives the identified fulfillment goods from the retailer. | Define a single authoritative custody-acceptance event, linked to the fulfillment and identified agent, with server-recorded time and pickup evidence. Do not equate agent acceptance, arrival, or a status label lacking evidence with verified custody. |
| `OUT_FOR_DELIVERY` | The agent is transporting goods after custody transfer. | It follows verified pickup; preserve custody tracking. It is not itself a second pickup or payout event. |
| `DELIVERED` | Goods reach the customer and delivery completion is accepted/verified. | Record delivery once; preserve any required customer confirmation. Completion must not duplicate the fulfillment or earning. |
| Decline before acceptance | Agent has not accepted the offer. | Proposed ordinary decline/release: remove that agent from the offer and return the fulfillment to an eligible unassigned queue without changing fulfillment or payment state. Actor authority, reason requirements, and whether repeated declines are limited remain pending. |
| Agent cancellation/release after acceptance, before pickup | Agent has accepted but has not taken custody. | Proposed ordinary release only through an authorized, recorded transition; cancel/revoke the old assignment before offering it to a replacement. Acceptance still does not block customer cancellation. Whether agent self-cancellation is allowed, permitted reasons, reassignment authority, and any compensation are pending. |
| Decline after pickup | Agent possesses goods. | Not an ordinary decline or abandonment. Treat as an exception requiring immediate custody control and authorized, evidenced handoff/return. No unilateral cancellation or silent agent replacement. |
| Reassignment before acceptance | No acceptance/custody exists. | Proposed ordinary reassignment: withdraw or expire the offer and assign to another eligible agent while preserving history; maintain at most one current offer/active assignment. |
| Reassignment after acceptance, before pickup | Agent accepted but custody has not transferred. | Proposed ordinary reassignment only after the prior assignment is atomically released/cancelled and agent workload updated; record reason and successor. It does not close customer cancellation eligibility. |
| Reassignment after pickup / while out-for-delivery | Goods are in an agent's custody. | Emergency/exception handling only, not ordinary reassignment. Require authorized handoff, outgoing and incoming agent identities, event time, goods/condition evidence, and incoming custodian acceptance before changing active custody. No concurrent custodians or gap that loses custody record. |
| Reassignment after delivery | Fulfillment is complete. | Prohibit reassignment or a second completion; corrections use a separately auditable exception/adjustment, not reopened delivery. |

- **Proposed conceptual custody flow — PENDING EXPLICIT BUSINESS APPROVAL for actors/evidence and operating details:**

  ```text
  UNASSIGNED / OFFERED
      → ACCEPTED (agent accepts work; no custody)
      → ARRIVED_AT_RETAILER (arrival only; no custody)
      → PICKED_UP (verified retailer handover; custody begins)
      → OUT_FOR_DELIVERY (same active custodian remains responsible)
      → DELIVERED (verified customer handover; custody ends)

  Before verified pickup:
      decline/release → record reason → cancel old offer → reassign or return to queue
      customer cancellation remains eligible under COM-CAN-001

  After verified pickup:
      exception/authorized handoff or return only
      record outgoing custody end and incoming custody acceptance
      ordinary customer cancellation and ordinary agent decline are not allowed
  ```

- **Custody evidence — PENDING EXPLICIT BUSINESS APPROVAL:** Select the authoritative pickup confirmation mechanism. Proposed evidence record includes fulfillment/order/assignment, retailer or authorized handover actor, receiving agent identity, server timestamp, pickup result and exception reason, and a transaction-specific verification (for example a retailer handover confirmation/code or other independently verifiable evidence). Whether a code, retailer confirmation, customer confirmation, photo, signature, or other proof is required; who can attest; offline handling; and evidence retention/privacy are undecided. Arrival or agent-entered `PICKED_UP` alone is not independent verification unless explicitly approved as the authoritative mechanism.
- **Customer cancellation and refund interaction:** Before verified custody, customer cancellation remains eligible under COM-CAN-001, including after agent acceptance. Cancellation wins only if its authoritative fulfillment decision is recorded before verified pickup; after pickup, customer request/refusal follows exception/return/refund handling, not ordinary cancellation. If a late capture/refund obligation arises, apply COM-PAY-003 and COM-REF-001/002; do not reopen the order or mark a refund complete merely from a request/submission. Cancellation/rejection must not generate retailer payable for goods not delivered/accepted under COM-SET-001.
- **Multiple-agent and payout conservation — PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL:** Treat one fulfillment as one delivery service and one approved fulfillment-level payout entitlement, regardless of assignment count. Keep the approved formula `base_payout + (eligible_distance_km × courier_rate_per_km)` independent of customer delivery fee. Record each agent's verified service segment and custody responsibility; allocate no more than one fulfillment entitlement in total. A pre-pickup reassignment must not create another full earning. Post-pickup handoff records distinct, non-overlapping work/custody segments; no automatic full payout per agent or assignment. Prevent duplicate delivery, custody, completion, earning, and payout. Exact allocation formula, distance segmentation, rounding/remainder, eligible work/evidence, compensation for failed pickup/partial work/reassignment/cancellation/return trip, timing, and approval remain **PENDING EXPLICIT BUSINESS APPROVAL** as detailed in COM-PAY-001/002.
- **Agent workload — PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL:** On acceptance, mark unavailable for additional work according to an approved capacity policy; at pickup and out-for-delivery remain busy and accountable for custody; on ordinary pre-pickup decline/release/cancellation, clear the outgoing agent's active workload only after the release is committed; on reassignment, atomically release old and reserve new agent; after verified delivery or authorized return/handoff, update workload based on any other active assignment. Do not set an agent available merely because an API request was received, or clear workload while the agent still has custody. Whether availability is binary or supports multiple workloads is undecided.
- **Concurrency/idempotency — PROPOSED controls; implementation details are technical choices:** Lock or conditionally transition the assignment and relevant agent/fulfillment/order records so two agents cannot accept the same work; reassignment cannot race into a stale acceptance; customer cancellation and pickup serialize against the authoritative custody decision; completion and reassignment cannot both win; duplicate completion returns the existing result and cannot consume inventory, notify, or create earning twice. Agent acceptance, admin assignment, and delivery status now acquire locks in the order order → fulfillment → assignment → agent. Customer cancellation locks order → fulfillment → assignment before inventory work, and retailer rejection locks its order before fulfillment and assignment. This reduces the identified lock inversion, but production-database concurrency behavior remains to be verified; SQLite tests do not establish PostgreSQL lock guarantees. Arrival order of API requests is not the business authority.
- **Auditability — PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL:** Retain immutable assignment/custody event history with agent and authorized actor, assignment/fulfillment/order IDs, event type, server timestamp, previous/new state, retailer handoff and receiving identity, evidence/reference, reason, custody condition, cancellation/reassignment linkage, all participating agent segments, payout basis/allocation and any adjustment, and final delivery evidence. Corrections append linked events; do not overwrite earlier custody or payout history.
- **Unresolved decisions:** Who may offer, decline, release, cancel, or reassign; whether agents may self-release and under what reasons; custody evidence and retailer handover verification; offline or disputed custody process; reassignment authority after pickup/out-for-delivery and return destination; workload/capacity model; all multi-agent payout allocation/rounding/remainder and proof rules; failed-pickup, partial-work, reassignment, cancellation, and return compensation; payout timing and approval; delivery completion evidence when no confirmation-code hash exists; and dispute/appeal/incident escalation. These remain **PENDING EXPLICIT BUSINESS APPROVAL**; provider, evidence-retention, and finance/accounting constraints require appropriate confirmation.
- **Status:** Agent decline/cancel, reassignment, physical-custody evidence, workload transitions, and detailed payout allocation are **PENDING EXPLICIT BUSINESS APPROVAL**. Approved payout formula, no-double-payment direction, and COM-CAN-001 physical-pickup cancellation cutoff remain unchanged.

### COM-CAN-004 — Administrator cancellation and override

- **Business question:** What financial/operational exceptions may administrators authorize?
- **Current implementation:** Admin can set selected cancellation/failure states with guards, reason, audit event and notification.
- **Proposed rule:** Keep overrides auditable and prevent them from bypassing custody, captured-funds, or refund-confirmation controls. Preserve completed delivery history.
- **System behavior/data/tests:** Record request, actor, reason, resulting state and linked financial action; test unauthorized/duplicate overrides and terminal-state protection.
- **Approval:** **REQUIRES USER/BUSINESS APPROVAL**. Admin authority, dual approval, and self-approval are undecided.

### COM-REF-001 — Refund request vs confirmation

- **APPROVED execution direction:** WEWE supports provider-executed refunds where the selected provider supports them, and external/manual completed refunds where provider execution is unavailable or not applicable. MTN Mobile Money and Airtel Money remain the target customer payment methods and will use separate provider adapters; each provider's refund, idempotency, reference, callback, status-query, and reconciliation capabilities must be independently verified before relying on them. No refund capability is assumed to exist for either provider. A refund request or submission is not proof that funds have returned; confirmation requires authoritative provider evidence or a separately approved manual verification procedure.
- **CURRENT IMPLEMENTATION:** The payment model stores one full-payment status (`PENDING`, `SUCCESSFUL`, `FAILED`, or `REFUNDED`) and a captured amount; there is no separate refund record, refund amount, refund obligation, partial-refund ledger, refund initiation method, or refund-specific provider API in the provider protocol. No Mobile Money provider is registered. The admin `/payments/{payment_id}/confirm-refund` route changes a `SUCCESSFUL` payment to `REFUNDED` for its full recorded amount from an operator-supplied event/reference, emits a notification and audit event, but does not execute or independently verify an external transfer. The provider payment webhook also accepts `REFUNDED` for a successful payment and marks the entire payment refunded; it cannot represent a partial refund. Duplicate admin refund references and provider event IDs are idempotent. These existing behaviors are implementation facts, not sufficient refund evidence or authorization policy.
- **RELATED APPROVED DIRECTION AND PROPOSED TRIGGERS:** An eligible pre-pickup cancellation under COM-CAN-001 can create a refund obligation for attributable captured funds; the amount/allocation remains pending. COM-SET-001 proposes a refund obligation when a captured order includes rejected/unfulfilled goods, and COM-CAN-002 rejection remedies remain subject to business approval; do not treat their detailed refund formula or timing as approved. A late successful capture after cancellation does not reopen the order; it must be reconciled and routed to the appropriate refund/exception process under COM-PAY-003. Duplicate successful captures for the same order require separate reconciliation so captured funds are not retained or refunded twice.
- **PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL:** Create one refund obligation only when an evidenced business event establishes that an identified captured amount is due back to the customer: eligible cancelled fulfillment/line; rejected or unfulfilled goods; approved partial/mixed fulfillment adjustment; late successful capture attributable to a cancelled order/fulfillment; confirmed duplicate capture or other verified erroneous charge; or another explicitly authorized correction. A customer request alone does not establish eligibility or amount. Record separately the obligation to refund and execution attempts; never equate an obligation, approval, provider submission, or manual reference with completed refund.
- **Conceptual lifecycle (business-level; not a database-enum decision):**

  ```text
  ELIGIBILITY_REVIEW
      → REQUESTED (reason, affected order/fulfillment/payment and proposed amount recorded)
      → APPROVED (authorized decision and approved amount recorded)
      → SUBMITTED/INITIATED (provider/external execution attempt and unique reference recorded)
          → CONFIRMED (provider-authoritative evidence, or separately approved manual verification)
          → FAILED (authoritative failure; obligation remains open for review/retry decision)
          → UNKNOWN/UNCERTAIN (timeout, ambiguous response, or delayed confirmation; reconcile before retry)
      → REVIEW_REQUIRED (conflict, missing evidence, excess/duplicate request, or unresolved exception)
  ```

  Cancellation of a request before submission, decline, partial approval, and a retry after a definitively failed attempt require distinct auditable decisions. Whether those are separate persisted business states is an engineering choice after approval; do not infer a refund-specific enum from this conceptual flow.
- **Eligibility and amount guardrails — PROPOSED, PENDING EXPLICIT BUSINESS APPROVAL:**
  - Only funds confirmed captured (`SUCCESSFUL` under the current payment record, or an authoritative successful provider reconciliation under COM-PAY-003) can support a refund. `PENDING`, `UNKNOWN/UNCERTAIN`, and `FAILED` payments are not refundable as captured funds. Pending/uncertain outcomes require payment reconciliation; do not issue a refund merely because a payment might have succeeded.
  - A `REFUNDED` payment is not automatically evidence that every order amount or every fulfillment has been refunded. Reconcile its refund evidence and remaining refundable balance before any new request. Under the present full-payment-only implementation, do not request a second refund against a fully confirmed-refunded capture.
  - An order marked `CANCELLED` is not itself proof that every fulfillment or payment is refundable. Determine which fulfillment/lines were cancelled, delivered, rejected, or otherwise eligible, and attribute the obligation only to captured funds allocated to the affected goods/components. A cancelled individual fulfillment does not automatically make amounts for a separate delivered fulfillment refundable.
  - For each captured payment, cumulative **confirmed refunds plus amounts reserved by approved, submitted, or unresolved refund attempts** must not exceed the captured amount. A definitively failed attempt may release its reserved amount only after authoritative failure is recorded. An `UNKNOWN/UNCERTAIN` attempt continues to reserve its amount until resolved.
  - Refund execution must reconcile to the original successful payment/transaction and provider. Proposed destination is the original customer payment source where the provider supports it; an alternate destination must require explicit authorization and verified customer ownership. Neither rule is approved, and provider destination/capability must be verified.
- **Failure and reconciliation — PROPOSED, PENDING EXPLICIT BUSINESS APPROVAL:** A request timeout or ambiguous response moves the attempt to `UNKNOWN/UNCERTAIN`, not `FAILED`; retain the amount reservation, query/reconcile through a verified authoritative provider capability, and do not submit a second refund until the first is resolved. A definitive provider rejection is recorded as failed with response/evidence; the refund obligation remains visible and requires an authorized retry or other resolution. Provider acceptance with delayed confirmation remains submitted/unconfirmed, not refunded; reconcile until confirmed or escalated under an approved procedure. Duplicate callbacks have no repeated financial effect. Conflicting/out-of-order callback evidence is retained and routed to review; do not use “last callback wins.” Provider idempotency keys, transaction/refund references, callback authentication/correlation, and recovery from an indeterminate provider response must be verified per provider before execution is enabled.
- **Manual/external execution — PROPOSED, PENDING EXPLICIT BUSINESS APPROVAL:** Where provider execution is unavailable or not applicable, require an authorized operator to record the actual transfer evidence and an independent verification (such as approved statement/provider transaction evidence) before marking the refund confirmed. A typed reference, screenshot, operator assertion, or submitted instruction alone is not confirmation. Approver, verifier, separation of duties, evidence retention, allowed rails, and exception authority remain undecided.
- **Cancellation/payment interaction — APPROVED direction plus proposed controls:** A valid pre-pickup cancellation can create a refund obligation for attributable funds actually captured. If the payment is pending/uncertain, retain cancellation/payment resolution separately; a later confirmed capture creates or updates the obligation without reopening the cancelled order. A refund callback cannot change fulfillment/order status to active or erase cancellation history. Exact payment-to-fulfillment allocation and refund amount remain pending.
- **Retailer settlement interaction — PROPOSED, PENDING EXPLICIT BUSINESS APPROVAL:** Before retailer settlement eligibility, a refund obligation or open dispute attributable to the fulfillment holds the corresponding unsettled payable. If a settlement is eligible but not submitted, reduce/hold the attributable payable pending allocation and refund resolution. If settlement has been submitted but not confirmed, reconcile the transfer before any adjustment; do not assume it can be recalled or pay the same payable twice. If funds were already settled, record a linked recovery/receivable or future-settlement offset only under an approved retailer agreement and authority; do not silently deduct or assume a clawback. Keep customer refund, retailer recovery, courier payout, delivery fee, and payment-processing fee as distinct amounts and records under COM-SET-001.
- **Audit and concurrency invariants — PROPOSED, PENDING EXPLICIT BUSINESS APPROVAL:** Preserve reason and originating event; requester/initiator, approver and verifier; customer/order/fulfillment/line/payment IDs; captured, requested, approved, submitted, failed, confirmed and outstanding amounts; currency; funding/allocation basis; status history; provider/rail; provider refund idempotency key and reference; provider request/response and callback event IDs; all timestamps; reconciliation evidence; customer communication reference; and any linked retailer settlement hold/adjustment/recovery. Create/approve/submit/confirm under concurrency controls that reserve the refundable amount and attributable fulfillment amount once. Duplicate requests/callbacks must be idempotent; refund-versus-capture and refund-versus-cancellation races must reconcile the same captured transaction exactly once; no fulfillment amount, capture, or confirmed refund may be consumed twice. Preserve corrections as linked entries rather than overwriting the audit history.
- **Status:** **EXECUTION MODEL APPROVED; full and partial refund scope approved under COM-REF-002. Triggers consistent with approved cancellation/rejection directions must be honored, but amount allocation, authority, execution controls, and operating procedures remain PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL or UNRESOLVED / REQUIRES BUSINESS, OPERATIONS, ACCOUNTING, OR PROVIDER CONFIRMATION.**

### COM-REF-002 — Refund scope and amounts

- **APPROVED scope:** WEWE supports both full and partial refunds. Partial refunds may conceptually be associated with a fulfillment, an item/line, a delivery fee, or another approved financial component. No implementation granularity is selected here.
- **Required controls:** Cumulative refunds must never exceed captured funds. Captured/requested/submitted/confirmed/failed amounts must eventually be auditable. Multiple successful payment attempts must be reconciled correctly.
- **CURRENT IMPLEMENTATION:** Status-based full refunds only; no partial-refund amount or allocation ledger.
- **PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL:** Refund only against identified captured payment(s), up to the affected refundable component's eligible value and each capture's remaining refundable balance. For multiple successful payment attempts, reconcile each unique provider transaction once and allocate a refund to its originating capture; never refund an aggregate order amount twice against separate records. Track confirmed refunds and in-flight/unresolved refund reservations separately. Partial refund obligations may be linked to individual fulfillment, line/quantity, delivery component, or other approved component, but no proportional allocation formula or priority among captures is proposed as approved.
- **UNRESOLVED / REQUIRES BUSINESS OR ACCOUNTING CONFIRMATION:** Formula for allocating payment captures across multiple retailers/fulfillments and lines; treatment of discounts, delivery fees, platform/WEWE amounts, taxes, and processing fees; whether/when delivery fees are refundable for cancellation, rejection, or partial fulfillment; rules for partial quantities when the system cannot represent accepted quantities; maximum refundable amount by component; impact on courier earnings already accrued/paid; and retailer recovery after settlement. Do not infer that an order total, retailer payable, or delivery fee is wholly refundable solely from order status.
- **Other decisions PENDING EXPLICIT BUSINESS APPROVAL:** Refund SLA/timing; approval roles and thresholds; automatic versus manual initiation; retry and escalation authority; customer notification content/timing; destination/account rules; provider-specific execution and fees; manual evidence and segregation of duties; dispute/chargeback treatment. Provider capabilities and idempotency/reference semantics require verification under COM-PAY-004.
- **Status:** **FULL AND PARTIAL REFUND SCOPE APPROVED; CALCULATION AND CONTROLS PENDING**.

### COM-MULTI-001 — Multi-retailer cash collection (out of scope)

- **CURRENT BUSINESS DECISION:** WEWE is online-payment-only. Cash payments, cash collection, and cash settlement workflows are out of scope. The earlier approved fulfillment-level cash direction is superseded and not applicable unless the business explicitly reopens it.
- **Online payment direction:** Customer online payment methods target MTN Mobile Money and Airtel Money under COM-PAY-004, subject to provider verification. Multi-retailer online payment allocation/refund behavior remains governed by COM-PAY-003, COM-REF-001/002, and COM-SET-001.
- **CURRENT IMPLEMENTATION:** Cash payment records and an order-level cash completion behavior exist in the codebase; this is an implementation fact only, not authorization to design, extend, or implement cash workflows. Delivery of one fulfillment can currently mark an order-level pending cash payment successful while other fulfillments remain incomplete.
- **Status:** **CASH COLLECTION OUT OF SCOPE / NOT APPLICABLE; prior cash model not an active approved requirement**.

## 5. Commerce state reference

These are states found in the current model/API; they are not all independently transitionable, and their presence does not approve a business transition.

### Order statuses

`PENDING`, `CONFIRMED`, `PREPARING`, `READY`, `OUT_FOR_DELIVERY`, `DELIVERED`, `PARTIALLY_REJECTED`, `PARTIALLY_DELIVERED`, `CANCELLED`, `REJECTED`, `FAILED`.

Checkout creates `PENDING`. Most progress states are derived from fulfillment states. Retailer actions can move a pending fulfillment to confirmed/rejected, then confirmed to preparing/ready. Delivery completion and customer pickup confirmation can produce delivered/partial terminal states. Current customer cancellation is limited to early order states and blocked by active delivery, successful payment or pending Mobile Money; this is not consistent with approved COM-CAN-001. Admin can cancel/fail eligible nonterminal orders. Full actor/stage changes require approval under COM-CAN rules. **Implementation gap:** `recompute_order_status` treats `CANCELLED` as a terminal fulfillment input, but has no explicit all-cancelled or delivered/cancelled/rejected aggregate outcome; those combinations can fall through to `PENDING` or another inappropriate derived state. Order-level mapping must be resolved under COM-CAN-001 before implementing fulfillment-level cancellation. A cancelled order with a late captured payment is a valid conceptual cross-lifecycle exception: order/fulfillment remain cancelled while the payment is reconciled as successful and a refund obligation is handled separately; payment success must not reopen the order.

### Fulfillment statuses

`PENDING`, `CONFIRMED`, `REJECTED`, `PREPARING`, `READY`, `OUT_FOR_DELIVERY`, `DELIVERED`, `CANCELLED`.

Current retailer actions: pending → confirmed or rejected; confirmed → preparing or ready; preparing → ready. A delivery agent can move a ready fulfillment to out-for-delivery/delivered through its assignment. Pickup confirmation can deliver ready fulfillments. A retailer rejects a whole fulfillment, not selected lines/quantities.

### Delivery-assignment statuses

`UNASSIGNED`, `ACCEPTED`, `PICKED_UP`, `OUT_FOR_DELIVERY`, `DELIVERED`, `CANCELLED`.

Current path: checkout → unassigned; verified available agent or admin assigns/accepts ready work; assigned agent advances accepted → picked-up → out-for-delivery → delivered. `ACCEPTED` records assignment acceptance, not physical pickup; current `PICKED_UP` sets a timestamp but has no separate retailer handover evidence. Delivery completion requires the customer's confirmation code when a hash exists. Cancellation/rejection can cancel an unassigned assignment. Agent decline, release and reassignment are not implemented. Proposed post-pickup handoff/return states are conceptual only; do not invent persisted statuses until approved behavior and technical representation are selected.

### Payment statuses

**CURRENT IMPLEMENTATION:** Payment records use `PENDING`, `SUCCESSFUL`, `FAILED`, and `REFUNDED`; order-level payment status is `UNPAID`, `PENDING`, `PAID`, `FAILED`, or `REFUNDED`. The current callback accepts successful, failed or refunded outcomes and rejects a refund of a non-successful payment. There is no expired or uncertain status.

The payment status is per payment attempt; the order-level payment status is an aggregate and must not be treated as a substitute for per-attempt capture/refund accounting. **Implementation gap:** the provider webhook sets the order-level status to `REFUNDED` when one successful payment is refunded without checking whether a different successful payment for that order remains captured; the admin refund-confirmation route does check for another successful attempt and may retain `PAID`. The order aggregate therefore differs by refund entry path. Multiple successful payments, partial refunds, and late success on a cancelled order require reconciliation by unique captured transaction and cannot be safely represented by a single order-level status alone.

**APPROVED DIRECTION, NOT IMPLEMENTED:** COM-PAY-003 requires an explicit `UNKNOWN/UNCERTAIN` business outcome distinct from `FAILED`, with retry blocked pending resolution and a reconciliation path. Exact persisted state names and transitions are later engineering choices. Refund lifecycle concepts are specified under COM-REF-001.

## 6. Financial invariants

The arithmetic checks below are safety constraints for the technical model, not approval of an unresolved commercial formula or parameter. Where a rule/register row identifies business terms as pending, that pending status remains controlling; implementation and enforcement details are engineering choices.

| Invariant | Required relationship | Enforcement |
|---|---|---|
| Order total | `final_amount_due = eligible_item_subtotal + sum(applicable fulfillment delivery fees) - approved adjustments` | Database row check for stored arithmetic; transactional service for cross-row aggregation; reconciliation/tests. |
| Line total | `line_total = unit_price × quantity` | Existing database check plus service tests. |
| Item subtotal | Sum of line totals eligible under the approved fulfillment states | Service logic and reconciliation; “eligible” status semantics need approval. |
| Delivery fee | Delivery order fee is the sum of fulfillment-specific fee snapshots; pickup delivery fee is zero | Persisted per-fulfillment quote and transaction; tests. |
| Payment amount | Each payment attempt records the amount submitted/authorized for that attempt | Immutable attempt/event history and service validation; provider reconciliation. |
| Captured/refunded | `0 ≤ confirmed_refunded + reserved_approved_or_in_flight_refunds ≤ confirmed_captured`; available refundable balance is captured funds less confirmed refunds and amounts reserved by approved, submitted, or unresolved refund attempts. Release an attempt reservation only after authoritative failure/cancellation resolution. | Cumulative refunds may not exceed captured funds under COM-REF-002; amount reservation implementation is required to enforce that approved cap against concurrent/partial attempts. |
| Retailer payable | Cumulative retailer settlements, less approved recoveries, must not exceed the legitimate payable attributable to delivered/accepted goods and captured funds allocated to those goods. Rejected/cancelled/undelivered goods are excluded from retailer payable. | Safety control; exact payable calculation, allocation, adjustments, and recovery authority remain **PENDING EXPLICIT BUSINESS APPROVAL** under COM-SET-001. Do not use gross order value as payout. |
| Settlement state | Distinguish `SETTLEMENT_SUBMITTED` from confirmed `SETTLED`; a submitted instruction is not proof of transfer. Pending/uncertain settlement amounts remain reserved against further instructions until reconciled. These labels are conceptual, not approved persisted statuses. | Settlement ledger and provider/manual transfer evidence; idempotent instruction/reference and reconciliation. |
| Agent payable | The approved model is `base_payout + (eligible_distance_km × courier_rate_per_km)`, independent of customer delivery fee. For reassigned/multi-agent work, total allocations must not exceed the single approved fulfillment entitlement; each verified work segment may be allocated once. | Earning ledger and reconciliation; parameters, qualification and allocation rules remain pending. Customer delivery fees must never be silently reused as courier payout. |
| Platform retained | Do not treat captured funds as free/retained platform funds until confirmed refunds, approved or in-flight refund obligations, retailer payable, courier payable, and other approved liabilities are separately accounted for. | Accounting ledger under COM-SET-001; allocation, liability recognition, and financial parameters remain pending. |
| Inventory | `0 ≤ reserved_quantity ≤ quantity`; each reservation is released or consumed once | Existing database check, transactional row locks, concurrency tests. |
| Allocation conservation | Sum of per-fulfillment fees equals order delivery fee; every approved payout/refund/retailer allocation sums exactly to its source amount; multiple successful payment attempts and refunds reconcile once by unique transaction/reference; no captured funds, fulfillment value, service segment, settlement, or payout entitlement is consumed twice. | Transactional ledgers and automated reconciliation; allocation and rounding rules. |

Retailer settlement ledger and reconciliation are required by the approved COM-SET-001 collect/hold-and-settle direction. Transfer automation may be separately staged after its rail and operating policy are resolved.

## 7. Concurrency and idempotency contract

Engineering must implement these guarantees using approved business outcomes and test them against PostgreSQL. A serialized operation must not create duplicate financial, inventory, notification, or status side effects.

| Concurrent operations | Required guarantee |
|---|---|
| Checkout retry/concurrent checkout | Same customer key and same request yields one order/reservation. Reusing a key with a different request must not silently return a mismatched order. |
| Payment creation/retry | One attempt per logical client operation; uncertain provider result blocks a new charge pending reconciliation. |
| Cancellation vs payment callback | Serialize payment/order outcome; late success on a cancelled order enters exception/refund handling and does not reopen fulfillment automatically. |
| Cancellation vs physical pickup | Serialize the authoritative cancellation decision and verified custody event per fulfillment; acceptance/arrival alone does not close cancellation eligibility. Exactly one pre-pickup cancellation or pickup outcome wins. |
| Retailer rejection vs customer cancellation | One consistent adjustment/status result; no duplicate fee reduction or stock release. |
| Agent acceptance vs admin assignment | At most one assigned agent; consistent lock ordering and clean conflict for the losing request. |
| Reassignment vs acceptance/delivery completion | One current assignment/custodian; do not allow stale acceptance, reassignment, pickup, or completion to overwrite a newer committed assignment/custody event. |
| Delivery completion vs cancellation | One committed outcome; after verified custody transfer, apply the exception/handoff rule. Duplicate completion cannot consume inventory, notify, or create earnings twice. |
| Refund vs capture/cancellation/duplicate refund | Reserve refundable amount atomically; cumulative confirmed plus approved/in-flight/unresolved refunds cannot exceed captured funds or eligible component value. Reconcile refund/capture and cancellation/refund races to one obligation and one execution effect. |
| Retailer settlement vs refund/adjustment | Hold or adjust only the attributable unsettled payable; submitted-but-unconfirmed transfers must be reconciled before retry/offset; already-settled funds require separately approved recovery authority. Never settle the same amount twice. |
| Courier payout vs reassignment/duplicate payout | One fulfillment-level payout entitlement; verify and allocate work segments once; idempotent earning creation and payout reference prevent duplicate payout across assignments/agents. |
| Duplicate provider payment/refund callbacks | Persist authenticated/correlated event and state atomically; concurrent replay returns idempotent acknowledgement; conflicting callbacks are reviewed, not resolved by last-arrival-wins. |
| Inventory update vs checkout/release/consume | Stock/reservations remain conserved and within database checks under concurrency. |

The audit noted potential opposing lock orders between agent/admin assignment and delivery completion/admin cancellation. Implementation must define a consistent lock order and test deadlock/retry outcomes without weakening the business guarantees.

## 8. Phase 4 scope boundary

### Must be implemented before real-money production commerce

- Implement the approved distance-based per-fulfillment pricing, quote display/snapshot, routing-failure handling, and fee conservation.
- Resolve tie rounding, the 15 km quote process, coordinate requirements, and route-correction approval before enabling delivery quotes.
- Implement the approved payment uncertainty, blocked-retry, idempotency, and reconciliation direction; resolve its pending operating parameters and verify provider capabilities before enabling a real provider.
- Implement the approved refund lifecycle and full/partial refund scope; resolve authorization, evidence, amount/allocation, timing and provider/external execution controls before accepting real payments.
- Implement the approved per-fulfillment cancellation cutoff; resolve pending compensation, refusal, return and post-pickup financial procedures. Approve separate agent release/custody/reassignment authority under COM-CAN-003.
- Resolve payout parameters/allocation and retailer settlement financial/operating terms before WEWE collects or owes real funds.
- Provide a retailer settlement ledger and reconciliation before settling retailer funds, as required by COM-SET-001. Transfer automation may be separately staged after its rail and operating policy are resolved.
- Preserve Phase 3 regressions and immutable migrations `0001–0005`; use reviewed new migrations only if approved design requires schema changes.

### Should be included if operationally required and resourced

- Automated payout execution after the payout ledger and rail are approved.
- Customer-facing fee-adjustment/refund tracking.
- Admin separation of refund request, approval, execution, and confirmation.

### Deferred unless separately approved

- Surge/demand, time, weather, category, promotional, loyalty, batching, and route-optimization pricing.
- Dynamic delivery pricing beyond the initial configurable base/minimum/rate formula.
- Fine-grained partial quantity fulfillment within one retailer fulfillment.
- Post-delivery returns, exchanges, and warranty workflows beyond any separately approved minimum claims process.
- Automated payout/retailer transfer rails without an approved provider and operating policy.

## 9. Decision register

| ID | Decision | Status |
|---|---|---|
| COM-FEE-001 | Distance-based, per-fulfillment customer delivery pricing | **Approved direction and initial parameters**; implementation details/clarifications in §2 remain open. |
| COM-FEE-002 | Independent per-retailer route and fee; sum fulfillment fees | **Approved**. |
| COM-FEE-003 | Pickup delivery fee is UGX 0; no separate pickup charge | **Approved**. |
| COM-FEE-004 | Road-route distance is preferred; retain quote inputs; routing provider unselected | **Approved direction**; routing provider/API and capabilities not selected. |
| COM-FEE-005 | Show before checkout; snapshot; later setting/agent route/reassignment does not silently alter fee | **Approved**; post-checkout correction process needs clarification. |
| COM-FEE-006 | Remove rejected fulfillment's own stored fee; leave others unchanged | **Approved pricing treatment**; payment/refund outcome follows separately approved rules. |
| COM-FEE-007 | Customer fee and agent payout are separate | **Approved**. |
| COM-FEE-008 | Initial approved parameters and configuration (not hard-coded permanent values) | **Approved**. |
| COM-FEE-009 | No invented fallback distance/price on routing failure; prevent quote or offer pickup | **Approved direction**; exact fallback selection/UX remains to be specified. |
| COM-FEE-010 | Listed dynamic/discount/surcharge extensions excluded initially | **Approved**. |
| COM-FEE-011 | Initial pricing philosophy | **Approved**. |
| COM-PAY-001 | Base-plus-distance courier payout independent of customer fee | **Model approved**; parameters/operating rules pending business approval. |
| COM-PAY-002 | Multi-agent/reassignment allocation and payout settlement | **Direction approved**; allocation/settlement rules pending. |
| COM-PAY-003 | Uncertain payment outcome, blocked retry, reconciliation | **Direction approved**; operating parameters pending; current implementation lacks this behavior. |
| COM-PAY-004 | MTN Mobile Money and Airtel Money target providers | **Target providers approved**; provider capabilities pending verification. |
| COM-SET-001 | WEWE collects/holds customer funds and settles retailers | **Operating direction approved**; financial/operating parameters pending. |
| COM-CAN-001 | Customer cancellation until physical pickup of each fulfillment | **Cutoff approved**; consequences pending; current implementation does not support this cutoff. |
| COM-CAN-002 | Retailer rejection/cancellation/inability | Requires business approval. |
| COM-CAN-003 | Delivery-agent decline, custody, reassignment and payout allocation | **Approved principles:** acceptance is not physical pickup; customer cancellation stays available until verified physical pickup under COM-CAN-001; payout follows the base-plus-distance model and must not double-pay the same work under COM-PAY-001/002. **Pending:** decline/self-release rights; ordinary versus emergency reassignment; authoritative pickup/handoff evidence; workload changes; one-custodian and multi-agent segment rules; assignment/completion idempotency; exact payout allocation, rounding/remainder, failed-pickup/partial-work/reassignment/cancellation/return compensation, timing and approval. |
| COM-CAN-004 | Admin cancellation/override and financial authority | Requires business approval. |
| COM-REF-001 | Provider-executed or external/manual refund lifecycle | **Execution direction approved**; controls and operating procedures pending. |
| COM-REF-002 | Full and partial refund scope | **Scope approved**; calculation/allocation and controls pending. |
| COM-MULTI-001 | Multi-retailer cash collection | **Out of scope / not applicable** under online-payment-only decision; previous fulfillment-level cash direction is superseded unless explicitly reopened. |

## 10. Phase 4A approval checklist

- [x] Distance-based per-fulfillment delivery pricing direction and initial numeric parameters approved.
- [x] Multi-retailer fees independently calculated and summed.
- [x] Pickup delivery fee approved at UGX 0, with no separate initial pickup charge.
- [x] Pricing snapshot and separation of customer fee from courier payout approved.
- [x] Dynamic/time/demand and promotional pricing excluded from the initial model.
- [x] Base-plus-distance courier payout model independent of the customer delivery fee approved (COM-PAY-001).
- [x] Auditable, conserved multi-agent/reassignment payout direction approved (COM-PAY-002).
- [x] Uncertain payment concept, blocked retry, and reconciliation direction approved (COM-PAY-003).
- [x] MTN and Airtel approved as target providers, subject to capability verification (COM-PAY-004).
- [x] WEWE collect/hold and retailer settlement operating direction approved (COM-SET-001).
- [x] Customer cancellation cutoff at physical pickup of each fulfillment approved (COM-CAN-001).
- [x] Provider-executed or external/manual refund execution model approved (COM-REF-001).
- [x] Full and partial refund scope approved (COM-REF-002).
- [x] Online-payment-only direction recorded; cash collection is out of scope (COM-MULTI-001 is not applicable).
- [ ] Rounding tie behavior, 15 km quote workflow, coordinate standards, and post-checkout route-correction process specified.
- [ ] Payout parameters, multi-agent/reassignment allocation and settlement procedures approved.
- [ ] Retailer settlement financial and operating parameters approved.
- [ ] Cancellation compensation, refusal, returns and post-pickup financial procedures specified.
- [ ] Refund amount/allocation, authority, evidence, timing and failure/retry controls specified.
- [ ] Payment uncertainty/reconciliation operating parameters specified and provider capabilities verified.
- [ ] Agent release/reassignment and custody policy approved.
- [ ] Remaining business financial definitions, including COM-CAN-002 through COM-CAN-004, resolved; technical concurrency mechanisms are handled by engineering.
- [ ] Phase 4 implementation scope boundary confirmed.

Do not begin affected Phase 4 implementation until its pending decisions are resolved. Approved directions do not mean implementation is complete; they do not approve unlisted parameters or separate agent release/custody authority.

## 11. Consolidated pending decisions

The following items remain unresolved. An approved direction is not repeated as a pending decision; only its open parameters, operating procedures, or verification work are listed. “Blocks implementation?” refers to completing or enabling the affected behavior, not unrelated engineering work.

| ID | Area | Decision/Parameter Still Pending | Blocks Implementation? |
|---|---|---|---|
| COM-FEE-001, COM-FEE-008, COM-FEE-009 | Business approval pending — customer delivery pricing | UGX 500 rounding tie behavior; scope/handling of the 15 km threshold; restricted/quote-based process and authority; coordinate accuracy/validation and correction; routing-provider selection/availability and acceptable reliable-route definition; approval/customer-consent process for post-checkout price correction; explicit selection between blocking delivery checkout and offering pickup when route pricing fails. Existing approved pricing values remain as recorded in §2. | Yes — affected pricing behavior must be resolved before enabling unsupported quote cases. |
| COM-PAY-001 | Business approval pending — courier payout | **Proposed, not approved:** base UGX 1,000; rate UGX 300/km; minimum UGX 1,500; no separate monetary maximum but 15 km aggregate eligible-distance cap per fulfillment, including authorized return (formula amount UGX 5,500 at 15 km); road-route source; eligible route/return distance; 0.1 km distance precision; nearest UGX 100, ties upward; confirmed-delivery earning creation and proposed 24-hour review hold; qualifying work; failed-pickup, pre-pickup cancellation, refusal, failed/partial delivery, return-trip, decline/custody treatment; settlement cadence/rail. All proposed values and rules require explicit business approval. | Yes — do not enable payout calculation/settlement using these values until approved. |
| COM-PAY-002 | Business approval pending — agent allocation and settlement | **Proposed, not approved:** pre-pickup reassignment transfers one entitlement to replacement agent; post-pickup authorized, evidenced handoff; base plus any minimum top-up divided equally among verified segment contributors; distance component divided by verified non-overlapping route segments; aggregate eligible distance capped at 15 km including authorized return; round once and assign indivisible remainder to final verified segment; hold multi-handoff/missing-evidence cases. Allocation formula, evidence, remainder recipient, payout authorization/timing/evidence/rail, and dispute/adjustment process all require explicit approval. | Yes — do not implement allocation until the proposal is approved and exceptions resolved. |
| COM-PAY-003 | Business/operations approval pending — payment lifecycle parameters | **Proposed, not approved:** 30-minute automatic reconciliation window; queries immediately, then at +1, +3, +5, +10, +15, and +30 minutes; after the window retain unresolved status and require review without inferring failure; customer messages for pending/support/success/failure; retry restrictions for every state and behavior after app closure; duplicate/conflicting/out-of-order event handling; provider-authoritative override criteria; late success after cancellation routed to manual reconciliation and confirmed refund; expiry semantics; manual-review trigger, role, evidence, allowed resolutions, and audit fields; callback validation of authenticity, WEWE/provider/order references, amount, UGX currency, merchant account, event ID, and attempt; one-transaction/one-payment, no-duplicate-effects, refund cap, no-blind-retry, no-cancelled-order-restart invariants. All proposed operating parameters and exception outcomes require explicit business approval. Provider query/status semantics remain subject to COM-PAY-004 verification. | Yes — before enabling real provider payments, retries, or automated reconciliation. |
| COM-PAY-004 | Provider verification pending — MTN and Airtel | For each provider separately: API/integration mechanism; initiation; callbacks/webhooks; status query; refund API; idempotency; sandbox availability/limitations; transaction/reference semantics; settlement/reconciliation; fees; production onboarding; credentials. | Yes — before relying on or enabling the unverified provider capability. |
| COM-SET-001 | Business/finance approval pending — retailer settlement | **Proposed, not approved:** payable from delivered/accepted checkout-snapshotted goods net of retailer-funded discounts; no platform commission deduction absent written agreement; WEWE bears processing fees by default pending approval/provider verification; eligibility after confirmed delivery and captured/attributed online funds; proposed 7-calendar-day hold and weekly Tuesday settlement; exclude rejected/cancelled/undelivered goods; allocate confirmed full/partial refunds to originating captured payment and goods, with approved future-settlement offset/receivable recovery if already settled; reconcile multiple successful online payments once; proposed UGX 50,000 minimum threshold with balances rolling forward; manually initiated finance-approved transfer to verified retailer-owned destination pending method verification; auditable settlement record, dispute holds, and idempotent no-double-settlement controls. All terms, recovery rights, business/accounting approvals, and settlement controls remain pending. Taxes/withholding and contractual treatment require appropriate business/accounting confirmation; provider fees and payout-rail capabilities require verification. | Yes — before settling real retailer funds. |
| COM-CAN-001 | Business/operations/finance approval pending — cancellation parameters | **Approved direction:** fulfillment-level cancellation until verified physical pickup; assignment/acceptance alone is not pickup; after pickup use exception/return/refund handling. **Proposed, not approved:** customer-selected or default-all-eligible fulfillment scope; state-to-eligibility rule and order-status aggregation for mixed delivered/cancelled/rejected outcomes; pickup evidence/dispute source; cancellation during preparation; one-time inventory release; cancellation intent while payment is pending/uncertain; refund obligations for attributable successful captures, including multiple captures; assignment cancellation/workload release; no automatic retailer compensation, cancellation fee, or agent compensation absent separate approval; refusal/return process; audit, concurrency, and idempotency controls. Payment allocation to fulfillment, refund amount/timing, retailer recovery after settlement, compensation/fee decisions, return logistics, and evidence authority require business/operations/finance confirmation. | Yes — before enabling customer cancellation or related inventory/payment/refund/delivery effects under this policy. |
| COM-REF-001 | Business/operations/finance approval pending — refund lifecycle and execution controls | **Approved:** provider-executed refunds where supported and external/manual completed refunds where provider execution is unavailable or not applicable; a request/submission is not proof of return; provider-authoritative evidence or a separately approved manual verification procedure is required. **Proposed, not approved:** conceptual requested → approved → submitted → confirmed/failed/unknown/review lifecycle; create obligations only for evidenced eligible captured amounts; preserve an amount reservation across unresolved attempts; reconcile timeout/late/conflicting/duplicate callbacks without blind retry or duplicate effects; verified-provider idempotency/reference controls; evidence, audit, and concurrency requirements. **Pending:** approver/verifier roles and thresholds; automatic/manual initiation; SLA/timing; notification; destination rules; provider-specific refund capabilities/fees; manual evidence, segregation of duties, retry/escalation; disputes/chargebacks. | Yes — before enabling refund execution or confirmation. |
| COM-REF-002 | Business/finance approval pending — refund amount/allocation | **Approved:** full and partial refund scope; partial refunds may conceptually relate to fulfillment, line, delivery fee, or another approved financial component. **Proposed, not approved:** refund only identified captured amounts, allocate each refund to its originating successful payment, reserve submitted/unresolved amounts against the remaining refundable balance, and reconcile multiple successful captures once. **Pending:** payment-to-fulfillment/line allocation; calculation and component caps; partial-quantity support; discount/delivery/platform/tax/processing-fee treatment; courier payout effect; refund timing/authority; provider behavior/fees; retailer recovery after settlement; manual evidence and failure/retry policy. | Yes — before calculating, allocating, or executing refunds. |
| COM-CAN-002 | Business approval pending — retailer rejection/inability | Merchant obligations and remedies when a retailer cannot fulfill after confirmation or preparation; applicable rejection/adjustment rules; item/line eligibility for order subtotal under fulfillment states. | Yes — before implementing post-confirmation retailer inability handling and final subtotal eligibility. |
| COM-CAN-003 | Business/operations/finance approval pending — delivery-agent custody, decline, reassignment and workload | **Approved principles:** assignment acceptance is not custody; customer cancellation remains available until verified physical pickup; after pickup use exception/authorized handoff/return handling; courier payout is the approved base-plus-distance amount and cannot duplicate work/entitlement. **Proposed, not approved:** pre-acceptance decline and pre-pickup agent release; ordinary reassignment before custody; emergency-only authorized handoff/reassignment after pickup; one active custodian and non-overlapping verified service segments; workload release/assignment transitions; idempotent completion and conserved single fulfillment payout. **Pending:** who can offer/decline/release/reassign and reasons; pickup/retailer handover evidence and dispute process; reassignment/return authority after pickup or out-for-delivery; workload capacity model; exact payout allocation formula, rounding/remainder, failed-pickup/partial-work/reassignment/cancellation/return compensation, timing, approval and evidence. | Yes — before enabling agent release/reassignment, custody handoff, multi-agent payout, or related cancellation/pickup behavior. |
| COM-CAN-004 | Business approval pending — administrator authority | Admin override scope; dual approval; self-approval rules. | Yes — before enabling the affected financial/operational overrides. |
| COM-PAY-003, COM-REF-001 | Technical implementation choice — persisted state names and transitions | Engineering must select persisted payment/refund state names and transition representation while preserving the approved lifecycle behavior. | No business approval; decide during engineering design before implementing the state handling. |
| Cross-cutting | Technical implementation choice — audit and concurrency | Engineering must choose event/ledger representation, transaction boundaries, a consistent lock order across agent/assignment/fulfillment/order/inventory/payment/payout records, and idempotency mechanisms that enforce the approved financial, inventory, callback, cancellation, refund, settlement, custody, and payout guarantees. Current assignment and delivery paths acquire agent, assignment, fulfillment, and order locks in different orders; address this deadlock risk in technical design before implementing reassignment or changing concurrency behavior. | No business approval; resolve in technical design before implementing affected workflows. |

Items marked as technical implementation choices are not requests for additional business decisions. They must preserve the approved behavior and the established Phase 3 technical baseline.

## 12. Final Phase 4A Decision Register

This register is the final summary of approval status. “Approved” applies only to the stated direction/parameters; it does not approve neighboring proposals or mean that code exists. Implementation findings are not requirements.

| Rule | Status | Key decision | Remaining qualification / gap |
|---|---|---|---|
| COM-FEE-001, COM-FEE-008 | **APPROVED** | Initial per-fulfillment distance-pricing model and stated UGX parameters, including pickup at UGX 0. | Tie rounding, distance threshold/quote workflow, coordinates, provider, and post-checkout corrections remain unresolved as listed in §2. |
| COM-FEE-002, COM-FEE-003, COM-FEE-005, COM-FEE-006, COM-FEE-007, COM-FEE-010, COM-FEE-011 | **APPROVED** | Independent fulfillment fees; no pickup delivery fee; checkout snapshot; rejection affects that fulfillment fee only; customer delivery fee separate from courier earnings; listed extensions excluded. | Payment/refund outcomes, rejection remedies, and route corrections remain governed by their respective pending rules. |
| COM-FEE-004, COM-FEE-009 | **APPROVED** | Road route is preferred; do not invent a route/price on routing failure. | Routing service/capability is unselected; operational choice between blocking delivery checkout or offering pickup and other route clarifications remain pending. |
| COM-PAY-001 | **APPROVED** | Courier payout model is `base_payout + (eligible_distance_km × courier_rate_per_km)` and is independent of the customer delivery fee. | All numeric payout parameters, eligible work/distance, timing, and exceptional compensation remain **PENDING EXPLICIT BUSINESS APPROVAL**. |
| COM-PAY-002 | **APPROVED** | Support auditable multi-agent/reassignment payout without duplicate payment; conserve the approved payout. | Allocation, rounding/remainder, evidence, authorization, timing, settlement rail, and exception handling remain **PENDING EXPLICIT BUSINESS APPROVAL**. |
| COM-PAY-003 | **APPROVED** | Distinguish `UNKNOWN/UNCERTAIN` from `FAILED`; block blind retries until resolution; reconcile uncertain outcomes; callbacks idempotent; late success does not reopen a cancelled order. | Time windows, retry details, messages, manual review, verification and other operating parameters remain **PENDING EXPLICIT BUSINESS APPROVAL**; provider-specific behavior remains subject to verification. |
| COM-PAY-004 | **APPROVED** | Online-payment-only scope; MTN Mobile Money and Airtel Money are target customer methods using separate adapters. | Every provider capability (initiation, callback, query, refund, idempotency, sandbox, fees, settlement/reconciliation, onboarding) remains **PENDING PROVIDER VERIFICATION**. |
| COM-SET-001 | **APPROVED** | WEWE intends to collect/hold customer funds and later settle appropriate retailer amounts; retailer settlement is separate from customer payments, refunds, delivery economics, platform amounts, and courier payout. | Calculation, eligibility, holds, cadence, threshold, fees, tax/accounting, method, records, dispute, recovery and authorization remain **PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL** or **UNRESOLVED / REQUIRES BUSINESS OR ACCOUNTING CONFIRMATION**. |
| COM-CAN-001 | **APPROVED** | Customer may cancel each relevant fulfillment until verified physical pickup; assignment/acceptance alone is not pickup; after pickup use exception/return/refund handling. | Fulfillment selection/order aggregation, pickup evidence, payment/refund procedures, compensation, workload and return details remain pending; current implementation does not conform. |
| COM-CAN-002 | **UNRESOLVED / REQUIRES EXPLICIT BUSINESS APPROVAL** | Retailer rejection/inability direction and remedies after confirmation/preparation are not finalized. | Existing pending-only rejection is implementation behavior, not full business policy; refund/adjustment treatment and partial quantity rules remain pending. |
| COM-CAN-003 | **APPROVED** (cross-rule principles only) | Acceptance is not custody; apply COM-CAN-001 cutoff; follow approved payout model and no-duplicate-payment principle. | Decline/release, reassignment, custody evidence/handoff, workload, and multi-agent allocation/compensation details remain **PENDING EXPLICIT BUSINESS APPROVAL**. |
| COM-CAN-004 | **UNRESOLVED / REQUIRES EXPLICIT BUSINESS APPROVAL** | Administrator cancellation/override authority is not approved. | Scope, dual approval, self-approval and financial authority remain pending. |
| COM-REF-001 | **APPROVED** | Provider-executed refunds where supported, otherwise external/manual completed refunds; request/submission is not proof of return; confirmation requires provider-authoritative evidence or a separately approved manual verification procedure. | Roles, SLA, execution controls, manual evidence, failure/retry, destination, fees, notifications, disputes and provider capabilities remain pending. |
| COM-REF-002 | **APPROVED** | Full and partial refund scope, conceptually associable with fulfillment, line, delivery fee, or another approved component. | Amount/allocation formula, component treatment, partial quantities, multiple-capture allocation, authority, provider behavior and recovery remain pending. |
| COM-MULTI-001 | **OUT OF SCOPE** | WEWE is online-payment-only. Cash collection, cash handoff, cash settlement, and cash courier collection are not active requirements. | Historical cash code may remain documented only as an implementation fact; do not extend it as policy without an explicit reopening decision. |
| Payment/order/refund state representation | **IMPLEMENTATION GAP** | Current payment and order statuses do not represent the approved uncertainty/refund lifecycle or multiple partial captures/refunds. | No new persisted state names are approved; engineering representation follows the approved lifecycle and pending refund rules. |
| Fulfillment cancellation/status aggregation | **IMPLEMENTATION GAP** | Current cancellation is order-wide and blocks at acceptance; fulfillment status recomputation does not reliably aggregate all-cancelled/mixed-cancelled outcomes. | Implement only after COM-CAN-001's pending scope/evidence/aggregation choices are approved. |
| Custody/reassignment and courier earning | **IMPLEMENTATION GAP** | No decline/release/reassignment or verified pickup evidence workflow exists; current earning divides customer delivery fee among assignments rather than the approved payout model. | Custody evidence and allocation decisions remain pending; do not infer them from current routes. |
| Retailer settlement/refund accounting | **IMPLEMENTATION GAP** | No retailer payable/settlement ledger or refund obligation/partial refund ledger exists; status-only refund cannot accurately represent all captured/refunded balances. | Financial formulas, permissions, evidence, and recovery rights remain pending. |
| Cross-lifecycle concurrency | **IMPLEMENTATION GAP** | Code paths have inconsistent lock ordering and lack multiple business event ledgers/idempotency mechanisms needed for the stated guarantees. | Lock order, transactions, ledgers, callback idempotency, and safe retries are technical design choices, not approvals to change business outcomes. |

### Approval-status key

- **APPROVED** — only the explicitly summarized business direction or parameter is approved; listed qualifications remain pending.
- **PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL** — recommendation only; not a rule to implement as final policy.
- **UNRESOLVED / REQUIRES BUSINESS OR ACCOUNTING CONFIRMATION** — no policy selected; obtain the appropriate decision before affected behavior.
- **PENDING PROVIDER VERIFICATION** — capability not established for WEWE; do not claim availability or enable dependent production behavior.
- **OUT OF SCOPE** — excluded from the current business scope.
- **IMPLEMENTATION GAP** — observed code does not meet or cannot represent an approved direction; not a new business decision.

## 13. Phase 4A → Phase 4B Readiness

### Business rules sufficiently approved to implement

- The initial delivery-pricing model and values in COM-FEE-001/008, subject to resolving the explicitly listed quote/rounding/location details before affected edge cases are enabled.
- Independent per-fulfillment delivery fee snapshots, zero delivery fee for pickup, no silent post-checkout repricing, and separation of customer delivery fees from courier payout.
- The courier payout formula and separation from customer fee. The formula's business direction can be represented in design, but no numeric payout can be calculated for production until its pending inputs and qualifying work are approved.
- Payment lifecycle principles: uncertainty is distinct from failure; do not blindly retry; reconcile; callbacks are idempotent; late success must not reopen a cancelled order.
- Online-payment-only scope and intended MTN/Airtel target methods, with no assumption of provider capabilities.
- Retailer collect/hold-and-settle direction, without a payable formula or live settlement authority.
- Fulfillment-level customer cancellation cutoff at verified physical pickup; assignment acceptance alone does not close eligibility.
- Full/partial refund scope and the requirement that submission is not confirmation.
- Cross-cutting conservation and no-duplicate-effect requirements, using approved amounts/eligibility only.

### Blocked on business/provider decisions

- Enabling real Mobile Money payment/refund execution until provider onboarding and capabilities are verified and COM-PAY-003/COM-REF procedures are approved.
- Real refund calculation/execution until amount allocation, authorization, evidence, destination, timing, failure/retry and dispute decisions are approved; in particular, no partial-refund allocation formula is approved.
- Retailer payable calculation or live retailer settlement until discounts, deductions, payment allocation, eligibility/hold/cadence, threshold, fees, taxes/accounting, destination, dispute and recovery terms are approved.
- Courier payout calculation/settlement until numeric values, eligible work/distance, multi-agent/reassignment allocation, rounding/remainder, evidence, exceptional compensation, timing and authorization are approved.
- Full cancellation and agent custody/reassignment behavior until cancellation scope/order aggregation, authoritative pickup evidence, release authority, workload, post-pickup handoff/return and related financial consequences are approved.
- Retailer post-confirmation rejection/inability remedies and administrator financial overrides until COM-CAN-002/004 decisions are approved.
- Beyond-normal route quotes and post-checkout price corrections until the remaining COM-FEE clarifications are decided.

### Technical gaps to address in Phase 4B

1. Establish an auditable event/ledger foundation and consistent transaction/lock ordering for order, fulfillment, assignment, payment, refund, inventory, settlement and payout operations; make event processing idempotent.
2. Implement the approved payment uncertainty and late-success semantics without restarting cancelled orders; retain per-attempt evidence rather than relying on a single order payment status.
3. Implement fulfillment-level cancellation and order-status aggregation only after the related business decisions above are resolved; preserve the verified-pickup cutoff and inventory conservation.
4. Add pickup/custody evidence and assignment-history capability only after the evidence mechanism and authority are approved; distinguish acceptance, arrival, pickup, transit, handoff and delivery.
5. Build refund and retailer payable/settlement accounting only after approved allocation, authorization, evidence and recovery rules; represent submitted/unresolved separately from confirmed refund or settled transfer.
6. Replace current delivery-fee-derived earnings with the approved payout basis only after required inputs and allocation rules are approved; preserve one fulfillment entitlement and audit actual payout evidence.
7. Verify all changes against PostgreSQL concurrency behavior, callback replay/conflict cases, cancellation/pickup and reassignment races, duplicate completion, financial conservation, and Phase 3 regression tests before production use.

### Phase 4B.1 technical implementation note (historical)

- **Payment uncertainty remains an implementation gap:** No persisted `UNKNOWN/UNCERTAIN` status or reconciliation workflow was added. A provider initiation timeout is retained as `PENDING` and blocks a second attempt; this prevents an unsafe retry but does not distinguish an unresolved outcome from an ordinarily pending attempt. Payment callbacks now reject conflicting terminal transitions, suppress duplicate effects, and aggregate all payment attempts so one refunded capture cannot make an order fully refunded while another capture remains successful. A late success updates payment status without reopening a cancelled order.
- **Cancellation remains an order-level technical compromise:** The current endpoint has no fulfillment selector, so it atomically cancels the whole order only when no assignment indicates pickup or later custody. It does not support cancelling eligible fulfillments separately from already-picked-up fulfillments. The existing `PICKED_UP` status/timestamp is not independent proof of retailer handover; authoritative custody evidence and cancellation scope remain unresolved. Agent workload release on cancellation is also not performed pending an approved workload policy.
- **Payment/refund accounting remains incomplete:** Successful payment records are still full-capture/full-refund statuses only. There is no partial-refund ledger or representation for submitted, in-flight, or unresolved refund amounts. The single-payment full-refund transition is guarded and idempotent, but cumulative reserved-refund balance protection cannot be implemented safely without that accounting model and approved procedures.
- **Financial paths still gated:** No retailer settlement ledger or payout allocation was added. The legacy delivery-earning calculation still derives its amount from the customer delivery fee and therefore does not satisfy the approved fee/payout separation. It must not be treated as an approved payout basis; replacing or disabling it requires the approved payout inputs and a safe representation for an uncalculated earning.
- **Concurrency verification remains incomplete:** The relevant route lock order has been aligned as described above, but these changes have not been proven under PostgreSQL concurrency or multiple-process callback/reassignment races.
- No schema or migration change was made. No MTN/Airtel provider integration or cash workflow was added.

### Phase 4B.2 technical implementation note

- **Payment attempts:** Each `Payment` row now has an immutable internal attempt reference, optional client idempotency key, and initiation/resolution timestamps. Persisted `UNKNOWN` is the technical representation of Phase 4A's conceptual `UNKNOWN/UNCERTAIN`. Existing payment rows are retained and receive a deterministic legacy attempt reference.
- **Idempotency and retry protection:** The payment endpoint reuses a matching attempt for the same key and rejects request-context mismatches. An unresolved or pending attempt blocks a new charge; an authoritative failure permits a new attempt with a new key; a successful attempt remains non-retryable. Replaying the same key returns the existing attempt, including after its status changes.
- **Events and reconciliation:** Duplicate provider events are idempotent. Conflicting event IDs and outcomes are held as reconciliation conflicts rather than overwriting terminal outcomes. A provider-neutral reconciliation protocol and persisted requested/attempted/unresolved/authoritative/conflict/manual-review records exist; no provider status query or adapter is implemented.
- **Late capture:** A late successful callback or authoritative reconciliation updates the payment attempt while leaving a cancelled order cancelled and recording `MANUAL_REVIEW`. The refund obligation is not automatically created because refund authority and allocation remain gated.
- **Refund balance:** Refund attempts are tracked per capture. Confirmed, submitted, and unknown refund amounts reserve captured balance; a reservation exceeding the successful capture is rejected. Full admin/provider refund paths use this ledger. Partial-refund allocation and settlement accounting remain unimplemented.
- **Schema:** Revision `0006_payment_attempt_uncertainty` adds attempt identity/idempotency and timestamps, payment-event disposition, plus payment-reconciliation and payment-refund tables. A targeted SQLite migration test verifies legacy payment/event preservation and schema extension. The full legacy Alembic chain could not be smoke-tested on SQLite because revision `0003_case_insensitive_email` uses unsupported SQLite constraint alteration; production-dialect migration validation remains required.
- No MTN/Airtel provider integration, real callback semantics, provider refund/query API, retailer transfer, or new cash workflow was implemented. Existing legacy cash behavior was not intentionally removed or expanded.

### Must not be implemented as approved policy yet

- Any proposed payout amount/rate/minimum/cap/rounding/hold or multi-agent split.
- Any proposed settlement fee/commission, threshold, timing, eligibility formula, discount allocation, processing-fee bearer, tax/withholding treatment, payout rail, or retailer recovery/clawback.
- Any proposed payment/refund timing, SLA, automatic polling schedule, customer message, approver role, manual resolution, refund destination, partial allocation formula, or provider capability not verified.
- Any cancellation fee, retailer/agent compensation, post-pickup customer cancellation, refusal/return rule, or agent self-decline/reassignment authority.
- Any particular custody proof method, provider API/callback/query/refund/idempotency/sandbox/settlement feature, new persisted lifecycle state, or order aggregate status not approved/verified.
- Cash collection, cash handoff, cash settlement, or cash courier collection workflows.

Phase 4B may implement approved principles and technical safeguards, but must gate dependent real-money and exception workflows until the listed business approvals and provider verification are complete. This readiness section does not authorize Phase 4B work or change any pending decision.

### Final decision register snapshot

| Rule group | Status | Decision |
|---|---|---|
| COM-FEE-001–011 | **APPROVED** | Initial pricing directions/parameters as specified; remaining quote, rounding, location, and routing details are listed as pending. |
| COM-PAY-001–003 | **APPROVED** | Payout/payment lifecycle directions only; all specified operating parameters remain pending. |
| COM-PAY-004 | **APPROVED** | MTN Mobile Money and Airtel Money target methods; all provider capabilities remain **PENDING PROVIDER VERIFICATION**. |
| COM-SET-001 | **APPROVED** | WEWE collect/hold and retailer settlement direction; all settlement calculation/operating terms remain **PROPOSED — PENDING EXPLICIT BUSINESS APPROVAL** or accounting confirmation. |
| COM-CAN-001 | **APPROVED** | Fulfillment-level cancellation cutoff at verified physical pickup; operational and financial details remain pending. |
| COM-CAN-002, COM-CAN-004 | **UNRESOLVED / REQUIRES EXPLICIT BUSINESS APPROVAL** | Retailer post-confirmation inability/rejection remedies and administrator override authority. |
| COM-CAN-003 | **APPROVED** | Cross-rule acceptance/custody and payout principles only; decline, reassignment, evidence, workload, and compensation details remain pending. |
| COM-REF-001, COM-REF-002 | **APPROVED** | Refund execution model and full/partial scope only; amount, authority, timing, evidence, and provider details remain pending. |
| COM-MULTI-001 | **OUT OF SCOPE** | Cash collection, handoff, settlement, and courier collection. Historical code is implementation evidence only. |
| Cross-cutting state, ledger, custody, settlement, refund, and payout gaps | **IMPLEMENTATION GAP** | Current system does not yet implement all approved directions; engineering work must preserve the approved scope and wait for listed decisions where gated. |
