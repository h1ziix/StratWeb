"""Parser-independent domain models with cycle-safe lazy public exports."""

from typing import Any

__all__ = ["AnalysisFinding", "AnalysisRun", "DemoFile", "EvidenceReference", "Match"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from stratweb.domain import models

        return getattr(models, name)
    raise AttributeError(name)
