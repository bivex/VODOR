"""Filesystem implementation of source discovery and loading."""

from __future__ import annotations

from pathlib import Path

from vodor.domain.errors import InputValidationError, SourceAccessError
from vodor.domain.model import SourceUnit, SourceUnitId
from vodor.domain.ports import SourceRepository


class FileSystemSourceRepository(SourceRepository):
    def load_file(self, path: str) -> SourceUnit:
        source_path = Path(path).expanduser().resolve()
        if not source_path.exists():
            raise InputValidationError(f"source file does not exist: {source_path}")
        if not source_path.is_file():
            raise InputValidationError(f"path is not a file: {source_path}")
        if source_path.suffix != ".v":
            raise InputValidationError(f"expected a .v file, got: {source_path}")

        return self._load_source_unit(source_path)

    def list_verilog_sources(self, root_path: str) -> tuple[SourceUnit, ...]:
        root = Path(root_path).expanduser().resolve()
        if not root.exists():
            raise InputValidationError(f"source directory does not exist: {root}")
        if not root.is_dir():
            raise InputValidationError(f"path is not a directory: {root}")

        source_paths = tuple(sorted(path for path in root.rglob("*.v") if path.is_file()))
        if not source_paths:
            raise InputValidationError(f"no .v files found under: {root}")

        return tuple(self._load_source_unit(path) for path in source_paths)

    # Transitional alias while callers migrate to Verilog naming.
    def list_swift_sources(self, root_path: str) -> tuple[SourceUnit, ...]:
        return self.list_verilog_sources(root_path)

    def _load_source_unit(self, path: Path) -> SourceUnit:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as error:
            raise SourceAccessError(f"unable to read source file {path}: {error}") from error
        except UnicodeDecodeError as error:
            raise SourceAccessError(f"source file is not valid UTF-8 {path}: {error}") from error

        normalized = str(path)
        return SourceUnit(
            identifier=SourceUnitId(normalized),
            location=normalized,
            content=content,
        )

