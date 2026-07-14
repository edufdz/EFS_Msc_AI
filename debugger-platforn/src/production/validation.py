"""
Ground-truth validation: does an independent annotator agree with the
structured-signal failure labels?

The ground truth (src/production/scoring.py) is heuristic: structured
human-process signals mapped to eight failure categories.  Before the
dissertation leans on it, an annotator who reads the actual transcripts must
agree with it at a defensible rate.  This module provides:

  - a STRATIFIED BLIND SAMPLE: flagged conversations across categories plus
    clean controls, presented without the heuristic labels or scores;
  - an ANNOTATION PROTOCOL (written to the packet) so labels are applied
    consistently;
  - AGREEMENT STATISTICS: Cohen's kappa on the binary failed/not-failed
    decision, and per-category precision/recall of the heuristic labels
    with the annotator as reference.

Two annotator paths:
  - HUMAN (the number the dissertation reports): the interactive CLI in
    run_validation.py, or hand-editing the packet's annotations file.
  - LLM PILOT (preliminary only): an LLM reads the anonymised transcripts
    and applies the same protocol.  Results are stamped
    ``annotator_type="llm_pilot"`` and every artefact carries a caveat —
    an LLM annotator can NEVER substitute for the human check, because the
    study's criterion validity rests on independence from model judgement.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.production.ground_truth import GroundTruthSet
from src.production.scoring import score_conversation

CATEGORY_DEFINITIONS: Dict[str, str] = {
    "comprehension": "The agent did not understand what the customer was asking (wrong topic, generic replies, re-asking for provided info).",
    "resolution": "The agent understood but could not resolve the issue; the customer demanded a human.",
    "data_gap": "The agent's logic was right but backend data (orders/warranty/cost) was missing or incomplete.",
    "loop_stall": "The conversation circled without progress (repeated questions or answers).",
    "delivery_infra": "Messages failed to reach the customer (WhatsApp/API delivery errors).",
    "missed_escalation": "The customer expressed frustration or asked for help but the agent did not escalate or change behaviour.",
    "silent_abandonment": "The customer stopped responding with no resolution and no escalation.",
    "hallucination": "The agent gave incorrect information (wrong price, status, or process).",
}

PROTOCOL = """# Annotation Protocol — Ground-Truth Validation

You will see anonymised WhatsApp support conversations, in order, WITHOUT
any automated labels. For each conversation answer:

1. did_fail — Did the agent fail this customer?
   - "yes": the customer was left unserved, misinformed, or had to fight the agent
   - "partial": the issue was eventually served but with real friction caused by the agent
   - "no": the agent served the customer adequately
2. categories — If yes/partial, every category that applies (see definitions).
3. note — One sentence on the decisive evidence (optional but encouraged).

Rules:
- Judge ONLY from the transcript and its visible metadata (status, counts).
- Template/system notifications are not agent failures by themselves.
- Delivery failures count when the transcript shows sends that never reached
  the customer.
- When torn between "no" and "partial", ask: would this customer complain
  about the bot? If plausibly yes, choose "partial".
