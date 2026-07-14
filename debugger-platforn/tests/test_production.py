"""Tests for production ingestion, scoring, ground truth and projection."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.diagnosis.models import RootCauseType
from src.evaluation.projection import (
    PRODUCTION_CATEGORIES,
    PRODUCTION_CATEGORY_PROJECTION,
    ROOT_CAUSE_PROJECTION,
    project_diagnosis_report,
    project_production_category,
    project_root_cause,
    projection_table,
)
from src.evaluation.taxonomy import FailureCategory
from src.production import (
    build_ground_truth,
    load_export,
    score_conversation,
    time_split,
    to_production_signals,
)


def _conv(**overrides):
    base = {
        "id": "conv-1",
        "status": "active",
        "escalated_at": None,
        "escalation_reason": None,
        "is_human_handling": False,
        "taken_over_at": None,
        "message_count": 4,
        "created_at": "2026-03-01T12:00:00+00:00",
        "messages": [
            {"source": "customer", "text_body": "Hola, estado de mi orden",
             "ai_intent_detected": "order_status", "created_at": "2026-03-01T12:00:00+00:00"},
            {"source": "ai_agent", "text_body": "Su orden está en reparación",
             "ai_confidence_score": 0.9, "created_at": "2026-03-01T12:00:05+00:00"},
        ],
    }
    base.update(overrides)
    return base


# ----------------------------------------------------------------------
# Projection totality and stability
# ----------------------------------------------------------------------

class TestProjection:
    def test_production_projection_total(self):
        for cat in PRODUCTION_CATEGORIES:
            assert isinstance(project_production_category(cat), FailureCategory)

    def test_root_cause_projection_total(self):
        for rc in RootCauseType:
            assert isinstance(project_root_cause(rc), FailureCategory)

    def test_projection_accepts_string_root_cause(self):
        assert project_root_cause("hallucination") == FailureCategory.HALLUCINATION

    def test_unknown_production_category_raises(self):
        with pytest.raises(KeyError):
            project_production_category("not_a_category")

    def test_frozen_rows(self):
        # Anchor rows the dissertation cites; changing them silently would
        # invalidate previously computed results.
        assert PRODUCTION_CATEGORY_PROJECTION["loop_stall"] == FailureCategory.INFINITE_LOOP
        assert PRODUCTION_CATEGORY_PROJECTION["silent_abandonment"] == FailureCategory.PREMATURE_EXIT
        assert ROOT_CAUSE_PROJECTION[RootCauseType.TOOL_SELECTION_ERROR] == FailureCategory.WRONG_TOOL

    def test_projection_table_shape(self):
        table = projection_table()
        assert len(table["production_to_shared"]) == len(PRODUCTION_CATEGORIES)
        assert len(table["root_cause_to_shared"]) == len(RootCauseType)

    def test_project_diagnosis_report(self):
        report = {"clusters": [
            {"cluster_id": "c1", "root_cause": {"root_cause_type": "hallucination"},
             "primary_tool": "lookup_order", "frequency": 3},
            {"cluster_id": "c2", "root_cause": {"root_cause_type": "not_a_cause"}},
        ]}
        failures = project_diagnosis_report(report)
        assert len(failures) == 1
        assert failures[0]["failure_category"] == "hallucination"
        assert failures[0]["tool_involved"] == "lookup_order"


# ----------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------

class TestScoring:
    def test_clean_conversation_scores_zero(self):
        score = score_conversation(_conv())
        assert score.failure_score == 0.0
        assert score.categories == []

    def test_explicit_human_request(self):
        conv = _conv(
            escalated_at="2026-03-01T12:10:00+00:00",
            escalation_reason="El cliente solicitó hablar con un agente.",
        )
        score = score_conversation(conv)
        assert score.escalated and score.requested_human
        assert "resolution" in score.categories
        assert score.failure_score >= 8  # escalated(3) + human request(5)

    def test_data_gap_from_escalation_reason(self):
        conv = _conv(escalation_reason="Orden 4175435752 sin datos completos (garantía)")
        score = score_conversation(conv)
        assert "data_gap" in score.categories

    def test_comprehension_from_unknown_intents(self):
        msgs = [
            {"source": "customer", "text_body": "algo raro", "ai_intent_detected": "unknown",
             "created_at": "2026-03-01T12:00:00+00:00"},
            {"source": "ai_agent", "text_body": "¿Puede repetir?", "ai_intent_detected": "unknown",
             "ai_confidence_score": 0.8, "created_at": "2026-03-01T12:00:05+00:00"},
            {"source": "ai_agent", "text_body": "No comprendo", "ai_intent_detected": "unknown",
             "ai_confidence_score": 0.8, "created_at": "2026-03-01T12:00:10+00:00"},
        ]
        score = score_conversation(_conv(messages=msgs))
        assert "comprehension" in score.categories

    def test_loop_stall_from_message_count(self):
        score = score_conversation(_conv(message_count=55))
        assert "loop_stall" in score.categories

    def test_loop_stall_from_repeated_ai_responses(self):
        same = {"source": "ai_agent", "text_body": "Su orden sigue en proceso",
                "ai_confidence_score": 0.9}
        msgs = [dict(same, created_at=f"2026-03-01T12:0{i}:00+00:00") for i in range(3)]
        score = score_conversation(_conv(messages=msgs))
        assert "loop_stall" in score.categories

    def test_delivery_failure(self):
        msgs = [{"source": "ai_agent", "text_body": "hola", "status": "failed",
                 "error_code": "131026", "created_at": "2026-03-01T12:00:00+00:00"}]
        score = score_conversation(_conv(messages=msgs))
        assert "delivery_infra" in score.categories
        assert score.evidence["delivery_infra"]["error_codes"] == ["131026"]

    def test_missed_escalation(self):
        msgs = [
            {"source": "customer", "text_body": "esto es inaceptable, pésimo servicio",
             "created_at": "2026-03-01T12:00:00+00:00"},
            {"source": "ai_agent", "text_body": "¡Con gusto le ayudo!",
             "ai_confidence_score": 0.9, "created_at": "2026-03-01T12:00:05+00:00"},
        ]
        score = score_conversation(_conv(messages=msgs))
        assert score.frustration
        assert "missed_escalation" in score.categories

    def test_frustration_escalated_is_not_missed(self):
        msgs = [{"source": "customer", "text_body": "pésimo servicio",
                 "created_at": "2026-03-01T12:00:00+00:00"}]
        conv = _conv(messages=msgs, escalated_at="2026-03-01T12:05:00+00:00",
                     escalation_reason="complaint_escalation")
        score = score_conversation(conv)
        assert "missed_escalation" not in score.categories

    def test_silent_abandonment(self):
        msgs = [
            {"source": "customer", "text_body": "estado de orden",
             "created_at": "2026-03-01T12:00:00+00:00"},
            {"source": "ai_agent", "text_body": "¿Me da su número de orden?",
             "ai_confidence_score": 0.9, "created_at": "2026-03-01T12:00:05+00:00"},
        ]
        score = score_conversation(_conv(status="expired", messages=msgs))
        assert "silent_abandonment" in score.categories

    def test_hallucination_pushback(self):
        msgs = [
            {"source": "ai_agent", "text_body": "El costo es $500",
             "ai_confidence_score": 0.9, "created_at": "2026-03-01T12:00:00+00:00"},
            {"source": "customer", "text_body": "Eso no es correcto, me dijeron otra cosa",
             "created_at": "2026-03-01T12:00:05+00:00"},
        ]
        score = score_conversation(_conv(messages=msgs))
        assert "hallucination" in score.categories

    def test_tool_names_skip_unknown(self):
        msgs = [{"source": "ai_agent", "text_body": "ok", "ai_confidence_score": 0.9,
                 "ai_tool_calls": [{"name": "unknown"}, {"name": "get_order_status"}],
                 "created_at": "2026-03-01T12:00:00+00:00"}]
        score = score_conversation(_conv(messages=msgs))
        assert score.tools_involved == ["get_order_status"]


# ----------------------------------------------------------------------
# Ground truth + split
# ----------------------------------------------------------------------

class TestGroundTruth:
    def _failing_conv(self, cid, created_at):
        return _conv(
            id=cid,
            created_at=created_at,
            escalated_at=created_at,
            escalation_reason="El cliente solicitó hablar con un agente.",
        )

    def test_build_and_threshold(self):
        convs = [_conv(id="clean"), self._failing_conv("bad", "2026-03-02T10:00:00+00:00")]
        for c in convs:
            c["_created_dt"] = datetime.fromisoformat(c["created_at"])
        gt = build_ground_truth(convs)
        assert gt.n_conversations_analysed == 2
        assert [f.conversation_id for f in gt.failures] == ["bad"]
        assert gt.by_category["resolution"] == 1
        assert gt.by_shared_category["resolution_failure"] == 1

    def test_time_split_chronological(self):
        convs = [
            self._failing_conv(f"c{i}", f"2026-0{m}-01T10:00:00+00:00")
            for i, m in enumerate([1, 2, 3, 4, 5], start=1)
        ]
        for c in convs:
            c["_created_dt"] = datetime.fromisoformat(c["created_at"])
        gt = build_ground_truth(convs)
        train, held = time_split(gt, holdout_fraction=0.4)
        assert len(train) == 3 and len(held) == 2
        assert max(f.timestamp for f in train) < min(f.timestamp for f in held)

    def test_time_split_cutoff(self):
        convs = [self._failing_conv(f"c{m}", f"2026-0{m}-01T10:00:00+00:00") for m in (1, 3, 5)]
        for c in convs:
            c["_created_dt"] = datetime.fromisoformat(c["created_at"])
        gt = build_ground_truth(convs)
        cutoff = datetime(2026, 4, 1, tzinfo=timezone.utc)
        train, held = time_split(gt, cutoff=cutoff)
        assert [f.conversation_id for f in train] == ["c1", "c3"]
        assert [f.conversation_id for f in held] == ["c5"]

    def test_signals_one_per_category(self):
        conv = self._failing_conv("multi", "2026-03-02T10:00:00+00:00")
        conv["message_count"] = 60  # adds loop_stall on top of resolution
        conv["_created_dt"] = datetime.fromisoformat(conv["created_at"])
        gt = build_ground_truth([conv])
        signals = to_production_signals(gt.failures)
        cats = sorted(s.failure_category.value for s in signals)
        assert cats == ["infinite_loop", "resolution_failure"]
        assert all(s.trace_id == "multi" for s in signals)


# ----------------------------------------------------------------------
# Loader
# ----------------------------------------------------------------------

class TestLoader:
    def test_load_export_normalises(self, tmp_path):
        export = {
            "exported_at": "2026-06-28",
            "total_conversations": 1,
            "total_messages": 2,
            "conversations": [{
                "id": "c1", "status": "closed",
                "created_at": "2026-03-01T12:00:00+00:00",
                "messages": [
                    {"source": "ai_agent", "created_at": "2026-03-01T12:00:10+00:00"},
                    {"source": "customer", "created_at": "2026-03-01T12:00:00+00:00"},
                ],
            }],
        }
        p = tmp_path / "export.json"
        p.write_text(json.dumps(export))
        convs = load_export(p)
        assert len(convs) == 1
        assert convs[0]["messages"][0]["source"] == "customer"  # re-sorted
        assert convs[0]["_created_dt"].year == 2026

    def test_load_export_rejects_wrong_shape(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps({"foo": 1}))
        with pytest.raises(ValueError):
            load_export(p)
