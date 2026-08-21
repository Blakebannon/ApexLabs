"""Evidence-backed reconciliation of the Research Recorder profile against iRacing.

Every capability statement here names the exact iRacing variables that support it
and is checked against a sanitized variable inventory before it is emitted. A claim
whose variable, SDK type, array count, or unit the inventory does not support is a
hard refusal, not a warning: that is precisely the class of error this module
exists to prevent.

The inventory proves *capability*. It proves nothing about driving, because no
telemetry values were sampled. Nothing in this module may be read as a finding.
"""

from __future__ import annotations

from typing import Any

from apex_labs.capability.inventory import VariableInventory
from apex_labs.errors import ContractValidationError

CAPABILITY_MAP_CONTRACT = "apex-labs.iracing-capability-map/v1"
RECORDER_PROFILE_ID = "apex-labs-research-recorder-profile/1.0.0"

# The strict Research Recorder channel inventory, in profile order. A test binds
# this tuple to contracts/v1/apex-research-recorder-profile-v1.json.
REQUIRED_CHANNELS = (
    "timestamp", "brake", "throttle", "steering_angle", "speed", "gear", "rpm",
    "longitudinal_acceleration", "lateral_acceleration", "yaw_rate", "wheel_state",
    "tire_state", "fuel", "setup", "assists", "damage", "flags", "weather",
    "traffic", "track_conditions",
)

# Classification vocabulary required by the capability review.
DIRECTLY_AVAILABLE = "directly_available"
CAR_OR_SESSION_DEPENDENT = "available_car_or_session_dependent"
PARTIAL = "partial_semantically_limited"
DERIVABLE = "derivable_from_available_metadata"
UNAVAILABLE = "unavailable"
REQUIRES_LIVE_VALUE_VALIDATION = "requires_live_value_validation"
NOT_JUSTIFIED = "not_scientifically_justified_for_initial_corpus"

CLASSIFICATIONS = frozenset({
    DIRECTLY_AVAILABLE, CAR_OR_SESSION_DEPENDENT, PARTIAL, DERIVABLE,
    UNAVAILABLE, REQUIRES_LIVE_VALUE_VALIDATION, NOT_JUSTIFIED,
})

# What the recorder must do before this channel means what the profile says.
RECORDER_ACTIONS = frozenset({"none", "correct_existing_mapping", "add_new_capture", "keep_unavailable"})

PROVENANCE = frozenset({"measured", "derived", "unavailable"})


def _v(name: str, sdk_type: str, count: int, unit: str | None) -> dict[str, Any]:
    """Declare one supporting variable claim, verified later against the inventory."""
    return {"name": name, "sdk_type": sdk_type, "count": count, "unit": unit}


# Repeated corner-wise variable families, declared once.
_TIRE_CARCASS_TEMPS = tuple(
    _v(f"{corner}temp{position}", "Float", 1, "C")
    for corner in ("LF", "RF", "LR", "RR")
    for position in ("CL", "CM", "CR")
)
_TIRE_WEAR = tuple(
    _v(f"{corner}wear{position}", "Float", 1, "%")
    for corner in ("LF", "RF", "LR", "RR")
    for position in ("L", "M", "R")
)
_TIRE_COLD_PRESSURES = tuple(
    _v(f"{corner}coldPressure", "Float", 1, "kPa") for corner in ("LF", "RF", "LR", "RR")
)
_TIRE_ODOMETERS = tuple(
    _v(f"{corner}odometer", "Float", 1, "m") for corner in ("LF", "RF", "LR", "RR")
)
_SHOCK_DEFLECTION = tuple(
    _v(f"{corner}shockDefl", "Float", 1, "m") for corner in ("LF", "RF", "LR", "RR")
)
_SHOCK_VELOCITY = tuple(
    _v(f"{corner}shockVel", "Float", 1, "m/s") for corner in ("LF", "RF", "LR", "RR")
)
_BRAKE_LINE_PRESSURE = tuple(
    _v(f"{corner}brakeLinePress", "Float", 1, "bar") for corner in ("LF", "RF", "LR", "RR")
)


