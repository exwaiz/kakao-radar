import pytest
from pydantic import ValidationError

from radar_server.evaluation import EvaluationData, evaluate


def dataset(n=50):
    return {"labels": [{"topic_id": str(i), "interested": i % 2 == 0, "claims_supported": True} for i in range(n)],
            "predictions": [{"topic_id": str(i), "is_candidate": i % 2 == 0} for i in range(n)]}


def test_metrics_for_a_fully_reviewed_labelled_sample():
    result = evaluate(EvaluationData.model_validate(dataset()))
    assert result["interest_recall"] == 1 and result["candidate_precision"] == 1
    assert result["quality_pass"] is True


def test_fewer_than_50_labels_does_not_pass():
    assert not evaluate(EvaluationData.model_validate(dataset(49)))["quality_pass"]


def test_missing_predictions_count_as_missed_interests():
    data = dataset()
    data["predictions"] = data["predictions"][10:]
    result = evaluate(EvaluationData.model_validate(data))
    assert result["interest_recall"] == .8 and result["false_negative"] == 5
    assert not result["quality_pass"]


def test_unsupported_or_unreviewed_claims_block_quality_pass():
    for value in (False, None):
        data = dataset()
        data["labels"][0]["claims_supported"] = value
        assert not evaluate(EvaluationData.model_validate(data))["quality_pass"]


def test_empty_denominators_are_null_and_do_not_pass():
    result = evaluate(EvaluationData(labels=[], predictions=[]))
    assert result["interest_recall"] is None and result["candidate_precision"] is None
    assert not result["quality_pass"]


def test_unlabelled_predictions_and_duplicate_labels_are_detected():
    data = dataset()
    data["predictions"].append({"topic_id": "unlabelled", "is_candidate": True})
    assert not evaluate(EvaluationData.model_validate(data))["quality_pass"]
    data["labels"].append(data["labels"][0])
    with pytest.raises(ValidationError):
        EvaluationData.model_validate(data)
