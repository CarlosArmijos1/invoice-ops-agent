"""Decision policy: findings in, action out. Deliberately boring and auditable.

Precedence: any RISK finding -> human review; otherwise any MISSING_INFO
finding -> request info from the supplier; otherwise auto-approve.
Auto-approval therefore requires the *absence* of every known problem, which
makes "approved by mistake" the hardest outcome to reach.
"""

from dataclasses import dataclass

from opsagent.domain.findings import Finding, Severity
from opsagent.domain.schemas import DecisionAction

ACTION_LABEL = {
    DecisionAction.AUTO_APPROVE: "Aprobada automáticamente",
    DecisionAction.HUMAN_REVIEW: "Enviada a revisión humana",
    DecisionAction.REQUEST_INFO: "Se solicita información al proveedor",
}


@dataclass(frozen=True)
class PolicyDecision:
    action: DecisionAction
    blocking: list[Finding]  # the findings that determined the action
    justification: str  # deterministic, always available even if the LLM is down


def decide(findings: list[Finding]) -> PolicyDecision:
    risks = [f for f in findings if f.severity is Severity.RISK]
    missing = [f for f in findings if f.severity is Severity.MISSING_INFO]

    if risks:
        action, blocking = DecisionAction.HUMAN_REVIEW, risks
    elif missing:
        action, blocking = DecisionAction.REQUEST_INFO, missing
    else:
        action, blocking = DecisionAction.AUTO_APPROVE, []

    if blocking:
        reasons = "\n".join(f"- {f.message}" for f in blocking)
        justification = f"{ACTION_LABEL[action]} por:\n{reasons}"
    else:
        context = "\n".join(f"- {f.message}" for f in findings)
        justification = f"{ACTION_LABEL[action]}: todos los controles pasaron." + (
            f"\n{context}" if context else ""
        )
    return PolicyDecision(action=action, blocking=blocking, justification=justification)
