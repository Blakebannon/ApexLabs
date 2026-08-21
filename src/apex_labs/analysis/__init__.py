"""Descriptive-only analysis runs; no inferential statistics exist in v1."""

from apex_labs.analysis.descriptive import summarize
from apex_labs.analysis.runner import run_analysis, verify_analysis_run

__all__ = ["run_analysis", "summarize", "verify_analysis_run"]
