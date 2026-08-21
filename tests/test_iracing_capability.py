"""Capability reconciliation against the committed live iRacing inventory.

These tests defend one property above all others: Apex Labs must never claim a
simulator capability the evidence does not support. The inventory is metadata,
so every assertion here is about schema, type, count, unit, and semantics. None
of it is a claim about driving.
"""

from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path

from _support import ROOT

from apex_labs.capability import (
    REQUIRED_CHANNELS,
    VariableInventory,
    build_capability_map,
    load_variable_inventory,
    product_recorder_handoff,
    rehearsal_readiness,
    validate_variable_inventory,
)
from apex_labs.capability.reconciliation import (
    CAR_OR_SESSION_DEPENDENT,
    DIRECTLY_AVAILABLE,
    PARTIAL,
    UNAVAILABLE,
)
from apex_labs.errors import ContractValidationError
from apex_labs.io import canonical_json_bytes
from apex_labs.ingestion import apex_research

CAPABILITY_DIR = ROOT / "research" / "capability"
INVENTORY_PATH = CAPABILITY_DIR / "iracing-variable-inventory.2026-08-21.json"
CAPABILITY_MAP_PATH = CAPABILITY_DIR / "iracing-capability-map.json"
PROFILE_PATH = ROOT / "contracts" / "v1" / "apex-research-recorder-profile-v1.json"

# The exact acquisition evidence this milestone reconciled.
INVENTORY_SHA256 = "81c5c88d46c112968e9de463c58c2a0820e62592bf43dde285f3f34b81c61f2f"
INVENTORY_VARIABLE_COUNT = 331


def _minimal(**overrides: object) -> dict:
    document = {
        "schema_version": "apex-iracing-variable-inventory/1.0.0",
        "values_sampled": False,
        "direct_identifiers_included": False,
        "variables": [
            {"name": "Speed", "sdk_type": "Float", "count": 1, "unit": "m/s", "description": "GPS vehicle speed"},
        ],
    }
    document.update(overrides)
    return document


class InventoryContractTests(unittest.TestCase):
    def test_a_minimal_inventory_validates(self) -> None:
        self.assertEqual(validate_variable_inventory(_minimal())["variables"][0]["name"], "Speed")

    def test_a_sampled_inventory_is_refused_rather_than_filtered(self) -> None:
        with self.assertRaises(ContractValidationError) as error:
            validate_variable_inventory(_minimal(values_sampled=True))
        self.assertIn("metadata-only", str(error.exception))

    def test_an_inventory_declaring_identifiers_is_refused(self) -> None:
        with self.assertRaises(ContractValidationError) as error:
            validate_variable_inventory(_minimal(direct_identifiers_included=True))
        self.assertIn("identifiers", str(error.exception))

    def test_a_foreign_contract_version_is_refused(self) -> None:
        with self.assertRaises(ContractValidationError):
            validate_variable_inventory(_minimal(schema_version="apex-iracing-variable-inventory/2.0.0"))

    def test_structural_defects_are_refused(self) -> None:
        duplicate = _minimal()
        duplicate["variables"] = duplicate["variables"] * 2
        cases = {
            "duplicate name": duplicate,
            "unknown sdk type": _minimal(variables=[{**_minimal()["variables"][0], "sdk_type": "Quaternion"}]),
            "zero count": _minimal(variables=[{**_minimal()["variables"][0], "count": 0}]),
            "boolean count": _minimal(variables=[{**_minimal()["variables"][0], "count": True}]),
            "missing description": _minimal(variables=[{"name": "A", "sdk_type": "Int", "count": 1, "unit": None}]),
            "extra top-level key": {**_minimal(), "captured_at": "2026-08-21"},
            "empty variables": _minimal(variables=[]),
        }
        for label, document in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(ContractValidationError):
                    validate_variable_inventory(document)


