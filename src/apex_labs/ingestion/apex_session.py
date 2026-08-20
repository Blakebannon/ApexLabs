"""Secure adapter for Apex Sim Coach customer session bundles.

The supported telemetry rows are one-metre aggregates.  They are deliberately
normalized as ``distance_bin`` records, never as timestamped simulator frames.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import stat
import unicodedata
import zipfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterable, Iterator

from apex_labs.atomic import atomic_output_directory
from apex_labs.errors import ContractValidationError, IngestionError, IntegrityError
from apex_labs.io import canonical_json_bytes, parse_json_bytes, read_json, validate_contract_path, write_json
from apex_labs.normalization.concepts import CANONICAL_CONVENTIONS, CANONICAL_UNITS, NORMALIZED_CONCEPTS
from apex_labs.normalization.integrity import NormalizedIntegrityTracker
from apex_labs.provenance import (
    apex_labs_code_identity,
    build_dataset_fingerprint,
    normalized_dataset_fingerprint_basis,
    require_research_code_identity,
    sha256_bytes,
    sha256_file,
)
from apex_labs.schemas import (
    validate_apex_session_manifest,
    validate_adapter_conformance,
    validate_collection_record,
    validate_normalized_manifest,
    validate_normalized_record,
    validate_product_annotations,
)
from apex_labs.schemas.versions import (
    APEX_SESSION_EXPORT,
    NORMALIZATION_VERSION,
    NORMALIZED_MANIFEST,
    NORMALIZED_RECORD,
    PRODUCT_ANNOTATIONS,
)

ADAPTER_ID = "apex-session-export"
ADAPTER_VERSION = "1.0.0"
CONFORMANCE_SCHEMA = "apex-labs.adapter-conformance/v1"

MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_ENTRY_COUNT = 32
MAX_ENTRY_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_COMPRESSION_RATIO = 250
MAX_LAP_ROWS = 100_000
MAX_TELEMETRY_ROWS = 2_000_000
MAX_CSV_FIELD_BYTES = 64 * 1024

REQUIRED_ENTRIES = {
    "README.md",
    "session-summary.md",
    "analysis-prompt.md",
    "data-dictionary.md",
    "findings.json",
    "laps.csv",
    "telemetry.csv",
    "manifest.json",
}
MANIFESTED_ENTRIES = REQUIRED_ENTRIES - {"manifest.json"}

LAP_HEADERS = [
    "lap_number", "lap_time_seconds", "lap_time_display", "is_best_valid_lap",
    "is_reviewed_lap", "is_valid", "is_reference", "exclusion_reasons", "lap_kind",
    "stint", "laps_since_pit_exit", "sampled_bins", "total_bins", "coverage_fraction",
    "coaching_delivered_on_lap", "delivered_cue_count",
]
TELEMETRY_HEADERS = [
    "lap_number", "distance_m", "lap_fraction", "brake", "throttle", "steering_rad",
    "steering_deg", "speed_ms", "speed_kph", "sample_count", "has_sample",
    "lap_is_valid", "lap_is_reference", "lap_is_excluded", "lap_exclusion_reason",
    "lap_kind", "stint", "incident_on_lap", "in_finding_region", "finding_keys",
]
FINDINGS_TOP_KEYS = {
    "schema", "productVersion", "referencePolicy", "timeDeltaConvention", "session", "findings",
}
FINDING_SESSION_KEYS = {
    "simulator", "car", "track", "sessionType", "recordedLocal", "durationSeconds",
    "trackLengthMeters", "reviewedLapNumber", "comparableLapCount", "comparableLapNumbers",
    "bestValidLapNumber", "bestValidLapTimeSeconds", "driverDisplayName",
}
FINDING_KEYS = {
    "key", "rank", "channel", "findingType", "lapNumber", "startDistanceMeters",
    "endDistanceMeters", "startLapFraction", "endLapFraction", "locationLabel",
    "observedValue", "referenceValue", "referenceSpread", "measurementUnit", "direction",
    "confidence", "confidenceBand", "severitySigma", "repeatability",
    "cleanComparisonLapCount", "coverage", "performanceVerdict", "timeDeltaSeconds",
    "timeDeltaUnavailableReason", "recommendedAction", "limitations", "attributionState",
    "attribution", "deterministicExplanation", "aiExplanation", "aiExplanationSource",
    "aiFallbackCategory",
}


@dataclass(frozen=True)
class BundleAudit:
    bundle_sha256: str
    manifest_sha256: str
    manifest: dict[str, Any]
    laps: tuple[dict[str, Any], ...]
    findings_document: dict[str, Any]
    inventory: tuple[dict[str, Any], ...]
    telemetry_rows: int
    sampled_bins: int
    source_frames_represented: int
    bins_per_lap: int
    valid_laps: int
    reference_laps: int
    excluded_laps: int
    reviewed_lap: int
    lap_fraction_rule: str
    limitations: tuple[str, ...]

    def report(self) -> dict[str, Any]:
        session = self.findings_document["session"]
        return {
            "valid": True,
            "source_schema_version": self.manifest["schema"],
            "product_version": self.manifest["productVersion"],
            "privacy_mode": self.manifest["privacyMode"],
            "bundle_sha256": self.bundle_sha256,
            "manifest_sha256": self.manifest_sha256,
            "inventory": list(self.inventory),
            "session": {
                "simulator": session["simulator"],
                "car": session["car"],
                "track": session["track"],
                "session_type": session["sessionType"],
                "duration_seconds": session["durationSeconds"],
                "track_length_meters": session["trackLengthMeters"],
                "reviewed_lap": self.reviewed_lap,
            },
            "counts": {
                "laps": len(self.laps),
                "telemetry_distance_bins": self.telemetry_rows,
                "bins_per_lap": self.bins_per_lap,
                "sampled_bins": self.sampled_bins,
                "source_frames_represented": self.source_frames_represented,
                "valid_laps": self.valid_laps,
                "reference_laps": self.reference_laps,
                "excluded_laps": self.excluded_laps,
                "product_annotations": len(self.findings_document["findings"]),
            },
            "source_semantics": "distance_binned_aggregate_not_raw_frames",
            "lap_fraction_rule": self.lap_fraction_rule,
            "limitations": list(self.limitations),
        }


@dataclass
class _Snapshot:
    path: Path
    bundle_sha256: str
    archive: zipfile.ZipFile
    infos: dict[str, zipfile.ZipInfo]

    def read_bounded(self, name: str) -> bytes:
        info = self.infos[name]
        if info.file_size > MAX_ENTRY_BYTES:
            raise IngestionError(f"Archive entry exceeds the {MAX_ENTRY_BYTES}-byte limit: {name}")
        with self.archive.open(info, "r") as handle:
            content = handle.read(MAX_ENTRY_BYTES + 1)
        if len(content) != info.file_size:
            raise IntegrityError(f"Archive entry size changed while reading: {name}")
        return content

    def open_text(self, name: str) -> io.TextIOWrapper:
        return io.TextIOWrapper(self.archive.open(self.infos[name], "r"), encoding="utf-8", errors="strict", newline="")


def _portable_archive_name(name: str) -> str:
    if unicodedata.normalize("NFC", name) != name:
        raise IngestionError(f"Archive entry name is not Unicode NFC canonical: {name!r}")
    return validate_contract_path(name)


@contextmanager
def _snapshot_bundle(source: Path) -> Iterator[_Snapshot]:
    source = source.resolve()
    try:
        size = source.stat().st_size
    except FileNotFoundError as exc:
        raise IngestionError(f"Apex session bundle does not exist: {source}") from exc
    if not source.is_file() or source.is_symlink():
        raise IngestionError("Apex session bundle must be a regular, non-symlink file")
    if size > MAX_ARCHIVE_BYTES:
        raise IngestionError(f"Archive exceeds the {MAX_ARCHIVE_BYTES}-byte compressed limit")
    with TemporaryDirectory(prefix="apex-labs-apex-session-") as temporary:
        snapshot = Path(temporary) / "source.zip"
        digest = hashlib.sha256()
        copied = 0
        with source.open("rb") as source_handle, snapshot.open("xb") as target_handle:
            while chunk := source_handle.read(1024 * 1024):
                copied += len(chunk)
                if copied > MAX_ARCHIVE_BYTES:
                    raise IngestionError("Archive grew beyond the compressed-size limit while snapshotting")
                digest.update(chunk)
                target_handle.write(chunk)
        try:
            archive = zipfile.ZipFile(snapshot, "r")
        except zipfile.BadZipFile as exc:
            raise IngestionError(f"Malformed ZIP archive: {exc}") from exc
        try:
            infos_list = archive.infolist()
            if len(infos_list) > MAX_ENTRY_COUNT:
                raise IngestionError(f"Archive has more than {MAX_ENTRY_COUNT} entries")
            infos: dict[str, zipfile.ZipInfo] = {}
            portable_seen: set[str] = set()
            total_expanded = 0
            for info in infos_list:
                name = _portable_archive_name(info.filename)
                key = name.replace("\\", "/").casefold()
                if key in portable_seen:
                    raise IngestionError(f"Duplicate or case/separator-ambiguous ZIP entry: {name}")
                portable_seen.add(key)
                if info.is_dir():
                    raise IngestionError(f"Directories are not permitted in the flat bundle: {name}")
                mode = (info.external_attr >> 16) & 0xFFFF
                if mode and stat.S_ISLNK(mode):
                    raise IngestionError(f"Symlink ZIP entries are forbidden: {name}")
                if info.flag_bits & 0x1:
                    raise IngestionError(f"Encrypted ZIP entries are unsupported: {name}")
                if info.file_size > MAX_ENTRY_BYTES:
                    raise IngestionError(f"Archive entry exceeds the expanded-size limit: {name}")
                total_expanded += info.file_size
                if total_expanded > MAX_EXPANDED_BYTES:
                    raise IngestionError("Archive exceeds the total expanded-size limit")
                if info.file_size and info.compress_size == 0:
                    raise IngestionError(f"Invalid zero compressed size for non-empty entry: {name}")
                if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                    raise IngestionError(f"Archive entry exceeds the compression-ratio limit: {name}")
                infos[name] = info
            actual = set(infos)
            if actual != REQUIRED_ENTRIES:
                raise IngestionError(
                    f"Bundle entries do not match apex-session-export/1.0.0; missing={sorted(REQUIRED_ENTRIES - actual)}, extra={sorted(actual - REQUIRED_ENTRIES)}"
                )
            yield _Snapshot(snapshot, digest.hexdigest(), archive, infos)
        finally:
            archive.close()


def _strict_csv_rows(snapshot: _Snapshot, name: str, expected_headers: list[str], max_rows: int) -> Iterator[tuple[int, dict[str, str]]]:
    old_limit = csv.field_size_limit()
    csv.field_size_limit(MAX_CSV_FIELD_BYTES)
    try:
        with snapshot.open_text(name) as handle:
            reader = csv.reader(handle, strict=True)
            try:
                headers = next(reader)
            except StopIteration as exc:
                raise ContractValidationError(f"{name}: CSV is empty") from exc
            if len(headers) != len(set(headers)):
                raise ContractValidationError(f"{name}: duplicate CSV headers are forbidden")
            if headers != expected_headers:
                raise ContractValidationError(f"{name}: unexpected headers: {headers!r}")
            for row_number, row in enumerate(reader, start=2):
                if row_number - 1 > max_rows:
                    raise IngestionError(f"{name}: exceeds the {max_rows}-row limit")
                if len(row) != len(headers):
                    raise ContractValidationError(
                        f"{name}:{row_number}: expected {len(headers)} columns, received {len(row)}"
                    )
                yield row_number, dict(zip(headers, row, strict=True))
    except UnicodeDecodeError as exc:
        raise ContractValidationError(f"{name}: must be well-formed UTF-8") from exc
    except csv.Error as exc:
        raise ContractValidationError(f"{name}: malformed CSV: {exc}") from exc
    finally:
        csv.field_size_limit(old_limit)


def _integer(text: str, field: str, *, minimum: int = 0) -> int:
    if not text or any(character not in "0123456789" for character in text):
        raise ContractValidationError(f"{field}: expected an unsigned base-10 integer")
    value = int(text)
    if value < minimum:
        raise ContractValidationError(f"{field}: must be >= {minimum}")
    return value


def _boolean(text: str, field: str) -> bool:
    if text not in {"0", "1"}:
        raise ContractValidationError(f"{field}: booleans must be encoded as 0 or 1")
    return text == "1"


def _float(text: str, field: str, *, optional: bool = False) -> float | None:
    if text == "" and optional:
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise ContractValidationError(f"{field}: expected a finite decimal number") from exc
    if not math.isfinite(value):
        raise ContractValidationError(f"{field}: non-finite numeric values are forbidden")
    return value


def _verify_manifest(snapshot: _Snapshot) -> tuple[dict[str, Any], str, tuple[dict[str, Any], ...]]:
    manifest_bytes = snapshot.read_bounded("manifest.json")
    manifest = validate_apex_session_manifest(parse_json_bytes(manifest_bytes, source="manifest.json"))
    declared = {item["name"]: item for item in manifest["files"]}
    if set(declared) != MANIFESTED_ENTRIES:
        raise IntegrityError(
            f"Manifest inventory mismatch; missing={sorted(MANIFESTED_ENTRIES - set(declared))}, extra={sorted(set(declared) - MANIFESTED_ENTRIES)}"
        )
    inventory: list[dict[str, Any]] = []
    for name in sorted(MANIFESTED_ENTRIES, key=str.casefold):
        info = snapshot.infos[name]
        entry = declared[name]
        if entry["sizeBytes"] != info.file_size:
            raise IntegrityError(f"Manifest size mismatch for {name}")
        digest = hashlib.sha256()
        actual_size = 0
        with snapshot.archive.open(info, "r") as handle:
            while chunk := handle.read(1024 * 1024):
                actual_size += len(chunk)
                digest.update(chunk)
        actual_hash = digest.hexdigest()
        if actual_size != entry["sizeBytes"] or actual_hash != entry["sha256"]:
            raise IntegrityError(f"Manifest content hash/size mismatch for {name}")
        inventory.append({"name": name, "size_bytes": actual_size, "sha256": actual_hash})
    return manifest, sha256_bytes(manifest_bytes), tuple(inventory)


def _finite_json_numbers(value: Any, path: str = "$") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ContractValidationError(f"{path}: non-finite JSON number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _finite_json_numbers(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for name, item in value.items():
            _finite_json_numbers(item, f"{path}.{name}")
        return
    raise ContractValidationError(f"{path}: unsupported JSON value")


def _parse_findings(snapshot: _Snapshot, manifest: dict[str, Any], file_hashes: dict[str, str]) -> dict[str, Any]:
    obj = parse_json_bytes(snapshot.read_bounded("findings.json"), source="findings.json")
    if not isinstance(obj, dict) or set(obj) != FINDINGS_TOP_KEYS:
        raise ContractValidationError("findings.json: unexpected or missing top-level fields")
    if obj["schema"] != APEX_SESSION_EXPORT or obj["productVersion"] != manifest["productVersion"]:
        raise IntegrityError("findings.json schema/productVersion disagrees with manifest.json")
    session = obj["session"]
    if not isinstance(session, dict) or set(session) != FINDING_SESSION_KEYS:
        raise ContractValidationError("findings.json.session: unexpected or missing fields")
    for name in ("simulator", "car", "track", "sessionType"):
        if not isinstance(session[name], str) or not session[name]:
            raise ContractValidationError(f"findings.json.session.{name}: must be a non-empty string")
    for name in ("durationSeconds", "trackLengthMeters", "bestValidLapTimeSeconds"):
        if session[name] is not None and (isinstance(session[name], bool) or not isinstance(session[name], (int, float)) or not math.isfinite(session[name])):
            raise ContractValidationError(f"findings.json.session.{name}: must be finite or null")
    findings = obj["findings"]
    if not isinstance(findings, list):
        raise ContractValidationError("findings.json.findings: must be an array")
    if len(findings) != manifest["sources"]["findingCount"]:
        raise IntegrityError("findings.json count disagrees with manifest.json")
    keys: set[str] = set()
    ranks: set[int] = set()
    ai_count = 0
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict) or set(finding) != FINDING_KEYS:
            raise ContractValidationError(f"findings.json.findings[{index}]: unexpected or missing fields")
        key = finding["key"]
        rank = finding["rank"]
        if not isinstance(key, str) or not key or key in keys:
            raise ContractValidationError(f"findings.json.findings[{index}].key: must be unique")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1 or rank in ranks:
            raise ContractValidationError(f"findings.json.findings[{index}].rank: must be a unique positive integer")
        keys.add(key)
        ranks.add(rank)
        if finding["aiExplanation"] is not None:
            ai_count += 1
    if ranks != set(range(1, len(findings) + 1)):
        raise ContractValidationError("findings.json finding ranks must be contiguous from one")
    if ai_count != manifest["sources"]["localAiExplanationCount"]:
        raise IntegrityError("AI explanation count disagrees with manifest.json")
    _finite_json_numbers(obj)
    if file_hashes["findings.json"] != hashlib.sha256(snapshot.read_bounded("findings.json")).hexdigest():
        raise IntegrityError("findings.json changed after manifest verification")
    return obj


def _parse_laps(snapshot: _Snapshot) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row_number, raw in _strict_csv_rows(snapshot, "laps.csv", LAP_HEADERS, MAX_LAP_ROWS):
        prefix = f"laps.csv:{row_number}"
        lap = _integer(raw["lap_number"], f"{prefix}.lap_number")
        if lap in seen:
            raise IntegrityError(f"{prefix}: duplicate lap_number {lap}")
        seen.add(lap)
        row = {
            **raw,
            "lap_number": lap,
            "lap_time_seconds": _float(raw["lap_time_seconds"], f"{prefix}.lap_time_seconds", optional=True),
            "is_best_valid_lap": _boolean(raw["is_best_valid_lap"], f"{prefix}.is_best_valid_lap"),
            "is_reviewed_lap": _boolean(raw["is_reviewed_lap"], f"{prefix}.is_reviewed_lap"),
            "is_valid": _boolean(raw["is_valid"], f"{prefix}.is_valid"),
            "is_reference": _boolean(raw["is_reference"], f"{prefix}.is_reference"),
            "stint": _integer(raw["stint"], f"{prefix}.stint"),
            "laps_since_pit_exit": None if raw["laps_since_pit_exit"] == "" else _integer(raw["laps_since_pit_exit"], f"{prefix}.laps_since_pit_exit"),
            "sampled_bins": _integer(raw["sampled_bins"], f"{prefix}.sampled_bins"),
            "total_bins": _integer(raw["total_bins"], f"{prefix}.total_bins", minimum=1),
            "coverage_fraction": _float(raw["coverage_fraction"], f"{prefix}.coverage_fraction"),
            "coaching_delivered_on_lap": _boolean(raw["coaching_delivered_on_lap"], f"{prefix}.coaching_delivered_on_lap"),
            "delivered_cue_count": _integer(raw["delivered_cue_count"], f"{prefix}.delivered_cue_count"),
            "source_row": row_number,
        }
        coverage = row["sampled_bins"] / row["total_bins"]
        if abs(row["coverage_fraction"] - coverage) > 0.00005:
            raise IntegrityError(f"{prefix}: coverage_fraction does not reconcile to four-decimal precision")
        if row["is_valid"] and row["exclusion_reasons"]:
            raise IntegrityError(f"{prefix}: valid lap declares exclusion reasons")
        if row["is_reference"] and not row["is_valid"]:
            raise IntegrityError(f"{prefix}: reference lap is not valid")
        if row["is_best_valid_lap"] and not row["is_valid"]:
            raise IntegrityError(f"{prefix}: best-valid lap is not valid")
        rows.append(row)
    if not rows:
        raise IntegrityError("laps.csv contains no laps")
    return tuple(rows)


def _audit_telemetry(snapshot: _Snapshot, laps: tuple[dict[str, Any], ...], findings: dict[str, Any]) -> dict[str, Any]:
    lap_by_number = {row["lap_number"]: row for row in laps}
    counts: Counter[int] = Counter()
    sampled: Counter[int] = Counter()
    represented: Counter[int] = Counter()
    previous_key: tuple[int, int] | None = None
    region_bins: dict[str, list[tuple[int, float]]] = defaultdict(list)
    known_findings = {item["key"]: item for item in findings["findings"]}
    fraction_error_integer = 0.0
    fraction_error_track = 0.0
    track_length = float(findings["session"]["trackLengthMeters"])
    steering_error = 0.0
    speed_error = 0.0
    incident_by_lap: dict[int, bool] = {}
    total_rows = 0
    total_sampled = 0
    total_frames = 0
    for row_number, row in _strict_csv_rows(snapshot, "telemetry.csv", TELEMETRY_HEADERS, MAX_TELEMETRY_ROWS):
        prefix = f"telemetry.csv:{row_number}"
        lap_number = _integer(row["lap_number"], f"{prefix}.lap_number")
        if lap_number not in lap_by_number:
            raise IntegrityError(f"{prefix}: lap_number does not resolve to laps.csv")
        distance_value = _float(row["distance_m"], f"{prefix}.distance_m")
        assert distance_value is not None
        if distance_value < 0 or not distance_value.is_integer():
            raise ContractValidationError(f"{prefix}.distance_m: must be a non-negative integer-metre bin")
        distance = int(distance_value)
        key = (lap_number, distance)
        if previous_key is not None and key <= previous_key:
            raise IntegrityError(f"{prefix}: lap/distance keys must be unique and strictly ordered")
        previous_key = key
        if distance != counts[lap_number]:
            raise IntegrityError(f"{prefix}: distance bins must be contiguous from zero within each lap")
        counts[lap_number] += 1
        source_lap = lap_by_number[lap_number]
        fraction = _float(row["lap_fraction"], f"{prefix}.lap_fraction")
        assert fraction is not None
        if not 0 <= fraction < 1:
            raise IntegrityError(f"{prefix}.lap_fraction: must be in [0,1)")
        total_bins = source_lap["total_bins"]
        fraction_error_integer = max(fraction_error_integer, abs(fraction - distance / total_bins))
        fraction_error_track = max(fraction_error_track, abs(fraction - distance / track_length))
        sample_count = _integer(row["sample_count"], f"{prefix}.sample_count")
        has_sample = _boolean(row["has_sample"], f"{prefix}.has_sample")
        if has_sample != (sample_count > 0):
            raise IntegrityError(f"{prefix}: has_sample must agree with sample_count")
        channel_names = ("brake", "throttle", "steering_rad", "steering_deg", "speed_ms", "speed_kph")
        if not has_sample and any(row[name] != "" for name in channel_names):
            raise IntegrityError(f"{prefix}: unsampled bin contains channel values")
        if has_sample and any(row[name] == "" for name in channel_names):
            raise IntegrityError(f"{prefix}: sampled bin omits a channel value")
        for name in ("lap_is_valid", "lap_is_reference", "lap_is_excluded"):
            _boolean(row[name], f"{prefix}.{name}")
        if _boolean(row["lap_is_valid"], f"{prefix}.lap_is_valid") != source_lap["is_valid"]:
            raise IntegrityError(f"{prefix}: lap validity disagrees with laps.csv")
        if _boolean(row["lap_is_reference"], f"{prefix}.lap_is_reference") != source_lap["is_reference"]:
            raise IntegrityError(f"{prefix}: reference flag disagrees with laps.csv")
        excluded = _boolean(row["lap_is_excluded"], f"{prefix}.lap_is_excluded")
        if excluded != (not source_lap["is_valid"]):
            raise IntegrityError(f"{prefix}: exclusion flag disagrees with laps.csv")
        exclusion_components = [item.strip() for item in source_lap["exclusion_reasons"].split(";") if item.strip()]
        if excluded and row["lap_exclusion_reason"] not in exclusion_components:
            raise IntegrityError(f"{prefix}: primary exclusion reason is not declared by laps.csv")
        if not excluded and row["lap_exclusion_reason"]:
            raise IntegrityError(f"{prefix}: valid lap has an exclusion reason")
        if row["lap_kind"] != source_lap["lap_kind"] or _integer(row["stint"], f"{prefix}.stint") != source_lap["stint"]:
            raise IntegrityError(f"{prefix}: lap kind/stint disagrees with laps.csv")
        incident = _boolean(row["incident_on_lap"], f"{prefix}.incident_on_lap")
        if lap_number in incident_by_lap and incident_by_lap[lap_number] != incident:
            raise IntegrityError(f"{prefix}: incident_on_lap changes within a lap")
        incident_by_lap[lap_number] = incident
        finding_keys = [item for item in row["finding_keys"].split(" ") if item]
        in_region = _boolean(row["in_finding_region"], f"{prefix}.in_finding_region")
        if in_region != bool(finding_keys) or len(finding_keys) != len(set(finding_keys)):
            raise IntegrityError(f"{prefix}: finding region/key flags are inconsistent")
        for finding_key in finding_keys:
            if finding_key not in known_findings:
                raise IntegrityError(f"{prefix}: finding key {finding_key!r} does not resolve")
            finding = known_findings[finding_key]
            if finding["lapNumber"] != lap_number:
                raise IntegrityError(f"{prefix}: finding key resolves to a different lap")
            region_bins[finding_key].append((lap_number, distance_value))
        if has_sample:
            brake = _float(row["brake"], f"{prefix}.brake")
            throttle = _float(row["throttle"], f"{prefix}.throttle")
            steering = _float(row["steering_rad"], f"{prefix}.steering_rad")
            steering_deg = _float(row["steering_deg"], f"{prefix}.steering_deg")
            speed = _float(row["speed_ms"], f"{prefix}.speed_ms")
            speed_kph = _float(row["speed_kph"], f"{prefix}.speed_kph")
            assert None not in (brake, throttle, steering, steering_deg, speed, speed_kph)
            if not 0 <= brake <= 1 or not 0 <= throttle <= 1 or speed < 0:
                raise IntegrityError(f"{prefix}: brake/throttle/speed outside structural ranges")
            steering_error = max(steering_error, abs(steering_deg - math.degrees(steering)))
            speed_error = max(speed_error, abs(speed_kph - speed * 3.6))
            if steering_error > 0.0005001 or speed_error > 0.0050001:
                raise IntegrityError(f"{prefix}: convenience units disagree with authoritative values")
            sampled[lap_number] += 1
            represented[lap_number] += sample_count
            total_sampled += 1
            total_frames += sample_count
        total_rows += 1
    if set(counts) != set(lap_by_number):
        raise IntegrityError("telemetry.csv does not cover every laps.csv lap")
    bin_counts = set(counts.values())
    if len(bin_counts) != 1:
        raise IntegrityError("telemetry.csv laps do not share a stable total-bin count")
    for lap_number, lap in lap_by_number.items():
        if counts[lap_number] != lap["total_bins"] or sampled[lap_number] != lap["sampled_bins"]:
            raise IntegrityError(f"lap {lap_number}: sampled/total bin counts disagree across CSV files")
    for key, finding in known_findings.items():
        bins = region_bins[key]
        if not bins:
            raise IntegrityError(f"Finding {key} has no resolvable telemetry region")
        if finding["lapNumber"] not in lap_by_number:
            raise IntegrityError(f"Finding {key} references an unknown lap")
        start = float(finding["startDistanceMeters"])
        end = float(finding["endDistanceMeters"])
        if not 0 <= start < end <= next(iter(bin_counts)) + 1:
            raise IntegrityError(f"Finding {key} has an invalid distance range")
        if min(distance for _, distance in bins) < math.floor(start) or max(distance for _, distance in bins) >= math.ceil(end):
            raise IntegrityError(f"Finding {key} telemetry region lies outside its declared range")
        if not 0 <= float(finding["coverage"]) <= 1:
            raise IntegrityError(f"Finding {key} has invalid coverage")
    return {
        "rows": total_rows,
        "sampled": total_sampled,
        "frames": total_frames,
        "bins_per_lap": next(iter(bin_counts)),
        "fraction_error_integer": fraction_error_integer,
        "fraction_error_track": fraction_error_track,
        "steering_display_error": steering_error,
        "speed_display_error": speed_error,
        "finding_bin_ranges": {
            key: [int(min(distance for _, distance in bins)), int(max(distance for _, distance in bins))]
            for key, bins in sorted(region_bins.items())
        },
    }


def _validate_finding_coverage(
    snapshot: _Snapshot,
    findings: dict[str, Any],
    ranges: dict[str, list[int]],
    comparison_laps: set[int],
) -> None:
    totals: Counter[tuple[str, int]] = Counter()
    sampled: Counter[tuple[str, int]] = Counter()
    for row_number, row in _strict_csv_rows(snapshot, "telemetry.csv", TELEMETRY_HEADERS, MAX_TELEMETRY_ROWS):
        lap = _integer(row["lap_number"], f"telemetry.csv:{row_number}.lap_number")
        if lap not in comparison_laps:
            continue
        distance = int(float(row["distance_m"]))
        has_sample = row["has_sample"] == "1"
        for key, (start, end) in ranges.items():
            if start <= distance <= end:
                totals[(key, lap)] += 1
                sampled[(key, lap)] += int(has_sample)
    for finding in findings["findings"]:
        key = finding["key"]
        values: list[float] = []
        for lap in comparison_laps:
            total = totals[(key, lap)]
            if total == 0:
                raise IntegrityError(f"Finding {key} coverage range is absent on comparison lap {lap}")
            values.append(sampled[(key, lap)] / total)
        if abs(float(finding["coverage"]) - min(values)) > 0.0005:
            raise IntegrityError(f"Finding {key} coverage does not reconcile to the minimum comparable-lap coverage at three-decimal precision")


def _audit_snapshot(snapshot: _Snapshot) -> BundleAudit:
    manifest, manifest_hash, inventory = _verify_manifest(snapshot)
    hashes = {entry["name"]: entry["sha256"] for entry in inventory}
    documentation: dict[str, str] = {}
    for name in ("README.md", "session-summary.md", "analysis-prompt.md", "data-dictionary.md"):
        try:
            text = snapshot.read_bounded(name).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractValidationError(f"{name}: must be well-formed UTF-8") from exc
        if not text.strip():
            raise ContractValidationError(f"{name}: documentation file must not be empty")
        documentation[name] = text
    findings = _parse_findings(snapshot, manifest, hashes)
    laps = _parse_laps(snapshot)
    telemetry = _audit_telemetry(snapshot, laps, findings)
    sources = manifest["sources"]
    if sources["lapsWithTelemetry"] != len(laps) or sources["lapsWithRecordedFacts"] != len(laps):
        raise IntegrityError("Manifest lap counts disagree with laps.csv")
    reviewed = [lap for lap in laps if lap["is_reviewed_lap"]]
    best = [lap for lap in laps if lap["is_best_valid_lap"]]
    if len(reviewed) != 1 or len(best) != 1:
        raise IntegrityError("Exactly one reviewed and one best-valid lap are required")
    session = findings["session"]
    if reviewed[0]["lap_number"] != session["reviewedLapNumber"]:
        raise IntegrityError("Reviewed lap disagrees between laps.csv and findings.json")
    if best[0]["lap_number"] != session["bestValidLapNumber"] or best[0]["lap_time_seconds"] != session["bestValidLapTimeSeconds"]:
        raise IntegrityError("Best-valid lap disagrees between laps.csv and findings.json")
    refs = sorted(lap["lap_number"] for lap in laps if lap["is_reference"])
    comparable = sorted(session["comparableLapNumbers"])
    if session["comparableLapCount"] != len(comparable) or comparable != sorted({*refs, reviewed[0]["lap_number"]}):
        raise IntegrityError("Comparable/reference/reviewed lap information is inconsistent")
    for finding in findings["findings"]:
        if finding["lapNumber"] != reviewed[0]["lap_number"]:
            raise IntegrityError(f"Finding {finding['key']} does not refer to the reviewed lap")
        if finding["cleanComparisonLapCount"] != len(refs):
            raise IntegrityError(f"Finding {finding['key']} clean-comparison count disagrees with reference selection")
    _validate_finding_coverage(snapshot, findings, telemetry["finding_bin_ranges"], set(comparable))
    expected_documentation = {
        "Simulator": str(session["simulator"]),
        "Car": str(session["car"]),
        "Track": str(session["track"]),
        "Session type": str(session["sessionType"]),
        "Laps with telemetry": str(len(laps)),
        "Valid laps": str(sum(lap["is_valid"] for lap in laps)),
        "Excluded laps": str(sum(not lap["is_valid"] for lap in laps)),
        "Reviewed lap": str(reviewed[0]["lap_number"]),
    }
    for name in ("README.md", "session-summary.md"):
        metadata = _markdown_metadata(documentation[name])
        for field, expected in expected_documentation.items():
            if metadata.get(field) != expected:
                raise IntegrityError(f"{name}: {field} metadata disagrees with machine-readable payloads")
        if not metadata.get("Best valid lap", "").startswith(f"Lap {best[0]['lap_number']} "):
            raise IntegrityError(f"{name}: best-valid lap metadata disagrees with laps.csv")
    if telemetry["fraction_error_integer"] <= 0.00000051 and telemetry["fraction_error_track"] > telemetry["fraction_error_integer"]:
        fraction_rule = "source_values_match_distance_m/integer_total_bins_with_six_decimal_rounding"
    else:
        fraction_rule = "source_denominator_not_definitively_established"
    limitations = (
        "Telemetry is one-metre distance-binned aggregate data, not timestamped raw simulator frames.",
        "Brake is a bin maximum; throttle, steering_rad, and speed_ms are bin arithmetic means.",
        "Time-domain, acceleration, yaw, wheel/tire, fuel, setup, traffic, weather, and track-condition channels are unavailable.",
        "Lap validity, exclusions, references, incidents, and finding regions are Apex Sim Coach product-derived classifications.",
        "Product findings and explanations are annotations only and are not scientific evidence or ground truth.",
        "trackLengthMeters and the apparent integer-total-bin lap_fraction denominator differ; exported lap_fraction is preserved.",
    )
    return BundleAudit(
        bundle_sha256=snapshot.bundle_sha256,
        manifest_sha256=manifest_hash,
        manifest=manifest,
        laps=laps,
        findings_document=findings,
        inventory=inventory,
        telemetry_rows=telemetry["rows"],
        sampled_bins=telemetry["sampled"],
        source_frames_represented=telemetry["frames"],
        bins_per_lap=telemetry["bins_per_lap"],
        valid_laps=sum(lap["is_valid"] for lap in laps),
        reference_laps=sum(lap["is_reference"] for lap in laps),
        excluded_laps=sum(not lap["is_valid"] for lap in laps),
        reviewed_lap=reviewed[0]["lap_number"],
        lap_fraction_rule=fraction_rule,
        limitations=limitations,
    )


def _markdown_metadata(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 2 or not cells[0] or cells[0] == "---":
            continue
        if cells[0] in metadata:
            raise IntegrityError(f"Duplicate documentation metadata field: {cells[0]}")
        metadata[cells[0]] = cells[1]
    return metadata


def inspect_apex_session_bundle(path: Path) -> dict[str, Any]:
    with _snapshot_bundle(path) as snapshot:
        return _audit_snapshot(snapshot).report()


def validate_apex_session_bundle(path: Path, collection_record_path: Path | None = None) -> dict[str, Any]:
    with _snapshot_bundle(path) as snapshot:
        audit = _audit_snapshot(snapshot)
        report = audit.report()
        if collection_record_path is not None:
            collection = validate_collection_record(read_json(collection_record_path))
            _bind_collection(collection, audit)
            report["collection_record"] = {
                "valid": True,
                "dataset_id": collection["dataset_id"],
                "classification": collection["collection_classification"],
                "synthetic": collection["synthetic"],
            }
        return report


def _bind_collection(collection: dict[str, Any], audit: BundleAudit) -> None:
    if collection["source_bundle"]["sha256"] != audit.bundle_sha256:
        raise IntegrityError("Collection record source-bundle hash does not match the ZIP bytes")
    session = audit.findings_document["session"]
    identity = collection["session_identity"]
    comparisons = {"simulator": session["simulator"], "car": session["car"], "track": session["track"]}
    for name, expected in comparisons.items():
        if identity[name] != expected:
            raise IntegrityError(f"Collection record {name} identity disagrees with the bundle")
    lap_numbers = {lap["lap_number"] for lap in audit.laps}
    for assignment in collection["lap_assignments"]:
        if assignment["lap_number"] not in lap_numbers:
            raise IntegrityError("Collection record assigns a lap absent from the bundle")
    is_source_synthetic = audit.manifest["privacyMode"] == "Synthetic"
    if collection["synthetic"] != is_source_synthetic:
        raise IntegrityError("Collection-record synthetic classification disagrees with bundle privacy mode")


def _source_provenance(audit: BundleAudit, name: str, row: int | None = None, record_id: str | None = None) -> dict[str, Any]:
    hashes = {item["name"]: item["sha256"] for item in audit.inventory}
    value: dict[str, Any] = {
        "source_file": name,
        "source_file_sha256": hashes[name],
        "adapter_id": ADAPTER_ID,
        "adapter_version": ADAPTER_VERSION,
    }
    if row is not None:
        value.update({"row_start": row, "row_end": row})
    if record_id is not None:
        value["source_record_id"] = record_id
    return value


def _qualified(value: Any, concept: str, source: str, derivation: str, *, unavailable: bool = False, reference: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "value": None if unavailable else value,
        "provenance": "unavailable" if unavailable else "derived",
        "unit": CANONICAL_UNITS[concept],
    }
    if unavailable:
        item["source_channel"] = source
    else:
        item["source_channel"] = source
        item["derivation"] = derivation
    if reference is not None:
        item["reference"] = reference
    return item


def _iter_normalized_records(snapshot: _Snapshot, audit: BundleAudit, collection: dict[str, Any]) -> Iterable[dict[str, Any]]:
    dataset_id = collection["dataset_id"]
    session_id = f"session-{audit.bundle_sha256[:16]}"
    session = audit.findings_document["session"]
    yield {
        "schema_version": NORMALIZED_RECORD,
        "record_type": "session",
        "dataset_id": dataset_id,
        "session_id": session_id,
        "record_id": session_id,
        "sequence_index": 0,
        "source_provenance": _source_provenance(audit, "findings.json", record_id="session"),
        "simulator": session["simulator"],
        "driver_id": collection["participant"]["pseudonymous_participant_id"],
        "car": session["car"],
        "track": session["track"],
        "layout": collection["session_identity"]["layout"] or "unavailable",
        "fields": {
            "session_state": _qualified(session["sessionType"], "session_state", "findings.json/session/sessionType", "Product-generated session classification")
        },
    }
    for lap in audit.laps:
        lap_id = f"{session_id}-lap-{lap['lap_number']:06d}"
        fields = {
            "lap_time": _qualified(
                lap["lap_time_seconds"], "lap_time", "laps.csv/lap_time_seconds",
                "Apex Sim Coach exported lap-time value", unavailable=lap["lap_time_seconds"] is None,
            ),
            "lap_valid": _qualified(
                lap["is_valid"], "lap_valid", "laps.csv/is_valid",
                "Apex Sim Coach product-derived lap validity classification",
            ),
        }
        flags = [] if lap["is_valid"] else ["product_classified_excluded"]
        yield {
            "schema_version": NORMALIZED_RECORD,
            "record_type": "lap",
            "dataset_id": dataset_id,
            "session_id": session_id,
            "record_id": lap_id,
            "sequence_index": 0,
            "source_provenance": _source_provenance(audit, "laps.csv", lap["source_row"], str(lap["lap_number"])),
            "lap_id": lap_id,
            "lap_number": lap["lap_number"],
            "quality_flags": flags,
            "fields": fields,
        }
    lap_by_number = {lap["lap_number"]: lap for lap in audit.laps}
    for row_number, row in _strict_csv_rows(snapshot, "telemetry.csv", TELEMETRY_HEADERS, MAX_TELEMETRY_ROWS):
        lap_number = int(row["lap_number"])
        distance = int(float(row["distance_m"]))
        sample_count = int(row["sample_count"])
        has_sample = row["has_sample"] == "1"
        lap_id = f"{session_id}-lap-{lap_number:06d}"
        channel_values = {
            "brake": row["brake"],
            "throttle": row["throttle"],
            "steering_angle": row["steering_rad"],
            "speed": row["speed_ms"],
        }
        methods = {
            "brake": "maximum",
            "throttle": "arithmetic_mean",
            "steering_angle": "arithmetic_mean",
            "speed": "arithmetic_mean",
        }
        fields: dict[str, Any] = {
            "lap_distance": _qualified(float(row["distance_m"]), "lap_distance", "telemetry.csv/distance_m", "Distance-bin start exported by Apex Sim Coach"),
            "lap_fraction": _qualified(float(row["lap_fraction"]), "lap_fraction", "telemetry.csv/lap_fraction", "Source-exported convenience fraction; denominator is contract-ambiguous"),
        }
        for concept, text in channel_values.items():
            fields[concept] = _qualified(
                None if not has_sample else float(text),
                concept,
                f"telemetry.csv/{'steering_rad' if concept == 'steering_angle' else ('speed_ms' if concept == 'speed' else concept)}",
                f"One-metre bin {methods[concept]} across {sample_count} represented source frame(s)",
                unavailable=not has_sample,
            )
        flags: list[str] = []
        if not has_sample:
            flags.append("source_bin_unsampled")
        if not lap_by_number[lap_number]["is_valid"]:
            flags.append("product_classified_excluded")
        yield {
            "schema_version": NORMALIZED_RECORD,
            "record_type": "distance_bin",
            "dataset_id": dataset_id,
            "session_id": session_id,
            "record_id": f"{lap_id}-bin-{distance:06d}",
            "sequence_index": 0,
            "source_provenance": _source_provenance(audit, "telemetry.csv", row_number, f"{lap_number}:{distance}"),
            "lap_id": lap_id,
            "distance_bin_index": distance,
            "distance_start_m": float(distance),
            "distance_end_m": float(distance + 1),
            "sample_count": sample_count,
            "has_sample": has_sample,
            "aggregation": {
                "source_semantics": "distance_binned_aggregate",
                "distance_bin_width_m": 1.0,
                "channel_methods": methods,
            },
            "quality_flags": flags,
            "fields": fields,
        }


def _capabilities() -> dict[str, dict[str, Any]]:
    available = {
        "lap_time": ("laps.csv/lap_time_seconds", "Apex Sim Coach exported lap time"),
        "lap_valid": ("laps.csv/is_valid", "Apex Sim Coach product-derived validity"),
        "lap_distance": ("telemetry.csv/distance_m", "Distance-bin start"),
        "lap_fraction": ("telemetry.csv/lap_fraction", "Source convenience fraction with ambiguous denominator"),
        "brake": ("telemetry.csv/brake", "One-metre bin maximum"),
        "throttle": ("telemetry.csv/throttle", "One-metre bin arithmetic mean"),
        "steering_angle": ("telemetry.csv/steering_rad", "One-metre bin arithmetic mean; positive left"),
        "speed": ("telemetry.csv/speed_ms", "One-metre bin arithmetic mean"),
        "session_state": ("findings.json/session/sessionType", "Apex Sim Coach product-generated session classification"),
    }
    result: dict[str, dict[str, Any]] = {}
    for concept in sorted(NORMALIZED_CONCEPTS):
        if concept in available:
            source, derivation = available[concept]
            result[concept] = {
                "provenance": "derived",
                "unit": CANONICAL_UNITS[concept],
                "source_channel": source,
                "derivation": derivation,
            }
        else:
            result[concept] = {"provenance": "unavailable", "unit": CANONICAL_UNITS[concept]}
    return result


def adapter_conformance_report(audit: BundleAudit) -> dict[str, Any]:
    return {
        "schema_version": CONFORMANCE_SCHEMA,
        "source_schema_version": APEX_SESSION_EXPORT,
        "adapter": {"id": ADAPTER_ID, "version": ADAPTER_VERSION},
        "available": ["session_identity", "lap_time", "lap_distance", "sample_count", "coverage"],
        "aggregated": {
            "brake": "one_metre_bin_maximum",
            "throttle": "one_metre_bin_arithmetic_mean",
            "steering_angle": "one_metre_bin_arithmetic_mean_authoritative_radians",
            "speed": "one_metre_bin_arithmetic_mean_authoritative_metres_per_second",
        },
        "product_derived_annotations": ["lap_validity", "lap_exclusions", "reference_selection", "incident_on_lap", "finding_regions", "findings_and_explanations"],
        "ambiguous": {
            "lap_fraction_denominator": audit.lap_fraction_rule,
            "layout_identity": "not_present_in_customer_bundle",
        },
        "unavailable": [
            "timestamps", "source_clock", "acceleration", "yaw_rate", "gear", "rpm", "wheel_state",
            "tire_state", "fuel", "setup", "assists", "damage", "traffic", "flags", "weather",
            "track_conditions", "raw_frame_order", "recorder_gap_timing",
        ],
        "limitations": list(audit.limitations),
    }


def ingest_apex_session_bundle(
    path: Path,
    output_dir: Path,
    collection_record_path: Path,
    *,
    project_root: Path | None = None,
    integration_validation: bool = False,
) -> dict[str, Any]:
    collection_bytes = collection_record_path.read_bytes()
    collection = validate_collection_record(parse_json_bytes(collection_bytes, source="collection-record.json"))
    code_identity = apex_labs_code_identity(project_root)
    if not integration_validation:
        require_research_code_identity(code_identity, synthetic=collection["synthetic"])
    with _snapshot_bundle(path) as snapshot:
        audit = _audit_snapshot(snapshot)
        _bind_collection(collection, audit)
        with atomic_output_directory(output_dir, operation="apex-session-ingest", error_type=IngestionError) as staged:
            records_path = staged / "records.jsonl"
            temporal_policy = {
                "source_clock": "unavailable_distance_binned_export",
                "normalized_clock_origin": "session_start",
                "clock_resolution_seconds": None,
                "duplicate_timestamp_policy": "reject",
                "clock_reset_policy": "reject",
                "expected_sample_period_seconds": None,
                "gap_tolerance_seconds": None,
                "lap_distance_regression_policy": "reject",
                "interpolation": {"performed": False, "method": None, "affected_concepts": []},
            }
            tracker = NormalizedIntegrityTracker(collection["dataset_id"], temporal_policy)
            with records_path.open("xb") as handle:
                for sequence_index, record in enumerate(_iter_normalized_records(snapshot, audit, collection)):
                    record["sequence_index"] = sequence_index
                    validate_normalized_record(record)
                    tracker.add(record)
                    handle.write(canonical_json_bytes(record))
            integrity = tracker.finalize()
            collection_output = staged / "collection-record.json"
            collection_output.write_bytes(canonical_json_bytes(collection))
            annotations = {
                "schema_version": PRODUCT_ANNOTATIONS,
                "source_schema_version": APEX_SESSION_EXPORT,
                "source_file_sha256": {item["name"]: item["sha256"] for item in audit.inventory}["findings.json"],
                "classification": "product_generated_annotations_not_scientific_evidence",
                "scientific_evidence": False,
                "training_labels": False,
                "ground_truth": False,
                "product_recommendations": False,
                "scientific_promotion_allowed": False,
                "annotations": audit.findings_document["findings"],
            }
            validate_product_annotations(annotations)
            annotations_path = staged / "product-annotations.json"
            write_json(annotations_path, annotations)
            conformance_path = staged / "adapter-conformance.json"
            conformance = adapter_conformance_report(audit)
            validate_adapter_conformance(conformance)
            write_json(conformance_path, conformance)
            classification = (
                "synthetic_demo" if collection["synthetic"] else
                "integration_validation_only" if integration_validation else
                collection["collection_classification"]
            )
            eligible = classification in {"observational", "experimental"}
            eligibility_reason = (
                "Synthetic mechanics cannot support scientific promotion."
                if classification == "synthetic_demo"
                else "Dirty/uncommitted integration validation cannot support scientific promotion."
                if classification == "integration_validation_only"
                else "Structurally eligible for later analysis; this does not establish scientific validity."
            )
            configuration = {
                "source_schema_version": APEX_SESSION_EXPORT,
                "strict_archive_limits": {
                    "max_archive_bytes": MAX_ARCHIVE_BYTES,
                    "max_entry_count": MAX_ENTRY_COUNT,
                    "max_entry_bytes": MAX_ENTRY_BYTES,
                    "max_expanded_bytes": MAX_EXPANDED_BYTES,
                    "max_compression_ratio": MAX_COMPRESSION_RATIO,
                    "max_lap_rows": MAX_LAP_ROWS,
                    "max_telemetry_rows": MAX_TELEMETRY_ROWS,
                },
                "distance_bin_semantics": "one_metre_aggregate_no_interpolation",
                "lap_fraction_policy": "preserve_source_value_without_recomputation",
            }
            source_files = [
                {"path": item["name"], "sha256": item["sha256"], "role": "source_bundle_payload", "media_type": _media_type(item["name"])}
                for item in audit.inventory
            ]
            source_basis = {
                "bundle_sha256": audit.bundle_sha256,
                "manifest_sha256": audit.manifest_sha256,
                "canonical_manifest_sha256": sha256_bytes(canonical_json_bytes(audit.manifest)),
                "files": [{"sha256": item["sha256"], "role": "source_bundle_payload", "media_type": _media_type(item["name"])} for item in audit.inventory],
                "adapter": {"id": ADAPTER_ID, "version": ADAPTER_VERSION, "configuration": configuration},
                "normalization_version": NORMALIZATION_VERSION,
                "synthetic": collection["synthetic"],
            }
            manifest: dict[str, Any] = {
                "schema_version": NORMALIZED_MANIFEST,
                "dataset_id": collection["dataset_id"],
                "dataset_fingerprint": "0" * 64,
                "synthetic": collection["synthetic"],
                "created_at": collection["created_at"],
                "source_manifest_sha256": audit.manifest_sha256,
                "canonical_source_manifest_sha256": sha256_bytes(canonical_json_bytes(audit.manifest)),
                "source_fingerprint": sha256_bytes(canonical_json_bytes(source_basis)),
                "normalization_version": NORMALIZATION_VERSION,
                "adapter": {"id": ADAPTER_ID, "version": ADAPTER_VERSION, "configuration": configuration},
                "code_identity": code_identity,
                "preprocessing": {
                    "pipeline_id": "apex-session-distance-bin-normalization",
                    "pipeline_version": ADAPTER_VERSION,
                    "configuration": configuration,
                    "configuration_sha256": sha256_bytes(canonical_json_bytes(configuration)),
                },
                "collection_context": {"protocol_snapshot": None, "condition_id": None, "block_id": None, "schedule_assignment_id": None},
                "temporal_policy": temporal_policy,
                "conventions": CANONICAL_CONVENTIONS,
                "integrity_summary": integrity,
                "records_file": "records.jsonl",
                "records_sha256": sha256_file(records_path),
                "record_counts": dict(tracker.counts),
                "source_files": source_files,
                "capabilities": _capabilities(),
                "unknown_source_channels": [],
                "source_bundle": {
                    "schema_version": APEX_SESSION_EXPORT,
                    "sha256": audit.bundle_sha256,
                    "manifest_sha256": audit.manifest_sha256,
                    "privacy_mode": audit.manifest["privacyMode"],
                },
                "source_semantics": {
                    "record_semantics": "distance_binned_aggregate_not_raw_frames",
                    "distance_bin_width_m": 1.0,
                    "interpolation_performed": False,
                    "time_domain_available": False,
                },
                "research_eligibility": {
                    "classification": classification,
                    "scientific_promotion_eligible": eligible,
                    "reason": eligibility_reason,
                },
                "collection_record": {"path": "collection-record.json", "sha256": sha256_file(collection_output)},
                "product_annotations": {"path": "product-annotations.json", "sha256": sha256_file(annotations_path)},
                "adapter_conformance": {"path": "adapter-conformance.json", "sha256": sha256_file(conformance_path)},
            }
            manifest["dataset_fingerprint"] = build_dataset_fingerprint(normalized_dataset_fingerprint_basis(manifest))
            validate_normalized_manifest(manifest)
            write_json(staged / "manifest.json", manifest)
    return manifest


def _media_type(name: str) -> str:
    if name.endswith(".json"):
        return "application/json"
    if name.endswith(".csv"):
        return "text/csv"
    return "text/markdown"
