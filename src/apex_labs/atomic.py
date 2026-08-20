"""Small local-filesystem atomic output primitive.

The final path is never created until all staged content is complete. A short-lived
exclusive lock prevents concurrent writers from targeting the same output.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator, Type

from apex_labs.errors import ApexLabsError


@contextmanager
def atomic_output_directory(
    output_dir: Path,
    *,
    operation: str,
    error_type: Type[ApexLabsError],
) -> Iterator[Path]:
    output_dir = output_dir.resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir.parent / f".{output_dir.name}.apex-labs.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise error_type(
            f"Another {operation} may be targeting {output_dir}; lock exists: {lock_path.name}"
        ) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"operation={operation}\npid={os.getpid()}\n")
        if output_dir.exists():
            raise error_type(f"Output directory already exists; refusing to overwrite: {output_dir}")
        prefix = f".apex-labs-{operation}-{output_dir.name}-"
        with TemporaryDirectory(prefix=prefix, dir=output_dir.parent) as temporary:
            staged = Path(temporary) / "complete"
            staged.mkdir()
            yield staged
            try:
                staged.rename(output_dir)
            except FileExistsError as exc:
                raise error_type(
                    f"Output appeared during {operation}; refusing to overwrite: {output_dir}"
                ) from exc
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
