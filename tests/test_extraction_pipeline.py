"""
tests/test_extraction_pipeline.py
==================================
Day 19: Pytest Suite & Portfolio Benchmark Metrics for JobTracker.

Evaluates the end-to-end email extraction pipeline against the 73-sample
evaluation dataset in `tests/eval_data/` and annotations in `tests/ground_truth.json`.

Target Portfolio Metrics (SYSTEM_DESIGN.md & BUILD_TIMELINE.md):
- Stage Classification Accuracy: >= 90%
- Relevance Gate Precision:       >= 95%
- Entity Extraction Precision:   >= 93%
- Adversarial Resilience:        >= 85%
"""

import glob
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import pytest

from worker.agent_state import AgentState, ApplicationEventType
from worker.gmail_filter import check_email_relevance
from worker.graph_agent import node_extract_event

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = PROJECT_ROOT / "tests" / "eval_data"
GROUND_TRUTH_PATH = PROJECT_ROOT / "tests" / "ground_truth.json"

EVENT_CANONICAL_MAP = {
    "APPLICATION_CONFIRMATION": "APPLICATION_RECEIVED",
    "INTERVIEW_INVITE": "INTERVIEW_INVITE",
    "OA_INVITE": "OA_RECEIVED",
    "REJECTION": "REJECTED",
    "OFFER": "OFFER",
}


