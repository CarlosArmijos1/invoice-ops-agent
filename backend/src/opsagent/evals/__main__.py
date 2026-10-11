"""Evaluate extraction and decisions against the labelled synthetic dataset.

    uv run python -m opsagent.evals --llm replay        # CI: recorded responses, free
    uv run python -m opsagent.evals --llm record        # call Groq and (re)record cassettes
    uv run python -m opsagent.evals --llm oracle        # perfect extraction: isolates the rules
    ... --update-readme                                 # rewrite the results block in README.md
    ... --check                                         # exit 1 if quality gates fail

Same steps as the agent graph (prepare -> extract -> quality -> reconcile ->
decide), with an in-memory ledger instead of Postgres so it runs anywhere in
seconds. The graph wiring itself is covered by the integration tests.
"""

import argparse
import json
import sys
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from opsagent.datagen.records import Catalog, GroundTruth
from opsagent.domain.findings import Finding, FindingCode
from opsagent.domain.policy import decide
from opsagent.domain.quality import assess_extraction
from opsagent.domain.reconciliation import PolicyConfig, reconcile
from opsagent.domain.schemas import ExtractedInvoice
from opsagent.evals.metrics import FIELDS, InvoiceOutcome, field_matches, summarize
from opsagent.evals.report import render_markdown, update_readme
from opsagent.extraction.documents import prepare_document
from opsagent.extraction.extractor import InvoiceExtractor
from opsagent.infra.logging import configure_logging
from opsagent.infra.memory_ledger import InMemoryLedger
from opsagent.llm.errors import LLMError
from opsagent.llm.factory import build_llm_client
from opsagent.settings import REPO_ROOT, LLMMode, Settings, get_settings

DATA = REPO_ROOT / "data" / "synthetic"
RESULTS = REPO_ROOT / "evals" / "results"
TODAY = date(2026, 10, 11)  # fixed "today" so date checks are reproducible

GATES = {
    # Never auto-approve something a person should have seen.
    "max_false_approvals": 0,
    "min_decision_accuracy": 0.80,
    "min_critical_fields_ok": 0.80,
}


def run(llm_mode: str, settings: Settings) -> list[InvoiceOutcome]:
    catalog = Catalog.model_validate_json((DATA / "catalog.json").read_text(encoding="utf-8"))
    truths = sorted(
        (
            GroundTruth.model_validate(t)
            for t in json.loads((DATA / "ground_truth.json").read_text(encoding="utf-8"))
        ),
        key=lambda t: t.file,
    )
    ledger = InMemoryLedger(catalog)
    extractor = None
    if llm_mode != "oracle":
        llm = build_llm_client(settings.model_copy(update={"llm_mode": LLMMode(llm_mode)}))
        extractor = InvoiceExtractor(
            llm,
            text_model=settings.reasoning_model,
            vision_model=settings.vision_model,
            max_attempts=settings.extraction_max_attempts,
            own_tax_id=settings.own_tax_id,
            text_model_extra={"reasoning_effort": settings.reasoning_effort},
        )
    policy = PolicyConfig(
        amount_tolerance_abs=settings.amount_tolerance_abs,
        amount_tolerance_pct=settings.amount_tolerance_pct,
        auto_approval_limit=settings.auto_approval_limit,
        min_quality_score=settings.min_quality_score,
    )

    outcomes = []
    for truth in truths:
        content = (DATA / "invoices" / truth.file).read_bytes()
        doc = prepare_document(content)
        invoice: ExtractedInvoice | None
        error = None
        cost, latency, calls, method = Decimal(0), 0, 0, None
        if extractor is None:
            invoice, method = truth.extraction, "oracle"
        else:
            try:
                result = extractor.extract(doc, content)
                invoice, method = result.invoice, result.method
                cost, calls = result.cost_usd, len(result.calls)
                latency = sum(c.latency_ms for c in result.calls)
                error = result.error
            except LLMError as exc:
                invoice, error = None, f"{type(exc).__name__}: {exc}"

        invoice_id = uuid.uuid4()
        if invoice is not None:
            quality = assess_extraction(
                invoice, today=TODAY, source_text=doc.text if method == "text" else None
            )
            rec = reconcile(
                invoice, invoice_id=invoice_id, ledger=ledger, quality=quality, config=policy
            )
            findings = rec.findings
        else:
            rec, findings = None, [Finding(code=FindingCode.EXTRACTION_FAILED, message="")]
        decision = decide(findings)
        if invoice is not None and rec is not None:
            ledger.record(
                invoice_id=invoice_id,
                filename=truth.file,
                invoice=invoice,
                vendor=rec.vendor,
                po=rec.purchase_order,
                action=decision.action,
            )

        outcomes.append(
            InvoiceOutcome(
                file=truth.file,
                split=truth.split.value,
                scenario=truth.scenario,
                render=truth.render.value,
                expected_action=truth.expected_action.value,
                action=decision.action.value,
                expected_findings=[f.value for f in truth.expected_findings],
                findings=[f.code.value for f in findings],
                extracted=invoice is not None,
                method=method,
                field_hits=(
                    {f: field_matches(f, truth.extraction, invoice) for f in FIELDS}
                    if invoice is not None
                    else {}
                ),
                cost_usd=cost,
                latency_ms=latency,
                llm_calls=calls,
                error=error,
            )
        )
        status = "ok " if decision.action.value == truth.expected_action.value else "BAD"
        print(
            f"{status} {truth.file:12} {truth.scenario:22} {decision.action.value}", file=sys.stderr
        )
    return outcomes


def check_gates(summary: dict[str, Any]) -> list[str]:
    failures = []
    if len(summary["decisions"]["false_approvals"]) > GATES["max_false_approvals"]:
        failures.append(f"false approvals: {summary['decisions']['false_approvals']}")
    if (summary["decisions"]["accuracy"] or 0) < GATES["min_decision_accuracy"]:
        failures.append(f"decision accuracy {summary['decisions']['accuracy']}")
    if (summary["extraction"]["critical_fields_ok"] or 0) < GATES["min_critical_fields_ok"]:
        failures.append(f"critical fields ok {summary['extraction']['critical_fields_ok']}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--llm", choices=["replay", "record", "live", "hybrid", "oracle"], default="replay"
    )
    parser.add_argument("--update-readme", action="store_true")
    parser.add_argument("--check", action="store_true", help="fail on quality gates")
    args = parser.parse_args()
    configure_logging("WARNING", stream="stderr")
    settings = get_settings()

    outcomes = run(args.llm, settings)
    report: dict[str, Any] = {
        "mode": args.llm,
        "models": {"text": settings.reasoning_model, "vision": settings.vision_model},
        "all": summarize(outcomes),
        "test": summarize([o for o in outcomes if o.split == "test"]),
        "dev": summarize([o for o in outcomes if o.split == "dev"]),
        "gates": GATES,
        "invoices": [
            {**o.__dict__, "cost_usd": str(o.cost_usd), "critical_ok": o.critical_ok}
            for o in outcomes
        ],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    suffix = "oracle" if args.llm == "oracle" else "llm"
    (RESULTS / f"{suffix}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    markdown = render_markdown(report)
    (RESULTS / f"{suffix}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    if args.update_readme and args.llm != "oracle":
        update_readme(REPO_ROOT / "README.md", markdown)

    failures = check_gates(report["all"]) if args.check else []
    if failures:
        print("QUALITY GATES FAILED: " + "; ".join(failures), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
