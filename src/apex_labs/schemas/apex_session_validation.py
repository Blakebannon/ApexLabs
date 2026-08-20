"""Runtime validators for Apex customer bundles and research collection metadata."""

from __future__ import annotations

from typing import Any

from apex_labs.io import validate_contract_path
from apex_labs.schemas import versions
from apex_labs.schemas.validation import (
    _boolean,
    _enum,
    _id,
    _integer,
    _keys,
    _list,
    _number,
    _object,
    _sha,
    _string,
    _strings,
    _timestamp,
    _version,
)


def validate_apex_session_manifest(value: Any) -> dict[str, Any]:
    """Validate the product-owned apex-session-export/1.0.0 inventory."""
    obj = _object(value, "$")
    if obj.get("schema") != versions.APEX_SESSION_EXPORT:
        from apex_labs.errors import UnsupportedVersionError

        raise UnsupportedVersionError(
            f"$.schema: expected {versions.APEX_SESSION_EXPORT!r}, received {obj.get('schema')!r}"
        )
    _keys(
        obj,
        "$",
        required={"schema", "productVersion", "exportCreatedUtc", "privacyMode", "sources", "files"},
    )
    _string(obj["productVersion"], "$.productVersion")
    _timestamp(obj["exportCreatedUtc"], "$.exportCreatedUtc")
    _enum(obj["privacyMode"], {"Anonymized", "Synthetic"}, "$.privacyMode")
    sources = _object(obj["sources"], "$.sources")
    _keys(
        sources,
        "$.sources",
        required={
            "lapsWithTelemetry", "lapsWithRecordedFacts", "sessionIdentityRecorded",
            "overallDebriefIncluded", "findingCount", "localAiEnhancement",
            "localAiExplanationCount",
        },
    )
    for name in ("lapsWithTelemetry", "lapsWithRecordedFacts", "findingCount", "localAiExplanationCount"):
        _integer(sources[name], f"$.sources.{name}", minimum=0)
    _boolean(sources["sessionIdentityRecorded"], "$.sources.sessionIdentityRecorded")
    _boolean(sources["overallDebriefIncluded"], "$.sources.overallDebriefIncluded")
    _enum(sources["localAiEnhancement"], {"included", "not_included"}, "$.sources.localAiEnhancement")
    files = _list(obj["files"], "$.files", nonempty=True)
    seen: set[str] = set()
    for index, item in enumerate(files):
        path = f"$.files[{index}]"
        entry = _object(item, path)
        _keys(entry, path, required={"name", "sizeBytes", "sha256"})
        name = validate_contract_path(_string(entry["name"], f"{path}.name"))
        folded = name.replace("\\", "/").casefold()
        if folded in seen:
            from apex_labs.errors import ContractValidationError

            raise ContractValidationError(f"{path}.name: duplicate manifest entry under portable path semantics")
        seen.add(folded)
        _integer(entry["sizeBytes"], f"{path}.sizeBytes", minimum=0)
        _sha(entry["sha256"], f"{path}.sha256")
    return obj