CHANNEL_RECONCILIATION: tuple[dict[str, Any], ...] = (
    {
        "channel": "timestamp",
        "previous_classification": "available (measured)",
        "classification": DIRECTLY_AVAILABLE,
        "provenance": "measured",
        "variables": (_v("SessionTime", "Double", 1, "s"),),
        "semantics": "Seconds since session start on the simulator clock. Host observation UTC is recorded separately and is not simulator UTC.",
        "limitations": (
            "SessionTime is a session clock, not a wall clock, and its reset behaviour across session transitions must be read from recorder gap accounting.",
        ),
        "privacy": (),
        "recorder_supported_now": True,
        "recorder_action": "none",
        "required_for_rehearsal": True,
        "required_for_campaign": True,
        "scientific_reason": "Every time-domain metric, segment boundary, and event alignment depends on it.",
    },
    {
        "channel": "brake",
        "previous_classification": "available (measured)",
        "classification": DIRECTLY_AVAILABLE,
        "provenance": "measured",
        "variables": (_v("Brake", "Float", 1, "%"),),
        "semantics": "Processed brake application, 0 released to 1 maximum pedal force.",
        "limitations": (
            "The SDK unit token is '%' while the description defines a 0-to-1 fraction; Labs treats it as a ratio and the first live rehearsal must confirm the observed range.",
            "Brake is the processed input; BrakeRaw is the pre-processing input and is a separate variable.",
        ),
        "privacy": (),
        "recorder_supported_now": True,
        "recorder_action": "none",
        "required_for_rehearsal": True,
        "required_for_campaign": True,
        "scientific_reason": "Primary driver-input channel for every braking and brake-release question in the campaign.",
    },
    {
        "channel": "throttle",
        "previous_classification": "available (measured)",
        "classification": DIRECTLY_AVAILABLE,
        "provenance": "measured",
        "variables": (_v("Throttle", "Float", 1, "%"),),
        "semantics": "Processed throttle application, 0 off-throttle to 1 full throttle.",
        "limitations": (
            "Unit token '%' with a 0-to-1 description, as for brake; range confirmation is a live-value task.",
            "ThrottleRaw is a distinct pre-processing input and is not captured.",
        ),
        "privacy": (),
        "recorder_supported_now": True,
        "recorder_action": "none",
        "required_for_rehearsal": True,
        "required_for_campaign": True,
        "scientific_reason": "Primary driver-input channel for throttle-commitment and coasting blocks.",
    },
    {
        "channel": "steering_angle",
        "previous_classification": "available (measured)",
        "classification": DIRECTLY_AVAILABLE,
        "provenance": "measured",
        "variables": (_v("SteeringWheelAngle", "Float", 1, "rad"),),
        "semantics": "Steering wheel angle in radians.",
        "limitations": (
            "The inventory proves the variable and its unit but not the sign convention. The recorder and Labs both declare 'positive left'; that declaration is unverified by metadata and must be confirmed against live values before any sign-dependent metric is computed.",
        ),
        "privacy": (),
        "recorder_supported_now": True,
        "recorder_action": "none",
        "required_for_rehearsal": True,
        "required_for_campaign": True,
        "scientific_reason": "Required for steering and trajectory blocks and for turn-in characterisation.",
    },
    {
        "channel": "speed",
        "previous_classification": "available (measured)",
        "classification": DIRECTLY_AVAILABLE,
        "provenance": "measured",
        "variables": (_v("Speed", "Float", 1, "m/s"),),
        "semantics": "Vehicle speed in metres per second, described by the SDK as GPS vehicle speed.",
        "limitations": (
            "Described as GPS speed rather than a wheel-derived speed; it is a vehicle-frame ground speed and must not be treated as a wheel-rotation measurement.",
        ),
        "privacy": (),
        "recorder_supported_now": True,
        "recorder_action": "none",
        "required_for_rehearsal": True,
        "required_for_campaign": True,
        "scientific_reason": "Underpins corner-speed, approach-state comparability, and segment definitions.",
    },
    {
        "channel": "gear",
        "previous_classification": "available (measured)",
        "classification": DIRECTLY_AVAILABLE,
        "provenance": "measured",
        "variables": (_v("Gear", "Int", 1, None),),
        "semantics": "Selected gear, encoded -1 reverse, 0 neutral, 1..n forward gears.",
        "limitations": (
            "The number of forward gears is car-dependent; gear indices are not comparable across cars.",
        ),
        "privacy": (),
        "recorder_supported_now": True,
        "recorder_action": "none",
        "required_for_rehearsal": True,
        "required_for_campaign": True,
        "scientific_reason": "Needed to exclude shift transients and to interpret engine-state channels.",
    },
    {
        "channel": "rpm",
        "previous_classification": "available (measured)",
        "classification": DIRECTLY_AVAILABLE,
        "provenance": "measured",
        "variables": (_v("RPM", "Float", 1, "revs/min"),),
        "semantics": "Engine revolutions per minute.",
        "limitations": (
            "Car-dependent absolute scale; never comparable across cars without normalisation.",
        ),
        "privacy": (),
        "recorder_supported_now": True,
        "recorder_action": "none",
        "required_for_rehearsal": True,
        "required_for_campaign": True,
        "scientific_reason": "Supports shift detection and engine-state context for throttle work.",
    },
    {
        "channel": "longitudinal_acceleration",
        "previous_classification": "declared available if 'LonAccel' was present; that variable does not exist, so every recording would have declared it unavailable",
        "classification": DIRECTLY_AVAILABLE,
        "provenance": "measured",
        "variables": (_v("LongAccel", "Float", 1, "m/s^2"),),
        "semantics": "Longitudinal acceleration in the vehicle frame, including gravity.",
        "limitations": (
            "The value includes gravity, so it is not a pure inertial longitudinal acceleration on a graded or banked surface; gradient effects are confounded with driver-commanded acceleration.",
            "Sign convention is not proven by metadata and requires live-value confirmation.",
        ),
        "privacy": (),
        "recorder_supported_now": False,
        "recorder_action": "correct_existing_mapping",
        "required_for_rehearsal": True,
        "required_for_campaign": True,
        "scientific_reason": "The braking and brake-release blocks are the campaign's primary controlled conditions; deceleration evidence is not substitutable.",
    },
    {
        "channel": "lateral_acceleration",
        "previous_classification": "available (measured)",
        "classification": DIRECTLY_AVAILABLE,
        "provenance": "measured",
        "variables": (_v("LatAccel", "Float", 1, "m/s^2"),),
        "semantics": "Lateral acceleration in the vehicle frame, including gravity.",
        "limitations": (
            "Includes gravity, so banking contributes to the measured value.",
            "Sign convention is unproven by metadata.",
        ),
        "privacy": (),
        "recorder_supported_now": True,
        "recorder_action": "none",
        "required_for_rehearsal": True,
        "required_for_campaign": True,
        "scientific_reason": "Required for cornering-state characterisation and combined-grip context.",
    },
    {
        "channel": "yaw_rate",
        "previous_classification": "available (measured)",
        "classification": DIRECTLY_AVAILABLE,
        "provenance": "measured",
        "variables": (_v("YawRate", "Float", 1, "rad/s"),),
        "semantics": "Vehicle yaw rate in radians per second.",
        "limitations": ("Sign convention is unproven by metadata.",),
        "privacy": (),
        "recorder_supported_now": True,
        "recorder_action": "none",
        "required_for_rehearsal": True,
        "required_for_campaign": True,
        "scientific_reason": "Rotation evidence for turn-in and mid-corner behaviour.",
    },
    {
        "channel": "wheel_state",
        "previous_classification": "unavailable, pending live variable-table evidence",
        "classification": UNAVAILABLE,
        "provenance": "unavailable",
        "variables": (),
        "semantics": "Per-wheel rotational state (wheel speed, slip ratio, or lock-up state) as the profile defines it.",
        "limitations": (
            "The 331-variable inventory contains no per-wheel rotational speed, angular velocity, or slip-ratio variable of any kind.",
            "Shock deflection, shock velocity, brake-line pressure, and tyre odometer are corner-located chassis and tyre measurements. They are not wheel rotational state and must not be substituted for it.",
            "BrakeABSactive indicates ABS intervention, which is a consequence of wheel behaviour, not a measurement of it.",
        ),
        "privacy": (),
        "recorder_supported_now": False,
        "recorder_action": "keep_unavailable",
        "required_for_rehearsal": False,
        "required_for_campaign": False,
        "scientific_reason": "No first-campaign metric depends on wheel rotational state; declaring it unavailable is the honest outcome and closes a previously open question.",
    },
    {
        "channel": "tire_state",
        "previous_classification": "available, limited to middle carcass temperature and cold pressure",
        "classification": PARTIAL,
        "provenance": "measured",
        "variables": _TIRE_CARCASS_TEMPS + _TIRE_WEAR + _TIRE_COLD_PRESSURES + _TIRE_ODOMETERS + (
            _v("PlayerTireCompound", "Int", 1, None),
            _v("TireSetsUsed", "Int", 1, None),
            _v("TireSetsAvailable", "Int", 1, None),
        ),
        "semantics": (
            "Live per-corner carcass temperature at three across-tread positions (CL inner-to-outer left, CM middle, CR right), "
            "live per-corner percent tread remaining at three positions, per-corner distance travelled since the tyre was fitted, "
            "the current tyre compound index, and the garage-set cold inflation pressure."
        ),
        "limitations": (
            "COLD PRESSURE IS NOT LIVE PRESSURE. LFcoldPressure and its siblings are explicitly 'as set in the garage'. The inventory contains no hot or running tyre pressure variable at all, so live inflation pressure is genuinely unavailable and must never be inferred from the cold value.",
            "The recorder currently captures only the middle carcass temperature (CM) and the cold pressure, so across-tread temperature gradient and tread wear are proven available but not yet recorded.",
            "PlayerTireCompound is an integer index whose compound dictionary is car- and content-dependent and is not carried by the inventory.",
            "Tyre wear is reported as percent tread remaining, so it decreases with use; it is not a wear-accumulated quantity.",
        ),
        "privacy": (),
        "recorder_supported_now": True,
        "recorder_action": "add_new_capture",
        "required_for_rehearsal": False,
        "required_for_campaign": True,
        "scientific_reason": "Tyre temperature, wear, compound, and age are first-order confounds for any lap- or corner-level performance comparison across a 25-to-35 minute stint.",
    },
    {
        "channel": "fuel",
        "previous_classification": "available (measured)",
        "classification": DIRECTLY_AVAILABLE,
        "provenance": "measured",
        "variables": (
            _v("FuelLevel", "Float", 1, "l"),
            _v("FuelLevelPct", "Float", 1, "%"),
        ),
        "semantics": "Litres of fuel remaining and the corresponding fraction of tank capacity.",
        "limitations": (
            "Fuel mass depends on fuel density, which the inventory does not expose; Labs normalises a volume, not a mass.",
            "FuelUsePerHour exists as an instantaneous consumption rate in kg/h and is not currently captured.",
        ),
        "privacy": (),
        "recorder_supported_now": True,
        "recorder_action": "none",
        "required_for_rehearsal": True,
        "required_for_campaign": True,
        "scientific_reason": "Fuel load is a monotone within-stint confound on lap time and must be controlled or reported.",
    },
    {
        "channel": "setup",
        "previous_classification": "unavailable, pending live evidence and an approved setup declaration",
        "classification": PARTIAL,
        "provenance": "measured",
        "variables": _TIRE_COLD_PRESSURES + (
            _v("dcBrakeBias", "Float", 1, None),
            _v("dcABS", "Float", 1, None),
            _v("dcTractionControl", "Float", 1, None),
            _v("PitSvLFP", "Float", 1, "kPa"),
            _v("PitSvRFP", "Float", 1, "kPa"),
            _v("PitSvLRP", "Float", 1, "kPa"),
            _v("PitSvRRP", "Float", 1, "kPa"),
            _v("PitSvTireCompound", "Int", 1, None),
        ),
        "semantics": (
            "A partial vehicle-configuration view: garage-set cold inflation pressures, driver-adjustable brake bias, "
            "driver-adjustable ABS and traction-control settings, and pending pit-service pressure and compound selections."
        ),
        "limitations": (
            "THE FULL GARAGE SETUP REMAINS UNAVAILABLE. Suspension geometry, spring and damper rates, aerodynamic configuration, differential settings, and gearing are not present anywhere in the 331-variable inventory.",
            "These signals are configuration context, not a setup file, and must be declared in configuration-setup.json rather than promoting the setup channel to a measured full setup.",
            "Driver-adjustable values change during a session; they are a time-varying control state, not a static setup declaration.",
        ),
        "privacy": (),
        "recorder_supported_now": False,
        "recorder_action": "add_new_capture",
        "required_for_rehearsal": False,
        "required_for_campaign": True,
        "scientific_reason": "Brake bias and assist settings are directly relevant to the braking blocks, and an undocumented mid-campaign setup change would silently break comparability.",
    },
    {
        "channel": "assists",
        "previous_classification": "unavailable, pending live variable-table evidence",
        "classification": CAR_OR_SESSION_DEPENDENT,
        "provenance": "measured",
        "variables": (
            _v("dcABS", "Float", 1, None),
            _v("dcTractionControl", "Float", 1, None),
            _v("BrakeABSactive", "Bool", 1, None),
            _v("dcPitSpeedLimiterToggle", "Bool", 1, None),
            _v("SteeringFFBEnabled", "Bool", 1, None),
        ),
        "semantics": (
            "Two distinct kinds of evidence. dcABS and dcTractionControl are the driver-adjustable in-car assist SETTINGS. "
            "BrakeABSactive is an ACTUAL INTERVENTION flag, true while ABS is reducing brake force."
        ),
        "limitations": (
            "A SETTING IS NOT AN INTERVENTION. dcABS records what the driver selected; BrakeABSactive records what the system did. They answer different questions and must never be merged into one assist state.",
            "Assist exposure is car-dependent. A car that does not expose dcABS may still have ABS, and a car may expose the variable while the session or ruleset disables the assist.",
            "ABSENCE OF dcABS ACTIVITY IS NOT PROOF THAT A CAR HAS NO ABS. Any per-car assist conclusion needs explicit car-level provenance, not an inference from a missing or constant value.",
            "SteeringFFBEnabled describes the participant's force-feedback rig, not the vehicle, and is hardware context only.",
        ),
        "privacy": (),
        "recorder_supported_now": False,
        "recorder_action": "add_new_capture",
        "required_for_rehearsal": False,
        "required_for_campaign": True,
        "scientific_reason": "ABS intervention during braking would change what a braking-technique block actually measures; without it, an intervention-driven result could be misread as a technique effect.",
    },
    {
        "channel": "damage",
        "previous_classification": "unavailable, pending live variable-table evidence",
        "classification": UNAVAILABLE,
        "provenance": "unavailable",
        "variables": (),
        "semantics": "Physical vehicle damage state as the profile defines it.",
        "limitations": (
            "The inventory contains no vehicle damage-state variable: no per-part damage, no aerodynamic damage, no mechanical failure state.",
            "PitRepairLeft, PitOptRepairLeft, FastRepairAvailable, FastRepairUsed, PlayerFastRepairsUsed, and PlayerCarTowTime are repair-service and tow timers and counters. They indicate that repair time or a tow was required, not what is damaged or by how much.",
            "Repair evidence is retained separately as auxiliary session context and is deliberately not promoted into the damage channel.",
        ),
        "privacy": (),
        "recorder_supported_now": False,
        "recorder_action": "keep_unavailable",
        "required_for_rehearsal": False,
        "required_for_campaign": False,
        "scientific_reason": "Promoting a repair timer to a damage model would be an unsupported semantic upgrade; a damaged-car lap is instead excluded using incident, tow, and pit evidence.",
    },
    {
        "channel": "flags",
        "previous_classification": "unavailable, pending live variable-table evidence",
        "classification": PARTIAL,
        "provenance": "measured",
        "variables": (
            _v("SessionFlags", "BitField", 1, "irsdk_Flags"),
            _v("SessionState", "Int", 1, "irsdk_SessionState"),
            _v("PaceMode", "Int", 1, "irsdk_PaceMode"),
            _v("PitsOpen", "Bool", 1, None),
        ),
        "semantics": (
            "Session-level flag and state evidence for the player's session: the session flag bitfield, the session state, "
            "the pacing mode, and whether pit entry is currently permitted."
        ),
        "limitations": (
            "THE INVENTORY NAMES THE ENUMERATIONS BUT DOES NOT CARRY THEIR VALUE DICTIONARIES. It proves SessionFlags is an irsdk_Flags bitfield and SessionState an irsdk_SessionState enumeration, but it contains no bit-to-meaning or value-to-meaning table.",
            "Labs therefore cannot decode green, yellow, checkered, or pacing state from this evidence alone. The recorder links the real SDK and must export the authoritative value dictionary alongside the raw values.",
            "Until that dictionary is exported, raw bitfield values must be preserved verbatim and never interpreted, per the rule against analysing bitfields without authoritative meaning.",
            "PitsOpen is documented as applying to the current player, not as a global session property.",
        ),
        "privacy": (
            "CarIdxSessionFlags and CarIdxPaceFlags carry per-opponent flag state for up to 72 cars and are excluded from the initial corpus.",
        ),
        "recorder_supported_now": False,
        "recorder_action": "add_new_capture",
        "required_for_rehearsal": False,
        "required_for_campaign": True,
        "scientific_reason": "Caution, pacing, and session-state periods must be excludable. Without them, a yellow-flag lap can silently enter a comparison and corrupt it. The recorder declares the channel unavailable honestly today, so a mechanics rehearsal is unaffected; the campaign is not.",
    },
    {
        "channel": "weather",
        "previous_classification": "unavailable, pending live variable-table evidence",
        "classification": DIRECTLY_AVAILABLE,
        "provenance": "measured",
        "variables": (
            _v("AirTemp", "Float", 1, "C"),
            _v("AirPressure", "Float", 1, "Pa"),
            _v("AirDensity", "Float", 1, "kg/m^3"),
            _v("RelativeHumidity", "Float", 1, "%"),
            _v("Precipitation", "Float", 1, "%"),
            _v("FogLevel", "Float", 1, "%"),
            _v("WindVel", "Float", 1, "m/s"),
            _v("WindDir", "Float", 1, "rad"),
            _v("Skies", "Int", 1, None),
            _v("WeatherDeclaredWet", "Bool", 1, None),
        ),
        "semantics": (
            "Environment state at the start/finish line: air temperature, pressure, density, relative humidity, "
            "precipitation, fog, wind velocity and direction, sky condition, and the steward's wet declaration."
        ),
        "limitations": (
            "EVERY ATMOSPHERIC VARIABLE IS EXPLICITLY MEASURED AT THE START/FINISH LINE. It is a single-point measurement, not a track-wide field, and must not be presented as the condition at a specific corner.",
            "Skies is an integer condition index (0 clear, 1 partly cloudy, 2 mostly cloudy, 3 overcast) documented in the variable description itself; it is ordinal-looking but is a category.",
            "WeatherDeclaredWet is a stewarding decision about tyre eligibility, not a physical measurement of the surface.",
            "SolarAltitude and SolarAzimuth are available but are classified as derived secondary context, not environment state.",
        ),
        "privacy": (),
        "recorder_supported_now": False,
        "recorder_action": "add_new_capture",
        "required_for_rehearsal": False,
        "required_for_campaign": True,
        "scientific_reason": "Air density and temperature move grip and aerodynamic performance across a ten-hour campaign; without them a session-order effect and a weather effect are indistinguishable.",
    },
    {
        "channel": "traffic",
        "previous_classification": "unavailable, pending live evidence; position explicitly not treated as traffic",
        "classification": PARTIAL,
        "provenance": "measured",
        "variables": (
            _v("CarDistAhead", "Float", 1, "m"),
            _v("CarDistBehind", "Float", 1, "m"),
            _v("CarLeftRight", "Int", 1, "irsdk_CarLeftRight"),
        ),
        "semantics": (
            "A privacy-minimal three-signal proximity view: metres to the first car ahead, metres to the first car behind, "
            "and an enumerated indicator of a car alongside on the left or right."
        ),
        "limitations": (
            "CarLeftRight is an irsdk_CarLeftRight enumeration whose value dictionary the inventory does not carry, so alongside and overlap states cannot be decoded without the recorder exporting the authoritative dictionary.",
            "These three signals identify no opponent. They are relational distances and an alongside indicator, with no car index, name, or identity.",
            "CarDistAhead and CarDistBehind describe the nearest car only; they cannot describe a multi-car pack.",
            "The behaviour of these variables when the track is empty is not proven by metadata and needs live-value confirmation before a clear-air threshold is fixed.",
        ),
        "privacy": (
            "The 27 CarIdx* arrays covering up to 72 cars are deliberately excluded from the initial corpus.",
            "Opponent identity, radio participant variables (RadioTransmitCarIdx, RadioTransmitFrequencyIdx, RadioTransmitRadioIdx), and session identifiers that could resolve to public results are never captured.",
        ),
        "recorder_supported_now": False,
        "recorder_action": "add_new_capture",
        "required_for_rehearsal": False,
        "required_for_campaign": True,
        "scientific_reason": "Clear-air versus compromised laps is the single largest uncontrolled confound in naturalistic driving blocks; three scalars close most of it at negligible volume and privacy cost.",
    },
    {
        "channel": "track_conditions",
        "previous_classification": "unavailable, pending live variable-table evidence",
        "classification": PARTIAL,
        "provenance": "measured",
        "variables": (
            _v("TrackTempCrew", "Float", 1, "C"),
            _v("TrackWetness", "Int", 1, "irsdk_TrackWetness"),
            _v("PlayerTrackSurface", "Int", 1, "irsdk_TrkLoc"),
            _v("PlayerTrackSurfaceMaterial", "Int", 1, "irsdk_TrkSurf"),
        ),
        "semantics": (
            "Track-surface context distinct from weather: crew-measured track temperature, average surface wetness, "
            "and the player car's own track location and surface material."
        ),
        "limitations": (
            "TrackTempCrew is temperature MEASURED BY THE CREW AROUND THE TRACK. It is not the surface temperature at an arbitrary point on track and must be labelled with that provenance.",
            "TrackWetness is explicitly the AVERAGE track surface wetness. It cannot represent a locally wet corner or a drying line.",
            "TrackWetness, PlayerTrackSurface, and PlayerTrackSurfaceMaterial are irsdk_* enumerations whose value dictionaries the inventory does not carry.",
            "TRACK LOCATION AND SURFACE MATERIAL ARE NOT WEATHER AND NOT A CONDITION SCORE. They describe where the car is and what it is on. These distinct concepts must never be collapsed into a single 'track condition' number.",
            "The variable TrackTemp exists but the inventory documents it as deprecated and set to TrackTempCrew; Labs must read TrackTempCrew and never TrackTemp.",
        ),
        "privacy": (
            "CarIdxTrackSurface and CarIdxTrackSurfaceMaterial expose per-opponent location for up to 72 cars and are excluded.",
        ),
        "recorder_supported_now": False,
        "recorder_action": "add_new_capture",
        "required_for_rehearsal": False,
        "required_for_campaign": True,
        "scientific_reason": "Track temperature drives grip evolution across a stint, and off-track or wet samples must be excludable rather than silently pooled.",
    },
)


