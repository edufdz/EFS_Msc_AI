"""
FailureClusterer: groups similar failures using text similarity + heuristics.

Two modes:
  - sentence-transformers (if installed): embedding-based DBSCAN
  - fallback: TF-IDF + Agglomerative clustering from sklearn
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

import numpy as np


def _load_trace(trace_file: str) -> Optional[Dict]:
    if not trace_file or not os.path.exists(trace_file):
        return None
    with open(trace_file) as f:
        return json.load(f)


class FailureClusterer:
    """Cluster failures into groups of similar issues."""

    def __init__(self, use_embeddings: bool = False):
        self._use_embeddings = use_embeddings
        self._embedder = None

        if use_embeddings:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
            except ImportError:
                self._use_embeddings = False

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def cluster_failures(self, failures: List[Dict]) -> List[List[Dict]]:
        """Return list of clusters (each cluster is a list of failure dicts)."""
        if len(failures) < 2:
            return [failures] if failures else []

        texts = [self._failure_to_text(f) for f in failures]
        features = [self._extract_heuristic_features(f) for f in failures]

        if self._use_embeddings and self._embedder is not None:
            return self._cluster_with_embeddings(failures, texts, features)
        return self._cluster_with_tfidf(failures, texts, features)

    # ------------------------------------------------------------------
    # Embedding-based clustering
    # ------------------------------------------------------------------

    def _cluster_with_embeddings(
        self,
        failures: List[Dict],
        texts: List[str],
        features: List[Dict],
    ) -> List[List[Dict]]:
        from sklearn.cluster import DBSCAN

        embeddings = self._embedder.encode(texts)
        combined = self._combine(embeddings, features)

        labels = DBSCAN(eps=0.35, min_samples=2, metric="cosine").fit_predict(combined)
        return self._group_by_labels(failures, labels)

    # ------------------------------------------------------------------
    # TF-IDF fallback clustering
    # ------------------------------------------------------------------

    def _cluster_with_tfidf(
        self,
        failures: List[Dict],
        texts: List[str],
        features: List[Dict],
    ) -> List[List[Dict]]:
        from sklearn.cluster import AgglomerativeClustering
        from sklearn.feature_extraction.text import TfidfVectorizer

        vectorizer = TfidfVectorizer(max_features=200, stop_words="english")
        tfidf_matrix = vectorizer.fit_transform(texts).toarray()

        combined = self._combine(tfidf_matrix, features)

        n_clusters = max(2, min(len(failures) // 3, 10))
        labels = AgglomerativeClustering(
            n_clusters=n_clusters,
            metric="cosine",
            linkage="average",
        ).fit_predict(combined)

        return self._group_by_labels(failures, labels)

    # ------------------------------------------------------------------
    # Feature extraction
    # ------------------------------------------------------------------

    def _failure_to_text(self, failure: Dict) -> str:
        parts = [
            f"scenario: {failure.get('scenario', '')}",
            f"failure: {failure.get('failure_reason', '')}",
            f"status: {failure.get('status', '')}",
            f"difficulty: {failure.get('difficulty', '')}",
            f"coverage: {failure.get('coverage_goal', '')}",
        ]
        return " | ".join(parts)

    def _extract_heuristic_features(self, failure: Dict) -> Dict[str, float]:
        reason = (failure.get("failure_reason") or "").lower()
        trace = _load_trace(failure.get("trace_file", ""))

        tools_called: List[str] = []
        if trace:
            for turn in trace.get("turns", []):
                for tc in turn.get("tool_calls", []):
                    tools_called.append(tc.get("tool_name", ""))

        return {
            "is_timeout": float("timeout" in reason or "max turns" in reason),
            "is_service_error": float("unavailable" in reason or "service" in reason),
            "is_agent_error": float("agent error" in reason),
            "turn_count": float(failure.get("total_turns", 0)),
            "tools_called_count": float(len(tools_called)),
            "has_chaos": float(len(failure.get("chaos_events", [])) > 0),
            "difficulty_hard": float(failure.get("difficulty") == "hard"),
            "duration": float(failure.get("duration_sec", 0)),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _combine(self, text_features: np.ndarray, heuristic_features: List[Dict]) -> np.ndarray:
        heuristic_matrix = np.array([
            list(f.values()) for f in heuristic_features
        ])
        # Normalize heuristic columns to 0-1
        maxes = heuristic_matrix.max(axis=0, keepdims=True)
        maxes[maxes == 0] = 1
        heuristic_matrix = heuristic_matrix / maxes

        return np.concatenate([
            text_features * 2,  # weight text similarity higher
            heuristic_matrix,
        ], axis=1)

    @staticmethod
    def _group_by_labels(failures: List[Dict], labels) -> List[List[Dict]]:
        groups: Dict[int, List[Dict]] = defaultdict(list)
        for idx, label in enumerate(labels):
            groups[int(label)].append(failures[idx])
        return list(groups.values())
