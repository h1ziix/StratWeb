"""Deterministic precision/recall evaluation against analyst labels."""

from __future__ import annotations

from .manifest import GoldenCorpusError, manifest_fingerprint
from .models import (
    FindingClassificationMetrics,
    FindingLabelValue,
    GoldenCorpusManifest,
    GoldenEvaluationReport,
    GoldenPredictionSet,
    PredictionValue,
)


class GoldenFindingEvaluator:
    def evaluate(
        self,
        manifest: GoldenCorpusManifest,
        predictions: GoldenPredictionSet,
    ) -> GoldenEvaluationReport:
        fingerprint = manifest_fingerprint(manifest)
        if predictions.manifest_fingerprint != fingerprint:
            raise GoldenCorpusError(
                "Prediction manifest_fingerprint does not match the selected manifest."
            )

        labels = {item.label_id: item for item in manifest.finding_labels}
        predicted = {item.label_id: item for item in predictions.predictions}
        indeterminate = tuple(
            sorted(
                item.label_id
                for item in labels.values()
                if item.value is FindingLabelValue.INDETERMINATE
            )
        )
        determinate = {
            key: item
            for key, item in labels.items()
            if item.value is not FindingLabelValue.INDETERMINATE
        }
        missing = tuple(sorted(set(determinate) - set(predicted)))
        unknown = tuple(sorted(set(predicted) - set(labels)))
        unavailable = tuple(
            sorted(
                key
                for key, item in predicted.items()
                if key in determinate and item.value is PredictionValue.UNAVAILABLE
            )
        )

        true_positive = false_positive = true_negative = false_negative = 0
        for label_id, label in sorted(determinate.items()):
            prediction = predicted.get(label_id)
            if prediction is None or prediction.value is PredictionValue.UNAVAILABLE:
                continue
            expected_present = label.value is FindingLabelValue.PRESENT
            predicted_present = prediction.value is PredictionValue.PRESENT
            if expected_present and predicted_present:
                true_positive += 1
            elif not expected_present and predicted_present:
                false_positive += 1
            elif not expected_present and not predicted_present:
                true_negative += 1
            else:
                false_negative += 1

        sample_size = true_positive + false_positive + true_negative + false_negative
        precision = _ratio(true_positive, true_positive + false_positive)
        recall = _ratio(true_positive, true_positive + false_negative)
        false_positive_rate = _ratio(false_positive, false_positive + true_negative)
        f1 = (
            None
            if precision is None or recall is None
            else _ratio(2 * precision * recall, precision + recall)
        )
        limitations: list[str] = []
        if indeterminate:
            limitations.append("indeterminate_labels_excluded")
        if missing:
            limitations.append("predictions_missing_for_determinate_labels")
        if unavailable:
            limitations.append("predictions_unavailable_for_determinate_labels")
        if unknown:
            limitations.append("predictions_reference_unknown_labels")
        if sample_size == 0:
            limitations.append("no_evaluable_labels")
        complete = not missing and not unavailable and not unknown and sample_size > 0
        return GoldenEvaluationReport(
            manifest_fingerprint=fingerprint,
            algorithm_version=predictions.algorithm_version,
            complete=complete,
            metrics=FindingClassificationMetrics(
                sample_size=sample_size,
                true_positive=true_positive,
                false_positive=false_positive,
                true_negative=true_negative,
                false_negative=false_negative,
                precision=precision,
                recall=recall,
                false_positive_rate=false_positive_rate,
                f1=f1,
            ),
            indeterminate_label_ids=indeterminate,
            unavailable_prediction_ids=unavailable,
            missing_prediction_ids=missing,
            unknown_prediction_ids=unknown,
            limitations=tuple(limitations),
        )


def _ratio(numerator: float | int, denominator: float | int) -> float | None:
    return None if denominator == 0 else float(numerator / denominator)


__all__ = ["GoldenFindingEvaluator"]
