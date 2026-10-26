"""
Direct Execution Tests for EscrowArbitrator with Enforced Escrow Invariants
===========================================================================
Run with: pytest tests/test_escrow_arbitrator.py -v
"""

import json
import pytest

BUYER_ADDRESS = "0x" + "B" * 40
SELLER_ADDRESS = "0x" + "5" * 40
CONTRACT_TERMS = "Build a verified REST API with auth and tests"


def deploy_contract():
    """Helper to deploy a fresh EscrowArbitrator instance."""
    from contracts.escrow_arbitrator import EscrowArbitrator

    contract = EscrowArbitrator.__new__(EscrowArbitrator)
    contract.__init__(
        seller=SELLER_ADDRESS,
        contract_terms=CONTRACT_TERMS,
    )
    return contract


class TestEscrowInvariants:
    """Verifies all Steward-requested escrow accounting & arbitration invariants."""

    def test_initialization(self):
        contract = deploy_contract()
        assert contract.seller == SELLER_ADDRESS
        assert contract.contract_terms == CONTRACT_TERMS
        assert contract.is_active is True
        assert contract.total_deposited_wei == "0"
        assert contract.total_released_wei == "0"
        assert contract.total_refunded_wei == "0"

    def test_invariant_prevent_overwriting_milestone(self):
        """Invariant: add_milestone cannot overwrite an existing lifecycle record."""
        contract = deploy_contract()
        milestones = json.loads(contract.milestones_json)
        assert "0" in milestones

        # Attempting to re-add existing milestone "0" must fail
        with pytest.raises(Exception, match="already exists and cannot be overwritten"):
            contract.add_milestone("0", "New Title", "New Description", "500000000000000000")

    def test_invariant_add_milestone_validates_positive_amount(self):
        """Invariant: Milestone amounts must be strictly positive."""
        contract = deploy_contract()
        # Zero amount
        with pytest.raises(Exception, match="strictly positive"):
            contract.add_milestone("1", "M1", "Desc", "0")

        # Negative amount
        with pytest.raises(Exception, match="strictly positive"):
            contract.add_milestone("2", "M2", "Desc", "-100")

    def test_invariant_arbitration_fails_closed_on_missing_or_invalid_evidence(self):
        """
        Invariant: Arbitration fails closed without transferring funds when
        required deliverable, buyer, or seller evidence cannot be acquired.
        """
        contract = deploy_contract()
        milestones = json.loads(contract.milestones_json)
        milestones["0"]["status"] = "DISPUTED"
        milestones["0"]["escrowed_wei"] = "1000000000000000000"
        milestones["0"]["deliverable_url"] = "not-a-valid-http-url"
        contract.milestones_json = json.dumps(milestones)

        ev_all = {
            "0": {
                "buyer_claim": "API broken",
                "buyer_url": "https://example.com/buyer-error.html",
                "seller_defense": "API works",
                "seller_url": "https://example.com/seller-test.html",
                "ruling": "",
                "reasoning": "",
                "evidence_validation_summary": ""
            }
        }
        contract.evidence_json = json.dumps(ev_all)

        # Must fail closed before transferring any funds
        with pytest.raises(Exception, match="Arbitration failed closed"):
            contract.arbitrate_dispute("0")

        # Escrowed amount remains untouched in contract
        ms_after = json.loads(contract.milestones_json)["0"]
        assert ms_after["escrowed_wei"] == "1000000000000000000"
        assert contract.total_released_wei == "0"
        assert contract.total_refunded_wei == "0"

    def test_invariant_cannot_settle_unfunded_milestone(self):
        """Invariant: Approval and dispute settlement can never pay more than escrowed funds."""
        contract = deploy_contract()
        milestones = json.loads(contract.milestones_json)
        milestones["0"]["status"] = "DELIVERED"
        milestones["0"]["escrowed_wei"] = "0"  # Unfunded
        contract.milestones_json = json.dumps(milestones)

        with pytest.raises(Exception, match="No escrowed funds available"):
            contract.approve_milestone("0")
