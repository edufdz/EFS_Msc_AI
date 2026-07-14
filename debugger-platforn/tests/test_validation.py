"""Tests for ground-truth validation (sampling, packet, agreement stats)."""

from __future__ import annotations

import json

from src.production import build_ground_truth
from src.production.validation import (
    Annotation,
    build_validation_sample,
    cohens_kappa,
    compute_agreement,
    items_from_packet,
    write_packet,
)


def _conv(cid, escalated, month=3):
    return {
        "id": cid, "status": "closed",
        "escalated_at": f"2026-{month:02d}-02T10:00:00+00:00" if escalated else None,
        "escalation_reason": "El cliente solicitó hablar con un agente." if escalated else None,
        "message_count": 4,
        "created_at": f"2026-{month:02d}-01T10:00:00+00:00",
        "messages": [
            {"source": "customer", "text_body": "Estado de mi orden",
             "created_at": f"2026-{month:02d}-01T10:00:00+00:00"},
            {"source": "ai_agent", "text_body": "Un momento", "ai_confidence_score": 0.9,
             "created_at": f"2026-{month:02d}-01T10:00:05+00:00"},
        ],
    }


def _fixture(n_fail=12, n_ok=8):
    convs = [_conv(f"fail-{i}", True, (i % 6) + 1) for i in range(n_fail)]
    convs += [_conv(f"ok-{i}", False, (i % 6) + 1) for i in range(n_ok)]
    gt = build_ground_truth(convs)
    return convs, gt


class TestSampling:
    def test_stratified_blind_sample(self):
        convs, gt = _fixture()
        items = build_validation_sample(convs, gt, n_flagged=6, n_clean=4, seed=1)
        assert len(items) == 10
        assert sum(1 for it in items if it.heuristic_failed) == 6
        assert sum(1 for it in items if not it.heuristic_failed) == 4
        # Blind view fields present
        assert all(it.transcript for it in items)

    def test_deterministic(self):
        convs, gt = _fixture()
        a = [it.conversation_id for it in build_validation_sample(convs, gt, 6, 4, seed=1)]
        b = [it.conversation_id for it in build_validation_sample(convs, gt, 6, 4, seed=1)]
        assert a == b

    def test_packet_roundtrip_and_blindness(self, tmp_path):
        convs, gt = _fixture()
        items = build_validation_sample(convs, gt, 6, 4, seed=1)
        out = write_packet(items, tmp_path / "packet")
        # items.json must NOT contain heuristic labels (blind)
        items_text = (out / "items.json").read_text()
        assert "heuristic" not in items_text and "failure_score" not in items_text
        # annotations.json skeleton exists with empty labels
        anns = json.loads((out / "annotations.json").read_text())
        assert len(anns) == 10 and all(a["did_fail"] == "" for a in anns)
        # Round-trip restores the key
        restored = items_from_packet(out)
        assert {it.conversation_id for it in restored} == {it.conversation_id for it in items}
        assert sum(it.heuristic_failed for it in restored) == 6


class TestKappa:
    def test_perfect_agreement(self):
        assert cohens_kappa([(True, True)] * 5 + [(False, False)] * 5) == 1.0

    def test_chance_agreement_is_zero(self):
        # One rater says yes half the time independently of the other
        pairs = [(True, True), (True, False), (False, True), (False, False)]
        assert cohens_kappa(pairs) == 0.0

    def test_empty(self):
        assert cohens_kappa([]) == 0.0


class TestAgreement:
    def _items(self):
        convs, gt = _fixture()
        return build_validation_sample(convs, gt, 6, 4, seed=1)

    def test_full_agreement_report(self):
        items = self._items()
        annotations = [
            Annotation(it.conversation_id,
                       "yes" if it.heuristic_failed else "no",
                       it.heuristic_categories)
            for it in items
        ]
        report = compute_agreement(items, annotations)
        assert report["n_labelled"] == 10
        assert report["binary_lenient"]["observed_agreement"] == 1.0
        assert report["binary_lenient"]["cohens_kappa"] == 1.0
        assert report["disagreements"] == []
        assert report["per_category"]["resolution"]["precision"] == 1.0

    def test_partial_counts_as_fail_only_in_lenient(self):
        items = self._items()
        annotations = [
            Annotation(it.conversation_id,
                       "partial" if it.heuristic_failed else "no",
                       it.heuristic_categories)
            for it in items
        ]
        report = compute_agreement(items, annotations)
        assert report["binary_lenient"]["observed_agreement"] == 1.0
        assert report["binary_strict"]["observed_agreement"] < 1.0

    def test_unlabelled_excluded(self):
        items = self._items()
        annotations = [
            {"conversation_id": it.conversation_id, "did_fail": "", "categories": []}
            for it in items[:3]
        ] + [
            {"conversation_id": it.conversation_id,
             "did_fail": "yes" if it.heuristic_failed else "no",
             "categories": it.heuristic_categories}
            for it in items[3:]
        ]
        report = compute_agreement(items, annotations)
        assert report["n_labelled"] == 7
        assert len(report["unlabelled"]) == 3

    def test_disagreements_reported(self):
        items = self._items()
        annotations = [
            Annotation(it.conversation_id, "no", [])  # annotator disagrees with all flags
            for it in items
        ]
        report = compute_agreement(items, annotations)
        assert len(report["disagreements"]) == 6
        assert report["binary_lenient"]["heuristic_precision"] == 0.0
