# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
Decentralized Escrow Arbitrator — GenLayer Intelligent Contract
===============================================================
A production-grade, milestone-based escrow primitive with AI-powered dispute
resolution via GenLayer's Optimistic Democracy consensus.
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


class EscrowArbitrator(gl.Contract):
    """
    Milestone-based escrow primitive with AI consensus arbitration.
    """

    buyer: Address
    seller: Address
    contract_terms: str
    milestones_json: str
    evidence_json: str
    total_deposited_wei: str
    total_released_wei: str
    total_refunded_wei: str
    is_active: bool

    def __init__(self, seller: Address, contract_terms: str):
        """
        Deploy the escrow contract.
        Deployer is the buyer. Terms are permanently locked.
        """
        self.buyer = gl.message.sender_address
        self.seller = seller
        self.contract_terms = contract_terms

        # Initialize default milestones schema
        default_milestones = {
            "0": {
                "title": "Initial Deliverable",
                "description": contract_terms,
                "amount_wei": "1000000000000000000",
                "status": STATUS_CREATED,
                "deliverable_url": "",
                "delivery_notes": ""
            }
        }
        self.milestones_json = json.dumps(default_milestones)
        self.evidence_json = json.dumps({})
        self.total_deposited_wei = "0"
        self.total_released_wei = "0"
        self.total_refunded_wei = "0"
        self.is_active = True

    # ══════════════════════════════════════════════════════════════════
    # FUNDING & MILESTONE SETUP
    # ══════════════════════════════════════════════════════════════════

    @gl.public.write
    def add_milestone(self, milestone_id: str, title: str, description: str, amount_wei: str) -> None:
        """Buyer adds a new milestone specification."""
        self._require_active()
        self._require_buyer()

        milestones = json.loads(self.milestones_json)
        milestones[milestone_id] = {
            "title": title,
            "description": description,
            "amount_wei": amount_wei,
            "status": STATUS_CREATED,
            "deliverable_url": "",
            "delivery_notes": ""
        }
        self.milestones_json = json.dumps(milestones)

    @gl.public.write.payable
    def fund_milestone(self, milestone_id: str) -> None:
        """Buyer deposits the required funds for a milestone."""
        self._require_active()
        self._require_buyer()

        milestones = json.loads(self.milestones_json)
        if milestone_id not in milestones:
            raise gl.vm.UserError(f"Milestone {milestone_id} does not exist")

        ms = milestones[milestone_id]
        if ms["status"] != STATUS_CREATED:
            raise gl.vm.UserError("Milestone already funded or completed")

        ms["status"] = STATUS_FUNDED
        milestones[milestone_id] = ms
        self.milestones_json = json.dumps(milestones)

        new_dep = int(self.total_deposited_wei) + int(str(gl.message.value))
        self.total_deposited_wei = str(new_dep)

    # ══════════════════════════════════════════════════════════════════
    # DELIVERY & STRICT CONSENSUS URL VERIFICATION
    # ══════════════════════════════════════════════════════════════════

    @gl.public.write
    def submit_deliverable(self, milestone_id: str, deliverable_url: str, delivery_notes: str) -> None:
        """Seller submits work for a funded milestone."""
        self._require_active()
        self._require_seller()

        milestones = json.loads(self.milestones_json)
        if milestone_id not in milestones:
            raise gl.vm.UserError("Milestone does not exist")

        ms = milestones[milestone_id]
        if ms["status"] != STATUS_FUNDED:
            raise gl.vm.UserError("Milestone is not in FUNDED status")

        ms["status"] = STATUS_DELIVERED
        ms["deliverable_url"] = deliverable_url
        ms["delivery_notes"] = delivery_notes
        milestones[milestone_id] = ms
        self.milestones_json = json.dumps(milestones)

    @gl.public.write
    def verify_deliverable_url(self, milestone_id: str, expected_keyword: str) -> bool:
        """
        Consensus verification using strict_eq.
        All validators fetch the deliverable URL and confirm the keyword matches identically.
        """
        self._require_active()
        milestones = json.loads(self.milestones_json)
        if milestone_id not in milestones:
            raise gl.vm.UserError("Milestone does not exist")

        url = milestones[milestone_id]["deliverable_url"]
        if not url:
            raise gl.vm.UserError("No deliverable URL submitted")

        def check_url_live():
            page = gl.nondet.web.render(url, mode="html")
            return expected_keyword.lower() in page.lower()

        return gl.eq_principle.strict_eq(check_url_live)

    @gl.public.write
    def approve_milestone(self, milestone_id: str) -> None:
        """Buyer approves deliverable and releases funds to seller."""
        self._require_active()
        self._require_buyer()

        milestones = json.loads(self.milestones_json)
        if milestone_id not in milestones:
            raise gl.vm.UserError("Milestone does not exist")

        ms = milestones[milestone_id]
        if ms["status"] != STATUS_DELIVERED:
            raise gl.vm.UserError("Milestone is not in DELIVERED status")

        amount_val = int(ms["amount_wei"])
        ms["status"] = STATUS_APPROVED
        milestones[milestone_id] = ms
        self.milestones_json = json.dumps(milestones)

        new_rel = int(self.total_released_wei) + amount_val
        self.total_released_wei = str(new_rel)

        seller_ref = gl.get_contract_at(self.seller)
        seller_ref.emit_transfer(value=u256(amount_val), on="finalized")

    # ══════════════════════════════════════════════════════════════════
    # AI DISPUTE ARBITRATION (prompt_non_comparative)
    # ══════════════════════════════════════════════════════════════════

    @gl.public.write
    def raise_dispute(self, milestone_id: str, claim: str, evidence_url: str) -> None:
        """Buyer disputes the deliverable, providing evidence."""
        self._require_active()
        self._require_buyer()

        milestones = json.loads(self.milestones_json)
        if milestone_id not in milestones:
            raise gl.vm.UserError("Milestone not found")

        ms = milestones[milestone_id]
        if ms["status"] != STATUS_DELIVERED:
            raise gl.vm.UserError("Can only dispute DELIVERED milestones")

        ms["status"] = STATUS_DISPUTED
        milestones[milestone_id] = ms
        self.milestones_json = json.dumps(milestones)

        ev_all = json.loads(self.evidence_json)
        ev_all[milestone_id] = {
            "buyer_claim": claim,
            "buyer_url": evidence_url,
            "seller_defense": "",
            "seller_url": "",
            "ruling": "",
            "reasoning": ""
        }
        self.evidence_json = json.dumps(ev_all)

    @gl.public.write
    def submit_defense(self, milestone_id: str, defense: str, defense_url: str) -> None:
        """Seller submits counter-evidence before arbitration can proceed."""
        self._require_active()
        self._require_seller()

        ev_all = json.loads(self.evidence_json)
        if milestone_id not in ev_all:
            raise gl.vm.UserError("Dispute record not found")

        ev = ev_all[milestone_id]
        ev["seller_defense"] = defense
        ev["seller_url"] = defense_url
        ev_all[milestone_id] = ev
        self.evidence_json = json.dumps(ev_all)

    @gl.public.write
    def arbitrate_dispute(self, milestone_id: str) -> str:
        """
        AI Arbitration Consensus primitive using prompt_non_comparative.
        Validators evaluate the leader's ruling against the raw evidence
        and original contract terms without wasteful duplicate generation.
        """
        self._require_active()

        milestones = json.loads(self.milestones_json)
        if milestone_id not in milestones:
            raise gl.vm.UserError("Milestone not found")

        ms = milestones[milestone_id]
        if ms["status"] != STATUS_DISPUTED:
            raise gl.vm.UserError("Milestone is not in DISPUTED status")

        ev_all = json.loads(self.evidence_json)
        if milestone_id not in ev_all:
            raise gl.vm.UserError("No dispute recorded")

        ev = ev_all[milestone_id]
        if not ev["seller_defense"]:
            raise gl.vm.UserError("Seller must submit defense before arbitration")

        context = json.dumps({
            "contract_terms": self.contract_terms,
            "milestone_title": ms["title"],
            "deliverable_url": ms["deliverable_url"],
            "buyer_claim": ev["buyer_claim"],
            "seller_defense": ev["seller_defense"]
        })

        def generate_ruling():
            prompt = f"""You are an impartial arbitrator evaluating a contract dispute.
Analyze all evidence against the contract terms and deliver a fair ruling.

Context:
{context}

Respond strictly in JSON format:
{{
  "ruling": "BUYER" | "SELLER" | "SPLIT",
  "reasoning": "Explanation citing contract terms and evidence"
}}"""
            return gl.nondet.exec_prompt(prompt, response_format="json")

        ruling_raw = gl.eq_principle.prompt_non_comparative(
            generate_ruling,
            task="Evaluate whether this dispute ruling is fair and grounded in contract terms.",
            criteria="The ruling must be BUYER, SELLER, or SPLIT, and cite specific terms."
        )

        ruling = ruling_raw if isinstance(ruling_raw, dict) else json.loads(str(ruling_raw))
        decision = ruling.get("ruling", "SELLER").upper()
        amount_val = int(ms["amount_wei"])

        ev["ruling"] = decision
        ev["reasoning"] = ruling.get("reasoning", "")
        ev_all[milestone_id] = ev
        self.evidence_json = json.dumps(ev_all)

        if decision == "BUYER":
            ms["status"] = STATUS_RESOLVED_BUYER
            new_ref = int(self.total_refunded_wei) + amount_val
            self.total_refunded_wei = str(new_ref)
            gl.get_contract_at(self.buyer).emit_transfer(value=u256(amount_val), on="finalized")

        elif decision == "SELLER":
            ms["status"] = STATUS_RESOLVED_SELLER
            new_rel = int(self.total_released_wei) + amount_val
            self.total_released_wei = str(new_rel)
            gl.get_contract_at(self.seller).emit_transfer(value=u256(amount_val), on="finalized")

        elif decision == "SPLIT":
            ms["status"] = STATUS_RESOLVED_SPLIT
            half = amount_val // 2
            other_half = amount_val - half
            new_ref = int(self.total_refunded_wei) + half
            new_rel = int(self.total_released_wei) + other_half
            self.total_refunded_wei = str(new_ref)
            self.total_released_wei = str(new_rel)
            gl.get_contract_at(self.buyer).emit_transfer(value=u256(half), on="finalized")
            gl.get_contract_at(self.seller).emit_transfer(value=u256(other_half), on="finalized")

        milestones[milestone_id] = ms
        self.milestones_json = json.dumps(milestones)
        return json.dumps(ruling)

    # ══════════════════════════════════════════════════════════════════
    # VIEWS
    # ══════════════════════════════════════════════════════════════════

    @gl.public.view
    def get_milestone(self, milestone_id: str) -> str:
        milestones = json.loads(self.milestones_json)
        return json.dumps(milestones.get(milestone_id, {}))

    @gl.public.view
    def get_contract_summary(self) -> str:
        return json.dumps({
            "buyer": str(self.buyer),
            "seller": str(self.seller),
            "terms": self.contract_terms,
            "deposited_wei": self.total_deposited_wei,
            "released_wei": self.total_released_wei,
            "refunded_wei": self.total_refunded_wei,
            "is_active": self.is_active
        })

    # ══════════════════════════════════════════════════════════════════
    # INTERNAL HELPERS
    # ══════════════════════════════════════════════════════════════════

    def _require_buyer(self) -> None:
        if gl.message.sender_address != self.buyer:
            raise gl.vm.UserError("Only buyer can perform this action")

    def _require_seller(self) -> None:
        if gl.message.sender_address != self.seller:
            raise gl.vm.UserError("Only seller can perform this action")

    def _require_active(self) -> None:
        if not self.is_active:
            raise gl.vm.UserError("Contract is inactive")
