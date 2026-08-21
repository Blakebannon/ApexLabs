"""Parsing and validation for a sanitized iRacing variable-table inventory.

The inventory is simulator *capability* metadata: variable name, SDK type, array
count, unit token, and description. It carries no telemetry values and no
participant identifiers, and it proves only what the simulator exposed on the
build and in the session that produced it. It is a point-in-time snapshot, never
eternal simulator truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from apex_labs.errors import ContractValidationError
from apex_labs.io import read_json
from apex_labs.provenance import sha256_file

INVENTORY_CONTRACT = "apex-iracing-variable-inventory/1.0.0"

# SDK storage classes the recorder is allowed to report. An unknown type is a
# refusal rather than a silently retained string.
SDK_TYPES = {"Bool", "Int", "BitField", "Float", "Double"}

# A unit token naming an `irsdk_*` enumeration tells us the value space is an
# enumeration or bitfield, but the inventory never carries the value dictionary
# that gives those integers meaning.
ENUM_UNIT_PREFIX = "irsdk_"


@dataclass(frozen=True)
class InventoryVariable:
    name: str
    sdk_type: str
    count: int
    unit: str | None
    description: str

    @property
    def is_array(self) -> bool:
        return self.count > 1

    @property
    def enumeration(self) -> str | None:
        """The `irsdk_*` enumeration this variable's values belong to, if any."""
        if self.unit is not None and self.unit.startswith(ENUM_UNIT_PREFIX):
            return self.unit
        return None

    @property
    def requires_enum_dictionary(self) -> bool:
        """True when values cannot be interpreted without an SDK value dictionary."""
        return self.sdk_type == "BitField" or self.enumeration is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sdk_type": self.sdk_type,
            "count": self.count,
            "unit": self.unit,
            "description": self.description,
        }


def validate_variable_inventory(value: Any) -> dict[str, Any]:
    """Validate the sanitized inventory contract without trusting its own claims."""
    if not isinstance(value, dict):
        raise ContractValidationError("$: iRacing variable inventory must be a JSON object")
    expected_keys = {"schema_version", "values_sampled", "direct_identifiers_included", "variables"}
    if set(value) != expected_keys:
        missing = sorted(expected_keys - set(value))
        extra = sorted(set(value) - expected_keys)
        raise ContractValidationError(
            f"$: unexpected inventory shape; missing={missing}, extra={extra}"
        )
    if value["schema_version"] != INVENTORY_CONTRACT:
        raise ContractValidationError(
            f"$.schema_version: expected {INVENTORY_CONTRACT}, got {value['schema_version']!r}"
        )
    # Labs ingests capability metadata only. A sampled or identifying inventory is
    # refused here rather than filtered, because filtering would hide the breach.
    if value["values_sampled"] is not False:
        raise ContractValidationError("$.values_sampled: Labs accepts metadata-only inventories")
    if value["direct_identifiers_included"] is not False:
        raise ContractValidationError(
            "$.direct_identifiers_included: an inventory declaring identifiers is refused"
        )
    variables = value["variables"]
    if not isinstance(variables, list) or not variables:
        raise ContractValidationError("$.variables: must be a non-empty array")
    seen: set[str] = set()
    for index, entry in enumerate(variables):
        path = f"$.variables[{index}]"
        if not isinstance(entry, dict) or set(entry) != {
            "name", "sdk_type", "count", "unit", "description"
        }:
            raise ContractValidationError(f"{path}: unexpected variable shape")
        name = entry["name"]
        if not isinstance(name, str) or not name:
            raise ContractValidationError(f"{path}.name: must be a non-empty string")
        if name in seen:
            raise ContractValidationError(f"{path}.name: duplicate variable {name!r}")
        seen.add(name)
        if entry["sdk_type"] not in SDK_TYPES:
            raise ContractValidationError(
                f"{path}.sdk_type: unsupported SDK type {entry['sdk_type']!r}"
            )
        count = entry["count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ContractValidationError(f"{path}.count: must be a positive integer")
        if entry["unit"] is not None and not isinstance(entry["unit"], str):
            raise ContractValidationError(f"{path}.unit: must be a string or null")
        if not isinstance(entry["description"], str):
            raise ContractValidationError(f"{path}.description: must be a string")
    return value


class VariableInventory:
    """An immutable, queryable view over one sanitized inventory snapshot."""

    def __init__(self, document: dict[str, Any], *, source_sha256: str | None = None) -> None:
        validated = validate_variable_inventory(document)
        self._variables = {
            entry["name"]: InventoryVariable(
                name=entry["name"],
                sdk_type=entry["sdk_type"],
                count=entry["count"],
                unit=entry["unit"],
                description=entry["description"],
            )
            for entry in validated["variables"]
        }
        self.schema_version: str = validated["schema_version"]
        self.values_sampled: bool = validated["values_sampled"]
        self.direct_identifiers_included: bool = validated["direct_identifiers_included"]
        self.source_sha256 = source_sha256

    def __contains__(self, name: object) -> bool:
        return name in self._variables

    def __len__(self) -> int:
        return len(self._variables)

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._variables)

    def get(self, name: str) -> InventoryVariable | None:
        return self._variables.get(name)

    def require(
        self,
        name: str,
        *,
        sdk_type: str | None = None,
        count: int | None = None,
        unit: str | None = None,
        context: str = "capability claim",
    ) -> InventoryVariable:
        """Return a variable, refusing any claim the inventory does not support.

        This is the guard that stops Labs from naming a simulator variable that
        does not exist, or from asserting a type/count/unit the evidence denies.
        """
        variable = self._variables.get(name)
        if variable is None:
            raise ContractValidationError(
                f"{context}: iRacing variable {name!r} is absent from the inventory"
            )
        for field, expected, actual in (
            ("sdk_type", sdk_type, variable.sdk_type),
            ("count", count, variable.count),
            ("unit", unit, variable.unit),
        ):
            if expected is not None and expected != actual:
                raise ContractValidationError(
                    f"{context}: {name}.{field} is {actual!r} in the inventory, not {expected!r}"
                )
        return variable

    def missing(self, names: Iterable[str]) -> list[str]:
        return sorted(name for name in names if name not in self._variables)

    def select(self, names: Iterable[str]) -> list[InventoryVariable]:
        return [self.require(name) for name in names]

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for variable in self._variables.values():
            counts[variable.sdk_type] = counts.get(variable.sdk_type, 0) + 1
        return {
            "schema_version": self.schema_version,
            "values_sampled": self.values_sampled,
            "direct_identifiers_included": self.direct_identifiers_included,
            "source_sha256": self.source_sha256,
            "variable_count": len(self._variables),
            "sdk_type_counts": dict(sorted(counts.items())),
            "array_variable_count": sum(1 for v in self._variables.values() if v.is_array),
            "sub_sample_channels": sorted(
                v.name for v in self._variables.values() if v.name.endswith("_ST")
            ),
            "enumerated_or_bitfield_variables": sorted(
                v.name for v in self._variables.values() if v.requires_enum_dictionary
            ),
        }


def load_variable_inventory(path: Path) -> VariableInventory:
    """Load one inventory snapshot and bind it to the exact bytes on disk."""
    path = Path(path)
    return VariableInventory(read_json(path), source_sha256=sha256_file(path))