def load_dataset():
    """Loads all eval files and corresponding ground truth records."""
    assert GROUND_TRUTH_PATH.exists(), f"Ground truth missing at {GROUND_TRUTH_PATH}"
    with open(GROUND_TRUTH_PATH, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    files = sorted(glob.glob(str(EVAL_DIR / "*.txt")))
    assert len(files) >= 65, f"Expected at least 65 eval files, found {len(files)}"
    return files, ground_truth


# ==============================================================================
# 1. Dataset Integrity & Annotation Validation Tests
# ==============================================================================

def test_evaluation_dataset_integrity():
    """Validates 1:1 correspondence between tests/eval_data/*.txt and tests/ground_truth.json."""
    files, ground_truth = load_dataset()
    basenames = [os.path.basename(f) for f in files]

    # Exactly match keys
    assert set(basenames) == set(ground_truth.keys()), (
        f"Mismatch: {set(basenames) ^ set(ground_truth.keys())}"
    )

    # Validate categories present
    categories = {v.get("category") for v in ground_truth.values()}
    assert "confirmation" in categories
    assert "interview" in categories
    assert "oa" in categories
    assert "rejection" in categories
    assert "irrelevant" in categories
    assert "adversarial" in categories


def test_adversarial_dataset_distribution():
    """Ensures at least 15 high-capacity adversarial samples are present."""
    _, ground_truth = load_dataset()
    adversarial_entries = [
        k for k, v in ground_truth.items() if v.get("category") == "adversarial"
    ]
    assert len(adversarial_entries) >= 15, f"Expected >=15 adversarial files, found {len(adversarial_entries)}"


# ==============================================================================
# 2. Pipeline Extraction Benchmark Test
# ==============================================================================

@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_pipeline_benchmark_metrics():
    """
    Executes all 73 samples through the Relevance Gate and Entity Extractor,
    computing Stage Accuracy, Relevance Precision, Company Precision, and Adversarial Resilience.
    """
    files, ground_truth = load_dataset()

    stats = {
        "total": len(files),
        "relevant_true": 0,
        "irrelevant_true": 0,
        "gate_tp": 0,
        "gate_tn": 0,
        "gate_fp": 0,
        "gate_fn": 0,
        "stage_matches": 0,
        "stage_total": 0,
        "company_matches": 0,
        "company_total": 0,
        "adversarial_total": 0,
        "adversarial_correct": 0,
    }

    for fpath in files:
        fname = os.path.basename(fpath)
        gt = ground_truth[fname]
        is_rel_expected = gt["is_relevant"]
        expected_raw = gt.get("expected_event")
        expected_canonical = EVENT_CANONICAL_MAP.get(expected_raw)
        expected_company = gt.get("expected_company")
        category = gt.get("category")

        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        lines = [l.strip() for l in content.splitlines() if l.strip()]
        subj = next((l[8:].strip() for l in lines if l.startswith("Subject:")), "")
        sender = next((l[5:].strip() for l in lines if l.startswith("From:")), "")
        body = "\n".join(
            [l for l in lines if not any(l.startswith(h) for h in ["From:", "To:", "Subject:", "Date:"])]
        )

        # Node 0: Relevance Gate
        rel_dec = check_email_relevance(subject=subj, sender=sender, body_text=body)

        if is_rel_expected:
            stats["relevant_true"] += 1
            if rel_dec.is_relevant:
                stats["gate_tp"] += 1
            else:
                stats["gate_fn"] += 1
        else:
            stats["irrelevant_true"] += 1
            if not rel_dec.is_relevant:
                stats["gate_tn"] += 1
            else:
                stats["gate_fp"] += 1

        if category == "adversarial":
            stats["adversarial_total"] += 1
            if rel_dec.is_relevant == is_rel_expected:
                stats["adversarial_correct"] += 1

        # Node 1: Entity Extractor
        mock_state: AgentState = {
            "raw_email_text": body,
            "email_received_at": datetime.now(timezone.utc),
            "sender": sender,
            "subject": subj,
            "is_relevant": rel_dec.is_relevant,
            "relevance_category": rel_dec.category,
            "relevance_reason": rel_dec.reason,
            "parsed_event": None,
            "validation_errors": [],
            "retry_count": 0,
            "matched_application_id": None,
            "resolution_confidence": "NONE",
            "resolution_note": "",
            "is_new_application": False,
            "candidate_apps": None,
            "current_status": None,
            "target_status": None,
            "transition_note": None,
            "status_changed": False,
            "committed": False,
            "db_session": None,
            "dead_letter_reason": None,
            "execution_path": [],
        }

        extract_res = node_extract_event(mock_state)
        parsed = extract_res.get("parsed_event", {})
        extracted_event = parsed.get("event_type")
        extracted_company = parsed.get("company_raw")

        if is_rel_expected:
            stats["stage_total"] += 1
            if extracted_event == expected_canonical:
                stats["stage_matches"] += 1

            if expected_company:
                stats["company_total"] += 1
                if expected_company.lower() in (extracted_company or "").lower() or (
                    extracted_company or ""
                ).lower() in expected_company.lower():
                    stats["company_matches"] += 1

    # Metrics computation
    precision = stats["gate_tp"] / (stats["gate_tp"] + stats["gate_fp"]) if (stats["gate_tp"] + stats["gate_fp"]) else 0
    recall = stats["gate_tp"] / (stats["gate_tp"] + stats["gate_fn"]) if (stats["gate_tp"] + stats["gate_fn"]) else 0
    stage_acc = stats["stage_matches"] / stats["stage_total"] if stats["stage_total"] else 0
    company_prec = stats["company_matches"] / stats["company_total"] if stats["company_total"] else 0
    adv_resilience = (
        stats["adversarial_correct"] / stats["adversarial_total"]
        if stats["adversarial_total"]
        else 0
    )

    print("\n" + "=" * 65)
    print(" DAY 19: CAREER PIPELINE BENCHMARK METRICS SUMMARY")
    print("=" * 65)
    print(f"Total Evaluated Corpus:        {stats['total']} samples")
    print(f"Relevance Gate Precision:      {precision * 100:.2f}% (Target: >= 95.0%)")
    print(f"Relevance Gate Recall:         {recall * 100:.2f}%")
    print(f"Stage Classification Accuracy: {stage_acc * 100:.2f}% (Target: >= 90.0%)")
    print(f"Company Extraction Precision:  {company_prec * 100:.2f}% (Target: >= 93.0%)")
    print(f"Adversarial Defense Rate:      {adv_resilience * 100:.2f}% (Target: >= 85.0%)")
    print("=" * 65)

    # Threshold Assertions
    assert precision >= 0.95, f"Relevance Gate Precision {precision*100:.1f}% below 95% threshold"
    assert stage_acc >= 0.90, f"Stage Accuracy {stage_acc*100:.1f}% below 90% threshold"
    assert company_prec >= 0.93, f"Company Extraction Precision {company_prec*100:.1f}% below 93% threshold"
    assert adv_resilience >= 0.85, f"Adversarial Resilience {adv_resilience*100:.1f}% below 85% threshold"
