"""Cross-repository conformance for the synchronized Research Recorder shape.

The product recorder and Apex Labs pin the same sample-column list by exact equality, and
nothing in the versioned profile records that list. These tests use a bundle in exactly the
shape the Apex Sim Coach recorder emits, and drive it through Labs validation, collection
binding and ingestion, so a one-sided column change fails here rather than during a live
rehearsal.

No live simulator, and no telemetry values from a real driver, are involved.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from _support import ROOT

from apex_labs.errors import ContractValidationError, IntegrityError
from apex_labs.ingestion.apex_research import (
    BOOLEAN_COLUMNS,
    CHANNEL_COLUMNS,
    INTEGER_COLUMNS,
    RETAINED_SOURCE_COLUMNS,
    SAMPLE_HEADERS,
    _enum_dictionaries,
    _off_track_values,
    audit_research_bundle,
    ingest_research_bundle,
    inspect_research_bundle,
    validate_research_bundle,
)
from apex_labs.io import canonical_json_bytes, read_json
from apex_labs.provenance import sha256_bytes

from recorder_bundle import RECORDER_COLUMNS, build_recorder_bundle, collection_record, rebind


class SampleColumnContractTests(unittest.TestCase):
    """The two repositories must agree on the sample shape, exactly and in order."""

    def test_labs_headers_match_the_recorder_column_list_exactly(self) -> None:
        self.assertEqual(SAMPLE_HEADERS, RECORDER_COLUMNS)

    def test_column_names_are_unique_and_ordered_as_declared(self) -> None:
        self.assertEqual(len(SAMPLE_HEADERS), len(set(SAMPLE_HEADERS)))
        self.assertEqual(SAMPLE_HEADERS[0], "capture_sequence")
        self.assertEqual(SAMPLE_HEADERS[-1], "read_error_count")

    def test_every_typed_column_exists(self) -> None:
        for column in INTEGER_COLUMNS | BOOLEAN_COLUMNS:
            with self.subTest(column=column):
                self.assertIn(column, SAMPLE_HEADERS)

    def test_every_channel_column_exists_and_no_channel_claims_another_channels_column(self) -> None:
        seen: dict[str, str] = {}
        for channel, columns in CHANNEL_COLUMNS.items():
            self.assertIsInstance(columns, tuple, f"{channel} columns must be a tuple")
            for column in columns:
                with self.subTest(channel=channel, column=column):
                    self.assertIn(column, SAMPLE_HEADERS)
                    self.assertNotIn(column, seen, f"{column} already claimed by {seen.get(column)}")
                    seen[column] = channel

    def test_channels_without_simulator_evidence_own_no_columns(self) -> None:
        # wheel_state, damage and setup are unavailable on evidence. brake_bias_setting is
        # driver-adjustable control state declared in configuration-setup.json, not a setup.
        for channel in ("wheel_state", "damage", "setup"):
            with self.subTest(channel=channel):
                self.assertNotIn(channel, CHANNEL_COLUMNS)
        self.assertNotIn("brake_bias_setting", {c for cols in CHANNEL_COLUMNS.values() for c in cols})

    def test_retained_columns_are_declared_rather_than_dropped(self) -> None:
        for column in RETAINED_SOURCE_COLUMNS:
            self.assertIn(column, SAMPLE_HEADERS)
        # Traffic, flag and tire-wear evidence is carried but not promoted to a normalized
        # concept in this contract version; promoting it is a deliberate later review.
        for column in ("car_distance_ahead_m", "session_flags", "tire_wear_lf_middle_pct",
                       "abs_setting", "brake_bias_setting", "precipitation_pct"):
            with self.subTest(column=column):
                self.assertIn(column, RETAINED_SOURCE_COLUMNS)
        # Anything promoted to a concept must NOT also be declared unknown.
        for column in ("air_temp_c", "track_temp_crew_c", "abs_active", "track_surface",
                       "longitudinal_acceleration_mps2", "tire_temp_lf_middle_c"):
            with self.subTest(column=column):
                self.assertNotIn(column, RETAINED_SOURCE_COLUMNS)


class RecorderBundleFlowTests(unittest.TestCase):
    """product recorder shape -> Labs validation -> binding -> normalized dataset."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="apex-labs-cross-repo-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = build_recorder_bundle(self.root / "bundle")
        self.collection = collection_record(self.bundle, self.root / "collection-record.json")

    def _ingest(self) -> tuple[dict, Path]:
        output = self.root / "normalized"
        manifest = ingest_research_bundle(
            self.bundle, output, self.collection,
            project_root=ROOT, integration_validation=True,
        )
        return manifest, output

    def test_the_synchronized_bundle_inspects_and_validates(self) -> None:
        report = inspect_research_bundle(self.bundle)
        self.assertTrue(report["valid"])
        self.assertEqual(report["profile_id"], "apex-labs-research-recorder-profile/1.0.0")
        for channel in ("weather", "traffic", "flags", "track_conditions", "assists", "tire_state",
                        "longitudinal_acceleration"):
            with self.subTest(channel=channel):
                self.assertEqual(report["channels"][channel], "available")
        for channel in ("wheel_state", "damage", "setup"):
            with self.subTest(channel=channel):
                self.assertEqual(report["channels"][channel], "unavailable")
        validated = validate_research_bundle(self.bundle, self.collection)
        self.assertTrue(validated["collection_record_validated"])

    def test_ingestion_produces_a_normalized_dataset_with_the_new_evidence(self) -> None:
        manifest, _ = self._ingest()
        capabilities = manifest["capabilities"]

        # Corrected longitudinal acceleration is measured evidence, attributed to LongAccel.
        self.assertEqual(capabilities["longitudinal_acceleration"]["provenance"], "measured")
        self.assertEqual(capabilities["longitudinal_acceleration"]["source_channel"], "LongAccel")

        # Newly promotable concepts, and only those.
        self.assertEqual(capabilities["air_temperature"]["source_channel"], "AirTemp")
        self.assertEqual(capabilities["track_temperature"]["source_channel"], "TrackTempCrew")
        self.assertEqual(capabilities["abs_active"]["source_channel"], "BrakeABSactive")
        self.assertEqual(capabilities["off_track_state"]["provenance"], "derived")

        # A driver-adjustable SETTING never becomes an intervention concept, and iRacing
        # exposes no traction-control intervention variable at all.
        self.assertEqual(capabilities["traction_control_active"]["provenance"], "unavailable")

        # Evidence-backed unavailable concepts stay unavailable.
        for concept in ("wheel_speed_front_left", "track_wetness"):
            with self.subTest(concept=concept):
                self.assertEqual(capabilities[concept]["provenance"], "unavailable")

        self.assertEqual(manifest["unknown_source_channels"], list(RETAINED_SOURCE_COLUMNS))

    def test_cold_pressure_never_presents_itself_as_live_pressure(self) -> None:
        manifest, _ = self._ingest()
        pressure = manifest["capabilities"]["tire_pressure_front_left"]
        self.assertEqual(pressure["provenance"], "derived")
        self.assertIn("cold", pressure["derivation"])
        self.assertIn("not live running tyre pressure", pressure["derivation"])
        self.assertIn("LFcoldPressure", pressure["derivation"])

    def test_a_missing_optional_value_stays_unavailable_and_never_becomes_zero(self) -> None:
        _, output = self._ingest()
        records = [
            json.loads(line)
            for line in (output / "records.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        samples = [r for r in records if r["record_type"] == "telemetry_sample"]
        self.assertGreaterEqual(len(samples), 2)
        sparse, populated = samples[0], samples[1]
        # Row 0 leaves the optional evidence empty.
        self.assertIsNone(sparse["fields"]["air_temperature"]["value"])
        self.assertEqual(sparse["fields"]["air_temperature"]["provenance"], "unavailable")
        self.assertIsNone(sparse["fields"]["abs_active"]["value"])
        # Row 1 supplies it, including a genuine measured zero that must survive as zero.
        self.assertEqual(populated["fields"]["air_temperature"]["provenance"], "measured")
        self.assertEqual(populated["fields"]["brake"]["value"], 0)
        self.assertEqual(populated["fields"]["brake"]["provenance"], "measured")

    def test_a_declared_unavailable_channel_may_not_carry_a_value(self) -> None:
        rows = (self.bundle / "samples.csv").read_text(encoding="utf-8").splitlines()
        columns = rows[1].split(",")
        columns[SAMPLE_HEADERS.index("car_distance_ahead_m")] = "12.5"
        rows[1] = ",".join(columns)
        (self.bundle / "samples.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
        manifest = read_json(self.bundle / "manifest.json")
        for channel in manifest["channels"]:
            if channel["name"] == "traffic":
                channel.update({"availability": "unavailable", "provenance": "unavailable",
                                "unit": None, "axis_and_sign": None,
                                "missing_value": "explicitly unavailable"})
        (self.bundle / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        rebind(self.bundle)
        with self.assertRaises(ContractValidationError) as error:
            inspect_research_bundle(self.bundle)
        self.assertIn("traffic", str(error.exception))

    def test_a_one_sided_column_change_is_rejected(self) -> None:
        rows = (self.bundle / "samples.csv").read_text(encoding="utf-8").splitlines()
        rows[0] = rows[0] + ",unexpected_future_column"
        rows[1:] = [row + "," for row in rows[1:]]
        (self.bundle / "samples.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
        rebind(self.bundle)
        with self.assertRaises(ContractValidationError) as error:
            inspect_research_bundle(self.bundle)
        self.assertIn("header mismatch", str(error.exception))

    def test_recorder_timestamp_precision_is_accepted(self) -> None:
        # The recorder writes .NET round-trip timestamps with seven fractional digits.
        manifest = read_json(self.bundle / "manifest.json")
        self.assertRegex(manifest["session"]["start_utc"], r"\.\d{7}Z$")
        self.assertTrue(inspect_research_bundle(self.bundle)["valid"])


class EnumDictionaryTests(unittest.TestCase):
    """Raw enum values are preserved; meaning is never invented."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="apex-labs-enum-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = build_recorder_bundle(self.root / "bundle")
        self.metadata = read_json(self.bundle / "recorder-metadata.json")

    def test_the_bundle_declares_enum_identity_for_every_enumerated_column(self) -> None:
        declared = _enum_dictionaries(self.metadata)
        for column in ("session_flags", "session_state", "pace_mode", "track_wetness",
                       "track_surface", "track_surface_material", "car_left_right"):
            with self.subTest(column=column):
                self.assertIn(column, declared)
                self.assertTrue(declared[column]["enumeration"])
                self.assertEqual(declared[column]["unknown_value_behavior"], "preserve_raw_value")

    def test_an_undeclared_dictionary_supplies_no_values(self) -> None:
        declared = _enum_dictionaries(self.metadata)
        flags = declared["session_flags"]
        self.assertEqual(flags["dictionary_provenance"], "unavailable")
        self.assertIsNone(flags.get("values"))
        self.assertEqual(flags["kind"], "bitfield")

    def test_a_declared_dictionary_carries_its_provenance(self) -> None:
        surface = _enum_dictionaries(self.metadata)["track_surface"]
        self.assertEqual(surface["dictionary_provenance"], "product_declared")
        self.assertEqual(surface["values"]["0"], "off_track")
        self.assertEqual(surface["values"]["3"], "on_track")

    def test_off_track_resolves_only_through_a_declared_dictionary(self) -> None:
        resolved = _off_track_values(_enum_dictionaries(self.metadata))
        self.assertIsNotNone(resolved)
        off, known, derivation = resolved
        self.assertEqual(off, frozenset({0}))
        self.assertEqual(known, frozenset({-1, 0, 1, 2, 3}))
        self.assertIn("product_declared", derivation)
        # With no dictionary the concept is simply not derivable.
        self.assertIsNone(_off_track_values({}))

    def test_an_unknown_enum_value_never_acquires_a_meaning(self) -> None:
        bundle = build_recorder_bundle(self.root / "unknown", track_surface=99)
        output = self.root / "normalized-unknown"
        ingest_research_bundle(
            bundle, output,
            collection_record(bundle, self.root / "collection-unknown.json"),
            project_root=ROOT, integration_validation=True,
        )
        records = [
            json.loads(line)
            for line in (output / "records.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        sample = next(r for r in records if r["record_type"] == "telemetry_sample")
        off_track = sample["fields"]["off_track_state"]
        self.assertIsNone(off_track["value"])
        self.assertEqual(off_track["provenance"], "unavailable")

    def test_a_dictionary_claiming_provenance_without_values_is_refused(self) -> None:
        metadata = read_json(self.bundle / "recorder-metadata.json")
        metadata["enum_dictionaries"]["track_surface"]["values"] = None
        with self.assertRaises(ContractValidationError):
            _enum_dictionaries(metadata)

    def test_a_dictionary_for_an_unknown_column_is_refused(self) -> None:
        metadata = read_json(self.bundle / "recorder-metadata.json")
        metadata["enum_dictionaries"]["not_a_column"] = dict(
            metadata["enum_dictionaries"]["session_flags"]
        )
        with self.assertRaises(ContractValidationError) as error:
            _enum_dictionaries(metadata)
        self.assertIn("not_a_column", str(error.exception))

    def test_a_dictionary_that_would_invent_meaning_for_unknown_values_is_refused(self) -> None:
        metadata = read_json(self.bundle / "recorder-metadata.json")
        metadata["enum_dictionaries"]["track_surface"]["unknown_value_behavior"] = "nearest_match"
        with self.assertRaises(ContractValidationError):
            _enum_dictionaries(metadata)


class RecorderMetadataDeclarationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="apex-labs-meta-")
        self.addCleanup(self.temporary.cleanup)
        self.bundle = build_recorder_bundle(Path(self.temporary.name) / "bundle")
        self.metadata = read_json(self.bundle / "recorder-metadata.json")

    def test_the_bundle_states_its_own_sample_shape(self) -> None:
        samples = self.metadata["samples"]
        self.assertEqual(samples["columns"], SAMPLE_HEADERS)
        self.assertEqual(samples["column_count"], len(SAMPLE_HEADERS))
        self.assertEqual(samples["nullable_value"], "empty-field")
        self.assertTrue(samples["null_is_never_zero"])

    def test_sub_sample_capture_is_declared_deferred_rather_than_silently_absent(self) -> None:
        deferred = self.metadata["deferred_capabilities"]["high_rate_360hz"]
        self.assertEqual(deferred["decision"], "DEFER UNTIL TIMING SEMANTICS PROVEN")
        self.assertFalse(deferred["captured"])

    def test_no_sub_sample_channel_reached_the_sample_columns(self) -> None:
        for column in SAMPLE_HEADERS:
            self.assertFalse(column.endswith("_st"), column)

    def test_partial_configuration_keeps_its_three_concepts_apart(self) -> None:
        configuration = read_json(self.bundle / "configuration-setup.json")
        self.assertEqual(configuration["setup"]["availability"], "unavailable")
        partial = configuration["partial_configuration"]
        self.assertIn("driver_adjustable_control", partial)
        self.assertIn("garage_cold_pressures_kpa", partial)
        self.assertIn("pit_service_request", partial)
        # A pending pit-service request is not the current tire state.
        self.assertNotEqual(
            partial["pit_service_request"]["lf_kpa"],
            partial["garage_cold_pressures_kpa"]["lf"],
        )
        self.assertIn("not the current tire state", partial["pit_service_request"]["semantics"])
        self.assertIn("not live running", partial["garage_cold_pressures_kpa"]["semantics"])

    def test_the_recorder_profile_version_is_unchanged(self) -> None:
        self.assertEqual(
            self.metadata["contract"]["profile_id"],
            "apex-labs-research-recorder-profile/1.0.0",
        )

    def test_no_opponent_or_radio_identity_reaches_the_bundle(self) -> None:
        for name in ("samples.csv", "recorder-metadata.json", "manifest.json",
                     "configuration-setup.json", "events.jsonl"):
            text = (self.bundle / name).read_text(encoding="utf-8")
            with self.subTest(file=name):
                self.assertNotIn("CarIdx", text)
                self.assertNotIn("RadioTransmit", text)


class CollectionBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="apex-labs-binding-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = build_recorder_bundle(self.root / "bundle")
        self.collection = collection_record(self.bundle, self.root / "collection-record.json")

    def test_a_collection_record_bound_to_another_bundle_is_refused(self) -> None:
        record = read_json(self.collection)
        record["source_bundle"]["sha256"] = sha256_bytes(b"a different bundle")
        self.collection.write_bytes(canonical_json_bytes(record))
        with self.assertRaises(IntegrityError):
            validate_research_bundle(self.bundle, self.collection)

    def test_a_truncated_sample_file_is_refused(self) -> None:
        (self.bundle / "samples.csv").write_bytes(
            (self.bundle / "samples.csv").read_bytes()[:-12]
        )
        with self.assertRaises(IntegrityError):
            inspect_research_bundle(self.bundle)

    def test_audit_reports_the_expected_counts(self) -> None:
        audit = audit_research_bundle(self.bundle)
        self.assertEqual(audit.sample_count, 2)
        self.assertGreaterEqual(audit.event_count, 1)


if __name__ == "__main__":
    unittest.main()
