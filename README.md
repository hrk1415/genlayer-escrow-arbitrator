# Decentralized Escrow Arbitrator

**A production-grade, milestone-based escrow primitive with AI-powered dispute arbitration for GenLayer.**

> Built on GenLayer's Optimistic Democracy consensus. Not a demo — a reusable contract primitive for freelancing, bounties, service agreements, and any scenario requiring trustless conditional payments with dispute resolution.

---

## Why This Contract Matters

Traditional escrow either requires a trusted third-party arbitrator (centralized risk) or locks funds behind rigid programmatic conditions that can't handle real-world disputes ("the deliverable doesn't match what I asked for"). 

This contract solves the gap: **AI-powered, consensus-verified dispute resolution grounded in the original contract terms** — not arbitrary "AI decides" logic, but structured arbitration where validators independently assess whether a ruling is fair based on evidence from both parties.

### Real-World Use Cases

| Use Case | How It Works |
|----------|-------------|
| **Freelance Platforms** | Client funds milestones, freelancer delivers, disputes resolved by evidence-based AI arbitration |
| **Bounty Systems** | Bounty poster defines acceptance criteria, contributor submits work, AI verifies against criteria |
| **Service Agreements** | SLA-based contracts with milestone payments and automated dispute resolution |
| **DAO Grants** | Grant recipients deliver against milestones, DAO treasury releases per milestone |
| **Agent-to-Agent Escrow** | AI agents hold each other accountable for delivered services |

---

## Architecture

### State Machine (Per Milestone)

```
CREATED ──fund──► FUNDED ──deliver──► DELIVERED ──approve──► APPROVED
                    │                     │                   (funds → seller)
                    │                     │
                    ▼                     ▼
                CANCELLED             DISPUTED ──arbitrate──► RESOLVED_BUYER
                (refund → buyer)          │                   (refund → buyer)
                                          │
                                          ├──────────────────► RESOLVED_SELLER
                                          │                   (funds → seller)
                                          │
                                          └──────────────────► RESOLVED_SPLIT
                                                              (proportional split)
```

### Consensus Design

This contract uses **two distinct equivalence principles** for different types of verification:

#### 1. `strict_eq` — Deliverable URL Verification
```python
def check_url_live():
    page = gl.nondet.web.render(url, mode="html")
    return expected_keyword.lower() in page.lower()

result = gl.eq_principle.strict_eq(check_url_live)
```
**Why `strict_eq`?** The output is a deterministic boolean. All validators fetch the same URL and check for the same keyword — the result must be identical across nodes.

#### 2. `prompt_non_comparative` — Dispute Arbitration
```python
ruling = gl.eq_principle.prompt_non_comparative(
    generate_ruling,
    task="Evaluate whether this dispute ruling is fair...",
    criteria="The ruling must: (1) Be BUYER/SELLER/SPLIT..."
)
```
**Why `prompt_non_comparative`?** 
- The ruling is an open-ended judgment — validators can't generate byte-identical rulings.
- Having each validator regenerate a full competing ruling would be wasteful and could diverge on wording while agreeing on substance.
- Instead, validators evaluate the leader's proposed ruling against the raw evidence and contract terms, checking whether it's logically consistent and well-grounded.
- The structured criteria prevent rubber-stamping: validators must verify specific properties of the ruling.

### Evidence-Based Arbitration (Not "AI Decides")

The arbitration prompt is carefully designed to:

1. **Ground decisions in contract terms** — The AI must cite which specific term was or was not met
2. **Consider both parties** — Both buyer's complaint and seller's defense are weighed
3. **Produce structured output** — JSON with constrained enums (`BUYER`/`SELLER`/`SPLIT`), preventing ambiguous rulings
4. **Include reasoning** — 3-5 sentences citing specific evidence, making the ruling auditable
5. **Support proportional outcomes** — `SPLIT` with a `buyer_split_pct` for partial-delivery scenarios

---

## Contract API Reference

