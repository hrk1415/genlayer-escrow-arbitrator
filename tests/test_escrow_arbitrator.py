"""
Direct Execution Tests for EscrowArbitrator
============================================
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


class TestDeployment:
    def test_initialization(self):
        contract = deploy_contract()
        assert contract.seller == SELLER_ADDRESS
        assert contract.contract_terms == CONTRACT_TERMS
        assert contract.is_active is True
        assert contract.total_deposited_wei == "0"
        assert contract.total_released_wei == "0"
        assert contract.total_refunded_wei == "0"

    def test_default_milestone(self):
        contract = deploy_contract()
        milestones = json.loads(contract.milestones_json)
        assert "0" in milestones
        assert milestones["0"]["status"] == "CREATED"

    def test_get_contract_summary(self):
        contract = deploy_contract()
        summary = json.loads(contract.get_contract_summary())
        assert summary["terms"] == CONTRACT_TERMS
        assert summary["is_active"] is True


class TestDisputeEvidenceAcquisitionFlow:
    """Verify dispute evidence recording and arbitration guards."""

    def test_dispute_and_defense_submission(self):
        contract = deploy_contract()
        milestones = json.loads(contract.milestones_json)
        # Transition to DELIVERED
        milestones["0"]["status"] = "DELIVERED"
        milestones["0"]["deliverable_url"] = "https://example.com/api"
        contract.milestones_json = json.dumps(milestones)

        # Buyer raises dispute with evidence URL
        buyer_claim = "API returns 500 on /auth/login"
        buyer_evidence_url = "https://example.com/evidence/buyer-error-logs.html"
        contract.raise_dispute("0", buyer_claim, buyer_evidence_url)

        ms_after = json.loads(contract.milestones_json)
        assert ms_after["0"]["status"] == "DISPUTED"

        ev_all = json.loads(contract.evidence_json)
        assert "0" in ev_all
        assert ev_all["0"]["buyer_claim"] == buyer_claim
        assert ev_all["0"]["buyer_url"] == buyer_evidence_url
        assert ev_all["0"]["seller_defense"] == ""

        # Seller submits counter-defense with evidence URL
        seller_defense = "500 was caused by misconfigured environment variables. Test report shows 100% pass."
        seller_evidence_url = "https://example.com/evidence/seller-ci-test-report.html"
        contract.submit_defense("0", seller_defense, seller_evidence_url)

        ev_after = json.loads(contract.evidence_json)["0"]
        assert ev_after["seller_defense"] == seller_defense
        assert ev_after["seller_url"] == seller_evidence_url
        assert "evidence_validation_summary" in ev_after

    def test_arbitration_requires_defense(self):
        contract = deploy_contract()
        milestones = json.loads(contract.milestones_json)
        milestones["0"]["status"] = "DELIVERED"
        contract.milestones_json = json.dumps(milestones)

        contract.raise_dispute("0", "Defect found", "https://example.com/proof")
        # Attempting arbitration before defense must fail
        with pytest.raises(Exception, match="Seller must submit defense"):
            contract.arbitrate_dispute("0")