def validate_collection_record(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.COLLECTION_RECORD)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "collection_record_id", "version", "dataset_id", "synthetic",
            "collection_classification", "participant", "authority", "privacy", "storage",
            "source_bundle", "session_identity", "session_condition", "protocol", "blocks",
            "lap_assignments", "deviations", "coaching", "operator_notes", "created_at",
        },
    )
    _id(obj["collection_record_id"], "$.collection_record_id")
    _string(obj["version"], "$.version")
    _id(obj["dataset_id"], "$.dataset_id")
    synthetic = _boolean(obj["synthetic"], "$.synthetic")
    classification = _enum(
        obj["collection_classification"], {"observational", "experimental"},
        "$.collection_classification",
    )
    participant = _object(obj["participant"], "$.participant")
    _keys(participant, "$.participant", required={"pseudonymous_participant_id", "external_identity_map_reference", "direct_identity_in_record"})
    _id(participant["pseudonymous_participant_id"], "$.participant.pseudonymous_participant_id")
    if participant["external_identity_map_reference"] is not None:
        _id(participant["external_identity_map_reference"], "$.participant.external_identity_map_reference")
    if _boolean(participant["direct_identity_in_record"], "$.participant.direct_identity_in_record"):
        from apex_labs.errors import ContractValidationError

        raise ContractValidationError("$.participant.direct_identity_in_record: must be false")
    authority = _object(obj["authority"], "$.authority")
    _keys(authority, "$.authority", required={"declaration", "recorded_at"})
    _string(authority["declaration"], "$.authority.declaration")
    _timestamp(authority["recorded_at"], "$.authority.recorded_at")
    privacy = _object(obj["privacy"], "$.privacy")
    _keys(privacy, "$.privacy", required={"classification", "pseudonymized", "direct_identifiers_present"})
    privacy_class = _enum(privacy["classification"], {"synthetic", "private", "sanitized"}, "$.privacy.classification")
    pseudonymized = _boolean(privacy["pseudonymized"], "$.privacy.pseudonymized")
    direct = _boolean(privacy["direct_identifiers_present"], "$.privacy.direct_identifiers_present")
    if synthetic != (privacy_class == "synthetic"):
        from apex_labs.errors import ContractValidationError

        raise ContractValidationError("$.privacy: synthetic must agree with privacy classification")
    if not synthetic and (not pseudonymized or direct):
        from apex_labs.errors import ContractValidationError

        raise ContractValidationError("$.privacy: real collections require pseudonymization and no direct identifiers")
    storage = _object(obj["storage"], "$.storage")
    _keys(storage, "$.storage", required={"source_bundle_location", "retention_declaration"})
    if storage["source_bundle_location"] != "external_untracked":
        from apex_labs.errors import ContractValidationError

        raise ContractValidationError("$.storage.source_bundle_location: must be 'external_untracked'")
    _string(storage["retention_declaration"], "$.storage.retention_declaration")
    bundle = _object(obj["source_bundle"], "$.source_bundle")
    _keys(bundle, "$.source_bundle", required={"sha256", "schema_version"})
    _sha(bundle["sha256"], "$.source_bundle.sha256")
    if bundle["schema_version"] != versions.APEX_SESSION_EXPORT:
        from apex_labs.errors import UnsupportedVersionError

        raise UnsupportedVersionError(f"$.source_bundle.schema_version: unsupported {bundle['schema_version']!r}")
    identity = _object(obj["session_identity"], "$.session_identity")
    _keys(identity, "$.session_identity", required={"simulator", "car", "track", "layout", "confirmation_method"})
    for name in ("simulator", "car", "track", "confirmation_method"):
        _string(identity[name], f"$.session_identity.{name}")
    if identity["layout"] is not None:
        _string(identity["layout"], "$.session_identity.layout")
    if obj["session_condition"] is not None:
        _string(obj["session_condition"], "$.session_condition")
    protocol = obj["protocol"]
    if protocol is not None:
        protocol = _object(protocol, "$.protocol")
        _keys(protocol, "$.protocol", required={"freeze_id", "freeze_sha256", "experiment_id", "experiment_version", "schedule_id", "schedule_sha256", "schedule_assignment_id"})
        for name in ("freeze_id", "experiment_id", "schedule_id", "schedule_assignment_id"):
            _id(protocol[name], f"$.protocol.{name}")
        _string(protocol["experiment_version"], "$.protocol.experiment_version")
        _sha(protocol["freeze_sha256"], "$.protocol.freeze_sha256")
        _sha(protocol["schedule_sha256"], "$.protocol.schedule_sha256")
    blocks = _list(obj["blocks"], "$.blocks")
    block_ids: set[str] = set()
    for index, item in enumerate(blocks):
        path = f"$.blocks[{index}]"
        block = _object(item, path)
        _keys(block, path, required={"block_id", "condition_id", "start_lap", "end_lap"})
        block_id = _id(block["block_id"], f"{path}.block_id")
        if block_id in block_ids:
            from apex_labs.errors import ContractValidationError

            raise ContractValidationError(f"{path}.block_id: duplicate block identity")
        block_ids.add(block_id)
        _id(block["condition_id"], f"{path}.condition_id")
        start = _integer(block["start_lap"], f"{path}.start_lap", minimum=0)
        end = _integer(block["end_lap"], f"{path}.end_lap", minimum=0)
        if end < start:
            from apex_labs.errors import ContractValidationError

            raise ContractValidationError(f"{path}: end_lap must not precede start_lap")
    assignments = _list(obj["lap_assignments"], "$.lap_assignments")
    assigned_laps: set[int] = set()
    for index, item in enumerate(assignments):
        path = f"$.lap_assignments[{index}]"
        assignment = _object(item, path)
        _keys(assignment, path, required={"lap_number", "block_id"})
        lap = _integer(assignment["lap_number"], f"{path}.lap_number", minimum=0)
        if lap in assigned_laps:
            from apex_labs.errors import ContractValidationError

            raise ContractValidationError(f"{path}.lap_number: duplicate lap assignment")
        assigned_laps.add(lap)
        if _id(assignment["block_id"], f"{path}.block_id") not in block_ids:
            from apex_labs.errors import ContractValidationError

            raise ContractValidationError(f"{path}.block_id: does not resolve to a declared block")
    _strings(obj["deviations"], "$.deviations")
    coaching = _object(obj["coaching"], "$.coaching")
    _keys(coaching, "$.coaching", required={"state", "notes"})
    _enum(coaching["state"], {"enabled", "disabled", "mixed", "unknown"}, "$.coaching.state")
    _string(coaching["notes"], "$.coaching.notes", nonempty=False)
    _strings(obj["operator_notes"], "$.operator_notes")
    _timestamp(obj["created_at"], "$.created_at")
    if classification == "observational" and (protocol is not None or blocks or assignments):
        from apex_labs.errors import ContractValidationError

        raise ContractValidationError("$: observational collection cannot claim protocol, blocks, or assignments")
    if classification == "experimental" and (protocol is None or not blocks or not assignments):
        from apex_labs.errors import ContractValidationError

        raise ContractValidationError("$: experimental collection requires a frozen protocol, blocks, and lap assignments")
    return obj


