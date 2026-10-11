"""With a perfect extraction, do the rules reach the labelled decision on the whole dataset?

This isolates the business rules from the LLM: if this test fails, the problem
is in the reconciliation/policy (or the labels), not in the extraction.
"""

import json
import uuid
from datetime import date
from pathlib import Path

from opsagent.datagen.records import Catalog, GroundTruth
from opsagent.domain.policy import decide
from opsagent.domain.quality import assess_extraction
from opsagent.domain.reconciliation import PolicyConfig, reconcile
from opsagent.infra.memory_ledger import InMemoryLedger

DATA = Path(__file__).resolve().parents[4] / "data" / "synthetic"


def test_rules_reproduce_every_label_with_oracle_extraction() -> None:
    catalog = Catalog.model_validate_json((DATA / "catalog.json").read_text(encoding="utf-8"))
    truths = [
        GroundTruth.model_validate(t)
        for t in json.loads((DATA / "ground_truth.json").read_text(encoding="utf-8"))
    ]
    ledger = InMemoryLedger(catalog)
    mismatches = []

    for truth in sorted(truths, key=lambda t: t.file):
        invoice = truth.extraction
        invoice_id = uuid.uuid4()
        quality = assess_extraction(invoice, today=date(2026, 10, 11))
        result = reconcile(
            invoice, invoice_id=invoice_id, ledger=ledger, quality=quality, config=PolicyConfig()
        )
        decision = decide(result.findings)
        ledger.record(
            invoice_id=invoice_id,
            filename=truth.file,
            invoice=invoice,
            vendor=result.vendor,
            po=result.purchase_order,
            action=decision.action,
        )
        missing_findings = set(truth.expected_findings) - result.codes
        if decision.action is not truth.expected_action or missing_findings:
            mismatches.append(
                f"{truth.file} [{truth.scenario}] expected {truth.expected_action.value} "
                f"got {decision.action.value}; missing {sorted(missing_findings)}; "
                f"found {sorted(result.codes)}"
            )

    assert not mismatches, "\n".join(mismatches)
