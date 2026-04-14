"""ANTLR-backed Verilog parser adapter."""

from __future__ import annotations

from time import perf_counter

from swifta.domain.model import (
    GrammarVersion,
    ParseOutcome,
    ParseStatistics,
    SourceUnit,
    StructuralElement,
    StructuralElementKind,
)
from swifta.domain.ports import VerilogSyntaxParser
from swifta.infrastructure.antlr.runtime import (
    ANTLR_GRAMMAR_VERSION,
    load_generated_types,
    parse_source_text,
)


class AntlrVerilogSyntaxParser(VerilogSyntaxParser):
    def __init__(self) -> None:
        self._generated = load_generated_types()

    @property
    def grammar_version(self) -> GrammarVersion:
        return ANTLR_GRAMMAR_VERSION

    def parse(self, source_unit: SourceUnit) -> ParseOutcome:
        started_at = perf_counter()
        try:
            parse_result = parse_source_text(source_unit.content, self._generated)
            elements = _extract_structural_elements(
                parse_result.token_stream.tokens,
                self._generated.lexer_type,
            )
            elapsed_ms = round((perf_counter() - started_at) * 1000, 3)

            return ParseOutcome.success(
                source_unit=source_unit,
                grammar_version=self.grammar_version,
                diagnostics=parse_result.diagnostics,
                structural_elements=tuple(elements),
                statistics=ParseStatistics(
                    token_count=len(parse_result.token_stream.tokens),
                    structural_element_count=len(elements),
                    diagnostic_count=len(parse_result.diagnostics),
                    elapsed_ms=elapsed_ms,
                ),
            )
        except Exception as error:
            elapsed_ms = round((perf_counter() - started_at) * 1000, 3)
            return ParseOutcome.technical_failure(
                source_unit=source_unit,
                grammar_version=self.grammar_version,
                message=str(error),
                elapsed_ms=elapsed_ms,
            )


def _extract_structural_elements(tokens: list[object], lexer_type: type) -> list[StructuralElement]:
    module_token = getattr(lexer_type, "MODULE", None)
    function_token = getattr(lexer_type, "FUNCTION", None)
    task_token = getattr(lexer_type, "TASK", None)
    identifier_token = getattr(lexer_type, "SIMPLE_IDENTIFIER", None)
    escaped_identifier_token = getattr(lexer_type, "ESCAPED_IDENTIFIER", None)
    eof_token = getattr(lexer_type, "EOF", -1)

    by_token_type = {
        module_token: StructuralElementKind.CLASS,
        function_token: StructuralElementKind.FUNCTION,
        task_token: StructuralElementKind.FUNCTION,
    }
    elements: list[StructuralElement] = []
    for index, token in enumerate(tokens):
        if token.type in {None, eof_token}:
            continue
        kind = by_token_type.get(token.type)
        if kind is None:
            continue

        name = _next_identifier(tokens, index + 1, identifier_token, escaped_identifier_token)
        if not name:
            continue
        elements.append(
            StructuralElement(
                kind=kind,
                name=name,
                line=token.line,
                column=token.column,
                container=None,
                signature=f"{token.text} {name}",
            )
        )
    return elements


def _next_identifier(
    tokens: list[object],
    start: int,
    identifier_token: int | None,
    escaped_identifier_token: int | None,
) -> str | None:
    for idx in range(start, len(tokens)):
        token = tokens[idx]
        if token.type in {identifier_token, escaped_identifier_token}:
            return str(token.text).strip("\\")
        if token.text in {";", "(", "{", ")"}:
            return None
    return None


# Backward-compatible alias for downstream imports during migration.
AntlrSwiftSyntaxParser = AntlrVerilogSyntaxParser