# Evidence that is real and useful but deliberately kept outside the twenty
# profile channels, so that the top-level contract is not widened just because
# data exists.
AUXILIARY_EVIDENCE: tuple[dict[str, Any], ...] = (
    {
        "category": "suspension_state",
        "classification": CAR_OR_SESSION_DEPENDENT,
        "variables": _SHOCK_DEFLECTION + _SHOCK_VELOCITY + _BRAKE_LINE_PRESSURE + _TIRE_ODOMETERS,
        "semantics": "Per-corner shock deflection and velocity, brake-line pressure, and tyre distance travelled.",
        "decision": "Recorded as available auxiliary evidence. NOT promoted into wheel_state, which means wheel rotational state.",
        "rationale": "Real corner-level chassis evidence, but no first-campaign question depends on it, and mislabelling it as wheel state would be semantic overreach.",
        "required_for_rehearsal": False,
        "required_for_campaign": False,
    },
    {
        "category": "repair_and_tow_state",
        "classification": DIRECTLY_AVAILABLE,
        "variables": (
            _v("PitRepairLeft", "Float", 1, "s"),
            _v("PitOptRepairLeft", "Float", 1, "s"),
            _v("FastRepairAvailable", "Int", 1, None),
            _v("FastRepairUsed", "Int", 1, None),
            _v("PlayerFastRepairsUsed", "Int", 1, None),
            _v("PlayerCarTowTime", "Float", 1, "s"),
        ),
        "semantics": "Mandatory and optional repair time remaining, fast-repair availability and usage, and tow time.",
        "decision": "Retained as auxiliary exclusion evidence. Explicitly NOT promoted to the damage channel.",
        "rationale": "Useful for excluding laps affected by a repair or tow, while making no claim about physical damage state.",
        "required_for_rehearsal": False,
        "required_for_campaign": False,
    },
    {
        "category": "solar_geometry",
        "classification": DERIVABLE,
        "variables": (
            _v("SolarAltitude", "Float", 1, "rad"),
            _v("SolarAzimuth", "Float", 1, "rad"),
            _v("SessionTimeOfDay", "Float", 1, "s"),
        ),
        "semantics": "Sun elevation above the horizon and bearing clockwise from north, plus session time of day.",
        "decision": "Secondary derived context, not environment state. Not required for the first campaign.",
        "rationale": "Solar geometry follows from track location and time of day; it is a visibility and surface-heating covariate, not an independent weather measurement.",
        "required_for_rehearsal": False,
        "required_for_campaign": False,
    },
    {
        "category": "session_and_incident_context",
        "classification": DIRECTLY_AVAILABLE,
        "variables": (
            _v("PlayerCarMyIncidentCount", "Int", 1, None),
            _v("OnPitRoad", "Bool", 1, None),
            _v("PlayerCarInPitStall", "Bool", 1, None),
            _v("PitstopActive", "Bool", 1, None),
            _v("PlayerCarWeightPenalty", "Float", 1, "kg"),
            _v("LapDist", "Float", 1, "m"),
            _v("LapDistPct", "Float", 1, "%"),
        ),
        "semantics": "The participant's own incident count, pit-lane and pit-stall state, any weight penalty, and lap distance.",
        "decision": "Incident count, pit road state, and lap distance are already captured. Pit-stall, pit-service, and weight-penalty evidence are recommended additions.",
        "rationale": "These define lap validity and exclusion boundaries. A weight penalty is a step change in vehicle mass that would otherwise appear as an unexplained performance shift.",
        "required_for_rehearsal": False,
        "required_for_campaign": True,
    },
    {
        "category": "raw_driver_inputs",
        "classification": NOT_JUSTIFIED,
        "variables": (
            _v("BrakeRaw", "Float", 1, "%"),
            _v("ThrottleRaw", "Float", 1, "%"),
            _v("ClutchRaw", "Float", 1, "%"),
            _v("HandbrakeRaw", "Float", 1, "%"),
        ),
        "semantics": "Pre-processing pedal and handbrake inputs, before in-sim input processing.",
        "decision": "Excluded from the initial corpus.",
        "rationale": "The first campaign asks what the driver commanded the car to do, which the processed Brake and Throttle channels answer. Raw inputs would only separate hardware calibration from driver intent, which is not a first-campaign question.",
        "required_for_rehearsal": False,
        "required_for_campaign": False,
    },
    {
        "category": "lap_delta_estimates",
        "classification": NOT_JUSTIFIED,
        "variables": (
            _v("LapDeltaToBestLap", "Float", 1, "s"),
            _v("LapDeltaToOptimalLap", "Float", 1, "s"),
            _v("LapDeltaToSessionBestLap", "Float", 1, "s"),
        ),
        "semantics": "Simulator-computed running delta to a reference lap.",
        "decision": "Excluded from the initial corpus.",
        "rationale": "These are the simulator's own derived estimates against an undocumented reference. Labs computes its own comparisons from measured channels under a frozen protocol; ingesting a black-box delta would import an unauditable method.",
        "required_for_rehearsal": False,
        "required_for_campaign": False,
    },
    {
        "category": "opponent_arrays",
        "classification": NOT_JUSTIFIED,
        "variables": (
            _v("CarIdxLapDistPct", "Float", 72, "%"),
            _v("CarIdxPosition", "Int", 72, None),
            _v("CarIdxOnPitRoad", "Bool", 72, None),
            _v("CarIdxTireCompound", "Int", 72, None),
            _v("CarIdxSessionFlags", "BitField", 72, "irsdk_Flags"),
        ),
        "semantics": "Per-opponent state arrays covering up to 72 cars. Twenty-seven such arrays exist in the inventory.",
        "decision": "Excluded from the initial corpus. Any later need is a separately reviewed expansion.",
        "rationale": "Volume, opponent-provenance complexity, and analytical complexity with no first-campaign question requiring them. CarDistAhead, CarDistBehind, and CarLeftRight answer the traffic question at a fraction of the cost.",
        "required_for_rehearsal": False,
        "required_for_campaign": False,
    },
    {
        "category": "push_to_pass",
        "classification": CAR_OR_SESSION_DEPENDENT,
        "variables": (
            _v("P2P_Status", "Bool", 1, None),
            _v("P2P_Count", "Int", 1, None),
        ),
        "semantics": "Push-to-pass activation state and usage count for the player's car.",
        "decision": "Excluded unless a selected car exposes push-to-pass.",
        "rationale": "Strongly car-dependent. If a campaign car has it, an activation is a step change in available power and would confound a throttle block; capture becomes required only for such a car.",
        "required_for_rehearsal": False,
        "required_for_campaign": False,
    },
)


