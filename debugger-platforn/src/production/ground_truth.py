"""
Ground-truth failure set construction and time split.

A conversation enters the ground truth when its structured failure score
clears a threshold AND at least one production failure category triggered.
Each ground-truth failure carries both vocabularies: the production category
(what the human-process signal said) and the shared-taxonomy projection
(what the measurement engine compares against).

The time split answers "does testing today predict the failures of
tomorrow?": train = the earliest fraction of failures (available to the
feedback loop), held-out = the latest fraction (used only for measurement).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.evaluation.predictive_validity import ProductionSignal
from src.evaluation.projection import project_production_category
from src.evaluation.taxonomy import CATEGORY_SEVERITY, FailureCategory
from src.production.scoring import ConversationScore, score_conversation

DEFAULT_MIN_SCORE = 3.0

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}

# Which ground-truth source label applies per production category.
_CATEGORY_SOURCE = {
    "resolution": "escalation",
    "data_gap": "escalation",
    "missed_escalation": "qa_flag",
    "comprehension": "qa_flag",
    "loop_stall": "qa_flag",
    "delivery_infra": "qa_flag",
    "silent_abandonment": "qa_flag",
    "hallucination": "complaint",
}


@dataclass
class GroundTruthFailure:
    conversation_id: str
    timestamp: Optional[datetime]                 # conversation created_at
    failure_score: float
    production_categories: List[str]              # production vocabulary
    shared_categories: List[str]                  # projected FailureCategory values
    severity: str                                 # max severity across categories
    evidence: Dict[str, Any] = field(default_factory=dict)
    tools_involved: List[str] = field(default_factory=list)
    escalated: bool = False
    human_takeover: bool = False
    message_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "failure_score": self.failure_score,
            "production_categories": self.production_categories,
            "shared_categories": self.shared_categories,
            "severity": self.severity,
            "evidence": self.evidence,
            "tools_involved": self.tools_involved,
            "escalated": self.escalated,
            "human_takeover": self.human_takeover,
            "message_count": self.message_count,
        }


@dataclass
class GroundTruthSet:
    failures: List[GroundTruthFailure] = field(default_factory=list)
    n_conversations_analysed: int = 0
    min_score: float = DEFAULT_MIN_SCORE
    by_category: Dict[str, int] = field(default_factory=dict)
    by_shared_category: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_conversations_analysed": self.n_conversations_analysed,
            "n_failures": len(self.failures),
            "min_score": self.min_score,
            "by_category": self.by_category,
            "by_shared_category": self.by_shared_category,
            "failures": [f.to_dict() for f in self.failures],
        }


def _severity_for(shared_categories: List[str]) -> str:
    best = "low"
    for value in shared_categories:
        sev = CATEGORY_SEVERITY[FailureCategory(value)]
        if _SEVERITY_RANK[sev] > _SEVERITY_RANK[best]:
            best = sev
    return best


def build_ground_truth(
    conversations: List[Dict[str, Any]],
    min_score: float = DEFAULT_MIN_SCORE,
) -> GroundTruthSet:
    """Score every conversation and keep those that constitute failures."""
    gt = GroundTruthSet(min_score=min_score, n_conversations_analysed=len(conversations))

    for conv in conversations:
        score: ConversationScore = score_conversation(conv)
        if score.failure_score < min_score or not score.categories:
            continue
        shared = sorted({project_production_category(c).value for c in score.categories})
        failure = GroundTruthFailure(
            conversation_id=score.conversation_id,
            timestamp=conv.get("_created_dt"),
            failure_score=score.failure_score,
            production_categories=score.categories,
            shared_categories=shared,
            severity=_severity_for(shared),
            evidence=score.evidence,
            tools_involved=score.tools_involved,
            escalated=score.escalated,
            human_takeover=score.human_takeover,
            message_count=score.message_count,
        )
        gt.failures.append(failure)
        for c in score.categories:
            gt.by_category[c] = gt.by_category.get(c, 0) + 1
        for c in shared:
            gt.by_shared_category[c] = gt.by_shared_category.get(c, 0) + 1

    gt.failures.sort(key=lambda f: f.timestamp or datetime.min.replace(tzinfo=timezone.utc))
    return gt


def time_split(
    ground_truth: GroundTruthSet,
    holdout_fraction: float = 0.3,
    cutoff: Optional[datetime] = None,
) -> Tuple[List[GroundTruthFailure], List[GroundTruthFailure]]:
    """Split failures chronologically into (train, held_out).

    With *cutoff*, failures strictly before it are train and the rest
    held-out.  Otherwise the earliest ``1 - holdout_fraction`` of failures
    are train.  Failures without a timestamp go to train (they cannot be
    "future" failures, and putting them in the held-out set would credit
    or penalise arms on undated evidence).
    """
    dated = [f for f in ground_truth.failures if f.timestamp is not None]
    undated = [f for f in ground_truth.failures if f.timestamp is None]
    dated.sort(key=lambda f: f.timestamp)

    if cutoff is not None:
        train = [f for f in dated if f.timestamp < cutoff]
        held_out = [f for f in dated if f.timestamp >= cutoff]
    else:
        n_train = int(round(len(dated) * (1 - holdout_fraction)))
        train, held_out = dated[:n_train], dated[n_train:]

    return train + undated, held_out


def to_production_signals(
    failures: List[GroundTruthFailure],
) -> List[ProductionSignal]:
    """Convert ground-truth failures into measurement-engine signals.

    One signal per (conversation, shared category) pair: a conversation that
    failed in two distinct ways contributes two recall targets, but repeated
    failures of the same kind within one conversation contribute one.
    """
    signals: List[ProductionSignal] = []
    for failure in failures:
        # Recover the production category that produced each shared category
        prod_by_shared: Dict[str, str] = {}
        for prod_cat in failure.production_categories:
            shared_value = project_production_category(prod_cat).value
            prod_by_shared.setdefault(shared_value, prod_cat)

        for shared_value in failure.shared_categories:
            prod_cat = prod_by_shared.get(shared_value, "")
            tool = failure.tools_involved[-1] if failure.tools_involved else None
            signals.append(ProductionSignal(
                signal_id=f"gt_{failure.conversation_id}_{shared_value}",
                trace_id=failure.conversation_id,
                failure_category=FailureCategory(shared_value),
                description=(
                    f"Production {prod_cat or 'failure'} "
                    f"(score={failure.failure_score}, severity={failure.severity})"
                ),
                tool_involved=tool,
                timestamp=failure.timestamp or datetime.now(timezone.utc),
                source=_CATEGORY_SOURCE.get(prod_cat, "human_label"),
            ))
    return signals
