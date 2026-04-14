"""Use cases for Verilog export from structured control flow diagrams."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from swifta.domain.ports import (
    SourceRepository,
    VerilogControlFlowExtractor,
    VerilogRenderer,
)


@dataclass(frozen=True, slots=True)
class ExportVerilogFileCommand:
    path: str


@dataclass(frozen=True, slots=True)
class ExportVerilogDirectoryCommand:
    root_path: str


@dataclass(frozen=True, slots=True)
class VerilogDocumentDTO:
    source_location: str
    function_count: int
    function_names: tuple[str, ...]
    verilog: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source_location": self.source_location,
            "function_count": self.function_count,
            "function_names": list(self.function_names),
        }


@dataclass(frozen=True, slots=True)
class VerilogBundleDTO:
    root_path: str
    document_count: int
    documents: tuple[VerilogDocumentDTO, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "root_path": self.root_path,
            "document_count": self.document_count,
            "documents": [doc.to_dict() for doc in self.documents],
        }


@dataclass(slots=True)
class VerilogExportService:
    source_repository: SourceRepository
    extractor: VerilogControlFlowExtractor
    renderer: VerilogRenderer

    def export_file(self, command: ExportVerilogFileCommand) -> VerilogDocumentDTO:
        source_unit = self.source_repository.load_file(command.path)
        return self._build_document(source_unit)

    def export_directory(
        self, command: ExportVerilogDirectoryCommand
    ) -> VerilogBundleDTO:
        source_units = tuple(
            self.source_repository.list_verilog_sources(command.root_path)
        )
        documents = tuple(
            self._build_document(source_unit) for source_unit in source_units
        )
        return VerilogBundleDTO(
            root_path=str(Path(command.root_path).expanduser().resolve()),
            document_count=len(documents),
            documents=documents,
        )

    def _build_document(self, source_unit) -> VerilogDocumentDTO:
        diagram = self.extractor.extract(source_unit)
        return VerilogDocumentDTO(
            source_location=diagram.source_location,
            function_count=len(diagram.functions),
            function_names=tuple(
                function.qualified_name for function in diagram.functions
            ),
            verilog=self.renderer.render(diagram),
        )