# The 360 Hz sub-sample assessment. Metadata proves these channels exist and
# carry six values described as 360 Hz. It proves nothing about their ordering
# or their individual timestamps.
SUB_SAMPLE_ASSESSMENT: dict[str, Any] = {
    "sdk_evidence": {
        "channel_count": 18,
        "array_count": 6,
        "declared_rate_hz": 360,
        "described_as": "The description of every such variable states 'at 360 Hz'.",
    },
    "first_tier_candidates": ("LongAccel_ST", "LatAccel_ST", "YawRate_ST"),
    "second_tier_candidates": (
        "SteeringWheelTorque_ST",
        "LFshockDefl_ST", "RFshockDefl_ST", "LRshockDefl_ST", "RRshockDefl_ST",
        "LFshockVel_ST", "RFshockVel_ST", "LRshockVel_ST", "RRshockVel_ST",
    ),
    "proven_semantics": (
        "Each listed variable is a Float array of exactly six elements.",
        "Each description declares a 360 Hz rate.",
        "A 360 Hz rate against a 60 Hz recorder cadence is arithmetically consistent with six sub-samples per update.",
    ),
    "unresolved_questions": (
        "Element ordering is not proven. Whether index 0 is the oldest or the newest sub-sample is not stated anywhere in the inventory.",
        "Per-sub-sample timestamps are not proven. The inventory carries no time offset, and inventing evenly spaced offsets would be fabricated provenance.",
        "The relationship to the SDK update is not proven. Whether the six samples precede, straddle, or follow the update tick is unstated.",
        "Behaviour across a dropped, repeated, or stale update tick is not proven. If the recorder misses a tick, whether sub-samples are lost or repeated is unknown.",
        "Behaviour across session transitions, resets, and reconnects is not proven.",
    ),
    "storage_implications": (
        "The three first-tier channels alone multiply their sample count sixfold, adding roughly 18 values per 60 Hz update.",
        "Across the planned ten-hour campaign this is a material but not prohibitive increase for three channels; all eighteen channels would be a far larger commitment.",
        "Labs' current normalized record model has no sub-sample nesting, so support would require new record or field structure, not merely new columns.",
    ),
    "labs_support_today": False,
    "recommendation": "defer_until_timing_semantics_proven",
    "recommendation_rationale": (
        "The scientific value is real: 360 Hz longitudinal acceleration, lateral acceleration, and yaw rate would materially "
        "sharpen brake-application, turn-in, and rotation analysis. But a sub-sample whose position in time is unproven cannot "
        "carry temporal meaning, and Labs must not invent offsets it cannot evidence. Capturing them with fabricated timing "
        "would produce a corpus that looks higher-resolution while being unusable for exactly the transient analysis that "
        "motivates it. The 60 Hz channels remain sufficient for the first campaign's questions."
    ),
    "how_to_resolve": (
        "Read the authoritative irsdk_defines header or SDK documentation for the sub-sample array contract.",
        "Confirm ordering and tick relationship against live values once the corrected recorder runs.",
        "Only then decide between an optional secondary evidence stream and main-contract capture.",
    ),
    "campaign_decision": "The first campaign proceeds at the 60 Hz recorder cadence. No _ST channel is captured.",
}


