"""Regression cases generated from agent traces."""

from wiicon5.regression.cases import RegressionCase, case_from_trace, load_cases, run_regression_cases
from wiicon5.regression.replay import (
    RegressionCaseReplayResult,
    RegressionReplayResult,
    has_successful_replay,
    run_regression_replay,
    save_replay_result,
)

__all__ = [
    "RegressionCase",
    "RegressionCaseReplayResult",
    "RegressionReplayResult",
    "case_from_trace",
    "has_successful_replay",
    "load_cases",
    "run_regression_cases",
    "run_regression_replay",
    "save_replay_result",
]