### Constructor
```python
EscrowArbitrator(
    seller: Address,
    contract_terms: str,
    milestone_titles: str,        # JSON array
    milestone_descriptions: str,  # JSON array
    milestone_amounts_wei: str,   # JSON array of u256 strings
    milestone_deadlines: str,     # JSON array of Unix timestamps
)
```

### Write Methods

| Method | Caller | Consensus | Description |
|--------|--------|-----------|-------------|
| `fund_milestone(id)` | Buyer (payable) | None | Deposit exact amount for a milestone |
| `submit_deliverable(id, url, notes)` | Seller | None | Submit work for a funded milestone |
| `verify_deliverable_url(id, keyword)` | Any | `strict_eq` | Verify deliverable URL is live |
| `approve_milestone(id)` | Buyer | None | Release funds to seller (happy path) |
| `raise_dispute(id, text, urls)` | Buyer | None | Raise dispute with evidence |
| `submit_defense(id, text, urls)` | Seller | None | Submit counter-evidence |
| `arbitrate_dispute(id)` | Any | `prompt_non_comparative` | **AI arbitration** |
| `mutual_cancel(id)` | Buyer | None | Cancel funded milestone (full refund) |

### View Methods

| Method | Returns |
|--------|---------|
| `get_milestone(id)` | Milestone state (JSON) |
| `get_evidence(id)` | Dispute evidence (JSON) |
| `get_contract_summary()` | Aggregate state (JSON) |
| `get_contract_terms()` | Immutable contract terms |

---

## Example Interaction Flow

### Happy Path
```
1. Buyer deploys contract with 3 milestones
2. Buyer funds milestone 0 → sends 1 GEN
3. Seller delivers milestone 0 → submits GitHub URL
4. Buyer verifies URL is live (strict_eq consensus)
5. Buyer approves milestone 0 → 1 GEN released to seller
6. Repeat for milestones 1 and 2
```

### Dispute Path
```
1. Buyer funds milestone 1 → sends 2 GEN  
2. Seller submits deliverable
3. Buyer raises dispute: "Tests only cover 45%, contract requires 80%"
   Evidence URLs: [coverage report screenshot, CI pipeline output]
4. Seller submits defense: "Coverage is 82% when including integration tests"
   Evidence URLs: [full test report, integration test results]
5. Anyone triggers arbitration → AI evaluates evidence against contract terms
6. Ruling: SPLIT (buyer_split_pct: 30)
   → 0.6 GEN refunded to buyer, 1.4 GEN released to seller
```

---

## Testing

```bash
# Run direct execution tests (no Docker/GenVM required)
pytest tests/test_escrow_arbitrator.py -v

# Run linter (requires genvm-lint)
genvm-lint check contracts/escrow_arbitrator.py
```

Tests cover:
- ✅ Deployment and initialization
- ✅ Milestone state transitions
- ✅ Financial counter tracking
- ✅ View method correctness
- ✅ Input validation (empty milestones, mismatched arrays)
- ✅ Evidence schema completeness
- ✅ Consensus design verification

---

## Design Decisions

### Why Milestone-Based (Not All-or-Nothing)?
Real-world contracts rarely have a single deliverable. Freelancers deliver incrementally, and clients want to pay incrementally. Milestone-based escrow prevents the "98% done but no payment" problem.

### Why JSON-Encoded State in TreeMap?
GenLayer's TreeMap doesn't support nested complex types. JSON encoding provides flexibility for rich milestone and evidence schemas while staying within GenVM's constraints. All JSON is validated at write-time.

### Why `prompt_non_comparative` for Arbitration?
- **Efficiency**: Validators don't waste compute regenerating full rulings
- **Fairness**: Validators assess the ruling's logic, not its wording
- **Determinism**: Structured criteria make validation objective despite subjective content
- **Auditability**: The reasoning field creates an on-chain record of why the ruling was made

### Why Require Evidence from Both Parties?
Adversarial evidence submission ensures the AI sees both sides before ruling. Without the seller's defense, arbitration could be trivially gamed by buyers filing bogus disputes.

---

## License

MIT