"""


@dataclass
class ValidationItem:
    conversation_id: str
    transcript: List[Dict[str, str]]           # [{source, text}]
    status: str
    message_count: int
    # Hidden from the annotator view; used by the agreement computation.
    heuristic_failed: bool
    heuristic_categories: List[str]
    failure_score: float


@dataclass
class Annotation:
    conversation_id: str
    did_fail: str                               # "yes" | "partial" | "no"
    categories: List[str] = field(default_factory=list)
    note: str = ""


# ----------------------------------------------------------------------
# Sampling
# ----------------------------------------------------------------------


def build_validation_sample(
    conversations: List[Dict[str, Any]],
    ground_truth: GroundTruthSet,
    n_flagged: int = 40,
    n_clean: int = 10,
    seed: int = 42,
    max_transcript_messages: int = 60,
) -> List[ValidationItem]:
    """Stratified blind sample: flagged conversations spread across primary
    categories (proportional, at least one per non-empty category) plus
    clean controls, shuffled so the annotator cannot infer the split."""
    rng = random.Random(seed)
    convs_by_id = {str(c.get("id")): c for c in conversations}

    by_category: Dict[str, List] = {}
    for f in ground_truth.failures:
        by_category.setdefault(f.production_categories[0], []).append(f)

    total_flagged = sum(len(v) for v in by_category.values())
    picked_ids: List[str] = []
    # Proportional allocation with a floor of 1 per category
    for category, failures in sorted(by_category.items()):
        share = max(1, round(n_flagged * len(failures) / total_flagged))
        failures = sorted(failures, key=lambda f: f.conversation_id)
        rng.shuffle(failures)
        picked_ids.extend(f.conversation_id for f in failures[:share])
    rng.shuffle(picked_ids)
    picked_ids = picked_ids[:n_flagged]

    flagged_id_set = {f.conversation_id for f in ground_truth.failures}
    clean_pool = sorted(
        cid for cid in convs_by_id
        if cid not in flagged_id_set and (convs_by_id[cid].get("messages") or [])
    )
    rng.shuffle(clean_pool)
    picked_ids.extend(clean_pool[:n_clean])
    rng.shuffle(picked_ids)

    failures_by_id = {f.conversation_id: f for f in ground_truth.failures}
    items: List[ValidationItem] = []
    for cid in picked_ids:
        conv = convs_by_id[cid]
        transcript = [
            {"source": m.get("source", "?"), "text": (m.get("text_body") or "").strip()}
            for m in (conv.get("messages") or [])[:max_transcript_messages]
            if (m.get("text_body") or "").strip()
        ]
        failure = failures_by_id.get(cid)
        items.append(ValidationItem(
            conversation_id=cid,
            transcript=transcript,
            status=str(conv.get("status", "")),
            message_count=int(conv.get("message_count") or len(transcript)),
            heuristic_failed=failure is not None,
            heuristic_categories=list(failure.production_categories) if failure else [],
            failure_score=failure.failure_score if failure else score_conversation(conv).failure_score,
        ))
    return items


def write_packet(items: List[ValidationItem], out_dir: str | Path) -> Path:
    """Write the annotation packet: protocol, blind items, empty annotations
    file, and a hidden answer key (separate file the annotator must not open
    until done)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    (out / "ANNOTATION_GUIDE.md").write_text(
        PROTOCOL + "\n## Category definitions\n\n" + "\n".join(
            f"- **{k}**: {v}" for k, v in CATEGORY_DEFINITIONS.items()
        ) + "\n"
    )
    (out / "items.json").write_text(json.dumps([
        {
            "conversation_id": it.conversation_id,
            "status": it.status,
            "message_count": it.message_count,
            "transcript": it.transcript,
        } for it in items
    ], indent=2, ensure_ascii=False))
    (out / "answer_key.json").write_text(json.dumps([
        {
            "conversation_id": it.conversation_id,
            "heuristic_failed": it.heuristic_failed,
            "heuristic_categories": it.heuristic_categories,
            "failure_score": it.failure_score,
        } for it in items
    ], indent=2))
    annotations_path = out / "annotations.json"
    if not annotations_path.exists():
        annotations_path.write_text(json.dumps([
            {"conversation_id": it.conversation_id, "did_fail": "", "categories": [], "note": ""}
            for it in items
        ], indent=2))
    return out


# ----------------------------------------------------------------------
# Agreement statistics
# ----------------------------------------------------------------------


def cohens_kappa(pairs: List[Tuple[bool, bool]]) -> float:
    """Cohen's kappa for two binary raters given paired judgements."""
    n = len(pairs)
    if n == 0:
        return 0.0
    po = sum(1 for a, b in pairs if a == b) / n
    a_yes = sum(1 for a, _ in pairs if a) / n
    b_yes = sum(1 for _, b in pairs if b) / n
    pe = a_yes * b_yes + (1 - a_yes) * (1 - b_yes)
    if pe == 1.0:
        return 1.0
    return round((po - pe) / (1 - pe), 4)


