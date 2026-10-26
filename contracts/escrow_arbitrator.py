# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
Decentralized Escrow Arbitrator — GenLayer Intelligent Contract
===============================================================
A production-grade, milestone-based escrow primitive with AI-powered dispute
resolution via GenLayer's Optimistic Democracy consensus.

Enforced Escrow Invariants:
1. Strict Deposit Equality: A milestone's actual deposit (gl.message.value) must
   exactly equal its validated positive amount (amount_wei > 0) before being marked FUNDED.
2. Immutability of Lifecycle Records: add_milestone cannot overwrite any existing record.
3. Fail-Closed Evidence Acquisition: If any required deliverable, buyer, or seller
   evidence URL is missing or fails to be acquired on-chain via gl.nondet.web, arbitration
   fails closed immediately with an error, preventing any fund transfer.
4. Fund Conservation: Approval and dispute settlement payouts are strictly bounded by
   the milestone's recorded escrowed balance (escrowed_wei) and clear that balance upon payout.
"""

from genlayer import *
import json

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
    Milestone-based escrow primitive with invariant-enforced accounting
    and fail-closed evidence-based AI dispute arbitration.
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
        self.buyer = gl.message.sender_address

        # Robust Address parsing: handles raw int passed by Studio RPC, hex string, or Address object
        if isinstance(seller, int):
            hex_str = hex(seller)[2:]
            self.seller = Address("0x" + hex_str.zfill(40))
        elif isinstance(seller, str):
            self.seller = Address(seller)
        elif hasattr(seller, "as_bytes"):
            self.seller = seller
        else:
            self.seller = Address(str(seller))

        self.contract_terms = str(contract_terms)

        default_milestones = {
            "0": {
                "title": "Initial Deliverable",
                "description": contract_terms,
                "amount_wei": "1000000000000000000",
                "escrowed_wei": "0",
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
    # FUNDING & MILESTONE SETUP (INVARIANTS 1 & 2)
    # ══════════════════════════════════════════════════════════════════

    @gl.public.write
    def add_milestone(self, milestone_id: str, title: str, description: str, amount_wei: str) -> None:
        """
        Buyer adds a new milestone specification.
        Invariant: Cannot overwrite an existing milestone lifecycle record.
        Invariant: Requires validated positive amount_wei > 0.
        """
        self._require_active()
        self._require_buyer()

        milestones = json.loads(self.milestones_json)

        # Invariant 2: Prevent overwriting any existing lifecycle record
        if milestone_id in milestones:
            raise gl.vm.UserError(f"Milestone {milestone_id} already exists and cannot be overwritten")

        # Invariant 1: Validate positive integer amount
        try:
            amt = int(amount_wei)
        except Exception:
            raise gl.vm.UserError("Milestone amount must be a valid integer in wei")

        if amt <= 0:
            raise gl.vm.UserError("Milestone amount must be strictly positive")

        milestones[milestone_id] = {
            "title": title,
            "description": description,
            "amount_wei": str(amt),
            "escrowed_wei": "0",
            "status": STATUS_CREATED,
            "deliverable_url": "",
            "delivery_notes": ""
        }
        self.milestones_json = json.dumps(milestones)

    @gl.public.write.payable
    def fund_milestone(self, milestone_id: str) -> None:
        """
        Buyer deposits funds for a milestone.
        Invariant 1: Requires actual deposit (gl.message.value) to exactly equal
        the validated positive amount before marking it funded.
        """
        self._require_active()
        self._require_buyer()

        milestones = json.loads(self.milestones_json)
        if milestone_id not in milestones:
            raise gl.vm.UserError(f"Milestone {milestone_id} does not exist")

        ms = milestones[milestone_id]
        if ms["status"] != STATUS_CREATED:
            raise gl.vm.UserError(f"Milestone {milestone_id} is not in CREATED status")

        expected_amount = int(ms.get("amount_wei", "0"))
        if expected_amount <= 0:
            raise gl.vm.UserError("Milestone amount must be strictly positive")

        actual_deposit = int(str(gl.message.value))
        if actual_deposit != expected_amount:
            raise gl.vm.UserError(
                f"Deposit value ({actual_deposit} wei) does not equal required milestone amount ({expected_amount} wei)"
            )

        # Record exact escrowed balance to enforce fund conservation invariant
        ms["escrowed_wei"] = str(actual_deposit)
        ms["status"] = STATUS_FUNDED
        milestones[milestone_id] = ms
        self.milestones_json = json.dumps(milestones)

        new_dep = int(self.total_deposited_wei) + actual_deposit
        self.total_deposited_wei = str(new_dep)

    # ══════════════════════════════════════════════════════════════════
    # DELIVERY & APPROVAL (INVARIANT 4)
    # ══════════════════════════════════════════════════════════════════

    @gl.public.write
    def submit_deliverable(self, milestone_id: str, deliverable_url: str, delivery_notes: str) -> None:
        """Seller submits work for a funded milestone."""
        self._require_active()
        self._require_seller()

        milestones = json.loads(self.milestones_json)
        if milestone_id not in milestones:
            raise gl.vm.UserError(f"Milestone {milestone_id} does not exist")

        ms = milestones[milestone_id]
        if ms["status"] != STATUS_FUNDED:
            raise gl.vm.UserError(f"Milestone {milestone_id} is not in FUNDED status")

        clean_url = deliverable_url.strip()
        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            raise gl.vm.UserError("Deliverable URL must be a valid HTTP or HTTPS address")

        ms["status"] = STATUS_DELIVERED
        ms["deliverable_url"] = clean_url
        ms["delivery_notes"] = delivery_notes
        milestones[milestone_id] = ms
        self.milestones_json = json.dumps(milestones)

    @gl.public.write
    def verify_deliverable_url(self, milestone_id: str, expected_keyword: str) -> bool:
        """
        Consensus verification using strict_eq.
        Confirms the deliverable URL is live and contains the expected keyword.
        """
        self._require_active()
        milestones = json.loads(self.milestones_json)
        if milestone_id not in milestones:
            raise gl.vm.UserError(f"Milestone {milestone_id} does not exist")

        url = milestones[milestone_id].get("deliverable_url", "")
        if not url:
            raise gl.vm.UserError("No deliverable URL submitted")

        def check_url_live():
            page = gl.nondet.web.render(url, mode="html")
            return expected_keyword.lower() in page.lower()

        return gl.eq_principle.strict_eq(check_url_live)

    @gl.public.write
    def approve_milestone(self, milestone_id: str) -> None:
        """
        Buyer approves deliverable and releases escrowed funds to seller.
        Invariant 4: Can never pay more than the amount escrowed for that milestone.
        """
        self._require_active()
        self._require_buyer()

        milestones = json.loads(self.milestones_json)
        if milestone_id not in milestones:
            raise gl.vm.UserError(f"Milestone {milestone_id} does not exist")

        ms = milestones[milestone_id]
        if ms["status"] != STATUS_DELIVERED:
            raise gl.vm.UserError(f"Milestone {milestone_id} is not in DELIVERED status")

        # Invariant 4: payout strictly bounded by escrowed balance
        escrowed_amount = int(ms.get("escrowed_wei", "0"))
        if escrowed_amount <= 0:
            raise gl.vm.UserError(f"No escrowed funds available for milestone {milestone_id}")

        # Clear milestone escrow balance to guarantee single payout
        ms["escrowed_wei"] = "0"
        ms["status"] = STATUS_APPROVED
        milestones[milestone_id] = ms
        self.milestones_json = json.dumps(milestones)

        new_rel = int(self.total_released_wei) + escrowed_amount
        self.total_released_wei = str(new_rel)

        seller_ref = gl.get_contract_at(self.seller)
        seller_ref.emit_transfer(value=u256(escrowed_amount), on="finalized")

    # ══════════════════════════════════════════════════════════════════
    # DISPUTE RECORDING & FAIL-CLOSED ARBITRATION (INVARIANTS 3 & 4)
    # ══════════════════════════════════════════════════════════════════

    @gl.public.write
    def raise_dispute(self, milestone_id: str, claim: str, evidence_url: str) -> None:
        """
        Buyer disputes the deliverable, providing claim and evidence URL.
        """
        self._require_active()
        self._require_buyer()

        milestones = json.loads(self.milestones_json)
        if milestone_id not in milestones:
            raise gl.vm.UserError(f"Milestone {milestone_id} not found")

        ms = milestones[milestone_id]
        if ms["status"] != STATUS_DELIVERED:
            raise gl.vm.UserError("Can only dispute DELIVERED milestones")

        clean_url = evidence_url.strip()
        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            raise gl.vm.UserError("Buyer evidence URL must be a valid HTTP or HTTPS address")

        ms["status"] = STATUS_DISPUTED
        milestones[milestone_id] = ms
        self.milestones_json = json.dumps(milestones)

        ev_all = json.loads(self.evidence_json)
        ev_all[milestone_id] = {
            "buyer_claim": claim,
            "buyer_url": clean_url,
            "seller_defense": "",
            "seller_url": "",
            "ruling": "",
            "reasoning": "",
            "evidence_validation_summary": ""
        }
        self.evidence_json = json.dumps(ev_all)

    @gl.public.write
    def submit_defense(self, milestone_id: str, defense: str, defense_url: str) -> None:
        """
        Seller submits counter-defense and evidence URL before arbitration.
        """
        self._require_active()
        self._require_seller()

        ev_all = json.loads(self.evidence_json)
        if milestone_id not in ev_all:
            raise gl.vm.UserError(f"Dispute record for milestone {milestone_id} not found")

        clean_url = defense_url.strip()
        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            raise gl.vm.UserError("Seller defense URL must be a valid HTTP or HTTPS address")

        ev = ev_all[milestone_id]
        ev["seller_defense"] = defense
        ev["seller_url"] = clean_url
        ev_all[milestone_id] = ev
        self.evidence_json = json.dumps(ev_all)

    @gl.public.write
    def arbitrate_dispute(self, milestone_id: str) -> str:
        """
        AI Dispute Arbitration via GenLayer Consensus.

        Invariant 3 (Fail-Closed Evidence Acquisition):
        If any required deliverable, buyer, or seller evidence cannot be acquired
        on-chain via gl.nondet.web, arbitration fails closed with a UserError without
        transferring any funds.

        Invariant 4 (Fund Conservation):
        Settlement payouts are strictly bounded by the milestone's recorded escrowed
        balance (escrowed_wei) and clear that balance upon execution.
        """
        self._require_active()

        milestones = json.loads(self.milestones_json)
        if milestone_id not in milestones:
            raise gl.vm.UserError(f"Milestone {milestone_id} not found")

        ms = milestones[milestone_id]
        if ms["status"] != STATUS_DISPUTED:
            raise gl.vm.UserError(f"Milestone {milestone_id} is not in DISPUTED status")

        # Invariant 4: Verify positive escrowed balance exists
        escrowed_amount = int(ms.get("escrowed_wei", "0"))
        if escrowed_amount <= 0:
            raise gl.vm.UserError(f"Milestone {milestone_id} has no escrowed funds available for settlement")

        ev_all = json.loads(self.evidence_json)
        if milestone_id not in ev_all:
            raise gl.vm.UserError("No dispute recorded for milestone")

        ev = ev_all[milestone_id]
        if not ev.get("seller_defense", ""):
            raise gl.vm.UserError("Seller must submit defense before arbitration")

        deliverable_url = ms.get("deliverable_url", "").strip()
        buyer_url = ev.get("buyer_url", "").strip()
        seller_url = ev.get("seller_url", "").strip()

        # Invariant 3: Pre-check URL presence and formatting
        if not (deliverable_url.startswith("http://") or deliverable_url.startswith("https://")):
            raise gl.vm.UserError("Arbitration failed closed: Required deliverable URL is missing or invalid")
        if not (buyer_url.startswith("http://") or buyer_url.startswith("https://")):
            raise gl.vm.UserError("Arbitration failed closed: Required buyer evidence URL is missing or invalid")
        if not (seller_url.startswith("http://") or seller_url.startswith("https://")):
            raise gl.vm.UserError("Arbitration failed closed: Required seller defense URL is missing or invalid")

        def generate_ruling():
            # Invariant 3: Fail-Closed On-Chain Evidence Acquisition
            def acquire_evidence_strict(url: str, label: str, max_chars: int = 3500) -> str:
                try:
                    data = gl.nondet.web.render(url, mode="html")
                except Exception as e:
                    raise gl.vm.UserError(f"Arbitration failed closed: Could not acquire {label} from {url}: {str(e)}")

                if not data or len(data.strip()) == 0:
                    raise gl.vm.UserError(f"Arbitration failed closed: Acquired {label} content from {url} is empty")

                return data[:max_chars]

            deliverable_content = acquire_evidence_strict(deliverable_url, "deliverable evidence")
            buyer_evidence_content = acquire_evidence_strict(buyer_url, "buyer dispute evidence")
            seller_evidence_content = acquire_evidence_strict(seller_url, "seller defense evidence")

            dispute_payload = {
                "contract_terms": self.contract_terms,
                "milestone_title": ms["title"],
                "milestone_escrowed_wei": str(escrowed_amount),
                "claims": {
                    "buyer_claim": ev["buyer_claim"],
                    "buyer_evidence_url": buyer_url,
                    "seller_defense": ev["seller_defense"],
                    "seller_defense_url": seller_url
                },
                "acquired_material_evidence": {
                    "deliverable_url": deliverable_url,
                    "deliverable_content_excerpt": deliverable_content,
                    "buyer_evidence_content_excerpt": buyer_evidence_content,
                    "seller_evidence_content_excerpt": seller_evidence_content
                }
            }

            prompt = f"""You are an impartial decentralized arbitrator evaluating a contract dispute.