# Confounds this evidence makes measurable. Measurable is not the same as
# primary; several of these will only ever be reported, never analysed.
CONFOUND_MODEL: tuple[dict[str, Any], ...] = (
    {"confound": "weather", "measurable": True, "basis": "AirTemp, AirPressure, AirDensity, RelativeHumidity, Precipitation, FogLevel, WindVel, WindDir, Skies", "role": "report_and_control", "note": "Start/finish-line point measurement only.", "previously": "not measurable"},
    {"confound": "track_wetness", "measurable": True, "basis": "TrackWetness, WeatherDeclaredWet, Precipitation", "role": "exclusion_criterion", "note": "Average surface wetness; enumeration dictionary still required.", "previously": "not measurable"},
    {"confound": "track_temperature", "measurable": True, "basis": "TrackTempCrew", "role": "report_and_control", "note": "Crew-measured, not per-point.", "previously": "not measurable"},
    {"confound": "traffic", "measurable": True, "basis": "CarDistAhead, CarDistBehind, CarLeftRight", "role": "exclusion_criterion", "note": "Nearest-car proximity only; no pack structure.", "previously": "not measurable"},
    {"confound": "tire_compound", "measurable": True, "basis": "PlayerTireCompound", "role": "comparability_stratifier", "note": "Integer index; compound dictionary is car-dependent.", "previously": "not measurable"},
    {"confound": "tire_wear", "measurable": True, "basis": "LFwearL/M/R and siblings for all four corners", "role": "report_and_control", "note": "Percent tread remaining; proven available, not yet recorded.", "previously": "not measurable"},
    {"confound": "tire_age_or_distance", "measurable": True, "basis": "LFodometer, RFodometer, LRodometer, RRodometer, TireSetsUsed", "role": "report_and_control", "note": "Distance since the tyre was fitted.", "previously": "not measurable"},
    {"confound": "tire_temperature", "measurable": True, "basis": "Twelve carcass temperatures across four corners and three tread positions", "role": "report_and_control", "note": "Recorder currently captures the middle position only.", "previously": "partially measurable"},
    {"confound": "fuel_load", "measurable": True, "basis": "FuelLevel, FuelLevelPct", "role": "report_and_control", "note": "Volume, not mass.", "previously": "measurable"},
    {"confound": "incidents", "measurable": True, "basis": "PlayerCarMyIncidentCount", "role": "exclusion_criterion", "note": "Already captured.", "previously": "measurable"},
    {"confound": "pit_state", "measurable": True, "basis": "OnPitRoad, PlayerCarInPitStall, PitstopActive, PitsOpen", "role": "exclusion_criterion", "note": "OnPitRoad already captured; the rest are additions.", "previously": "partially measurable"},
    {"confound": "assists", "measurable": True, "basis": "dcABS, dcTractionControl settings and BrakeABSactive intervention", "role": "report_and_control", "note": "Car-dependent; setting and intervention are distinct.", "previously": "not measurable"},
    {"confound": "weight_penalty", "measurable": True, "basis": "PlayerCarWeightPenalty", "role": "report_and_control", "note": "A step change in vehicle mass.", "previously": "not measurable"},
    {"confound": "session_type_and_flag_state", "measurable": True, "basis": "SessionState, SessionFlags, PaceMode", "role": "exclusion_criterion", "note": "Requires the SDK enumeration dictionary before decoding.", "previously": "partially measurable"},
    {"confound": "track_surface_location", "measurable": True, "basis": "PlayerTrackSurface, PlayerTrackSurfaceMaterial", "role": "exclusion_criterion", "note": "Off-track and surface-material exclusion; enumeration dictionary required.", "previously": "partially measurable"},
    {"confound": "live_tire_pressure", "measurable": False, "basis": "No hot or running tyre pressure variable exists in the inventory.", "role": "unavailable", "note": "Cold garage pressure must never be substituted.", "previously": "not measurable"},
    {"confound": "vehicle_damage_state", "measurable": False, "basis": "No damage-state variable exists; only repair and tow timers.", "role": "unavailable", "note": "Repair evidence supports exclusion, not a damage model.", "previously": "not measurable"},
    {"confound": "full_garage_setup", "measurable": False, "basis": "No suspension geometry, spring, damper, aerodynamic, differential, or gearing variable exists.", "role": "unavailable", "note": "Partial configuration only, declared in configuration-setup.json.", "previously": "not measurable"},
)


