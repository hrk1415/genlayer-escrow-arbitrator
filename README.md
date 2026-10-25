# Decentralized Escrow Arbitrator

**A production-grade, milestone-based escrow primitive with on-chain evidence acquisition and AI dispute arbitration for GenLayer.**

> Built on GenLayer's Optimistic Democracy consensus. Solves trustless conditional payments with dispute resolution by actively acquiring and evaluating material dispute evidence against written contract terms.

---

## Why This Contract Matters

Traditional escrow contracts either rely on centralized third-party arbiters or lock funds behind rigid programmatic rules that cannot assess the quality of delivered work. Meanwhile, naive "AI escrow" demos merely pass raw text claims into an LLM and let an AI arbitrarily decide who gets paid without looking at real evidence.

**This contract solves this critical flaw through genuine, on-chain Evidence-Based Arbitration:**
1. **On-Chain Evidence Acquisition**: During arbitration, the contract fetches the actual material evidence from the web (`gl.nondet.web.render`) for:
   - The submitted deliverable URL
   - The buyer's defect/complaint evidence URL (e.g., test failures, error logs)
   - The seller's counter-defense evidence URL (e.g., CI/CD reports, deployment proofs)
2. **Validator Consensus on Acquired Evidence**: Both the leader node and committee validators receive the complete acquired evidence payload and independently audit whether the deliverable conforms to the agreed contract terms.
3. **Structured & Auditable Rulings**: Output is constrained to strict JSON (`BUYER`, `SELLER`, or `SPLIT`), accompanied by specific citations of contract terms and an `evidence_validation_summary`.

---

## Architecture

### State Machine (Per Milestone)

```
CREATED ──fund_milestone──► FUNDED ──submit_deliverable──► DELIVERED ──approve_milestone──► APPROVED
                               │                               │                           (funds → seller)
                               │                               │
                               ▼                               ▼
                           CANCELLED                       DISPUTED ──arbitrate_dispute──► RESOLVED_BUYER
                           (refund → buyer)                    │                           (refund → buyer)
                                                               │
                                                               ├─────────────────────────► RESOLVED_SELLER
                                                               │                           (funds → seller)
                                                               │
                                                               └─────────────────────────► RESOLVED_SPLIT
                                                                                           (proportional split)
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

### 2. `prompt_non_comparative` — Material Evidence-Based Arbitration
```python
def generate_ruling():
    # 1. On-Chain Material Evidence Acquisition
    deliverable_content = safe_fetch(deliverable_url)
    buyer_evidence_content = safe_fetch(buyer_url)
    seller_evidence_content = safe_fetch(seller_url)

    dispute_payload = {
        "contract_terms": self.contract_terms,
        "milestone_title": ms["title"],
        "claims": {
            "buyer_claim": ev["buyer_claim"],
            "seller_defense": ev["seller_defense"]
        },
        "acquired_material_evidence": {
            "deliverable_content_excerpt": deliverable_content,
            "buyer_evidence_content_excerpt": buyer_evidence_content,
            "seller_evidence_content_excerpt": seller_evidence_content
        }
    }
    ...
    return gl.nondet.exec_prompt(prompt, response_format="json")

ruling = gl.eq_principle.prompt_non_comparative(
    generate_ruling,
    task="Audit the dispute ruling to ensure it thoroughly evaluates the acquired evidence content against the contract terms.",
    criteria="The ruling must: (1) Be BUYER, SELLER, or SPLIT. (2) Explicitly analyze acquired evidence fetched from submitted URLs. (3) Verify deliverable conformity against contract terms."
)
```
- **Purpose**: Evaluates contested milestones and determines fund allocation.
- **Why `prompt_non_comparative`**: Open-ended evaluation grounded in source evidence. Validators do not waste compute regenerating separate text; instead, they audit whether the leader's proposed ruling is logically substantiated by the acquired web evidence and the original contract terms.

---

## Contract API Reference

### Constructor
```python
EscrowArbitrator(
    seller: Address,
    contract_terms: str
)
```
- Deployer automatically becomes the `buyer`.
- Automatically initializes Milestone 0 with the agreed terms.

### Public Write Methods
| Method | Caller | Consensus | Description |
|--------|--------|-----------|-------------|
| `add_milestone(id, title, desc, amount_wei)` | Buyer | None | Defines a new milestone specification |
| `fund_milestone(id)` | Buyer (payable) | None | Deposits funds for a specific milestone |
| `submit_deliverable(id, url, notes)` | Seller | None | Submits work for a funded milestone |
| `verify_deliverable_url(id, keyword)` | Any | `strict_eq` | Verifies deliverable link is live and valid |
| `approve_milestone(id)` | Buyer | None | Releases milestone funds directly to seller |
| `raise_dispute(id, claim, evidence_url)` | Buyer | None | Initiates dispute with supporting proof URL |
| `submit_defense(id, defense, defense_url)` | Seller | None | Submits counter-evidence proof URL |
| `arbitrate_dispute(id)` | Any | `prompt_non_comparative` | **Acquires material evidence on-chain & arbitrates** |

### Public View Methods
| Method | Returns | Description |
|--------|---------|-------------|
| `get_milestone(id)` | JSON string | Milestone details, status, and deliverable URL |
| `get_contract_summary()` | JSON string | Aggregate balances, terms, parties, and contract state |

---

## Testing

Run direct execution unit tests:
```bash
pytest tests/test_escrow_arbitrator.py -v
```

Tests cover:
- Contract initialization and party binding
- State machine transitions (CREATED -> FUNDED -> DELIVERED -> DISPUTED)
- Evidence and defense URL submissions
- Arbitration pre-condition validation (preventing one-sided resolution)
- Evidence validation summary schema integrity

---

## License
MIT