You must assess the ACQUIRED MATERIAL EVIDENCE fetched directly from the submitted URLs against the agreed contract terms.

Dispute File and Acquired Material Evidence:
{json.dumps(dispute_payload, indent=2)}

Instructions:
1. Examine the acquired deliverable content to verify whether the work actually conforms to the agreed contract terms.
2. Examine the acquired buyer evidence content to verify if defect claims are substantiated by the fetched material.
3. Examine the acquired seller evidence content to verify if the defense is substantiated by the fetched material.
4. Base your ruling on the real acquired evidence content, NOT merely on unverified text claims.
5. Provide detailed reasoning linking the acquired evidence to the decision.

Respond strictly in JSON format:
{{
  "ruling": "BUYER" | "SELLER" | "SPLIT",
  "reasoning": "Detailed reasoning explaining how the acquired evidence from the URLs confirms or refutes the claims against the contract terms",
  "evidence_validation_summary": "Summary of findings from deliverable, buyer evidence, and seller evidence contents"
}}"""

            return gl.nondet.exec_prompt(prompt, response_format="json")

        ruling_raw = gl.eq_principle.prompt_non_comparative(
            generate_ruling,
            task="Audit the dispute ruling to ensure it thoroughly evaluates the acquired evidence content against the contract terms.",
            criteria=(
                "The ruling must: "
                "(1) Be one of BUYER, SELLER, or SPLIT. "
                "(2) Explicitly analyze the acquired evidence fetched from the submitted URLs. "
                "(3) Verify whether the deliverable content satisfies the contract terms based on the fetched evidence. "
                "(4) Provide a coherent explanation linking the acquired evidence to the decision."
            )
        )

        ruling = ruling_raw if isinstance(ruling_raw, dict) else json.loads(str(ruling_raw))
        decision = ruling.get("ruling", "SELLER").upper()

        ev["ruling"] = decision
        ev["reasoning"] = ruling.get("reasoning", "")
        ev["evidence_validation_summary"] = ruling.get("evidence_validation_summary", "")
        ev_all[milestone_id] = ev
        self.evidence_json = json.dumps(ev_all)

        # Invariant 4: Settlement payouts are strictly bounded by escrowed balance and clear it
        ms["escrowed_wei"] = "0"

        if decision == "BUYER":
            ms["status"] = STATUS_RESOLVED_BUYER
            new_ref = int(self.total_refunded_wei) + escrowed_amount
            self.total_refunded_wei = str(new_ref)
            gl.get_contract_at(self.buyer).emit_transfer(value=u256(escrowed_amount), on="finalized")

        elif decision == "SELLER":
            ms["status"] = STATUS_RESOLVED_SELLER
            new_rel = int(self.total_released_wei) + escrowed_amount
            self.total_released_wei = str(new_rel)
            gl.get_contract_at(self.seller).emit_transfer(value=u256(escrowed_amount), on="finalized")

        elif decision == "SPLIT":
            ms["status"] = STATUS_RESOLVED_SPLIT
            half = escrowed_amount // 2
            other_half = escrowed_amount - half
            # Invariant: exact fund conservation (half + other_half == escrowed_amount)
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