def _verify_variables(
    inventory: VariableInventory, claims: tuple[dict[str, Any], ...], context: str
) -> list[dict[str, Any]]:
    verified: list[dict[str, Any]] = []
    for claim in claims:
        variable = inventory.require(
            claim["name"],
            sdk_type=claim["sdk_type"],
            count=claim["count"],
            unit=claim["unit"],
            context=context,
        )
        verified.append({**variable.as_dict(), "requires_enum_dictionary": variable.requires_enum_dictionary})
    return verified


def build_capability_map(inventory: VariableInventory) -> dict[str, Any]:
    """Reconcile the recorder profile against one inventory snapshot.

    Every supporting variable is re-checked against the inventory. A channel that
    names a variable the simulator does not expose fails here rather than
    surviving as an unverified capability claim.
    """
    declared = tuple(entry["channel"] for entry in CHANNEL_RECONCILIATION)
    if declared != REQUIRED_CHANNELS:
        raise ContractValidationError(
            "capability map: channel reconciliation does not cover the profile channels in order"
        )
    channels: list[dict[str, Any]] = []
    for entry in CHANNEL_RECONCILIATION:
        context = f"capability map channel {entry['channel']!r}"
        if entry["classification"] not in CLASSIFICATIONS:
            raise ContractValidationError(f"{context}: unknown classification")
        if entry["recorder_action"] not in RECORDER_ACTIONS:
            raise ContractValidationError(f"{context}: unknown recorder action")
        if entry["provenance"] not in PROVENANCE:
            raise ContractValidationError(f"{context}: unknown provenance")
        variables = _verify_variables(inventory, entry["variables"], context)
        if entry["classification"] == UNAVAILABLE and variables:
            raise ContractValidationError(
                f"{context}: an unavailable channel must not claim supporting variables"
            )
        if entry["classification"] != UNAVAILABLE and not variables:
            raise ContractValidationError(
                f"{context}: an available channel must name the variables that support it"
            )
        channels.append({
            "channel": entry["channel"],
            "previous_classification": entry["previous_classification"],
            "classification": entry["classification"],
            "provenance": entry["provenance"],
            "semantics": entry["semantics"],
            "iracing_variables": variables,
            "limitations": list(entry["limitations"]),
            "privacy_restrictions": list(entry["privacy"]),
            "recorder_supported_now": entry["recorder_supported_now"],
            "recorder_action": entry["recorder_action"],
            "required_for_rehearsal": entry["required_for_rehearsal"],
            "required_for_campaign": entry["required_for_campaign"],
            "scientific_reason": entry["scientific_reason"],
            "requires_enum_dictionary": sorted(
                item["name"] for item in variables if item["requires_enum_dictionary"]
            ),
        })

    auxiliary: list[dict[str, Any]] = []
    for entry in AUXILIARY_EVIDENCE:
        context = f"capability map auxiliary category {entry['category']!r}"
        if entry["classification"] not in CLASSIFICATIONS:
            raise ContractValidationError(f"{context}: unknown classification")
        auxiliary.append({
            "category": entry["category"],
            "classification": entry["classification"],
            "semantics": entry["semantics"],
            "iracing_variables": _verify_variables(inventory, entry["variables"], context),
            "decision": entry["decision"],
            "rationale": entry["rationale"],
            "required_for_rehearsal": entry["required_for_rehearsal"],
            "required_for_campaign": entry["required_for_campaign"],
        })

    sub_samples = dict(SUB_SAMPLE_ASSESSMENT)
    observed_st = sorted(name for name in inventory.names if name.endswith("_ST"))
    for name in sub_samples["first_tier_candidates"] + sub_samples["second_tier_candidates"]:
        inventory.require(name, sdk_type="Float", count=6, context="capability map sub-sample candidate")
    sub_samples["available_channels"] = observed_st
    if len(observed_st) != sub_samples["sdk_evidence"]["channel_count"]:
        raise ContractValidationError(
            "capability map: sub-sample channel count does not match the inventory"
        )

    return {
        "schema_version": CAPABILITY_MAP_CONTRACT,
        "recorder_profile_id": RECORDER_PROFILE_ID,
        "evidence": {
            "kind": "point_in_time_simulator_capability_snapshot",
            "inventory_schema_version": inventory.schema_version,
            "inventory_sha256": inventory.source_sha256,
            "variable_count": len(inventory),
            "values_sampled": inventory.values_sampled,
            "direct_identifiers_included": inventory.direct_identifiers_included,
            "caveat": (
                "This snapshot proves what one iRacing build exposed in one session. It is not eternal "
                "simulator truth, it proves capability rather than behaviour, and it supports no scientific "
                "finding because no telemetry values were sampled."
            ),
        },
        "channels": channels,
        "auxiliary_evidence": auxiliary,
        "sub_sample_360hz": sub_samples,
        "confound_model": [dict(item) for item in CONFOUND_MODEL],
    }