def validate_product_annotations(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.PRODUCT_ANNOTATIONS)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "source_schema_version", "source_file_sha256", "classification",
            "scientific_evidence", "training_labels", "ground_truth", "product_recommendations",
            "scientific_promotion_allowed", "annotations",
        },
    )
    if obj["source_schema_version"] != versions.APEX_SESSION_EXPORT:
        from apex_labs.errors import UnsupportedVersionError

        raise UnsupportedVersionError("$.source_schema_version: unsupported source contract")
    _sha(obj["source_file_sha256"], "$.source_file_sha256")
    if obj["classification"] != "product_generated_annotations_not_scientific_evidence":
        from apex_labs.errors import ContractValidationError

        raise ContractValidationError("$.classification: product output must remain non-scientific annotation")
    for name in ("scientific_evidence", "training_labels", "ground_truth", "product_recommendations", "scientific_promotion_allowed"):
        if _boolean(obj[name], f"$.{name}"):
            from apex_labs.errors import ContractValidationError

            raise ContractValidationError(f"$.{name}: must be false")
    _list(obj["annotations"], "$.annotations")
    return obj


def validate_adapter_conformance(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.ADAPTER_CONFORMANCE)
    _keys(obj, "$", required={"schema_version", "source_schema_version", "adapter", "available", "aggregated", "product_derived_annotations", "ambiguous", "unavailable", "limitations"})
    if obj["source_schema_version"] != versions.APEX_SESSION_EXPORT:
        from apex_labs.errors import UnsupportedVersionError

        raise UnsupportedVersionError("$.source_schema_version: unsupported customer bundle")
    adapter = _object(obj["adapter"], "$.adapter")
    _keys(adapter, "$.adapter", required={"id", "version"})
    if adapter != {"id": "apex-session-export", "version": "1.0.0"}:
        from apex_labs.errors import ContractValidationError

        raise ContractValidationError("$.adapter: unsupported adapter identity")
    _strings(obj["available"], "$.available", nonempty=True)
    aggregated = _object(obj["aggregated"], "$.aggregated")
    _keys(aggregated, "$.aggregated", required={"brake", "throttle", "steering_angle", "speed"})
    for name in aggregated:
        _string(aggregated[name], f"$.aggregated.{name}")
    _strings(obj["product_derived_annotations"], "$.product_derived_annotations", nonempty=True)
    ambiguous = _object(obj["ambiguous"], "$.ambiguous")
    _keys(ambiguous, "$.ambiguous", required={"lap_fraction_denominator", "layout_identity"})
    for name in ambiguous:
        _string(ambiguous[name], f"$.ambiguous.{name}")
    _strings(obj["unavailable"], "$.unavailable", nonempty=True)
    _strings(obj["limitations"], "$.limitations", nonempty=True)
    return obj


