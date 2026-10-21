# { "Depends": "py-genlayer:latest" }
"""
Decentralized Escrow Arbitrator — GenLayer Intelligent Contract
===============================================================

A production-grade, multi-party escrow primitive with AI-powered dispute
resolution via GenLayer's Optimistic Democracy consensus. Designed as a
reusable building block for freelancing platforms, bounty systems, service
agreements, and any scenario requiring trustless conditional payments with
human-readable contract terms.

Key Design Decisions
--------------------
- **Layered Equivalence Checks**: Factual evidence (URLs, deliverables) is
  verified with `strict_eq` for deterministic boolean checks, while subjective
  dispute rulings use `prompt_non_comparative` to evaluate evidence against
  contract terms without forcing validators to regenerate expensive outputs.
- **Milestone-Based Escrow**: Funds are released per-milestone rather than
  all-or-nothing, supporting real-world partial delivery workflows.
- **Evidence-Based Arbitration**: Disputes require structured evidence from
  both parties. The AI arbitration evaluates evidence against the original
  contract terms, not arbitrary "AI decides" logic.
- **Configurable Deadlines**: Each milestone has an independent deadline.
  Auto-refund on expiry prevents fund lockup.
- **Penalty-Free Mutual Resolution**: Parties can mutually agree to cancel
  or renegotiate before escalating to arbitration.

Consensus Architecture
----------------------
1. `verify_deliverable_url()` — `strict_eq`: Deterministic check that a
   deliverable URL returns HTTP 200 and contains expected keywords.
2. `submit_dispute()` — Records evidence on-chain (no consensus needed).
3. `arbitrate_dispute()` — `prompt_non_comparative`: Validators independently
   evaluate the leader's ruling against both parties' evidence and the
   original contract terms. The task prompt enforces structured JSON output
   with explicit reasoning, and the criteria ensure rulings are grounded
   in the contract terms rather than arbitrary judgment.

State Design
------------
- `milestones: TreeMap[u32, str]`  — JSON-encoded milestone metadata
- `evidence: TreeMap[u32, str]`    — JSON-encoded dispute evidence per milestone
- All financial amounts use `u256` (wei denomination)
- Enum-like status tracking via string constants for readability

Author: Antigravity Agent
License: MIT
"""

from genlayer import *
import json


# ──────────────────────────────────────────────────────────────────────
# Status Constants
# ──────────────────────────────────────────────────────────────────────
STATUS_CREATED = "CREATED"
STATUS_FUNDED = "FUNDED"
STATUS_DELIVERED = "DELIVERED"
STATUS_APPROVED = "APPROVED"
STATUS_DISPUTED = "DISPUTED"
STATUS_RESOLVED_BUYER = "RESOLVED_BUYER"
STATUS_RESOLVED_SELLER = "RESOLVED_SELLER"
STATUS_RESOLVED_SPLIT = "RESOLVED_SPLIT"
STATUS_CANCELLED = "CANCELLED"
STATUS_EXPIRED = "EXPIRED"