def product_recorder_handoff(capability_map: dict[str, Any]) -> dict[str, Any]:
    """Extract the exact product-side change list implied by the capability map."""
    corrections = [
        entry for entry in capability_map["channels"]
        if entry["recorder_action"] == "correct_existing_mapping"
    ]
    additions = [
        entry for entry in capability_map["channels"]
        if entry["recorder_action"] == "add_new_capture"
    ]
    return {
        "boundary": (
            "Apex Labs never modifies the Apex Sim Coach repository. This is a review artifact for a "
            "separate, owner-reviewed product checkpoint."
        ),
        "blocking_corrections": [
            {
                "channel": entry["channel"],
                "iracing_variables": [item["name"] for item in entry["iracing_variables"]],
                "required_for_rehearsal": entry["required_for_rehearsal"],
                "reason": entry["previous_classification"],
            }
            for entry in corrections
        ],
        "capture_additions": [
            {
                "channel": entry["channel"],
                "iracing_variables": [item["name"] for item in entry["iracing_variables"]],
                "required_for_rehearsal": entry["required_for_rehearsal"],
                "required_for_campaign": entry["required_for_campaign"],
                "privacy_restrictions": entry["privacy_restrictions"],
                "requires_enum_dictionary": entry["requires_enum_dictionary"],
            }
            for entry in additions
        ],
        "sequencing_requirement": (
            "The recorder sample-column list and the Labs sample header are matched exactly on both sides. "
            "Any new sample column must land in the product recorder and in Labs together; a one-sided change "
            "makes every bundle fail its header check."
        ),
        "enum_dictionary_requirement": (
            "Any enumerated or bitfield channel must be exported with the authoritative SDK value dictionary "
            "in recorder-metadata.json alongside the raw value. Labs will not guess bit or enum meanings."
        ),
    }