def validate_research_export_manifest(value: Any) -> dict[str, Any]:
    """Validate the implementation-neutral future Research-build handoff contract."""
    obj = _object(value, "$")
    _version(obj, versions.APEX_RESEARCH_EXPORT)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "session", "timing", "channels", "events", "collection", "privacy", "storage",
            "files", "build_boundary",
        },
    )
    session = _object(obj["session"], "$.session")
    _keys(session, "$.session", required={"session_id", "participant_pseudonym", "simulator", "car", "track", "start_utc", "end_utc"})
    _id(session["session_id"], "$.session.session_id")
    _id(session["participant_pseudonym"], "$.session.participant_pseudonym")
    for name in ("simulator", "car", "track"):
        identity = _object(session[name], f"$.session.{name}")
        required = {"id", "version"} if name == "simulator" else {"id"} if name == "car" else {"id", "layout"}
        _keys(identity, f"$.session.{name}", required=required)
        for field in required:
            _string(identity[field], f"$.session.{name}.{field}")
    _timestamp(session["start_utc"], "$.session.start_utc")
    _timestamp(session["end_utc"], "$.session.end_utc")
    timing = _object(obj["timing"], "$.timing")
    timing_booleans = {"timestamped_samples", "utc_session_timing", "utc_lap_timing", "lap_elapsed_time", "lap_distance", "gaps_dropped_frames_and_backpressure_recorded"}
    _keys(timing, "$.timing", required=timing_booleans | {"source_clock", "nominal_frequency_hz", "resolution_seconds", "reset_behavior"})
    for name in timing_booleans:
        if _boolean(timing[name], f"$.timing.{name}") is not True:
            from apex_labs.errors import ContractValidationError

            raise ContractValidationError(f"$.timing.{name}: Research export requires this timing capability")
    for name in ("source_clock", "reset_behavior"):
        _string(timing[name], f"$.timing.{name}")
    for name in ("nominal_frequency_hz", "resolution_seconds"):
        if timing[name] is not None and _number(timing[name], f"$.timing.{name}") <= 0:
            from apex_labs.errors import ContractValidationError

            raise ContractValidationError(f"$.timing.{name}: must be positive when available")
    channels = _list(obj["channels"], "$.channels", nonempty=True)
    seen: set[str] = set()
    for index, item in enumerate(channels):
        path = f"$.channels[{index}]"
        channel = _object(item, path)
        _keys(channel, path, required={"name", "availability", "provenance", "unit", "axis_and_sign", "missing_value"})
        name = _id(channel["name"], f"{path}.name")
        if name in seen:
            from apex_labs.errors import ContractValidationError

            raise ContractValidationError(f"{path}.name: duplicate channel")
        seen.add(name)
        availability = _enum(channel["availability"], {"available", "unavailable"}, f"{path}.availability")
        provenance = _enum(channel["provenance"], {"measured", "derived", "estimated", "unavailable"}, f"{path}.provenance")
        for field in ("unit", "axis_and_sign", "missing_value"):
            if channel[field] is not None:
                _string(channel[field], f"{path}.{field}")
        if (availability == "unavailable") != (provenance == "unavailable"):
            from apex_labs.errors import ContractValidationError

            raise ContractValidationError(f"{path}: availability and provenance must agree")
    required_channels = {
        "timestamp", "brake", "throttle", "steering_angle", "speed", "gear", "rpm",
        "longitudinal_acceleration", "lateral_acceleration", "yaw_rate", "wheel_state",
        "tire_state", "fuel", "setup", "assists", "damage", "flags", "weather",
        "track_conditions",
    }
    if seen != required_channels:
        from apex_labs.errors import ContractValidationError

        raise ContractValidationError(f"$.channels: must declare every required capability; missing={sorted(required_channels - seen)}, extra={sorted(seen - required_channels)}")
    events = _object(obj["events"], "$.events")
    event_fields = {"incidents", "pit_transitions", "lap_validity", "session_state", "coaching_cue_authorization_and_delivery_receipts", "experimental_block_and_condition_markers"}
    _keys(events, "$.events", required=event_fields)
    for name in event_fields:
        _boolean(events[name], f"$.events.{name}")
    collection = _object(obj["collection"], "$.collection")
    _keys(collection, "$.collection", required={"protocol_identity", "configuration_setup_hash", "coaching_disabled_research_mode"})
    _id(collection["protocol_identity"], "$.collection.protocol_identity")
    _sha(collection["configuration_setup_hash"], "$.collection.configuration_setup_hash")
    if _boolean(collection["coaching_disabled_research_mode"], "$.collection.coaching_disabled_research_mode") is not True:
        from apex_labs.errors import ContractValidationError

        raise ContractValidationError("$.collection.coaching_disabled_research_mode: Research build must support coaching-disabled capture")
    privacy = _object(obj["privacy"], "$.privacy")
    _keys(privacy, "$.privacy", required={"classification", "direct_identifiers_present", "pseudonymization_supported"})
    _enum(privacy["classification"], {"synthetic", "private", "sanitized"}, "$.privacy.classification")
    if _boolean(privacy["direct_identifiers_present"], "$.privacy.direct_identifiers_present"):
        from apex_labs.errors import ContractValidationError

        raise ContractValidationError("$.privacy.direct_identifiers_present: must be false")
    _boolean(privacy["pseudonymization_supported"], "$.privacy.pseudonymization_supported")
    storage = _object(obj["storage"], "$.storage")
    _keys(storage, "$.storage", required={"local_only", "retention_declaration", "complete_marker_required", "truncation_and_corruption_behavior"})
    if _boolean(storage["local_only"], "$.storage.local_only") is not True or _boolean(storage["complete_marker_required"], "$.storage.complete_marker_required") is not True:
        from apex_labs.errors import ContractValidationError

        raise ContractValidationError("$.storage: research export must be local-only and require a completion marker")
    _string(storage["retention_declaration"], "$.storage.retention_declaration")
    _string(storage["truncation_and_corruption_behavior"], "$.storage.truncation_and_corruption_behavior")
    files = _list(obj["files"], "$.files", nonempty=True)
    for index, item in enumerate(files):
        path = f"$.files[{index}]"
        file_entry = _object(item, path)
        _keys(file_entry, path, required={"path", "size_bytes", "sha256", "role"})
        validate_contract_path(_string(file_entry["path"], f"{path}.path"))
        _integer(file_entry["size_bytes"], f"{path}.size_bytes", minimum=0)
        _sha(file_entry["sha256"], f"{path}.sha256")
        _string(file_entry["role"], f"{path}.role")
    boundary = _object(obj["build_boundary"], "$.build_boundary")
    required_true = {
        "shared_codebase", "isolated_research_capture_module", "research_build_capability",
        "production_capture_proven_absent", "local_only_recording", "bounded_streaming_to_disk",
        "disk_space_preflight", "low_disk_fail_safe", "configurable_output_location",
        "explicit_activation", "visible_recording_state",
    }
    required_false = {"public_research_ui", "production_high_resolution_artifacts", "automatic_upload"}
    _keys(boundary, "$.build_boundary", required=required_true | required_false)
    for name in required_true:
        if _boolean(boundary[name], f"$.build_boundary.{name}") is not True:
            from apex_labs.errors import ContractValidationError

            raise ContractValidationError(f"$.build_boundary.{name}: must be true")
    for name in required_false:
        if _boolean(boundary[name], f"$.build_boundary.{name}") is not False:
            from apex_labs.errors import ContractValidationError

            raise ContractValidationError(f"$.build_boundary.{name}: must be false")
    return obj
