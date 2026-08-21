"""Deterministic synthetic campaigns with known answers; never racing research."""

from apex_labs.campaigns.runner import (
    campaign_specs,
    check_expectations,
    run_all_campaigns,
    run_campaign,
)
from apex_labs.campaigns.references import regenerate_reference_artifacts
from apex_labs.campaigns.synthetic import campaign_paths, materialize, validate_campaign_spec

__all__ = [
    "campaign_paths",
    "campaign_specs",
    "check_expectations",
    "materialize",
    "regenerate_reference_artifacts",
    "run_all_campaigns",
    "run_campaign",
    "validate_campaign_spec",
]
