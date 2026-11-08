"""Sequence and multiplication operations for numerical sets.

This module is deliberately separate from `name_calculator.py`'s own
calculation engine, so the existing Name Calculator and its reserved JUFE
integration area (the "Show JUFE number script" export and the
provisional frequency/JUFE-runtime fields on `Fingerprint`) are never
touched by this extension.

No historical specification of an original "WRS V1" sequence-multiplication
rule set could be located for this task (searched: this repository and its
Git history; the WRS continuity records; the separate JUFE project's
specifications, contracts, and original/"oldmate" source files; the JUFE
research collection under INFORMATION_ARCHIVE; Local Recovery and installer
backups). Per that task's own instruction, no such rule is invented here.

Only two kinds of operation are implemented, both already mathematically
established rather than guessed:
  - ordinary arithmetic on a numerical sequence (sum, product, running sum,
    running product) -- standard, unambiguous definitions; and
  - per-element reduction using `name_calculator.digital_root_9` /
    `name_calculator.node18_root`, the two numerical reduction rules this
    codebase already implements and has already verified -- reused here
    exactly as they exist, not reinterpreted or extended.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from warrigal.name_calculator import digital_root_9, node18_root

SCHEMA_VERSION = "warrigal-sequence-multiplication-v1"
ALGORITHM_VERSION = "standard-arithmetic-and-double9-reuse-v1"

SUM = "Sum"
PRODUCT = "Product"
RUNNING_SUM = "Running sum"
RUNNING_PRODUCT = "Running product"
DIGITAL_ROOT_9_EACH = "Digital root (1-9) of each value"
NODE18_ROOT_EACH = "Double-9 root (1-18) of each value"

OPERATIONS = (
    SUM,
    PRODUCT,
    RUNNING_SUM,
    RUNNING_PRODUCT,
    DIGITAL_ROOT_9_EACH,
    NODE18_ROOT_EACH,
)

MULTIPLICATION_ALGORITHM_VERSION = "repeated-multiplication-v1"

MIN_MULTIPLIER = 0
MAX_MULTIPLIER = 99
MIN_REPETITIONS = 0
MAX_REPETITIONS = 99
DOUBLING_MULTIPLIER = 2

_TOKEN_PATTERN = re.compile(r"[,\s]+")


def parse_number_sequence(text: str) -> list[float]:
    """Parse a comma- and/or whitespace-separated set of numbers."""

    stripped = text.strip()
    if not stripped:
        raise ValueError("Enter one or more numbers.")

    tokens = [token for token in _TOKEN_PATTERN.split(stripped) if token]
    if not tokens:
        raise ValueError("Enter one or more numbers.")

    values: list[float] = []
    for token in tokens:
        try:
            values.append(float(token))
        except ValueError as exc:
            raise ValueError(f"'{token}' is not a number.") from exc

    return values


def _as_output_numbers(values: list) -> list[float] | list[int]:
    """Render whole numbers as ints for a cleaner, reproducible record.

    Already-`int` values are passed straight through, without a `float()`
    round-trip -- repeated multiplication can produce integers far beyond
    what a float can represent exactly (or even hold at all; `float()` on
    a sufficiently large `int` raises `OverflowError`), so this must never
    force one through `float`.
    """

    output: list = []
    for value in values:
        if isinstance(value, int):
            output.append(value)
        elif float(value).is_integer():
            output.append(int(value))
        else:
            output.append(value)
    return output


def _running_sum(values: list[float]) -> list[float]:
    running: list[float] = []
    total = 0.0
    for value in values:
        total += value
        running.append(total)
    return running


def _running_product(values: list[float]) -> list[float]:
    running: list[float] = []
    total = 1.0
    for value in values:
        total *= value
        running.append(total)
    return running


def _apply_operation(values: list[float], operation: str) -> list[float]:
    if operation == SUM:
        return [sum(values)]
    if operation == PRODUCT:
        total = 1.0
        for value in values:
            total *= value
        return [total]
    if operation == RUNNING_SUM:
        return _running_sum(values)
    if operation == RUNNING_PRODUCT:
        return _running_product(values)
    if operation == DIGITAL_ROOT_9_EACH:
        return [float(digital_root_9(value)) for value in values]
    if operation == NODE18_ROOT_EACH:
        return [float(node18_root(value)) for value in values]
    raise ValueError(
        f"'{operation}' is not an established sequence operation. "
        f"Choose one of: {', '.join(OPERATIONS)}."
    )


@dataclass(frozen=True)
class SequenceResult:
    schema_version: str
    algorithm_version: str
    result_id: str
    created_at: str
    raw_input: str
    values: list[float]
    operation: str
    output: list[float]
    source: str
    source_description: str
    notes: str

    def to_dict(self) -> dict:
        return asdict(self)


def compute_sequence_operation(
    raw_input: str,
    operation: str,
    *,
    source: str = "manual",
    source_description: str = "",
    notes: str = "",
    created_at: str | None = None,
) -> SequenceResult:
    """Parse a numerical set and apply one established sequence operation."""

    if operation not in OPERATIONS:
        raise ValueError(
            f"'{operation}' is not an established sequence operation. "
            f"Choose one of: {', '.join(OPERATIONS)}."
        )

    values = parse_number_sequence(raw_input)
    output = _apply_operation(values, operation)
    timestamp = created_at or datetime.now(timezone.utc).isoformat()

    identity_payload = {
        "schema_version": SCHEMA_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "raw_input": raw_input.strip(),
        "operation": operation,
        "source": source,
        "source_description": source_description,
    }
    digest = hashlib.sha256(
        json.dumps(identity_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]

    return SequenceResult(
        schema_version=SCHEMA_VERSION,
        algorithm_version=ALGORITHM_VERSION,
        result_id=f"WRG-SEQ-{digest.upper()}",
        created_at=timestamp,
        raw_input=raw_input.strip(),
        values=_as_output_numbers(values),
        operation=operation,
        output=_as_output_numbers(output),
        source=source,
        source_description=source_description.strip(),
        notes=notes.strip(),
    )


def _to_exact_number(value: float) -> int | float:
    """Return a whole-number value as a Python `int` (arbitrary precision,
    never silently overflows), else as `float` unchanged."""

    return int(value) if float(value).is_integer() else value


def _validate_multiplier(multiplier) -> int:
    value = float(multiplier)
    if not value.is_integer():
        raise ValueError(
            f"Multiplier must be a whole number between {MIN_MULTIPLIER} and {MAX_MULTIPLIER}."
        )
    whole = int(value)
    if not (MIN_MULTIPLIER <= whole <= MAX_MULTIPLIER):
        raise ValueError(
            f"Multiplier must be between {MIN_MULTIPLIER} and {MAX_MULTIPLIER}."
        )
    return whole


def _validate_repetitions(repetitions) -> int:
    value = float(repetitions)
    if not value.is_integer():
        raise ValueError(
            f"Repetitions must be a whole number between {MIN_REPETITIONS} and {MAX_REPETITIONS}."
        )
    whole = int(value)
    if not (MIN_REPETITIONS <= whole <= MAX_REPETITIONS):
        raise ValueError(
            f"Repetitions must be between {MIN_REPETITIONS} and {MAX_REPETITIONS}."
        )
    return whole


def generate_multiplication_stages(
    values: list[float],
    multiplier,
    repetitions,
) -> list[list[int | float]]:
    """Repeated-multiplication generator.

    Stage 0 is the untouched input, in its original order. Stage *n* is
    stage *n-1* with every element multiplied by `multiplier`, computed
    independently per element. A whole-number value multiplied by a
    whole-number multiplier is carried as a Python `int` at every stage,
    so arbitrarily large results (e.g. 99 repetitions at multiplier 99)
    are computed exactly, never silently overflowing or losing precision.
    """

    multiplier = _validate_multiplier(multiplier)
    repetitions = _validate_repetitions(repetitions)

    stage_zero = [_to_exact_number(value) for value in values]
    stages = [stage_zero]
    current = stage_zero
    for _ in range(repetitions):
        current = [value * multiplier for value in current]
        stages.append(current)

    return stages


@dataclass(frozen=True)
class MultiplicationStagesResult:
    schema_version: str
    algorithm_version: str
    result_id: str
    created_at: str
    raw_input: str
    values: list[float]
    multiplier: int
    repetitions: int
    stages: list[list[float]]
    source: str
    source_description: str
    notes: str

    def to_dict(self) -> dict:
        return asdict(self)


def compute_multiplication_stages(
    raw_input: str,
    multiplier,
    repetitions,
    *,
    source: str = "manual",
    source_description: str = "",
    notes: str = "",
    created_at: str | None = None,
) -> MultiplicationStagesResult:
    """Parse a numerical set and generate its repeated-multiplication stages."""

    values = parse_number_sequence(raw_input)
    multiplier = _validate_multiplier(multiplier)
    repetitions = _validate_repetitions(repetitions)
    stages = generate_multiplication_stages(values, multiplier, repetitions)
    timestamp = created_at or datetime.now(timezone.utc).isoformat()

    identity_payload = {
        "schema_version": SCHEMA_VERSION,
        "algorithm_version": MULTIPLICATION_ALGORITHM_VERSION,
        "raw_input": raw_input.strip(),
        "multiplier": multiplier,
        "repetitions": repetitions,
        "source": source,
        "source_description": source_description,
    }
    digest = hashlib.sha256(
        json.dumps(identity_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]

    return MultiplicationStagesResult(
        schema_version=SCHEMA_VERSION,
        algorithm_version=MULTIPLICATION_ALGORITHM_VERSION,
        result_id=f"WRG-MULT-{digest.upper()}",
        created_at=timestamp,
        raw_input=raw_input.strip(),
        values=_as_output_numbers(values),
        multiplier=multiplier,
        repetitions=repetitions,
        stages=[_as_output_numbers(stage) for stage in stages],
        source=source,
        source_description=source_description.strip(),
        notes=notes.strip(),
    )


def default_sequence_records_root() -> Path:
    return (
        Path.home()
        / "Desktop"
        / "INFORMATION_ARCHIVE"
        / "COLLECTIONS"
        / "JUFE"
        / "NAME_CALCULATOR"
        / "SEQUENCES"
        / "records"
    )


def _save_record(payload: dict, result_id: str, root: Path | None) -> Path:
    target_root = root or default_sequence_records_root()
    target_root.mkdir(parents=True, exist_ok=True)
    destination = target_root / f"{result_id}.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def save_sequence_result(result: SequenceResult, root: Path | None = None) -> Path:
    """Save one deterministic record; identical inputs reuse one filename."""

    return _save_record(result.to_dict(), result.result_id, root)


def save_multiplication_stages(
    result: MultiplicationStagesResult, root: Path | None = None
) -> Path:
    """Save one deterministic record; identical inputs reuse one filename."""

    return _save_record(result.to_dict(), result.result_id, root)
