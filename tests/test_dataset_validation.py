"""Dataset validation stays separate from test-dialogue text."""

import json

from data_layer.validate_dataset import validate


def test_import_validation_keeps_splits_and_review_separate():
    report = validate()
    encoded = json.dumps(report, ensure_ascii=False)
    assert report["manifest"]["status"] == "passed"
    assert report["structural"]["status"] == "passed"
    assert report["structural"]["error_count"] == 0
    assert report["counts"]["train"]["dialogues"] == 1000
    assert report["counts"]["test"]["dialogues"] == 200
    assert report["counts"]["train"]["turns"] == 5681
    assert report["counts"]["test"]["turns"] == 1078
    assert report["split_isolation"]["train_test_id_overlap"] == 0
    assert report["split_isolation"]["dev_count"] == 40
    assert report["split_isolation"]["dev_not_in_train"] == []
    assert report["split_isolation"]["dev_in_test"] == 0
    assert report["retrieval_pool"]["before_validation_exclusions"] == 960
    assert report["retrieval_pool"]["eligible"] == 960
    assert report["retrieval_pool"]["semantic_issues_excluded"] is False
    assert report["retrieval_pool"]["human_review_excluded"] is False
    assert report["human_review"]["expert_approved"] is False
    assert report["human_review"]["human_expert_reviewed"] == 0
    assert report["accepted_schema_values"]["ambiguous_candidates_on_known_service"] > 0
    assert report["test_integrity"]["hash_matches_manifest"] is True
    assert report["test_integrity"]["examples_printed"] is False
    assert report["test_integrity"]["isolated_from_train"] is True
    assert "raw_text" not in encoded
    assert "slots_after_message" not in encoded