def rehearsal_readiness(inventory: VariableInventory) -> dict[str, Any]:
    """Report campaign and rehearsal readiness against the profile channel inventory.

    Optional environmental and traffic evidence never fails this gate. Only a
    channel the protocol actually requires can block a rehearsal.
    """
    capability_map = build_capability_map(inventory)
    channels = capability_map["channels"]

    supported_now = [entry["channel"] for entry in channels if entry["recorder_supported_now"]]
    expected_unavailable = [entry["channel"] for entry in channels if entry["classification"] == UNAVAILABLE]
    car_dependent = [
        entry["channel"] for entry in channels
        if entry["classification"] == CAR_OR_SESSION_DEPENDENT
    ]
    semantically_limited = [entry["channel"] for entry in channels if entry["classification"] == PARTIAL]
    blocking = [
        entry["channel"] for entry in channels
        if entry["required_for_rehearsal"] and not entry["recorder_supported_now"]
    ]
    campaign_gaps = [
        entry["channel"] for entry in channels
        if entry["required_for_campaign"] and not entry["recorder_supported_now"]
    ]
    optional_gaps = [
        entry["channel"] for entry in channels
        if not entry["required_for_campaign"]
        and not entry["recorder_supported_now"]
        and entry["classification"] != UNAVAILABLE
    ]
    # A channel can be declared available while carrying only part of the evidence
    # the inventory proves exists. tire_state is captured today, but only its
    # middle carcass temperature and cold pressure, so a gap list keyed on
    # availability alone would hide the shortfall.
    capture_expansion = [
        entry["channel"] for entry in channels if entry["recorder_action"] == "add_new_capture"
    ]
    partially_captured = [
        entry["channel"] for entry in channels
        if entry["recorder_supported_now"] and entry["recorder_action"] == "add_new_capture"
    ]

    profile_mismatch = sorted(set(REQUIRED_CHANNELS) ^ {entry["channel"] for entry in channels})

    return {
        "recorder_profile_id": RECORDER_PROFILE_ID,
        "contract_version_change_required": False,
        "contract_version_rationale": (
            "The export contract already expresses available/unavailable, provenance, unit, axis and sign, and "
            "missing-value semantics per channel, and recorder-metadata.json accepts additional declarations. "
            "Every promotion in this pass fits those existing semantics, so "
            "apex-labs-research-recorder-profile/1.0.0 is retained."
        ),
        "expected_channels": list(REQUIRED_CHANNELS),
        "currently_supported_channels": supported_now,
        "expected_unavailable_channels": expected_unavailable,
        "car_or_session_dependent_channels": car_dependent,
        "semantically_limited_channels": semantically_limited,
        "missing_required_evidence_for_rehearsal": blocking,
        "missing_required_evidence_for_campaign": campaign_gaps,
        "channels_requiring_capture_expansion": capture_expansion,
        "partially_captured_channels": partially_captured,
        "optional_evidence_not_yet_captured": optional_gaps,
        "inventory_profile_mismatch": profile_mismatch,
        "sub_sample_recommendation": capability_map["sub_sample_360hz"]["recommendation"],
        "ready_for_rehearsal": not blocking and not profile_mismatch,
        "verdict": (
            "READY FOR 30-MINUTE REHEARSAL"
            if not blocking and not profile_mismatch
            else "RECORDER UPDATE REQUIRED BEFORE REHEARSAL"
        ),
        "handoff": product_recorder_handoff(capability_map),
    }