def compute_agreement(
    items: List[ValidationItem],
    annotations: List[Annotation | Dict[str, Any]],
    lenient: bool = True,
) -> Dict[str, Any]:
    """Agreement between heuristic labels and the annotator.

    lenient=True counts "partial" as failed (the heuristic threshold is
    itself lenient); the strict variant is also reported.
    """
    ann_by_id: Dict[str, Annotation] = {}
    for a in annotations:
        if isinstance(a, dict):
            a = Annotation(
                conversation_id=str(a.get("conversation_id")),
                did_fail=str(a.get("did_fail", "")).lower().strip(),
                categories=list(a.get("categories") or []),
                note=str(a.get("note", "")),
            )
        ann_by_id[a.conversation_id] = a

    unlabelled = [it.conversation_id for it in items if
                  ann_by_id.get(it.conversation_id, Annotation("", "")).did_fail
                  not in ("yes", "partial", "no")]
    labelled = [it for it in items if it.conversation_id not in set(unlabelled)]

    def _annotator_failed(a: Annotation, lenient_mode: bool) -> bool:
        return a.did_fail == "yes" or (lenient_mode and a.did_fail == "partial")

    def _binary_stats(lenient_mode: bool) -> Dict[str, Any]:
        pairs = [
            (it.heuristic_failed, _annotator_failed(ann_by_id[it.conversation_id], lenient_mode))
            for it in labelled
        ]
        tp = sum(1 for h, a in pairs if h and a)
        fp = sum(1 for h, a in pairs if h and not a)
        fn = sum(1 for h, a in pairs if not h and a)
        tn = sum(1 for h, a in pairs if not h and not a)
        n = len(pairs)
        return {
            "n": n,
            "observed_agreement": round((tp + tn) / n, 4) if n else 0.0,
            "cohens_kappa": cohens_kappa(pairs),
            "heuristic_precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
            "heuristic_recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
            "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        }

    # Per-category: heuristic labels vs annotator labels, over conversations
    # BOTH sides considered failed (category agreement is only meaningful
    # where a failure exists at all).
    per_category: Dict[str, Dict[str, Any]] = {}
    for category in CATEGORY_DEFINITIONS:
        tp = fp = fn = 0
        for it in labelled:
            a = ann_by_id[it.conversation_id]
            if not (it.heuristic_failed or _annotator_failed(a, True)):
                continue
            in_h = category in it.heuristic_categories
            in_a = category in a.categories
            tp += in_h and in_a
            fp += in_h and not in_a
            fn += (not in_h) and in_a
        if tp or fp or fn:
            per_category[category] = {
                "tp": tp, "fp": fp, "fn": fn,
                "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
                "recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
            }

    disagreements = []
    for it in labelled:
        a = ann_by_id[it.conversation_id]
        if it.heuristic_failed != _annotator_failed(a, lenient):
            disagreements.append({
                "conversation_id": it.conversation_id,
                "heuristic_failed": it.heuristic_failed,
                "heuristic_categories": it.heuristic_categories,
                "annotator": a.did_fail,
                "annotator_categories": a.categories,
                "note": a.note,
            })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_items": len(items),
        "n_labelled": len(labelled),
        "unlabelled": unlabelled,
        "binary_lenient": _binary_stats(True),
        "binary_strict": _binary_stats(False),
        "per_category": per_category,
        "disagreements": disagreements,
    }


# ----------------------------------------------------------------------
# LLM pilot annotator (preliminary check only — never the reported number)
# ----------------------------------------------------------------------

_LLM_PROMPT = """You are annotating a customer-support conversation between a customer and an AI agent (Spanish, anonymised placeholders like [PERSON_1] are expected).

{protocol}

Category definitions:
{definitions}

Conversation metadata: status={status}, total messages={message_count}
Transcript (source: text):
{transcript}

Respond with ONLY a JSON object:
{{"did_fail": "yes|partial|no", "categories": ["..."], "note": "one sentence"}}"""


def llm_annotate(
    items: List[ValidationItem],
    on_progress=lambda m: None,
) -> List[Annotation]:
    """Annotate the sample with an LLM following the same protocol.

    PILOT ONLY: stamped as such by the caller. Requires ANTHROPIC_API_KEY.
    The model sees exactly what the human sees — transcript and neutral
    metadata, never the heuristic labels.
    """
    import re

    from src.execution.llm_config import LLMProviderConfig

    config = LLMProviderConfig()
    client = config.create_sync_client()
    definitions = "\n".join(f"- {k}: {v}" for k, v in CATEGORY_DEFINITIONS.items())

    annotations: List[Annotation] = []
    for i, item in enumerate(items, 1):
        transcript = "\n".join(f"{t['source']}: {t['text']}" for t in item.transcript)
        prompt = _LLM_PROMPT.format(
            protocol=PROTOCOL,
            definitions=definitions,
            status=item.status,
            message_count=item.message_count,
            transcript=transcript[:12000],
        )
        raw, _in, _out = config.call_sync(client, prompt, max_tokens=400, temperature=0.0)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(match.group(0)) if match else {}
        categories = [c for c in (data.get("categories") or []) if c in CATEGORY_DEFINITIONS]
        annotations.append(Annotation(
            conversation_id=item.conversation_id,
            did_fail=str(data.get("did_fail", "no")).lower().strip(),
            categories=categories,
            note=str(data.get("note", ""))[:300],
        ))
        if i % 10 == 0:
            on_progress(f"LLM pilot: annotated {i}/{len(items)}")
    return annotations


def items_from_packet(packet_dir: str | Path) -> List[ValidationItem]:
    """Rehydrate ValidationItems from a written packet (items + answer key)."""
    packet = Path(packet_dir)
    items_data = json.loads((packet / "items.json").read_text())
    key = {k["conversation_id"]: k for k in json.loads((packet / "answer_key.json").read_text())}
    items = []
    for d in items_data:
        k = key[d["conversation_id"]]
        items.append(ValidationItem(
            conversation_id=d["conversation_id"],
            transcript=d["transcript"],
            status=d["status"],
            message_count=d["message_count"],
            heuristic_failed=k["heuristic_failed"],
            heuristic_categories=k["heuristic_categories"],
            failure_score=k["failure_score"],
        ))
    return items