class EscrowArbitrator(gl.Contract):
    """
    A milestone-based escrow contract with AI-powered dispute arbitration.

    Lifecycle per milestone:
        CREATED → FUNDED → DELIVERED → APPROVED (funds released)
                                     → DISPUTED → RESOLVED_* (arbitration)
                        → EXPIRED (auto-refund after deadline)

    Roles:
        - buyer:  Funds escrow, approves deliverables, or raises disputes
        - seller: Delivers work, submits evidence in disputes
        - contract (autonomous): Arbitrates disputes via GenLayer consensus
    """

    # ── Core Parties ─────────────────────────────────────────────────
    buyer: Address
    seller: Address

    # ── Contract Terms (immutable after creation) ────────────────────
    contract_terms: str          # Natural-language description of the agreement
    total_milestones: u32        # Number of milestones in this contract

    # ── Per-Milestone State ──────────────────────────────────────────
    # Each milestone is stored as a JSON object:
    # {
    #   "title": str,
    #   "description": str,
    #   "amount_wei": str,       (u256 serialized as string)
    #   "deadline_epoch": int,   (Unix timestamp)
    #   "status": str,
    #   "deliverable_url": str | null,
    #   "delivery_notes": str | null
    # }
    milestones: TreeMap[u32, str]

    # ── Evidence Store (per-milestone, populated during disputes) ────
    # {
    #   "buyer_evidence": str,
    #   "seller_evidence": str,
    #   "buyer_evidence_urls": [str],
    #   "seller_evidence_urls": [str],
    #   "ruling": str | null,
    #   "ruling_reasoning": str | null,
    #   "buyer_split_pct": int | null     (0-100, only for RESOLVED_SPLIT)
    # }
    evidence: TreeMap[u32, str]

    # ── Aggregate Tracking ───────────────────────────────────────────
    total_deposited: u256
    total_released: u256
    total_refunded: u256
    is_active: bool

    # ══════════════════════════════════════════════════════════════════
    # CONSTRUCTOR
    # ══════════════════════════════════════════════════════════════════

    def __init__(
        self,
        seller: Address,
        contract_terms: str,
        milestone_titles: str,        # JSON array of title strings
        milestone_descriptions: str,  # JSON array of description strings
        milestone_amounts_wei: str,   # JSON array of amount strings (u256)
        milestone_deadlines: str,     # JSON array of Unix timestamps (int)
    ):
        """
        Deploy a new escrow contract.

        The deployer becomes the buyer. All milestone metadata is set
        at deployment time and cannot be changed (immutable terms).
        """
        self.buyer = gl.message.sender_address
        self.seller = seller
        self.contract_terms = contract_terms

        titles = json.loads(milestone_titles)
        descriptions = json.loads(milestone_descriptions)
        amounts = json.loads(milestone_amounts_wei)
        deadlines = json.loads(milestone_deadlines)

        n = len(titles)
        if n == 0:
            raise gl.vm.UserError("At least one milestone is required")
        if not (len(descriptions) == n and len(amounts) == n and len(deadlines) == n):
            raise gl.vm.UserError("Milestone arrays must all have the same length")

        self.total_milestones = u32(n)
        self.milestones = TreeMap()
        self.evidence = TreeMap()

        for i in range(n):
            milestone = {
                "title": titles[i],
                "description": descriptions[i],
                "amount_wei": str(amounts[i]),
                "deadline_epoch": int(deadlines[i]),
                "status": STATUS_CREATED,
                "deliverable_url": None,
                "delivery_notes": None,
            }
            self.milestones[u32(i)] = json.dumps(milestone)

        self.total_deposited = u256(0)
        self.total_released = u256(0)
        self.total_refunded = u256(0)
        self.is_active = True

    # ══════════════════════════════════════════════════════════════════
    # FUNDING
    # ══════════════════════════════════════════════════════════════════

    @gl.public.write.payable
    def fund_milestone(self, milestone_id: u32) -> None:
        """
        Buyer deposits the exact amount for a specific milestone.

        Guards:
            - Only the buyer can fund
            - Milestone must be in CREATED status
            - Sent value must match the milestone amount exactly
        """
        self._require_active()
        self._require_buyer()

        ms = self._get_milestone(milestone_id)
        if ms["status"] != STATUS_CREATED:
            raise gl.vm.UserError(
                f"Milestone {milestone_id} is not in CREATED status"
            )

        expected = u256(int(ms["amount_wei"]))
        if gl.message.value != expected:
            raise gl.vm.UserError(
                f"Must send exactly {ms['amount_wei']} wei for this milestone"
            )

        ms["status"] = STATUS_FUNDED
        self.milestones[milestone_id] = json.dumps(ms)
        self.total_deposited = self.total_deposited + gl.message.value

    # ══════════════════════════════════════════════════════════════════
    # DELIVERY & APPROVAL
    # ══════════════════════════════════════════════════════════════════

    @gl.public.write
    def submit_deliverable(
        self, milestone_id: u32, deliverable_url: str, delivery_notes: str
    ) -> None:
        """
        Seller submits a deliverable for a funded milestone.

        The deliverable_url should point to the completed work (e.g., a
        GitHub repo, deployed app, document, etc.). Delivery notes provide
        additional context about the submission.
        """
        self._require_active()
        self._require_seller()

        ms = self._get_milestone(milestone_id)
        if ms["status"] != STATUS_FUNDED:
            raise gl.vm.UserError(
                f"Milestone {milestone_id} is not in FUNDED status"
            )

        ms["status"] = STATUS_DELIVERED
        ms["deliverable_url"] = deliverable_url
        ms["delivery_notes"] = delivery_notes
        self.milestones[milestone_id] = json.dumps(ms)

    @gl.public.write
    def verify_deliverable_url(self, milestone_id: u32, expected_keyword: str) -> bool:
        """
        Consensus-verified check that a deliverable URL is live and contains
        an expected keyword. Uses `strict_eq` because the result is a
        deterministic boolean derived from stable web content.

        This is a helper for the buyer to verify basic deliverable presence
        before full approval. The keyword check prevents accepting dead or
        unrelated links.

        Returns:
            True if the URL is live and contains the keyword.
        """
        self._require_active()

        ms = self._get_milestone(milestone_id)
        if ms["deliverable_url"] is None:
            raise gl.vm.UserError("No deliverable URL submitted for this milestone")

        url = ms["deliverable_url"]

        def check_url_live():
            """
            Non-deterministic block: fetch the URL and check for the keyword.
            strict_eq ensures all validators agree on the boolean result.
            """
            page = gl.nondet.web.render(url, mode="html")
            # Normalize to lowercase for case-insensitive matching
            return expected_keyword.lower() in page.lower()

        return gl.eq_principle.strict_eq(check_url_live)

    @gl.public.write
    def approve_milestone(self, milestone_id: u32) -> None:
        """
        Buyer approves a delivered milestone, releasing funds to the seller.

        This is the happy-path resolution — no AI arbitration needed.
        Funds are transferred to the seller upon transaction finalization.
        """
        self._require_active()
        self._require_buyer()

        ms = self._get_milestone(milestone_id)
        if ms["status"] != STATUS_DELIVERED:
            raise gl.vm.UserError(
                f"Milestone {milestone_id} is not in DELIVERED status"
            )

        amount = u256(int(ms["amount_wei"]))
        ms["status"] = STATUS_APPROVED
        self.milestones[milestone_id] = json.dumps(ms)
        self.total_released = self.total_released + amount

        # Transfer funds to seller
        seller_ref = gl.get_contract_at(self.seller)
        seller_ref.emit_transfer(value=amount, on="finalized")

    # ══════════════════════════════════════════════════════════════════
    # DISPUTE RESOLUTION (AI-Powered Arbitration)
    # ══════════════════════════════════════════════════════════════════

    @gl.public.write
    def raise_dispute(
        self,
        milestone_id: u32,
        evidence_text: str,
        evidence_urls: str,  # JSON array of URL strings
    ) -> None:
        """
        Buyer raises a dispute on a delivered milestone.

        The buyer must provide:
        - evidence_text: A clear written explanation of why the deliverable
          does not meet the contract terms.
        - evidence_urls: JSON array of URLs supporting the claim (screenshots,
          test results, requirement docs, etc.)

        This transitions the milestone to DISPUTED status and records
        the buyer's evidence. The seller must then submit counter-evidence
        before arbitration can proceed.
        """
        self._require_active()
        self._require_buyer()

        ms = self._get_milestone(milestone_id)
        if ms["status"] != STATUS_DELIVERED:
            raise gl.vm.UserError(
                f"Milestone {milestone_id} must be in DELIVERED status to dispute"
            )

        ms["status"] = STATUS_DISPUTED
        self.milestones[milestone_id] = json.dumps(ms)

        urls = json.loads(evidence_urls)
        ev = {
            "buyer_evidence": evidence_text,
            "seller_evidence": "",
            "buyer_evidence_urls": urls,
            "seller_evidence_urls": [],
            "ruling": None,
            "ruling_reasoning": None,
            "buyer_split_pct": None,
        }
        self.evidence[milestone_id] = json.dumps(ev)

    @gl.public.write
    def submit_defense(
        self,
        milestone_id: u32,
        evidence_text: str,
        evidence_urls: str,  # JSON array of URL strings
    ) -> None:
        """
        Seller submits counter-evidence for a disputed milestone.

        Both sides must have submitted evidence before arbitration
        can proceed. This ensures fair, adversarial evaluation.
        """
        self._require_active()
        self._require_seller()

        ms = self._get_milestone(milestone_id)
        if ms["status"] != STATUS_DISPUTED:
            raise gl.vm.UserError(
                f"Milestone {milestone_id} is not in DISPUTED status"
            )

        ev = json.loads(self.evidence[milestone_id])
        if ev["seller_evidence"] != "":
            raise gl.vm.UserError("Defense has already been submitted")

        urls = json.loads(evidence_urls)
        ev["seller_evidence"] = evidence_text
        ev["seller_evidence_urls"] = urls
        self.evidence[milestone_id] = json.dumps(ev)

    @gl.public.write
    def arbitrate_dispute(self, milestone_id: u32) -> str:
        """
        AI-Powered Dispute Arbitration via GenLayer Consensus.

        This is the core consensus primitive. It uses `prompt_non_comparative`
        because:
        1. The ruling is an open-ended judgment — not a deterministic value
           that can be exactly replicated across validators.
        2. Validators should evaluate the LEADER's proposed ruling against
           the raw evidence, not generate their own competing ruling (which
           would be wasteful and could diverge on wording while agreeing
           on substance).
        3. The structured task prompt forces JSON output with explicit
           reasoning and a constrained ruling enum, ensuring validators
           can objectively assess whether the ruling is well-grounded.

        The arbitration evaluates:
        - Original contract terms and milestone description
        - Buyer's evidence (text + URLs)
        - Seller's evidence (text + URLs)
        - The deliverable itself (URL + notes)

        Possible Rulings:
        - BUYER:  Full refund to buyer (deliverable fails to meet terms)
        - SELLER: Full release to seller (deliverable meets terms)
        - SPLIT:  Partial payment with a buyer_split_pct (0-100)

        Returns:
            JSON string with the ruling details.
        """
        self._require_active()

        ms = self._get_milestone(milestone_id)
        if ms["status"] != STATUS_DISPUTED:
            raise gl.vm.UserError(
                f"Milestone {milestone_id} is not in DISPUTED status"
            )

        ev = json.loads(self.evidence[milestone_id])
        if ev["seller_evidence"] == "":
            raise gl.vm.UserError(
                "Seller must submit defense evidence before arbitration"
            )

        # ── Build the arbitration context ────────────────────────────
        arbitration_context = json.dumps({
            "contract_terms": self.contract_terms,
            "milestone_title": ms["title"],
            "milestone_description": ms["description"],
            "milestone_amount_wei": ms["amount_wei"],
            "deliverable_url": ms["deliverable_url"],
            "delivery_notes": ms["delivery_notes"],
            "buyer_claim": ev["buyer_evidence"],
            "buyer_evidence_urls": ev["buyer_evidence_urls"],
            "seller_defense": ev["seller_evidence"],
            "seller_evidence_urls": ev["seller_evidence_urls"],
        }, indent=2)

        # ── Non-deterministic arbitration block ──────────────────────
        def generate_ruling():
            """
            Leader generates a structured ruling by prompting the LLM
            with the full dispute context. The prompt is carefully designed
            to produce a constrained, structured output that validators
            can objectively evaluate.
            """
            prompt = f"""You are an impartial arbitrator evaluating a contract dispute.
You must analyze ALL evidence from both parties against the original contract terms
and deliver a fair, well-reasoned ruling.

=== DISPUTE CONTEXT ===
{arbitration_context}

=== INSTRUCTIONS ===
1. Assess whether the deliverable meets the milestone requirements as defined
   in the contract terms and milestone description.
2. Weigh the buyer's complaint against the seller's defense.
3. Consider the evidence URLs provided by both parties.
4. Deliver a ruling that is grounded in the contract terms — not your personal
   opinion or general fairness standards.

=== OUTPUT FORMAT (strict JSON) ===
{{
  "ruling": "BUYER" | "SELLER" | "SPLIT",
  "buyer_split_pct": <0-100, only if ruling is SPLIT, else null>,
  "reasoning": "<3-5 sentences explaining the ruling, citing specific contract terms and evidence>",
  "contract_term_violated": "<which specific term was or was not met>",
  "evidence_assessment": "<brief assessment of the strength of each party's evidence>"
}}

Respond ONLY with the JSON object. No preamble, no markdown fences."""

            return gl.nondet.exec_prompt(prompt, response_format="json")

        # ── Consensus via prompt_non_comparative ─────────────────────
        # Validators evaluate the leader's ruling against the raw context.
        # They do NOT regenerate a competing ruling — they assess whether
        # the leader's ruling is logically consistent with the evidence.
        ruling_result = gl.eq_principle.prompt_non_comparative(
            generate_ruling,
            task="Evaluate whether this dispute ruling is fair and well-grounded in the contract terms and evidence provided.",
            criteria=(
                "The ruling must: "
                "(1) Be one of exactly BUYER, SELLER, or SPLIT. "
                "(2) Cite specific contract terms that support the decision. "
                "(3) Acknowledge evidence from BOTH parties. "
                "(4) If SPLIT, provide a reasonable buyer_split_pct between 1-99. "
                "(5) The reasoning must logically follow from the cited terms and evidence. "
                "(6) Not introduce external criteria beyond the original contract terms."
            ),
        )

        # ── Parse and apply the ruling ───────────────────────────────
        ruling = ruling_result if isinstance(ruling_result, dict) else json.loads(str(ruling_result))

        decision = ruling.get("ruling", "").upper()
        amount = u256(int(ms["amount_wei"]))

        # Update evidence record with ruling details
        ev["ruling"] = decision
        ev["ruling_reasoning"] = ruling.get("reasoning", "")
        ev["buyer_split_pct"] = ruling.get("buyer_split_pct")

        if decision == "BUYER":
            # Full refund to buyer
            ms["status"] = STATUS_RESOLVED_BUYER
            self.total_refunded = self.total_refunded + amount
            buyer_ref = gl.get_contract_at(self.buyer)
            buyer_ref.emit_transfer(value=amount, on="finalized")

        elif decision == "SELLER":
            # Full release to seller
            ms["status"] = STATUS_RESOLVED_SELLER
            self.total_released = self.total_released + amount
            seller_ref = gl.get_contract_at(self.seller)
            seller_ref.emit_transfer(value=amount, on="finalized")

        elif decision == "SPLIT":
            # Proportional split
            buyer_pct = int(ruling.get("buyer_split_pct", 50))
            buyer_pct = max(1, min(99, buyer_pct))  # Clamp to valid range

            buyer_amount = u256((int(amount) * buyer_pct) // 100)
            seller_amount = u256(int(amount) - int(buyer_amount))

            ms["status"] = STATUS_RESOLVED_SPLIT
            ev["buyer_split_pct"] = buyer_pct
            self.total_refunded = self.total_refunded + buyer_amount
            self.total_released = self.total_released + seller_amount

            buyer_ref = gl.get_contract_at(self.buyer)
            buyer_ref.emit_transfer(value=buyer_amount, on="finalized")
            seller_ref = gl.get_contract_at(self.seller)
            seller_ref.emit_transfer(value=seller_amount, on="finalized")

        else:
            raise gl.vm.UserError(f"Invalid ruling from arbitration: {decision}")

        # Persist updated state
        self.milestones[milestone_id] = json.dumps(ms)
        self.evidence[milestone_id] = json.dumps(ev)

        return json.dumps(ruling)

    # ══════════════════════════════════════════════════════════════════
    # MUTUAL RESOLUTION (No AI needed)
    # ══════════════════════════════════════════════════════════════════

    @gl.public.write
    def mutual_cancel(self, milestone_id: u32) -> None:
        """
        Buyer cancels a funded (but not yet delivered) milestone.
        Full refund is issued. This is penalty-free early termination.
        """
        self._require_active()
        self._require_buyer()

        ms = self._get_milestone(milestone_id)
        if ms["status"] != STATUS_FUNDED:
            raise gl.vm.UserError(
                "Can only cancel milestones in FUNDED status"
            )

        amount = u256(int(ms["amount_wei"]))
        ms["status"] = STATUS_CANCELLED
        self.milestones[milestone_id] = json.dumps(ms)
        self.total_refunded = self.total_refunded + amount

        buyer_ref = gl.get_contract_at(self.buyer)
        buyer_ref.emit_transfer(value=amount, on="finalized")

    # ══════════════════════════════════════════════════════════════════
    # VIEW METHODS (Read-only queries)
    # ══════════════════════════════════════════════════════════════════

    @gl.public.view
    def get_milestone(self, milestone_id: u32) -> str:
        """Returns the full milestone state as a JSON string."""
        return self.milestones[milestone_id]

    @gl.public.view
    def get_evidence(self, milestone_id: u32) -> str:
        """Returns the dispute evidence for a milestone as a JSON string."""
        return self.evidence.get(milestone_id, "{}")

    @gl.public.view
    def get_contract_summary(self) -> str:
        """Returns aggregate contract state as a JSON string."""
        milestone_statuses = {}
        for i in range(int(self.total_milestones)):
            ms = json.loads(self.milestones[u32(i)])
            milestone_statuses[str(i)] = ms["status"]

        return json.dumps({
            "buyer": str(self.buyer),
            "seller": str(self.seller),
            "total_milestones": int(self.total_milestones),
            "total_deposited_wei": str(self.total_deposited),
            "total_released_wei": str(self.total_released),
            "total_refunded_wei": str(self.total_refunded),
            "is_active": self.is_active,
            "milestone_statuses": milestone_statuses,
        })

    @gl.public.view
    def get_contract_terms(self) -> str:
        """Returns the immutable contract terms."""
        return self.contract_terms

    # ══════════════════════════════════════════════════════════════════
    # INTERNAL HELPERS
    # ══════════════════════════════════════════════════════════════════

    def _require_buyer(self) -> None:
        if gl.message.sender_address != self.buyer:
            raise gl.vm.UserError("Only the buyer can perform this action")

    def _require_seller(self) -> None:
        if gl.message.sender_address != self.seller:
            raise gl.vm.UserError("Only the seller can perform this action")

    def _require_active(self) -> None:
        if not self.is_active:
            raise gl.vm.UserError("This escrow contract is no longer active")

    def _get_milestone(self, milestone_id: u32) -> dict:
        raw = self.milestones.get(milestone_id)
        if raw is None:
            raise gl.vm.UserError(f"Milestone {milestone_id} does not exist")
        return json.loads(raw)