class CommittedSnapshotTests(unittest.TestCase):
    """The committed snapshot is point-in-time evidence bound to exact bytes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = load_variable_inventory(INVENTORY_PATH)

    def test_the_snapshot_is_the_reconciled_acquisition(self) -> None:
        self.assertEqual(self.inventory.source_sha256, INVENTORY_SHA256)
        self.assertEqual(len(self.inventory), INVENTORY_VARIABLE_COUNT)
        self.assertFalse(self.inventory.values_sampled)
        self.assertFalse(self.inventory.direct_identifiers_included)

    def test_sdk_types_and_array_counts_are_interpreted_as_declared(self) -> None:
        summary = self.inventory.summary()
        self.assertEqual(
            summary["sdk_type_counts"],
            {"BitField": 6, "Bool": 40, "Double": 4, "Float": 196, "Int": 85},
        )
        # Every count-6 array is a 360 Hz sub-sample channel and vice versa.
        six = {name for name in self.inventory.names if self.inventory.require(name).count == 6}
        self.assertEqual(six, set(summary["sub_sample_channels"]))
        self.assertEqual(len(six), 18)
        # Every count-72 array is a per-car opponent array.
        seventy_two = {name for name in self.inventory.names if self.inventory.require(name).count == 72}
        self.assertEqual(len(seventy_two), 27)
        self.assertTrue(all(name.startswith("CarIdx") for name in seventy_two))

    def test_enumerated_variables_are_detected_but_not_decoded(self) -> None:
        flags = self.inventory.require("SessionFlags", sdk_type="BitField", count=1, unit="irsdk_Flags")
        self.assertTrue(flags.requires_enum_dictionary)
        self.assertEqual(flags.enumeration, "irsdk_Flags")
        # A plain physical channel carries no enumeration.
        self.assertFalse(self.inventory.require("LatAccel").requires_enum_dictionary)

    def test_require_refuses_a_variable_the_simulator_does_not_expose(self) -> None:
        # Regression guard for the defect this milestone found: Labs and the
        # product recorder both named "LonAccel", which iRacing does not expose.
        self.assertNotIn("LonAccel", self.inventory)
        self.assertIn("LongAccel", self.inventory)
        with self.assertRaises(ContractValidationError) as error:
            self.inventory.require("LonAccel", context="regression")
        self.assertIn("absent from the inventory", str(error.exception))

    def test_require_refuses_a_wrong_type_count_or_unit(self) -> None:
        for kwargs in ({"sdk_type": "Int"}, {"count": 6}, {"unit": "km/h"}):
            with self.subTest(**kwargs):
                with self.assertRaises(ContractValidationError):
                    self.inventory.require("LatAccel", **kwargs)


class CapabilityMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = load_variable_inventory(INVENTORY_PATH)
        cls.map = build_capability_map(cls.inventory)
        cls.by_channel = {entry["channel"]: entry for entry in cls.map["channels"]}

    def test_the_map_covers_the_profile_channels_in_profile_order(self) -> None:
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(tuple(profile["required_channels"]), REQUIRED_CHANNELS)
        self.assertEqual(tuple(self.by_channel), REQUIRED_CHANNELS)

    def test_every_channel_classification_is_evidence_backed(self) -> None:
        expected = {
            "timestamp": DIRECTLY_AVAILABLE,
            "brake": DIRECTLY_AVAILABLE,
            "throttle": DIRECTLY_AVAILABLE,
            "steering_angle": DIRECTLY_AVAILABLE,
            "speed": DIRECTLY_AVAILABLE,
            "gear": DIRECTLY_AVAILABLE,
            "rpm": DIRECTLY_AVAILABLE,
            "longitudinal_acceleration": DIRECTLY_AVAILABLE,
            "lateral_acceleration": DIRECTLY_AVAILABLE,
            "yaw_rate": DIRECTLY_AVAILABLE,
            "wheel_state": UNAVAILABLE,
            "tire_state": PARTIAL,
            "fuel": DIRECTLY_AVAILABLE,
            "setup": PARTIAL,
            "assists": CAR_OR_SESSION_DEPENDENT,
            "damage": UNAVAILABLE,
            "flags": PARTIAL,
            "weather": DIRECTLY_AVAILABLE,
            "traffic": PARTIAL,
            "track_conditions": PARTIAL,
        }
        self.assertEqual({k: v["classification"] for k, v in self.by_channel.items()}, expected)

    def test_a_claim_naming_an_absent_variable_fails_the_build(self) -> None:
        document = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        document["variables"] = [v for v in document["variables"] if v["name"] != "LongAccel"]
        with self.assertRaises(ContractValidationError) as error:
            build_capability_map(VariableInventory(document))
        self.assertIn("LongAccel", str(error.exception))

    def test_a_claim_asserting_the_wrong_unit_fails_the_build(self) -> None:
        document = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        for variable in document["variables"]:
            if variable["name"] == "TrackTempCrew":
                variable["unit"] = "F"
        with self.assertRaises(ContractValidationError) as error:
            build_capability_map(VariableInventory(document))
        self.assertIn("TrackTempCrew", str(error.exception))

    # -- Category-specific semantics -------------------------------------

    def test_damage_remains_unavailable_and_claims_no_variables(self) -> None:
        damage = self.by_channel["damage"]
        self.assertEqual(damage["classification"], UNAVAILABLE)
        self.assertEqual(damage["provenance"], "unavailable")
        self.assertEqual(damage["iracing_variables"], [])
        self.assertEqual(damage["recorder_action"], "keep_unavailable")
        # Repair timers exist, but they live in auxiliary evidence, not damage.
        auxiliary = {entry["category"]: entry for entry in self.map["auxiliary_evidence"]}
        repair = {item["name"] for item in auxiliary["repair_and_tow_state"]["iracing_variables"]}
        self.assertIn("PitRepairLeft", repair)
        self.assertIn("FastRepairAvailable", repair)
        self.assertFalse(repair & {item["name"] for item in damage["iracing_variables"]})

    def test_wheel_state_remains_unavailable_because_no_rotational_variable_exists(self) -> None:
        wheel = self.by_channel["wheel_state"]
        self.assertEqual(wheel["classification"], UNAVAILABLE)
        self.assertEqual(wheel["iracing_variables"], [])
        rotational = re.compile(r"(?i)wheelspeed|wheelrot|rotation|slipratio|\bomega\b|\brps\b")
        self.assertEqual([n for n in self.inventory.names if rotational.search(n)], [])
        # Suspension evidence exists but is classified separately.
        auxiliary = {entry["category"]: entry for entry in self.map["auxiliary_evidence"]}
        suspension = {item["name"] for item in auxiliary["suspension_state"]["iracing_variables"]}
        self.assertIn("LFshockDefl", suspension)
        self.assertIn("LFshockVel", suspension)
        self.assertNotIn("suspension_state", self.by_channel)

    def test_setup_is_partial_and_a_full_garage_setup_stays_absent(self) -> None:
        setup = self.by_channel["setup"]
        self.assertEqual(setup["classification"], PARTIAL)
        names = {item["name"] for item in setup["iracing_variables"]}
        self.assertLessEqual({"dcBrakeBias", "LFcoldPressure", "PitSvTireCompound"}, names)
        # No spring, damper, geometry, aerodynamic, differential, or gearing variable exists.
        # No suspension geometry, spring, damper, aerodynamic, differential, or
        # gearing variable exists. SteeringWheelPctDamper is force-feedback
        # damping on the participant's wheel, not a vehicle damper, so the
        # steering-wheel family is excluded before the search.
        garage = re.compile(
            r"(?i)springrate|damper|camber|toe(?:in|out)|caster|wingangle|"
            r"downforce|differential|finaldrive|gearratio"
        )
        vehicle_setup = [
            name for name in self.inventory.names
            if garage.search(name) and not name.startswith("SteeringWheel")
        ]
        self.assertEqual(vehicle_setup, [])
        self.assertIn("Force feedback", self.inventory.require("SteeringWheelPctDamper").description)
        self.assertTrue(any("FULL GARAGE SETUP REMAINS UNAVAILABLE" in text for text in setup["limitations"]))

    def test_tire_state_preserves_cold_pressure_semantics(self) -> None:
        tire = self.by_channel["tire_state"]
        names = {item["name"] for item in tire["iracing_variables"]}
        # Across-tread carcass temperature, wear, odometer, compound, cold pressure.
        self.assertLessEqual({"LFtempCL", "LFtempCM", "LFtempCR"}, names)
        self.assertLessEqual({"LFwearL", "LFwearM", "LFwearR"}, names)
        self.assertLessEqual({"LFodometer", "RRodometer"}, names)
        self.assertIn("PlayerTireCompound", names)
        self.assertIn("LFcoldPressure", names)
        # The evidence itself says cold pressure is garage-set.
        cold = self.inventory.require("LFcoldPressure", sdk_type="Float", count=1, unit="kPa")
        self.assertIn("cold pressure", cold.description)
        self.assertIn("as set in the garage", cold.description)
        # No hot or running pressure variable exists anywhere.
        hot = [n for n in self.inventory.names if "ressure" in n and "cold" not in n.lower()]
        self.assertNotIn("LFhotPressure", hot)
        self.assertTrue(any("COLD PRESSURE IS NOT LIVE PRESSURE" in text for text in tire["limitations"]))

    def test_assists_separate_setting_from_intervention_and_stay_car_dependent(self) -> None:
        assists = self.by_channel["assists"]
        self.assertEqual(assists["classification"], CAR_OR_SESSION_DEPENDENT)
        names = {item["name"] for item in assists["iracing_variables"]}
        self.assertLessEqual({"dcABS", "dcTractionControl", "BrakeABSactive"}, names)
        # The SDK descriptions carry the distinction Labs relies on.
        self.assertIn("adjustment", self.inventory.require("dcABS").description)
        self.assertIn("abs is currently reducing", self.inventory.require("BrakeABSactive").description)
        self.assertTrue(any("A SETTING IS NOT AN INTERVENTION" in t for t in assists["limitations"]))
        self.assertTrue(any("NOT PROOF THAT A CAR HAS NO ABS" in t for t in assists["limitations"]))

    def test_flags_are_promoted_but_need_the_sdk_enum_dictionary(self) -> None:
        flags = self.by_channel["flags"]
        names = {item["name"] for item in flags["iracing_variables"]}
        self.assertEqual(names, {"SessionFlags", "SessionState", "PaceMode", "PitsOpen"})
        self.assertEqual(
            set(flags["requires_enum_dictionary"]), {"SessionFlags", "SessionState", "PaceMode"}
        )
        self.assertTrue(any("VALUE DICTIONARIES" in t for t in flags["limitations"]))
        # Per-opponent flag arrays stay out.
        self.assertFalse({n for n in names if n.startswith("CarIdx")})

    def test_weather_promotes_environment_state_and_keeps_solar_secondary(self) -> None:
        weather = self.by_channel["weather"]
        self.assertEqual(weather["classification"], DIRECTLY_AVAILABLE)
        names = {item["name"] for item in weather["iracing_variables"]}
        self.assertEqual(
            names,
            {
                "AirTemp", "AirPressure", "AirDensity", "RelativeHumidity", "Precipitation",
                "FogLevel", "WindVel", "WindDir", "Skies", "WeatherDeclaredWet",
            },
        )
        # Solar geometry is real but classified as derived secondary context.
        self.assertNotIn("SolarAltitude", names)
        auxiliary = {entry["category"]: entry for entry in self.map["auxiliary_evidence"]}
        solar = {item["name"] for item in auxiliary["solar_geometry"]["iracing_variables"]}
        self.assertLessEqual({"SolarAltitude", "SolarAzimuth"}, solar)
        # Provenance of the point measurement is preserved.
        self.assertIn("start/finish line", self.inventory.require("AirTemp").description)
        self.assertTrue(any("START/FINISH LINE" in t for t in weather["limitations"]))

    def test_track_conditions_use_the_crew_temperature_not_the_deprecated_one(self) -> None:
        track = self.by_channel["track_conditions"]
        names = {item["name"] for item in track["iracing_variables"]}
        self.assertEqual(
            names,
            {"TrackTempCrew", "TrackWetness", "PlayerTrackSurface", "PlayerTrackSurfaceMaterial"},
        )
        self.assertNotIn("TrackTemp", names)
        self.assertIn("Deprecated", self.inventory.require("TrackTemp").description)
        self.assertIn("measured by crew", self.inventory.require("TrackTempCrew").description)
        self.assertIn("average track surface", self.inventory.require("TrackWetness").description)
        self.assertTrue(any("NOT A CONDITION SCORE" in t for t in track["limitations"]))

    def test_traffic_is_the_privacy_minimal_three_signal_representation(self) -> None:
        traffic = self.by_channel["traffic"]
        names = {item["name"] for item in traffic["iracing_variables"]}
        self.assertEqual(names, {"CarDistAhead", "CarDistBehind", "CarLeftRight"})
        self.assertEqual(traffic["requires_enum_dictionary"], ["CarLeftRight"])
        self.assertTrue(traffic["privacy_restrictions"])

    def test_no_profile_channel_captures_opponent_arrays_or_radio_identity(self) -> None:
        forbidden = re.compile(r"^(CarIdx|RadioTransmit)")
        for channel, entry in self.by_channel.items():
            with self.subTest(channel=channel):
                named = [item["name"] for item in entry["iracing_variables"] if forbidden.match(item["name"])]
                self.assertEqual(named, [], f"{channel} must not capture per-opponent or radio identity")

    # -- 360 Hz sub-sample assessment -------------------------------------

    def test_sub_sample_channels_are_assessed_but_deferred(self) -> None:
        assessment = self.map["sub_sample_360hz"]
        self.assertEqual(len(assessment["available_channels"]), 18)
        self.assertEqual(assessment["recommendation"], "defer_until_timing_semantics_proven")
        self.assertFalse(assessment["labs_support_today"])
        self.assertLessEqual(
            {"LongAccel_ST", "LatAccel_ST", "YawRate_ST"}, set(assessment["available_channels"])
        )
        # Ordering and per-sub-sample timing are explicitly unresolved, so no
        # timing semantics are implemented and none are asserted.
        unresolved = " ".join(assessment["unresolved_questions"])
        self.assertIn("ordering is not proven", unresolved)
        self.assertIn("timestamps are not proven", unresolved)

    def test_no_sub_sample_channel_enters_a_profile_channel(self) -> None:
        for channel, entry in self.by_channel.items():
            with self.subTest(channel=channel):
                names = [item["name"] for item in entry["iracing_variables"] if item["name"].endswith("_ST")]
                self.assertEqual(names, [], "sub-sample capture is deferred, not silently included")

    # -- Determinism ------------------------------------------------------

    def test_the_committed_map_reproduces_from_the_committed_inventory(self) -> None:
        self.assertEqual(
            CAPABILITY_MAP_PATH.read_bytes(),
            canonical_json_bytes(build_capability_map(load_variable_inventory(INVENTORY_PATH))),
        )

    def test_the_map_binds_the_exact_inventory_bytes_and_states_its_caveat(self) -> None:
        evidence = self.map["evidence"]
        self.assertEqual(evidence["inventory_sha256"], INVENTORY_SHA256)
        self.assertEqual(evidence["variable_count"], INVENTORY_VARIABLE_COUNT)
        self.assertEqual(evidence["kind"], "point_in_time_simulator_capability_snapshot")
        self.assertIn("not eternal", evidence["caveat"])


class RecorderMappingTests(unittest.TestCase):
    """Labs' own declared source channels must exist in the simulator."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = load_variable_inventory(INVENTORY_PATH)

    def test_every_source_channel_labs_names_exists_in_the_inventory(self) -> None:
        source = (ROOT / "src" / "apex_labs" / "ingestion" / "apex_research.py").read_text(encoding="utf-8")
        # Source channels the adapter attributes to iRacing, as written in code.
        named = set(re.findall(r'"source_channel": "([A-Za-z0-9_]+)"', source))
        named |= set(re.findall(r'_qualified\([^)]*?"[a-z_]+", "([A-Za-z][A-Za-z0-9_]+)"', source, re.S))
        named |= set(re.findall(r'\("[a-z_]+", "([A-Z][A-Za-z0-9_]+)"\)', source))
        self.assertIn("LongAccel", named)
        self.assertNotIn("LonAccel", named)
        missing = self.inventory.missing(named)
        self.assertEqual(missing, [], f"Labs names simulator variables that do not exist: {missing}")

    def test_the_adapter_states_cold_pressure_semantics_in_its_derivation(self) -> None:
        derivation = apex_research.COLD_PRESSURE_DERIVATION.format(source="LFcoldPressure")
        self.assertIn("cold", derivation)
        self.assertIn("not live running tyre pressure", derivation)

    def test_the_adapter_version_records_the_corrected_mapping(self) -> None:
        # The corrected source channel changes normalized record content, so the
        # adapter that produces it must not still claim to be version 1.0.0.
        self.assertNotEqual(apex_research.ADAPTER_VERSION, "1.0.0")


class ReadinessGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = load_variable_inventory(INVENTORY_PATH)
        cls.readiness = rehearsal_readiness(cls.inventory)

    def test_the_gate_reports_every_required_readiness_dimension(self) -> None:
        for key in (
            "expected_channels",
            "currently_supported_channels",
            "expected_unavailable_channels",
            "car_or_session_dependent_channels",
            "missing_required_evidence_for_rehearsal",
            "missing_required_evidence_for_campaign",
            "inventory_profile_mismatch",
        ):
            with self.subTest(key=key):
                self.assertIn(key, self.readiness)
        self.assertEqual(self.readiness["expected_channels"], list(REQUIRED_CHANNELS))
        self.assertEqual(self.readiness["inventory_profile_mismatch"], [])

    def test_the_synchronized_recorder_clears_the_rehearsal_gate(self) -> None:
        # The LongAccel correction and the capture expansion landed together in the
        # coordinated recorder checkpoint, so nothing required is still missing.
        self.assertEqual(self.readiness["missing_required_evidence_for_rehearsal"], [])
        self.assertEqual(self.readiness["missing_required_evidence_for_campaign"], [])
        self.assertEqual(self.readiness["verdict"], "READY FOR 30-MINUTE REHEARSAL")
        self.assertTrue(self.readiness["ready_for_rehearsal"])

    def test_a_regressed_mapping_would_block_the_rehearsal_again(self) -> None:
        # The gate is not hard-coded to pass: losing a required channel re-blocks it.
        from apex_labs.capability import reconciliation

        regressed = tuple(
            {**entry, "recorder_supported_now": False}
            if entry["channel"] == "longitudinal_acceleration" else entry
            for entry in reconciliation.CHANNEL_RECONCILIATION
        )
        original = reconciliation.CHANNEL_RECONCILIATION
        reconciliation.CHANNEL_RECONCILIATION = regressed
        try:
            blocked = rehearsal_readiness(self.inventory)
        finally:
            reconciliation.CHANNEL_RECONCILIATION = original
        self.assertEqual(
            blocked["missing_required_evidence_for_rehearsal"], ["longitudinal_acceleration"]
        )
        self.assertEqual(blocked["verdict"], "RECORDER UPDATE REQUIRED BEFORE REHEARSAL")

    def test_optional_environmental_and_traffic_evidence_never_blocks_a_rehearsal(self) -> None:
        blocking = set(self.readiness["missing_required_evidence_for_rehearsal"])
        self.assertFalse(blocking & {"weather", "traffic", "track_conditions", "assists", "setup", "flags"})

    def test_no_channel_is_left_partially_captured(self) -> None:
        # tire_state previously carried only middle carcass temperature and cold
        # pressure. The recorder now captures across-tread temperature, wear,
        # odometer and compound, so no expansion remains outstanding.
        self.assertIn("tire_state", self.readiness["currently_supported_channels"])
        self.assertEqual(self.readiness["partially_captured_channels"], [])
        self.assertEqual(self.readiness["channels_requiring_capture_expansion"], [])

    def test_only_the_evidence_backed_unavailable_channels_are_uncaptured(self) -> None:
        supported = set(self.readiness["currently_supported_channels"])
        self.assertEqual(set(REQUIRED_CHANNELS) - supported, {"wheel_state", "damage"})

    def test_expected_unavailable_channels_are_declared_not_missing(self) -> None:
        self.assertEqual(sorted(self.readiness["expected_unavailable_channels"]), ["damage", "wheel_state"])
        for channel in ("damage", "wheel_state"):
            self.assertNotIn(channel, self.readiness["missing_required_evidence_for_campaign"])

    def test_the_promotion_needs_no_recorder_contract_version_change(self) -> None:
        self.assertFalse(self.readiness["contract_version_change_required"])
        self.assertIn("1.0.0", self.readiness["recorder_profile_id"])

    def test_the_handoff_is_discharged_but_keeps_its_standing_requirements(self) -> None:
        handoff = product_recorder_handoff(build_capability_map(self.inventory))
        # Every correction and addition has been implemented in the recorder.
        self.assertEqual(handoff["blocking_corrections"], [])
        self.assertEqual(handoff["capture_additions"], [])
        # The constraints that made them safe remain stated for any future change.
        self.assertIn("must land in the product recorder and in Labs together", handoff["sequencing_requirement"])
        self.assertIn("authoritative SDK value dictionary", handoff["enum_dictionary_requirement"])

    def test_the_map_records_that_both_repositories_were_synchronized(self) -> None:
        synchronization = build_capability_map(self.inventory)["recorder_synchronization"]
        self.assertEqual(synchronization["state"], "implemented")
        self.assertEqual(
            synchronization["profile_id_unchanged"], "apex-labs-research-recorder-profile/1.0.0"
        )

