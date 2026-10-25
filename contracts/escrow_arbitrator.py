# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
Decentralized Escrow Arbitrator — GenLayer Intelligent Contract
===============================================================
A production-grade, milestone-based escrow primitive with AI-powered dispute
resolution via GenLayer's Optimistic Democracy consensus.

Genuinely Evidence-Based Arbitration:
The settlement path actively fetches and acquires the material evidence on-chain
(deliverable URL, buyer's dispute evidence URL, and seller's counter-evidence URL)
via gl.nondet.web, providing the full acquired evidence payload to the leader and
validators to assess directly against the agreed contract terms.
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
    Milestone-based escrow primitive with AI consensus arbitration
    grounded in on-chain acquired material evidence.
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

    @gl.public.write
    def add_milestone(self, milestone_id: str, title: str, description: str, amount_wei: str) -> None:
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
        self._require_active()
        self._require_buyer()

        milestones = json.loads(self.milestones_json)
        if milestone_id not in milestones:
            raise gl.vm.UserError("Milestone does not exist")

        ms = milestones[milestone_id]
        if ms["status"] != STATUS_CREATED:
            raise gl.vm.UserError("Milestone already funded or completed")

        ms["status"] = STATUS_FUNDED
        milestones[milestone_id] = ms
        self.milestones_json = json.dumps(milestones)

        new_dep = int(self.total_deposited_wei) + int(str(gl.message.value))
        self.total_deposited_wei = str(new_dep)

    @gl.public.write
    def submit_deliverable(self, milestone_id: str, deliverable_url: str, delivery_notes: str) -> None:
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

    @gl.public.write
    def raise_dispute(self, milestone_id: str, claim: str, evidence_url: str) -> None:
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
            "reasoning": "",
            "evidence_validation_summary": ""
        }
        self.evidence_json = json.dumps(ev_all)

    @gl.public.write
    def submit_defense(self, milestone_id: str, defense: str, defense_url: str) -> None:
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
        Genuinely Evidence-Based AI Dispute Arbitration via GenLayer Consensus.

        Instead of resolving disputes solely based on text claims, this settlement
        path acquires the material evidence on-chain by fetching:
          1. The deliverable work from `deliverable_url`
          2. The buyer's submitted evidence from `buyer_url`
          3. The seller's counter-defense evidence from `seller_url`

        The leader and validators independently assess this acquired material evidence
        against the agreed contract terms using `prompt_non_comparative`.
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

        deliverable_url = ms.get("deliverable_url", "")
        buyer_url = ev.get("buyer_url", "")
        seller_url = ev.get("seller_url", "")

        def generate_ruling():
            # 1. On-chain Material Evidence Acquisition
            def safe_fetch(url: str, max_chars: int = 3500) -> str:
                if not url or not (url.startswith("http://") or url.startswith("https://")):
                    return "[No valid URL provided]"
                try:
                    data = gl.nondet.web.render(url, mode="html")
                    if not data:
                        return "[Empty response from URL]"
                    return data[:max_chars]
                except Exception as e:
                    return f"[Failed to acquire evidence from URL: {str(e)}]"

            # Fetch the actual contents of the evidence and deliverable URLs
            deliverable_content = safe_fetch(deliverable_url)
            buyer_evidence_content = safe_fetch(buyer_url)
            seller_evidence_content = safe_fetch(seller_url)

            dispute_payload = {
                "contract_terms": self.contract_terms,
                "milestone_title": ms["title"],
                "milestone_amount_wei": ms["amount_wei"],
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
1. Examine the acquired deliverable content to see if the work actually satisfies the agreed contract terms.
2. Examine the acquired buyer evidence content to see if their defect claims are substantiated by the fetched material.
3. Examine the acquired seller evidence content to see if their defense is substantiated by the fetched material.
4. Base your ruling on the real acquired evidence content, NOT merely on what either party asserts.
5. Provide clear reasoning explaining how the fetched evidence relates to the contract terms.

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
                "(3) Verify whether the deliverable content satisfies the contract terms based on the fetched evidence rather than unverified claims. "
                "(4) Provide a coherent explanation linking the acquired evidence to the decision."
            )
        )

        ruling = ruling_raw if isinstance(ruling_raw, dict) else json.loads(str(ruling_raw))
        decision = ruling.get("ruling", "SELLER").upper()
        amount_val = int(ms["amount_wei"])

        ev["ruling"] = decision
        ev["reasoning"] = ruling.get("reasoning", "")
        ev["evidence_validation_summary"] = ruling.get("evidence_validation_summary", "")
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

    def _require_buyer(self) -> None:
        if gl.message.sender_address != self.buyer:
            raise gl.vm.UserError("Only buyer can perform this action")

    def _require_seller(self) -> None:
        if gl.message.sender_address != self.seller:
            raise gl.vm.UserError("Only seller can perform this action")

    def _require_active(self) -> None:
        if not self.is_active:
            raise gl.vm.UserError("Contract is inactive")
