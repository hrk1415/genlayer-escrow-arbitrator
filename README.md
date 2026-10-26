# Decentralized Escrow Arbitrator

**A production-grade, milestone-based escrow primitive with on-chain evidence acquisition, fail-closed AI arbitration, and enforced escrow invariants for GenLayer.**

> Built natively on GenLayer's Optimistic Democracy consensus. Designed as an unexploitable, reusable building block for freelancing platforms, bounty systems, and service agreements.

---

## Enforced Escrow Invariants

This contract enforces four fundamental cryptographic and financial invariants:

1. **Strict Deposit Equality**:
   - `add_milestone()` strictly validates that `amount_wei` is a positive integer (`> 0`).
   - `fund_milestone()` verifies that the caller's actual deposit value (`gl.message.value`) exactly equals the milestone's required positive amount before transitioning to `STATUS_FUNDED`.
   - Records the exact deposited funds in `escrowed_wei`.

2. **Lifecycle Record Immutability**:
   - `add_milestone()` strictly prevents overwriting any existing milestone ID, preserving milestone history and preventing griefing/fund misdirection.

3. **Fail-Closed On-Chain Evidence Acquisition**:
   - Arbitration (`arbitrate_dispute()`) actively acquires material evidence on-chain via `gl.nondet.web.render()` for:
     1. The submitted deliverable URL
     2. The buyer's dispute evidence URL
     3. The seller's counter-defense URL
   - **Fail-Closed Guarantee**: If any of the required URLs are missing, malformed, or fail to return acquired content, arbitration aborts immediately with a `UserError`. **Zero funds are transferred, and escrowed balances remain preserved.**

4. **Fund Conservation & Payout Bounding**:
   - Both `approve_milestone()` and `arbitrate_dispute()` verify that positive `escrowed_wei` exists.
   - Payouts are strictly bounded by `escrowed_wei` and clear the balance upon execution to guarantee that approval and dispute settlement can **never pay more than the amount escrowed for that milestone**.

---

## State Machine (Per Milestone)

```
CREATED ──fund_milestone (exact deposit)──► FUNDED ──submit_deliverable──► DELIVERED
                                              │                               │
                                              ▼                               ▼
                                          CANCELLED                       DISPUTED
                                       (refund to buyer)                      │
                                                                 arbitrate_dispute()
                                                         (fail-closed evidence acquisition)
                                                                              │
                                                      ┌───────────────────────┼───────────────────────┐
                                                      ▼                       ▼                       ▼
                                                RESOLVED_BUYER          RESOLVED_SELLER         RESOLVED_SPLIT
                                             (escrowed → buyer)      (escrowed → seller)      (50/50 exact split)
```

---

## Consensus Architecture & Evidence Acquisition

This contract utilizes two distinct GenLayer consensus patterns:

### 1. `strict_eq` — Deliverable URL Verification
```python
def check_url_live():
    page = gl.nondet.web.render(url, mode="html")
    return expected_keyword.lower() in page.lower()

result = gl.eq_principle.strict_eq(check_url_live)
```
- **Purpose**: Verifies that a deliverable link is live and contains required keywords.
- **Why `strict_eq`**: Deterministic boolean check where all validators must agree on the identical byte-for-byte outcome.

### 2. `prompt_non_comparative` — Fail-Closed Material Evidence Arbitration
```python
def generate_ruling():
    # Fail-closed acquisition: aborts if any evidence is missing or fails to fetch
    deliverable_content = acquire_evidence_strict(deliverable_url, "deliverable evidence")
    buyer_evidence_content = acquire_evidence_strict(buyer_url, "buyer dispute evidence")
    seller_evidence_content = acquire_evidence_strict(seller_url, "seller defense evidence")

    dispute_payload = { ... }
    return gl.nondet.exec_prompt(prompt, response_format="json")

ruling = gl.eq_principle.prompt_non_comparative(
    generate_ruling,
    task="Audit the dispute ruling to ensure it thoroughly evaluates the acquired evidence content against the contract terms.",
    criteria="The ruling must: (1) Be BUYER, SELLER, or SPLIT. (2) Explicitly analyze acquired evidence fetched from submitted URLs. (3) Verify deliverable conformity against contract terms."
)
```

---

## Contract API Reference

### Constructor
```python
EscrowArbitrator(
    seller: Address,
    contract_terms: str
)
```

### Public Write Methods
| Method | Caller | Consensus | Description |
|--------|--------|-----------|-------------|
| `add_milestone(id, title, desc, amount_wei)` | Buyer | None | Adds new milestone; prevents overwriting and requires amount > 0 |
| `fund_milestone(id)` | Buyer (payable) | None | Requires exact deposit (`gl.message.value == amount_wei`) |
| `submit_deliverable(id, url, notes)` | Seller | None | Submits deliverable with valid HTTP/HTTPS URL |
| `verify_deliverable_url(id, keyword)` | Any | `strict_eq` | Deterministically verifies deliverable link is live |
| `approve_milestone(id)` | Buyer | None | Releases escrowed balance to seller; clears escrowed amount |
| `raise_dispute(id, claim, evidence_url)` | Buyer | None | Initiates dispute with validated evidence URL |
| `submit_defense(id, defense, defense_url)` | Seller | None | Submits counter-defense with validated evidence URL |
| `arbitrate_dispute(id)` | Any | `prompt_non_comparative` | **Acquires material evidence on-chain (fails closed if missing); settles bounded by escrowed balance** |

---

## Testing

Run direct execution unit tests verifying all four invariants:
```bash
pytest tests/test_escrow_arbitrator.py -v
```

Tests cover:
- Contract initialization and party binding
- Rejection of deposit mismatch during funding
- Prevention of milestone lifecycle overwrites in `add_milestone`
- Rejection of non-positive milestone amounts
- Fail-closed behavior when evidence cannot be acquired
- Bounded payout invariant preventing overpayment or double settlement

---

## License
MIT