class CapabilityCliTests(unittest.TestCase):
    def test_the_cli_exposes_inspect_map_and_readiness(self) -> None:
        from _support import run_cli

        for command, probe in (
            ("inspect", "variable_count"),
            ("map", "channels"),
            ("readiness", "verdict"),
        ):
            with self.subTest(command=command):
                result = run_cli("capability", command, str(INVENTORY_PATH))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(probe, json.loads(result.stdout))


class ConfoundModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = {
            entry["confound"]: entry
            for entry in build_capability_map(load_variable_inventory(INVENTORY_PATH))["confound_model"]
        }

    def test_newly_measurable_confounds_are_declared(self) -> None:
        for confound in (
            "weather", "track_wetness", "track_temperature", "traffic", "tire_compound",
            "tire_wear", "tire_age_or_distance", "assists", "weight_penalty",
        ):
            with self.subTest(confound=confound):
                self.assertTrue(self.model[confound]["measurable"])

    def test_confounds_the_evidence_cannot_measure_stay_unmeasurable(self) -> None:
        for confound in ("live_tire_pressure", "vehicle_damage_state", "full_garage_setup"):
            with self.subTest(confound=confound):
                self.assertFalse(self.model[confound]["measurable"])
                self.assertEqual(self.model[confound]["role"], "unavailable")


if __name__ == "__main__":
    unittest.main()
