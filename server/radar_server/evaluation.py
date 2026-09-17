"""Score explicit labels; missing review and undefined metrics cannot pass."""
import argparse
import json
from pathlib import Path

from pydantic import Field, ValidationError, model_validator

from .analysis_models import StrictModel


class Label(StrictModel):
    topic_id: str = Field(min_length=1, max_length=128)
    interested: bool
    claims_supported: bool | None = None


class Prediction(StrictModel):
    topic_id: str = Field(min_length=1, max_length=128)
    is_candidate: bool


class EvaluationData(StrictModel):
    labels: list[Label] = Field(max_length=10000)
    predictions: list[Prediction] = Field(max_length=10000)

    @model_validator(mode="after")
    def unique_ids(self):
        for values in (self.labels, self.predictions):
            if len({v.topic_id for v in values}) != len(values):
                raise ValueError("Duplicate topic labels or predictions")
        return self


def evaluate(data: EvaluationData):
    labels = {v.topic_id: v for v in data.labels}
    predictions = {v.topic_id: v for v in data.predictions}
    tp = sum(label.interested and predictions.get(key) is not None and predictions[key].is_candidate for key, label in labels.items())
    fp = sum(not label.interested and predictions.get(key) is not None and predictions[key].is_candidate for key, label in labels.items())
    fn = sum(label.interested and (predictions.get(key) is None or not predictions[key].is_candidate) for key, label in labels.items())
    recall = tp / (tp + fn) if tp + fn else None
    precision = tp / (tp + fp) if tp + fp else None
    unlabelled = len(set(predictions) - set(labels))
    unreviewed = sum(key not in labels or labels[key].claims_supported is None for key in predictions)
    unsupported = sum(key in labels and labels[key].claims_supported is False for key in predictions)
    return {
        "labelled_topics": len(labels), "predicted_topics": len(predictions),
        "true_positive": tp, "false_positive": fp, "false_negative": fn,
        "interest_recall": recall, "candidate_precision": precision,
        "unlabelled_predictions": unlabelled, "unreviewed_claims": unreviewed,
        "unsupported_topics": unsupported,
        "quality_pass": len(labels) >= 50 and recall is not None and recall >= .9
            and precision is not None and precision >= .8 and unlabelled == 0
            and unreviewed == 0 and unsupported == 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate labelled M3 topics")
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    try:
        data = EvaluationData.model_validate_json(args.input.read_bytes())
    except (OSError, ValidationError):
        print("Invalid evaluation input")
        raise SystemExit(1) from None
    report = evaluate(data)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["quality_pass"] else 2)


if __name__ == "__main__":
    main()
