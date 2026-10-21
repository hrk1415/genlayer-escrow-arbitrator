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
