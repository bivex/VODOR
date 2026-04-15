from __future__ import annotations

from dataclasses import dataclass

import pytest

from vodor.domain.errors import InputValidationError
from vodor.domain.control_flow import (
    ActionFlowStep,
    ActionKind,
    DelayFlowStep,
    EventWaitFlowStep,
    ForInFlowStep,
    ForkJoinFlowStep,
    ForeverFlowStep,
    DisableFlowStep,
    IfFlowStep,
    RepeatWhileFlowStep,
    SmellKind,
    SmellSeverity,
    SwitchFlowStep,
    WaitConditionFlowStep,
    WhileFlowStep,
)
from vodor.application.smell_detectors import detect_smells
from vodor.domain.model import SourceUnit, SourceUnitId, StructuralElementKind
from vodor.infrastructure.antlr.control_flow_extractor import (
    AntlrVerilogControlFlowExtractor,
)
from vodor.infrastructure.antlr.control_flow_extractor import (
    _extract_steps,
    _scan_procedural_blocks,
    _scan_top_level_actions,
    _strip_comments,
)
from vodor.infrastructure.antlr.parser_adapter import (
    _extract_structural_elements,
    _next_identifier,
)
from vodor.infrastructure.filesystem.source_repository import FileSystemSourceRepository


@dataclass(frozen=True)
class _Token:
    type: int
    text: str
    line: int = 1
    column: int = 0


class _Lexer:
    MODULE = 1
    FUNCTION = 2
    TASK = 3
    SIMPLE_IDENTIFIER = 4
    ESCAPED_IDENTIFIER = 5
    EOF = -1


def test_extract_structural_elements_finds_module_function_and_task() -> None:
    tokens = [
        _Token(_Lexer.MODULE, "module", line=1),
        _Token(_Lexer.SIMPLE_IDENTIFIER, "alu", line=1, column=7),
        _Token(_Lexer.FUNCTION, "function", line=5),
        _Token(_Lexer.SIMPLE_IDENTIFIER, "compute", line=5, column=9),
        _Token(_Lexer.TASK, "task", line=11),
        _Token(_Lexer.ESCAPED_IDENTIFIER, r"\do_work", line=11, column=5),
        _Token(_Lexer.EOF, "<EOF>", line=99),
    ]

    elements = _extract_structural_elements(tokens, _Lexer)
    assert [element.name for element in elements] == ["alu", "compute", "do_work"]
    assert [element.kind for element in elements] == [
        StructuralElementKind.CLASS,
        StructuralElementKind.FUNCTION,
        StructuralElementKind.FUNCTION,
    ]


def test_next_identifier_stops_at_statement_boundary() -> None:
    tokens = [
        _Token(_Lexer.MODULE, "module"),
        _Token(100, ";"),
        _Token(_Lexer.SIMPLE_IDENTIFIER, "never_reached"),
    ]
    assert _next_identifier(tokens, 1, _Lexer.SIMPLE_IDENTIFIER, _Lexer.ESCAPED_IDENTIFIER) is None


def test_scan_procedural_blocks_supports_nested_begin_end() -> None:
    source = """
module top;
  always @(posedge clk) begin
    if (en) begin
      value <= value + 1;
    end
  end
  initial begin
    done <= 1'b0;
  end
endmodule
"""
    blocks = _scan_procedural_blocks(source)
    assert [block.name for block in blocks] == ["always_1", "initial_2"]
    assert "value <= value + 1;" in blocks[0].body
    assert "done <= 1'b0;" in blocks[1].body


def test_extract_steps_maps_common_control_constructs() -> None:
    body = "\n".join(
        [
            "if (a > 0)",
            "result <= value;",
            "while (ready)",
            "result <= next;",
            "for (i = 0; i < 4; i = i + 1)",
            "result <= i;",
            "repeat (3)",
            "result <= result + 1;",
            "case (state)",
            "0: ",
            "result <= 0;",
            "default:",
            "result <= 1;",
            "endcase",
            "result <= value;",
        ]
    )
    steps = _extract_steps(body)
    assert isinstance(steps[0], IfFlowStep)
    assert isinstance(steps[1], WhileFlowStep)
    assert isinstance(steps[2], ForInFlowStep)
    assert isinstance(steps[3], RepeatWhileFlowStep)
    assert isinstance(steps[4], SwitchFlowStep)
    assert isinstance(steps[5], ActionFlowStep)


def test_extract_steps_builds_if_else_bodies() -> None:
    body = "\n".join(
        [
            "if (a > 0)",
            "begin",
            "x <= 1;",
            "end",
            "else",
            "begin",
            "x <= 0;",
            "end",
        ]
    )
    steps = _extract_steps(body)
    assert len(steps) == 1
    assert isinstance(steps[0], IfFlowStep)
    assert [step.label for step in steps[0].then_steps if isinstance(step, ActionFlowStep)] == [
        "x <= 1"
    ]
    assert [step.label for step in steps[0].else_steps if isinstance(step, ActionFlowStep)] == [
        "x <= 0"
    ]


def test_extract_steps_builds_case_labels() -> None:
    body = "\n".join(
        [
            "case (state)",
            "2'b00:",
            "result <= 0;",
            "2'b01:",
            "result <= 1;",
            "default:",
            "result <= 2;",
            "endcase",
        ]
    )
    steps = _extract_steps(body)
    assert len(steps) == 1
    assert isinstance(steps[0], SwitchFlowStep)
    assert [case.label for case in steps[0].cases] == ["2'b00", "2'b01", "default"]
    assert steps[0].cases[0].steps and isinstance(steps[0].cases[0].steps[0], ActionFlowStep)


def test_control_flow_extractor_builds_diagram_from_verilog_source() -> None:
    source = SourceUnit(
        identifier=SourceUnitId("simple.v"),
        location="simple.v",
        content=(
            "module simple;\n"
            "  always @(posedge clk) begin\n"
            "    if (rst) value <= 0;\n"
            "  end\n"
            "endmodule\n"
        ),
    )
    diagram = AntlrVerilogControlFlowExtractor().extract(source)
    assert diagram.source_location == "simple.v"
    assert len(diagram.functions) == 1
    assert diagram.functions[0].name == "always_1"


def test_source_repository_accepts_v_files(tmp_path) -> None:
    source_file = tmp_path / "good.v"
    source_file.write_text("module good; endmodule\n", encoding="utf-8")

    repository = FileSystemSourceRepository()
    loaded = repository.load_file(str(source_file))
    assert loaded.location.endswith("good.v")
    assert "module good" in loaded.content


def test_source_repository_rejects_non_verilog_extension(tmp_path) -> None:
    source_file = tmp_path / "bad.sv"
    source_file.write_text("module bad; endmodule\n", encoding="utf-8")

    repository = FileSystemSourceRepository()
    with pytest.raises(InputValidationError, match=r"expected a \.v file"):
        repository.load_file(str(source_file))


def test_extract_steps_handles_casez() -> None:
    body = "\n".join(
        [
            "casez (data)",
            "8'b1???_????: result <= 8'hFF;",
            "default: result <= 8'h00;",
            "endcase",
        ]
    )
    steps = _extract_steps(body)
    assert len(steps) == 1
    assert isinstance(steps[0], SwitchFlowStep)
    assert len(steps[0].cases) == 2


def test_extract_steps_handles_casex() -> None:
    body = "\n".join(
        [
            "casex (data)",
            "8'b1xxx_xxxx: result <= 8'hFE;",
            "default: result <= 8'h00;",
            "endcase",
        ]
    )
    steps = _extract_steps(body)
    assert len(steps) == 1
    assert isinstance(steps[0], SwitchFlowStep)
    assert len(steps[0].cases) == 2


def test_extract_steps_strips_comments() -> None:
    body = "\n".join(
        [
            "// This is a comment",
            "result <= data_in; /* inline block comment */",
            "accumulator <= accumulator + 1;",
        ]
    )
    steps = _extract_steps(body)
    # Comment line should NOT become an action step
    assert len(steps) == 2
    assert all(isinstance(s, ActionFlowStep) for s in steps)


def test_extract_steps_handles_named_begin() -> None:
    body = "\n".join(
        [
            "begin : my_block",
            "result <= data_in;",
            "end",
        ]
    )
    steps = _extract_steps(body)
    assert len(steps) == 1
    assert isinstance(steps[0], ActionFlowStep)


def test_scan_single_statement_always() -> None:
    source = "module top; always @(posedge clk) result <= data_in; endmodule\n"
    blocks = _scan_procedural_blocks(source)
    assert len(blocks) == 1
    assert "result <= data_in" in blocks[0].body


def test_scan_captures_sensitivity_list() -> None:
    source = "module top; always @(posedge clk or negedge rst) begin x <= 1; end endmodule\n"
    blocks = _scan_procedural_blocks(source)
    assert len(blocks) == 1
    assert blocks[0].sensitivity is not None
    assert "posedge clk" in blocks[0].sensitivity


def test_extract_steps_handles_fork_join() -> None:
    body = "\n".join(
        [
            "fork",
            "result <= data_in;",
            "accumulator <= 0;",
            "join",
        ]
    )
    steps = _extract_steps(body)
    assert len(steps) == 1
    assert isinstance(steps[0], ForkJoinFlowStep)
    assert steps[0].join_type == "join"
    assert len(steps[0].body_steps) == 2


def test_extract_steps_handles_fork_join_any() -> None:
    body = "\n".join(
        [
            "fork",
            "result <= data_in;",
            "join_any",
        ]
    )
    steps = _extract_steps(body)
    assert len(steps) == 1
    assert isinstance(steps[0], ForkJoinFlowStep)
    assert steps[0].join_type == "join_any"


def test_extract_steps_handles_delay() -> None:
    body = "#10 result <= 8'hAA;"
    steps = _extract_steps(body)
    assert len(steps) == 1
    assert isinstance(steps[0], DelayFlowStep)
    assert steps[0].delay == "10"


def test_extract_steps_handles_event_wait() -> None:
    body = "\n".join(
        [
            "@(posedge clk)",
            "result <= data_in;",
        ]
    )
    steps = _extract_steps(body)
    assert len(steps) == 1
    assert isinstance(steps[0], EventWaitFlowStep)
    assert "posedge clk" in steps[0].event


def test_extract_steps_handles_wait_condition() -> None:
    body = "\n".join(
        [
            "wait (ready == 1'b1)",
            "accumulator <= accumulator + 1;",
        ]
    )
    steps = _extract_steps(body)
    assert len(steps) == 1
    assert isinstance(steps[0], WaitConditionFlowStep)
    assert "ready" in steps[0].condition


def test_full_fixture_extracts_all_constructs() -> None:
    import pathlib

    fixture = pathlib.Path(__file__).parent / "fixtures" / "full.v"
    source = SourceUnit(
        identifier=SourceUnitId("full.v"),
        location=str(fixture),
        content=fixture.read_text(),
    )
    diagram = AntlrVerilogControlFlowExtractor().extract(source)
    # Should find multiple procedural blocks
    assert len(diagram.functions) >= 6
    step_types = set()
    for func in diagram.functions:
        _collect_step_types(func.steps, step_types)
    # Must have found core types
    assert IfFlowStep in step_types
    assert SwitchFlowStep in step_types
    assert ForInFlowStep in step_types
    assert WhileFlowStep in step_types
    assert RepeatWhileFlowStep in step_types
    assert ForeverFlowStep in step_types
    assert DisableFlowStep in step_types
    assert ForkJoinFlowStep in step_types
    assert DelayFlowStep in step_types
    assert EventWaitFlowStep in step_types
    assert WaitConditionFlowStep in step_types


def _collect_step_types(steps, result: set) -> None:
    from vodor.domain.control_flow import ControlFlowStep

    for s in steps:
        result.add(type(s))
        if hasattr(s, "then_steps"):
            _collect_step_types(s.then_steps, result)
        if hasattr(s, "else_steps"):
            _collect_step_types(s.else_steps, result)
        if hasattr(s, "body_steps"):
            _collect_step_types(s.body_steps, result)
        if hasattr(s, "cases"):
            for c in s.cases:
                _collect_step_types(c.steps, result)


# ── Additional extractor tests ──


class TestScanProceduralBlocks:
    def test_multiple_always_blocks(self) -> None:
        source = "\n".join(
            [
                "module top;",
                "always @(posedge clk) begin x <= 1; end",
                "always @(posedge rst) begin y <= 0; end",
                "endmodule",
            ]
        )
        blocks = _scan_procedural_blocks(source)
        assert len(blocks) == 2
        assert blocks[0].name == "always_1"
        assert blocks[1].name == "always_2"

    def test_initial_block(self) -> None:
        source = "module top; initial begin x <= 0; end endmodule"
        blocks = _scan_procedural_blocks(source)
        assert len(blocks) == 1
        assert blocks[0].kind == "initial"

    def test_sensitivity_star(self) -> None:
        source = "module top; always @* begin x <= y; end endmodule"
        blocks = _scan_procedural_blocks(source)
        assert len(blocks) == 1
        assert blocks[0].sensitivity == "*"

    def test_no_begin_skipped(self) -> None:
        """always without begin/end or single statement is handled."""
        source = "module top; always @(posedge clk) result <= data; endmodule"
        blocks = _scan_procedural_blocks(source)
        assert len(blocks) == 1
        assert "result <= data" in blocks[0].body

    def test_comments_in_source_ignored(self) -> None:
        source = "\n".join(
            [
                "module top;",
                "// always should not match",
                "always @(posedge clk) begin x <= 1; end",
                "endmodule",
            ]
        )
        blocks = _scan_procedural_blocks(source)
        assert len(blocks) == 1

    def test_deeply_nested_begin_end(self) -> None:
        source = "\n".join(
            [
                "module top;",
                "always @(posedge clk) begin",
                "  if (a) begin",
                "    if (b) begin",
                "      x <= 1;",
                "    end",
                "  end",
                "end",
                "endmodule",
            ]
        )
        blocks = _scan_procedural_blocks(source)
        assert len(blocks) == 1
        assert "x <= 1" in blocks[0].body


class TestExtractStepsIf:
    def test_if_else_if_chain(self) -> None:
        body = "\n".join(
            [
                "if (a > 0)",
                "x <= 1;",
                "else if (a > 10)",
                "x <= 2;",
                "else",
                "x <= 3;",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps) == 1
        if_step = steps[0]
        assert isinstance(if_step, IfFlowStep)
        assert len(if_step.then_steps) == 1
        assert len(if_step.else_steps) == 1
        nested_if = if_step.else_steps[0]
        assert isinstance(nested_if, IfFlowStep)
        assert len(nested_if.else_steps) == 1

    def test_if_with_begin_on_same_line(self) -> None:
        body = "\n".join(
            [
                "if (en) begin",
                "x <= 1;",
                "y <= 2;",
                "end",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], IfFlowStep)
        assert len(steps[0].then_steps) == 2

    def test_if_single_line_no_body(self) -> None:
        body = "if (flag) result <= done;"
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], IfFlowStep)


class TestExtractStepsWhile:
    def test_while_with_begin(self) -> None:
        body = "\n".join(
            [
                "while (count > 0) begin",
                "count <= count - 1;",
                "result <= result + 1;",
                "end",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], WhileFlowStep)
        assert steps[0].condition == "count > 0"
        assert len(steps[0].body_steps) == 2


class TestExtractStepsFor:
    def test_for_header_extraction(self) -> None:
        body = "\n".join(
            [
                "for (i = 0; i < 8; i = i + 1)",
                "result <= result << 1;",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], ForInFlowStep)
        assert "i = 0; i < 8; i = i + 1" in steps[0].header


class TestExtractStepsRepeat:
    def test_repeat_condition(self) -> None:
        body = "\n".join(
            [
                "repeat (8)",
                "result <= result + 1;",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], RepeatWhileFlowStep)
        assert steps[0].condition == "8"


class TestExtractStepsForever:
    def test_forever_with_begin(self) -> None:
        body = "\n".join(
            [
                "forever begin",
                "x <= x + 1;",
                "end",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], ForeverFlowStep)
        assert len(steps[0].body_steps) == 1


class TestExtractStepsDisable:
    def test_disable_target(self) -> None:
        body = "disable processing_block;"
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], DisableFlowStep)
        assert steps[0].target == "processing_block"


class TestExtractStepsCase:
    def test_case_single_line_labels(self) -> None:
        """Single-line case labels: label: statement;"""
        body = "\n".join(
            [
                "case (opcode)",
                "4'h0: result <= 0;",
                "4'h1: result <= 1;",
                "default: result <= 2;",
                "endcase",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], SwitchFlowStep)
        assert len(steps[0].cases) == 3
        # Each case should have a body statement from the same line
        assert all(len(c.steps) >= 1 for c in steps[0].cases)

    def test_case_multiline_labels(self) -> None:
        body = "\n".join(
            [
                "case (state)",
                "2'b00:",
                "result <= 0;",
                "result <= result + 1;",
                "2'b01:",
                "result <= 1;",
                "endcase",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps[0].cases[0].steps) >= 1
        assert len(steps[0].cases[1].steps) >= 1

    def test_case_with_begin_end(self) -> None:
        body = "\n".join(
            [
                "case (x)",
                "0: begin",
                "a <= 1;",
                "b <= 2;",
                "end",
                "default: c <= 0;",
                "endcase",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps[0].cases) == 2
        # "0:" label with begin on same line — body contains a and b
        assert len(steps[0].cases[0].steps) >= 2

    def test_casez_single_line_labels(self) -> None:
        body = "\n".join(
            [
                "casez (data)",
                "8'b1???_????: result <= 1;",
                "default: result <= 0;",
                "endcase",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps[0].cases) == 2
        assert all(len(c.steps) >= 1 for c in steps[0].cases)

    def test_casex_single_line_labels(self) -> None:
        body = "\n".join(
            [
                "casex (data)",
                "8'b1xxx_xxxx: result <= 1;",
                "default: result <= 0;",
                "endcase",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps[0].cases) == 2


class TestExtractStepsFork:
    def test_fork_join_none(self) -> None:
        body = "\n".join(
            [
                "fork",
                "x <= 1;",
                "join_none",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], ForkJoinFlowStep)
        assert steps[0].join_type == "join_none"

    def test_fork_with_nested_if(self) -> None:
        body = "\n".join(
            [
                "fork",
                "if (en) x <= 1;",
                "y <= 2;",
                "join",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], ForkJoinFlowStep)
        # The if consumes "y <= 2;" as its then-body (single-line if without begin)
        assert len(steps[0].body_steps) >= 1


class TestExtractStepsDelay:
    def test_delay_only(self) -> None:
        body = "#5;"
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], DelayFlowStep)

    def test_delay_same_line(self) -> None:
        body = "#10 x <= 1;"
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], DelayFlowStep)
        assert steps[0].delay == "10"
        assert len(steps[0].body_steps) == 1


class TestExtractStepsEventWait:
    def test_event_same_line(self) -> None:
        body = "@(posedge clk) x <= data;"
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], EventWaitFlowStep)
        assert "posedge clk" in steps[0].event
        assert len(steps[0].body_steps) == 1

    def test_event_next_line(self) -> None:
        body = "\n".join(
            [
                "@(posedge clk)",
                "x <= data;",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], EventWaitFlowStep)
        assert len(steps[0].body_steps) == 1


class TestExtractStepsWaitCondition:
    def test_wait_same_line(self) -> None:
        body = "wait (ready) x <= data;"
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], WaitConditionFlowStep)
        assert steps[0].condition == "ready"
        assert len(steps[0].body_steps) == 1

    def test_wait_next_line(self) -> None:
        body = "\n".join(
            [
                "wait (flag == 1)",
                "x <= 1;",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], WaitConditionFlowStep)


class TestExtractStepsComments:
    def test_line_comments_removed(self) -> None:
        body = "\n".join(
            [
                "// comment only",
                "x <= 1;",
                "// another comment",
                "y <= 2;",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps) == 2

    def test_block_comments_removed(self) -> None:
        body = "x <= 1; /* removed */ y <= 2;"
        steps = _extract_steps(body)
        # After stripping block comment, rest should parse
        assert any("x" in s.label for s in steps if isinstance(s, ActionFlowStep))


class TestExtractStepsNamedBegin:
    def test_named_begin_label_stripped(self) -> None:
        body = "\n".join(
            [
                ": my_block",
                "x <= 1;",
                "y <= 2;",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps) == 2
        assert all(isinstance(s, ActionFlowStep) for s in steps)

    def test_begin_named_colon_in_body(self) -> None:
        body = "\n".join(
            [
                "begin : labeled",
                "x <= 1;",
                "end",
            ]
        )
        steps = _extract_steps(body)
        assert len(steps) == 1
        assert isinstance(steps[0], ActionFlowStep)


class TestSignatureBuilding:
    def test_always_with_sensitivity(self) -> None:
        source = "module top; always @(posedge clk) begin x <= 1; end endmodule"
        diagram = AntlrVerilogControlFlowExtractor().extract(
            SourceUnit(identifier=SourceUnitId("t.v"), location="t.v", content=source)
        )
        assert len(diagram.functions) == 1
        assert "posedge clk" in diagram.functions[0].signature
        assert diagram.functions[0].sensitivity is not None

    def test_initial_without_sensitivity(self) -> None:
        source = "module top; initial begin x <= 1; end endmodule"
        diagram = AntlrVerilogControlFlowExtractor().extract(
            SourceUnit(identifier=SourceUnitId("t.v"), location="t.v", content=source)
        )
        assert len(diagram.functions) == 1
        assert diagram.functions[0].signature.startswith("initial")
        assert diagram.functions[0].sensitivity is None

    def test_qualified_name_without_container(self) -> None:
        source = "module top; always @(posedge clk) begin x <= 1; end endmodule"
        diagram = AntlrVerilogControlFlowExtractor().extract(
            SourceUnit(identifier=SourceUnitId("t.v"), location="t.v", content=source)
        )
        assert diagram.functions[0].qualified_name == "always_1"


class TestScanFunctionTask:
    def test_function_extraction(self) -> None:
        source = "\n".join(
            [
                "module top;",
                "function [7:0] adder;",
                "  input [7:0] a;",
                "  input [7:0] b;",
                "  begin",
                "    adder = a + b;",
                "  end",
                "endfunction",
                "endmodule",
            ]
        )
        diagram = AntlrVerilogControlFlowExtractor().extract(
            SourceUnit(identifier=SourceUnitId("t.v"), location="t.v", content=source)
        )
        func_names = [f.name for f in diagram.functions]
        assert "adder" in func_names
        adder = [f for f in diagram.functions if f.name == "adder"][0]
        assert adder.signature.startswith("function")
        assert any("a + b" in s.label for s in adder.steps if isinstance(s, ActionFlowStep))

    def test_task_extraction(self) -> None:
        source = "\n".join(
            [
                "module top;",
                "task reset_all;",
                "  begin",
                "    x <= 0;",
                "    y <= 0;",
                "  end",
                "endtask",
                "endmodule",
            ]
        )
        diagram = AntlrVerilogControlFlowExtractor().extract(
            SourceUnit(identifier=SourceUnitId("t.v"), location="t.v", content=source)
        )
        task_names = [f.name for f in diagram.functions]
        assert "reset_all" in task_names
        reset = [f for f in diagram.functions if f.name == "reset_all"][0]
        assert reset.signature.startswith("task")
        assert len(reset.steps) >= 1

    def test_function_with_control_flow(self) -> None:
        source = "\n".join(
            [
                "module top;",
                "function [7:0] clamp;",
                "  input [7:0] val;",
                "  begin",
                "    if (val > 8'hFF)",
                "      clamp = 8'hFF;",
                "    else",
                "      clamp = val;",
                "  end",
                "endfunction",
                "endmodule",
            ]
        )
        diagram = AntlrVerilogControlFlowExtractor().extract(
            SourceUnit(identifier=SourceUnitId("t.v"), location="t.v", content=source)
        )
        clamp = [f for f in diagram.functions if f.name == "clamp"][0]
        # Body includes input declarations + begin/end block with if/else
        assert len(clamp.steps) >= 1
        # The if should be somewhere in the steps
        if_steps = [s for s in clamp.steps if isinstance(s, IfFlowStep)]
        assert len(if_steps) >= 1

    def test_function_always_initial_coexist(self) -> None:
        source = "\n".join(
            [
                "module top;",
                "always @(posedge clk) begin x <= 1; end",
                "initial begin y <= 0; end",
                "function [7:0] compute; begin compute = x + y; end endfunction",
                "endmodule",
            ]
        )
        diagram = AntlrVerilogControlFlowExtractor().extract(
            SourceUnit(identifier=SourceUnitId("t.v"), location="t.v", content=source)
        )
        names = [f.name for f in diagram.functions]
        assert "always_1" in names
        assert "initial_2" in names
        assert "compute" in names

    def test_function_name_from_header(self) -> None:
        """Function name is the last identifier in the header line."""
        source = "\n".join(
            [
                "module top;",
                "function automatic [15:0] multiply;",
                "  begin multiply = 0; end",
                "endfunction",
                "endmodule",
            ]
        )
        diagram = AntlrVerilogControlFlowExtractor().extract(
            SourceUnit(identifier=SourceUnitId("t.v"), location="t.v", content=source)
        )
        func_names = [f.name for f in diagram.functions]
        assert "multiply" in func_names


class TestTopLevelActions:
    def test_scan_top_level_actions_simple(self):
        cleaned = "module top; assign a = b; assign c = d; endmodule"
        blocks = ()
        actions = _scan_top_level_actions(cleaned, blocks)
        assert len(actions) == 2
        assert actions[0].label == "assign a = b"
        assert actions[1].label == "assign c = d"

    def test_scan_top_level_actions_ignores_inside_always(self):
        source = """module top;
  always @(posedge clk) begin
    x <= y;
  end
  assign a = b;
endmodule"""
        cleaned = _strip_comments(source)
        blocks = _scan_procedural_blocks(cleaned)
        actions = _scan_top_level_actions(cleaned, blocks)
        assert len(actions) == 1
        assert actions[0].label == "assign a = b"

    def test_scan_top_level_actions_force_release(self):
        source = "module top; force sig = 1'b1; release sig; endmodule"
        cleaned = _strip_comments(source)
        blocks = _scan_procedural_blocks(cleaned)
        actions = _scan_top_level_actions(cleaned, blocks)
        assert len(actions) == 2
        assert actions[0].label == "force sig = 1'b1"
        assert actions[1].label == "release sig"

    def test_extractor_includes_top_level_steps(self):
        source = "module top; assign a = b; always @(posedge clk) x <= y; endmodule"
        source_unit = SourceUnit(identifier=SourceUnitId("top.v"), location="top.v", content=source)
        diagram = AntlrVerilogControlFlowExtractor().extract(source_unit)
        assert len(diagram.top_level_steps) == 1
        assert isinstance(diagram.top_level_steps[0], ActionFlowStep)
        assert diagram.top_level_steps[0].label == "assign a = b"
        # Also check that always block is in functions
        assert len(diagram.functions) == 1
        assert diagram.functions[0].name == "always_1"

    def test_top_level_steps_ordered_before_functions(self):
        source = """module top;
assign a = b;
always @(posedge clk) x <= y;
assign c = d;
initial z = 0;
endmodule"""
        source_unit = SourceUnit(identifier=SourceUnitId("top.v"), location="top.v", content=source)
        diagram = AntlrVerilogControlFlowExtractor().extract(source_unit)
        # top_level_steps: both assigns in order
        assert len(diagram.top_level_steps) == 2
        assert diagram.top_level_steps[0].label == "assign a = b"
        assert diagram.top_level_steps[1].label == "assign c = d"
        # functions: always and initial in order of appearance
        assert len(diagram.functions) == 2
        assert diagram.functions[0].name == "always_1"
        assert diagram.functions[1].name == "initial_2"


# ── Smell detector tests ──


class TestSmellDetectors:
    def _extract_functions(self, source: str):
        """Helper: extract functions from Verilog source."""
        source_unit = SourceUnit(
            identifier=SourceUnitId("test.v"),
            location="test.v",
            content=source,
        )
        diagram = AntlrVerilogControlFlowExtractor().extract(source_unit)
        return diagram.functions

    def test_blocking_in_sequential_detected(self) -> None:
        source = "module top; always @(posedge clk) begin count = count + 1; end endmodule"
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        blocking = [s for s in smells if s.kind == SmellKind.BLOCKING_IN_SEQUENTIAL]
        assert len(blocking) >= 1
        assert blocking[0].severity == SmellSeverity.ERROR

    def test_no_smell_nonblocking_in_sequential(self) -> None:
        source = "module top; always @(posedge clk) begin count <= count + 1; end endmodule"
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        blocking = [s for s in smells if s.kind == SmellKind.BLOCKING_IN_SEQUENTIAL]
        assert len(blocking) == 0

    def test_nonblocking_in_combinational_detected(self) -> None:
        source = "module top; always @* begin result <= a & b; end endmodule"
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        nb = [s for s in smells if s.kind == SmellKind.NONBLOCKING_IN_COMBINATIONAL]
        assert len(nb) >= 1
        assert nb[0].severity == SmellSeverity.WARNING

    def test_no_smell_blocking_in_combinational(self) -> None:
        source = "module top; always @* begin result = a & b; end endmodule"
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        nb = [s for s in smells if s.kind == SmellKind.NONBLOCKING_IN_COMBINATIONAL]
        assert len(nb) == 0

    def test_latch_risk_incomplete_if_detected(self) -> None:
        source = "\n".join([
            "module top;",
            "always @* begin",
            "if (en)",
            "result = data;",
            "end",
            "endmodule",
        ])
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        latch = [s for s in smells if s.kind == SmellKind.LATCH_RISK_INCOMPLETE_IF]
        assert len(latch) >= 1

    def test_no_latch_risk_with_else(self) -> None:
        source = "\n".join([
            "module top;",
            "always @* begin",
            "if (en)",
            "result = data;",
            "else",
            "result = 1'b0;",
            "end",
            "endmodule",
        ])
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        latch = [s for s in smells if s.kind == SmellKind.LATCH_RISK_INCOMPLETE_IF]
        assert len(latch) == 0

    def test_case_missing_default_detected(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "case (state)",
            "2'b00: x <= 0;",
            "2'b01: x <= 1;",
            "endcase",
            "end",
            "endmodule",
        ])
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        missing = [s for s in smells if s.kind == SmellKind.CASE_MISSING_DEFAULT]
        assert len(missing) >= 1

    def test_no_smell_case_with_default(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "case (state)",
            "2'b00: x <= 0;",
            "default: x <= 1;",
            "endcase",
            "end",
            "endmodule",
        ])
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        missing = [s for s in smells if s.kind == SmellKind.CASE_MISSING_DEFAULT]
        assert len(missing) == 0

    def test_casex_usage_detected(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "casex (data)",
            "8'b1xxx_xxxx: result <= 1;",
            "default: result <= 0;",
            "endcase",
            "end",
            "endmodule",
        ])
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        casex = [s for s in smells if s.kind == SmellKind.CASEX_USAGE]
        assert len(casex) >= 1
        assert casex[0].severity == SmellSeverity.INFO

    def test_no_smell_casez_not_flagged(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "casez (data)",
            "8'b1???_????: result <= 1;",
            "default: result <= 0;",
            "endcase",
            "end",
            "endmodule",
        ])
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        casex = [s for s in smells if s.kind == SmellKind.CASEX_USAGE]
        assert len(casex) == 0

    def test_initial_block_no_sequential_smells(self) -> None:
        """initial blocks have no sensitivity — no sequential/combinational smells."""
        source = "module top; initial begin count = 0; end endmodule"
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        blocking = [s for s in smells if s.kind == SmellKind.BLOCKING_IN_SEQUENTIAL]
        assert len(blocking) == 0


class TestSmellFalsePositiveFixes:
    """Tests for false positive suppression in smell detectors."""

    def _extract_functions(self, source: str):
        source_unit = SourceUnit(
            identifier=SourceUnitId("test.v"),
            location="test.v",
            content=source,
        )
        diagram = AntlrVerilogControlFlowExtractor().extract(source_unit)
        return diagram.functions

    def test_intermediate_variable_not_flagged(self) -> None:
        """Blocking to an intermediate variable that feeds into nonblocking RHS is not flagged."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "ptr_temp = ptr_reg + 1;",
            "ptr_reg <= ptr_temp;",
            "end",
            "endmodule",
        ])
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        blocking = [s for s in smells if s.kind == SmellKind.BLOCKING_IN_SEQUENTIAL]
        assert len(blocking) == 0

    def test_real_blocking_in_sequential_still_flagged(self) -> None:
        """Blocking to a register (not intermediate) is still flagged."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "count = count + 1;",
            "end",
            "endmodule",
        ])
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        blocking = [s for s in smells if s.kind == SmellKind.BLOCKING_IN_SEQUENTIAL]
        assert len(blocking) == 1

    def test_mixed_blocking_nonblocking_flagged(self) -> None:
        """Blocking and nonblocking to same register is flagged."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "if (rst) count = 0;",
            "else count <= count + 1;",
            "end",
            "endmodule",
        ])
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        blocking = [s for s in smells if s.kind == SmellKind.BLOCKING_IN_SEQUENTIAL]
        assert len(blocking) == 1

    def test_latch_risk_suppressed_with_default(self) -> None:
        """if without else in combinational is NOT flagged when default assigned above."""
        source = "\n".join([
            "module top;",
            "always @* begin",
            "result = 0;",
            "if (en)",
            "result = data;",
            "end",
            "endmodule",
        ])
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        latch = [s for s in smells if s.kind == SmellKind.LATCH_RISK_INCOMPLETE_IF]
        assert len(latch) == 0

    def test_latch_risk_still_flagged_without_default(self) -> None:
        """if without else in combinational IS flagged when no default exists."""
        source = "\n".join([
            "module top;",
            "always @* begin",
            "if (en)",
            "result = data;",
            "end",
            "endmodule",
        ])
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        latch = [s for s in smells if s.kind == SmellKind.LATCH_RISK_INCOMPLETE_IF]
        assert len(latch) == 1

    def test_partial_default_still_flagged(self) -> None:
        """Default for one var doesn't suppress latch risk on a different var."""
        source = "\n".join([
            "module top;",
            "always @* begin",
            "x = 0;",
            "if (en) begin",
            "x = data;",
            "y = 1;",
            "end",
            "end",
            "endmodule",
        ])
        functions = self._extract_functions(source)
        smells = detect_smells(functions[0])
        latch = [s for s in smells if s.kind == SmellKind.LATCH_RISK_INCOMPLETE_IF]
        assert len(latch) == 1  # y has no default


class TestNewSmellDetectors:
    """Tests for S6-S17 smell detectors."""

    def _extract(self, source: str):
        from vodor.application.smell_detectors import detect_module_smells, detect_smells
        su = SourceUnit(identifier=SourceUnitId("t.v"), location="t.v", content=source)
        diagram = AntlrVerilogControlFlowExtractor().extract(su)
        per_func = []
        for f in diagram.functions:
            per_func.extend(detect_smells(f))
        module = detect_module_smells(diagram)
        return per_func, module

    def _smells(self, source: str) -> list:
        per_func, _ = self._extract(source)
        return per_func

    # S6: Mixed blocking/nonblocking
    def test_mixed_blocking_nonblocking(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "if (rst) begin",
            "count = 0;",
            "end",
            "else begin",
            "count <= count + 1;",
            "end",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        mixed = [s for s in smells if s.kind == SmellKind.MIXED_BLOCKING_NONBLOCKING]
        assert len(mixed) >= 1
        assert mixed[0].severity == SmellSeverity.ERROR

    def test_no_mixed_when_consistent(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "count <= count + 1;",
            "valid <= 1;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        mixed = [s for s in smells if s.kind == SmellKind.MIXED_BLOCKING_NONBLOCKING]
        assert len(mixed) == 0

    # S7: Missing reset
    def test_missing_reset_detected(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "count <= count + 1;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        reset = [s for s in smells if s.kind == SmellKind.MISSING_RESET]
        assert len(reset) == 1
        assert reset[0].severity == SmellSeverity.INFO

    def test_no_missing_reset_with_rst(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "if (rst) count <= 0;",
            "else count <= count + 1;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        reset = [s for s in smells if s.kind == SmellKind.MISSING_RESET]
        assert len(reset) == 0

    # S8: Unsized literal
    def test_unsized_literal_detected(self) -> None:
        source = "module top; always @(posedge clk) begin count <= 0; end endmodule"
        smells = self._smells(source)
        unsized = [s for s in smells if s.kind == SmellKind.UNSIZED_LITERAL]
        assert len(unsized) >= 1

    def test_sized_literal_not_flagged(self) -> None:
        source = "module top; always @(posedge clk) begin count <= 8'h00; end endmodule"
        smells = self._smells(source)
        unsized = [s for s in smells if s.kind == SmellKind.UNSIZED_LITERAL]
        assert len(unsized) == 0

    # S9: Delay in synthesizable
    def test_delay_in_sequential_detected(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "#1 result <= data;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        delay = [s for s in smells if s.kind == SmellKind.DELAY_IN_SYNTHESIZABLE]
        assert len(delay) >= 1
        assert delay[0].severity == SmellSeverity.WARNING

    # S10: Procedural continuous assign
    def test_procedural_continuous_detected(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "assign out = data;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        pca = [s for s in smells if s.kind == SmellKind.PROCEDURAL_CONTINUOUS_USAGE]
        assert len(pca) >= 1

    # S11: Empty case branch
    def test_empty_case_branch_detected(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "case (state)",
            "2'b00:",
            "2'b01: x <= 1;",
            "endcase",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        empty = [s for s in smells if s.kind == SmellKind.EMPTY_CASE_BRANCH]
        assert len(empty) >= 1

    # S12: Deep nesting
    def test_deep_nesting_detected(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "if (a) begin",
            "  if (b) begin",
            "    if (c) begin",
            "      if (d) x <= 1;",
            "    end",
            "  end",
            "end",
            "end",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        deep = [s for s in smells if s.kind == SmellKind.DEEP_NESTING]
        assert len(deep) >= 1

    def test_shallow_nesting_not_flagged(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "if (a) begin",
            "  if (b) x <= 1;",
            "end",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        deep = [s for s in smells if s.kind == SmellKind.DEEP_NESTING]
        assert len(deep) == 0

    # S13: Large case
    def test_large_case_not_flagged_under_threshold(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "case (state)",
            "0: x <= 0;",
            "1: x <= 1;",
            "default: x <= 2;",
            "endcase",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        large = [s for s in smells if s.kind == SmellKind.LARGE_CASE]
        assert len(large) == 0

    # S14: Multi-driver signal
    def test_multi_driver_signal_detected(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin x <= 1; end",
            "always @(posedge rst) begin x <= 0; end",
            "endmodule",
        ])
        _, module_smells = self._extract(source)
        multi = [s for s in module_smells if s.kind == SmellKind.MULTI_DRIVER_SIGNAL]
        assert len(multi) >= 1
        assert multi[0].severity == SmellSeverity.ERROR

    def test_no_multi_driver_different_signals(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin x <= 1; end",
            "always @(posedge rst) begin y <= 0; end",
            "endmodule",
        ])
        _, module_smells = self._extract(source)
        multi = [s for s in module_smells if s.kind == SmellKind.MULTI_DRIVER_SIGNAL]
        assert len(multi) == 0

    def test_no_multi_driver_initial_plus_always(self) -> None:
        """initial + always driving same signal is not a multi-driver error."""
        source = "\n".join([
            "module top;",
            "initial begin x <= 0; end",
            "always @(posedge clk) begin x <= 1; end",
            "endmodule",
        ])
        _, module_smells = self._extract(source)
        multi = [s for s in module_smells if s.kind == SmellKind.MULTI_DRIVER_SIGNAL]
        assert len(multi) == 0

    # S15: Incomplete sensitivity
    def test_incomplete_sensitivity_detected(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(a) begin",
            "result = a + b;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        sens = [s for s in smells if s.kind == SmellKind.INCOMPLETE_SENSITIVITY]
        assert len(sens) >= 1
        assert "b" in sens[0].message

    def test_wildcard_sensitivity_not_flagged(self) -> None:
        source = "\n".join([
            "module top;",
            "always @* begin",
            "result = a + b;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        sens = [s for s in smells if s.kind == SmellKind.INCOMPLETE_SENSITIVITY]
        assert len(sens) == 0

    # S16: Duplicate case label
    def test_duplicate_case_label_detected(self) -> None:
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "case (state)",
            "2'b00: x <= 0;",
            "2'b00: x <= 1;",
            "default: x <= 2;",
            "endcase",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        dup = [s for s in smells if s.kind == SmellKind.DUPLICATE_CASE_LABEL]
        assert len(dup) >= 1
        assert dup[0].severity == SmellSeverity.ERROR

    def test_bus_index_case_label_not_false_positive(self) -> None:
        """Case labels with bus indices like [31:0] should not be split at the colon."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "case (sel)",
            "xgmii_rxd_next[31:0]: out <= a;",
            "xgmii_rxd_next[63:32]: out <= b;",
            "default: out <= 0;",
            "endcase",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        dup = [s for s in smells if s.kind == SmellKind.DUPLICATE_CASE_LABEL]
        assert len(dup) == 0

    # S17: Forever without disable
    def test_forever_without_disable_detected(self) -> None:
        source = "\n".join([
            "module top;",
            "initial begin",
            "forever begin",
            "clk <= ~clk;",
            "end",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        forever = [s for s in smells if s.kind == SmellKind.FOREVER_WITHOUT_DISABLE]
        assert len(forever) >= 1

    def test_forever_with_disable_not_flagged(self) -> None:
        source = "\n".join([
            "module top;",
            "initial begin",
            "forever begin",
            "clk <= ~clk;",
            "disable gen;",
            "end",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        forever = [s for s in smells if s.kind == SmellKind.FOREVER_WITHOUT_DISABLE]
        assert len(forever) == 0


class TestSmellDetectorHelpers:
    """Direct tests for internal helper functions."""

    def test_extract_lhs_var_simple(self) -> None:
        from vodor.application.smell_detectors import _extract_lhs_var
        assert _extract_lhs_var("count = count + 1") == "count"

    def test_extract_lhs_var_nonblocking(self) -> None:
        from vodor.application.smell_detectors import _extract_lhs_var
        assert _extract_lhs_var("result <= a & b") == "result"

    def test_extract_lhs_var_bus_index(self) -> None:
        from vodor.application.smell_detectors import _extract_lhs_var
        assert _extract_lhs_var("data[7:0] = 8'hFF") == "data"

    def test_extract_lhs_var_no_assignment(self) -> None:
        from vodor.application.smell_detectors import _extract_lhs_var
        assert _extract_lhs_var("$display(msg)") is None

    def test_extract_lhs_var_starts_with_digit(self) -> None:
        from vodor.application.smell_detectors import _extract_lhs_var
        assert _extract_lhs_var("2'b00 = something") is None

    def test_is_unsized_literal_decimal(self) -> None:
        from vodor.application.smell_detectors import _is_unsized_literal
        assert _is_unsized_literal("count <= 0") is True
        assert _is_unsized_literal("count <= 255") is True
        assert _is_unsized_literal("count = -1") is True

    def test_is_unsized_literal_sized_not_flagged(self) -> None:
        from vodor.application.smell_detectors import _is_unsized_literal
        assert _is_unsized_literal("count <= 8'h00") is False
        assert _is_unsized_literal("count <= 1'b1") is False
        assert _is_unsized_literal("count <= 4'd5") is False

    def test_is_unsized_literal_expression_not_flagged(self) -> None:
        from vodor.application.smell_detectors import _is_unsized_literal
        assert _is_unsized_literal("count <= a + 1") is False
        assert _is_unsized_literal("count = data") is False

    def test_is_combinational(self) -> None:
        from vodor.application.smell_detectors import _is_combinational
        assert _is_combinational("*") is True
        assert _is_combinational("(*)") is True  # strips parens internally
        assert _is_combinational("(posedge clk)") is False
        assert _is_combinational(None) is False

    def test_is_sequential(self) -> None:
        from vodor.application.smell_detectors import _is_sequential
        assert _is_sequential("(posedge clk)") is True
        assert _is_sequential("(negedge rst)") is True
        assert _is_sequential("(posedge clk or negedge rst)") is True
        assert _is_sequential("*") is False
        assert _is_sequential(None) is False

    def test_is_explicit_sensitivity(self) -> None:
        from vodor.application.smell_detectors import _is_explicit_sensitivity
        assert _is_explicit_sensitivity("(a or b)") is True
        assert _is_explicit_sensitivity("(a)") is True
        assert _is_explicit_sensitivity("*") is False
        assert _is_explicit_sensitivity("(posedge clk)") is False
        assert _is_explicit_sensitivity(None) is False

    def test_parse_sensitivity_signals(self) -> None:
        from vodor.application.smell_detectors import _parse_sensitivity_signals
        assert _parse_sensitivity_signals("(posedge clk or negedge rst)") == {"clk", "rst"}
        assert _parse_sensitivity_signals("(a or b or c)") == {"a", "b", "c"}
        assert _parse_sensitivity_signals("(a)") == {"a"}
        assert _parse_sensitivity_signals("(*)") == set()

    def test_extract_identifiers_excludes_keywords(self) -> None:
        from vodor.application.smell_detectors import _extract_identifiers
        ids = _extract_identifiers("count = if + begin")
        assert "count" in ids
        assert "if" not in ids
        assert "begin" not in ids

    def test_extract_identifiers_excludes_number_literals(self) -> None:
        from vodor.application.smell_detectors import _extract_identifiers
        ids = _extract_identifiers("data = 8'hFF + 2'b01")
        assert "data" in ids
        # hex/binary literal prefixes should be cleaned
        assert len(ids) >= 1

    def test_extract_read_signals(self) -> None:
        from vodor.application.smell_detectors import _extract_read_signals
        signals = _extract_read_signals("result <= a + b")
        assert "a" in signals
        assert "b" in signals
        assert "result" not in signals


class TestSmellEdgeCases:
    """Edge cases and interactions between multiple smell detectors."""

    def _extract(self, source: str):
        from vodor.application.smell_detectors import detect_module_smells, detect_smells
        su = SourceUnit(identifier=SourceUnitId("t.v"), location="t.v", content=source)
        diagram = AntlrVerilogControlFlowExtractor().extract(su)
        per_func = []
        for f in diagram.functions:
            per_func.extend(detect_smells(f))
        module = detect_module_smells(diagram)
        return per_func, module

    def _smells(self, source: str) -> list:
        per_func, _ = self._extract(source)
        return per_func

    # ── S1 edge cases ──

    def test_blocking_in_sequential_inside_nested_if(self) -> None:
        """Blocking assignment deeply nested in sequential block is still caught."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "if (a) begin",
            "  if (b) begin",
            "    count = count + 1;",
            "  end",
            "end",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        blocking = [s for s in smells if s.kind == SmellKind.BLOCKING_IN_SEQUENTIAL]
        assert len(blocking) == 1

    def test_intermediate_var_inside_if_else(self) -> None:
        """Intermediate variable inside if/else in sequential is not flagged."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "if (sel) begin",
            "  tmp = a + b;",
            "  result <= tmp;",
            "end else begin",
            "  tmp = c + d;",
            "  result <= tmp;",
            "end",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        blocking = [s for s in smells if s.kind == SmellKind.BLOCKING_IN_SEQUENTIAL]
        assert len(blocking) == 0

    def test_intermediate_var_inside_case(self) -> None:
        """Intermediate variable inside case branch is not flagged."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "case (state)",
            "2'b00: begin",
            "  tmp = a + b;",
            "  result <= tmp;",
            "end",
            "default: result <= 0;",
            "endcase",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        blocking = [s for s in smells if s.kind == SmellKind.BLOCKING_IN_SEQUENTIAL]
        assert len(blocking) == 0

    # ── S2 edge cases ──

    def test_multiple_nonblocking_in_combinational(self) -> None:
        """Each nonblocking assignment in combinational gets its own smell."""
        source = "\n".join([
            "module top;",
            "always @* begin",
            "a <= 1;",
            "b <= 2;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        nb = [s for s in smells if s.kind == SmellKind.NONBLOCKING_IN_COMBINATIONAL]
        assert len(nb) == 2

    # ── S3 edge cases ──

    def test_latch_risk_in_nested_if(self) -> None:
        """Nested incomplete if in combinational is flagged."""
        source = "\n".join([
            "module top;",
            "always @* begin",
            "if (a) begin",
            "  if (b)",
            "    result = 1;",
            "end",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        latch = [s for s in smells if s.kind == SmellKind.LATCH_RISK_INCOMPLETE_IF]
        assert len(latch) >= 1

    def test_latch_risk_sequential_not_flagged(self) -> None:
        """Incomplete if in sequential block is NOT a latch risk."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "if (en)",
            "result <= data;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        latch = [s for s in smells if s.kind == SmellKind.LATCH_RISK_INCOMPLETE_IF]
        assert len(latch) == 0

    # ── S4 edge cases ──

    def test_case_missing_default_combinational_message(self) -> None:
        """Missing default in combinational mentions latch inference."""
        source = "\n".join([
            "module top;",
            "always @* begin",
            "case (sel)",
            "2'b00: out = a;",
            "2'b01: out = b;",
            "endcase",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        missing = [s for s in smells if s.kind == SmellKind.CASE_MISSING_DEFAULT]
        assert len(missing) >= 1
        assert "latch" in missing[0].message.lower()

    def test_case_missing_default_sequential_no_latch_message(self) -> None:
        """Missing default in sequential does NOT mention latch."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "case (sel)",
            "2'b00: out <= a;",
            "2'b01: out <= b;",
            "endcase",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        missing = [s for s in smells if s.kind == SmellKind.CASE_MISSING_DEFAULT]
        assert len(missing) >= 1
        assert "latch" not in missing[0].message.lower()

    # ── S5 edge cases ──

    def test_casex_in_combinational_detected(self) -> None:
        """casex in combinational block is also detected."""
        source = "\n".join([
            "module top;",
            "always @* begin",
            "casex (data)",
            "8'b1xxx_xxxx: result = 1;",
            "default: result = 0;",
            "endcase",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        casex = [s for s in smells if s.kind == SmellKind.CASEX_USAGE]
        assert len(casex) >= 1

    # ── S6 edge cases ──

    def test_mixed_different_vars_not_flagged(self) -> None:
        """Blocking to one var and nonblocking to another is fine."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "tmp = a + b;",
            "result <= tmp;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        mixed = [s for s in smells if s.kind == SmellKind.MIXED_BLOCKING_NONBLOCKING]
        assert len(mixed) == 0

    def test_mixed_inside_case_branches(self) -> None:
        """Mixed blocking/nonblocking inside different case branches is flagged."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "case (state)",
            "2'b00: count = 0;",
            "default: count <= count + 1;",
            "endcase",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        mixed = [s for s in smells if s.kind == SmellKind.MIXED_BLOCKING_NONBLOCKING]
        assert len(mixed) >= 1

    # ── S7 edge cases ──

    def test_missing_reset_with_async_rst(self) -> None:
        """Block with async_rst in condition is not flagged."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "if (async_rst) count <= 0;",
            "else count <= count + 1;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        reset = [s for s in smells if s.kind == SmellKind.MISSING_RESET]
        assert len(reset) == 0

    def test_missing_reset_with_rst_n(self) -> None:
        """Block with rst_n (active-low reset) is not flagged."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "if (!rst_n) count <= 0;",
            "else count <= count + 1;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        reset = [s for s in smells if s.kind == SmellKind.MISSING_RESET]
        assert len(reset) == 0

    def test_missing_reset_combinational_not_flagged(self) -> None:
        """Combinational blocks don't need reset — not flagged."""
        source = "\n".join([
            "module top;",
            "always @* begin",
            "result = a + b;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        reset = [s for s in smells if s.kind == SmellKind.MISSING_RESET]
        assert len(reset) == 0

    def test_missing_reset_initial_not_flagged(self) -> None:
        """Initial blocks don't need reset — not flagged."""
        source = "module top; initial begin count <= 0; end endmodule"
        smells = self._smells(source)
        reset = [s for s in smells if s.kind == SmellKind.MISSING_RESET]
        assert len(reset) == 0

    # ── S8 edge cases ──

    def test_unsized_literal_in_combinational(self) -> None:
        """Unsized literal in combinational block is also flagged."""
        source = "module top; always @* begin result = 0; end endmodule"
        smells = self._smells(source)
        unsized = [s for s in smells if s.kind == SmellKind.UNSIZED_LITERAL]
        assert len(unsized) >= 1

    def test_unsized_literal_negative(self) -> None:
        """Negative unsized literal is flagged."""
        source = "module top; always @(posedge clk) begin count <= -1; end endmodule"
        smells = self._smells(source)
        unsized = [s for s in smells if s.kind == SmellKind.UNSIZED_LITERAL]
        assert len(unsized) >= 1

    def test_zero_is_unsized(self) -> None:
        """Bare 0 is unsized."""
        source = "module top; always @(posedge clk) begin count <= 0; end endmodule"
        smells = self._smells(source)
        unsized = [s for s in smells if s.kind == SmellKind.UNSIZED_LITERAL]
        assert len(unsized) >= 1

    # ── S9 edge cases ──

    def test_delay_in_combinational_not_flagged(self) -> None:
        """Delay in combinational block is not flagged by S9."""
        source = "\n".join([
            "module top;",
            "always @* begin",
            "#1 result = data;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        delay = [s for s in smells if s.kind == SmellKind.DELAY_IN_SYNTHESIZABLE]
        assert len(delay) == 0

    # ── S11 edge cases ──

    def test_multiple_empty_case_branches(self) -> None:
        """Multiple empty branches each get their own smell."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "case (state)",
            "2'b00:",
            "2'b01:",
            "2'b10: x <= 1;",
            "default: x <= 0;",
            "endcase",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        empty = [s for s in smells if s.kind == SmellKind.EMPTY_CASE_BRANCH]
        assert len(empty) == 2

    # ── S12 edge cases ──

    def test_deep_nesting_in_case(self) -> None:
        """Deep nesting inside case branches is detected."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "case (s)",
            "0: begin",
            "  if (a) begin",
            "    if (b) begin",
            "      if (c) begin",
            "        if (d) x <= 1;",
            "      end",
            "    end",
            "  end",
            "end",
            "end",
            "default: x <= 0;",
            "endcase",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        deep = [s for s in smells if s.kind == SmellKind.DEEP_NESTING]
        assert len(deep) >= 1

    def test_exactly_depth_3_not_flagged(self) -> None:
        """Nesting at exactly depth 3 (threshold) is not flagged."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "if (a) begin",
            "  if (b) begin",
            "    if (c) x <= 1;",
            "  end",
            "end",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        deep = [s for s in smells if s.kind == SmellKind.DEEP_NESTING]
        assert len(deep) == 0

    # ── S14 edge cases ──

    def test_multi_driver_three_always_blocks(self) -> None:
        """Signal driven by 3 always blocks is still flagged once."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin x <= 1; end",
            "always @(posedge rst) begin x <= 0; end",
            "always @(posedge en) begin x <= 2; end",
            "endmodule",
        ])
        _, module_smells = self._extract(source)
        multi = [s for s in module_smells if s.kind == SmellKind.MULTI_DRIVER_SIGNAL]
        assert len(multi) == 1
        assert multi[0].severity == SmellSeverity.ERROR

    def test_multi_driver_initial_excluded(self) -> None:
        """Only initial blocks — no multi-driver at all."""
        source = "\n".join([
            "module top;",
            "initial begin x <= 0; end",
            "initial begin x <= 1; end",
            "endmodule",
        ])
        _, module_smells = self._extract(source)
        multi = [s for s in module_smells if s.kind == SmellKind.MULTI_DRIVER_SIGNAL]
        assert len(multi) == 0

    # ── S15 edge cases ──

    def test_incomplete_sensitivity_multiple_missing(self) -> None:
        """Multiple missing signals are all reported."""
        source = "\n".join([
            "module top;",
            "always @(a) begin",
            "result = a + b + c;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        sens = [s for s in smells if s.kind == SmellKind.INCOMPLETE_SENSITIVITY]
        assert len(sens) >= 1
        assert "b" in sens[0].message
        assert "c" in sens[0].message

    def test_edge_triggered_not_flagged_s15(self) -> None:
        """Edge-triggered blocks are not checked for incomplete sensitivity."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "result <= a + b;",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        sens = [s for s in smells if s.kind == SmellKind.INCOMPLETE_SENSITIVITY]
        assert len(sens) == 0

    # ── S16 edge cases ──

    def test_no_duplicate_unique_labels(self) -> None:
        """Unique case labels produce no duplicate smell."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "case (state)",
            "2'b00: x <= 0;",
            "2'b01: x <= 1;",
            "2'b10: x <= 2;",
            "default: x <= 3;",
            "endcase",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        dup = [s for s in smells if s.kind == SmellKind.DUPLICATE_CASE_LABEL]
        assert len(dup) == 0

    def test_duplicate_count_in_message(self) -> None:
        """Duplicate label count is reported in the message."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "case (state)",
            "2'b00: x <= 0;",
            "2'b00: x <= 1;",
            "2'b00: x <= 2;",
            "default: x <= 3;",
            "endcase",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        dup = [s for s in smells if s.kind == SmellKind.DUPLICATE_CASE_LABEL]
        assert len(dup) >= 1
        assert "3 times" in dup[0].message

    # ── S17 edge cases ──

    def test_forever_with_disable_inside_if(self) -> None:
        """Disable nested inside if within forever is found."""
        source = "\n".join([
            "module top;",
            "initial begin",
            "forever begin",
            "if (done)",
            "  disable gen;",
            "clk <= ~clk;",
            "end",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        forever = [s for s in smells if s.kind == SmellKind.FOREVER_WITHOUT_DISABLE]
        assert len(forever) == 0

    def test_forever_in_sequential_flagged(self) -> None:
        """Forever without disable in sequential block is flagged."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "forever begin",
            "x <= ~x;",
            "end",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        forever = [s for s in smells if s.kind == SmellKind.FOREVER_WITHOUT_DISABLE]
        assert len(forever) >= 1


class TestSmellMultiDetectorInteraction:
    """Tests for multiple smells triggering on the same code."""

    def _extract(self, source: str):
        from vodor.application.smell_detectors import detect_module_smells, detect_smells
        su = SourceUnit(identifier=SourceUnitId("t.v"), location="t.v", content=source)
        diagram = AntlrVerilogControlFlowExtractor().extract(su)
        per_func = []
        for f in diagram.functions:
            per_func.extend(detect_smells(f))
        module = detect_module_smells(diagram)
        return per_func, module

    def _smells(self, source: str) -> list:
        per_func, _ = self._extract(source)
        return per_func

    def test_blocking_in_seq_plus_unsized_literal(self) -> None:
        """Blocking assignment with unsized literal triggers both S1 and S8."""
        source = "module top; always @(posedge clk) begin count = 0; end endmodule"
        smells = self._smells(source)
        blocking = [s for s in smells if s.kind == SmellKind.BLOCKING_IN_SEQUENTIAL]
        unsized = [s for s in smells if s.kind == SmellKind.UNSIZED_LITERAL]
        assert len(blocking) >= 1
        assert len(unsized) >= 1

    def test_case_no_default_plus_casex(self) -> None:
        """casex without default triggers both S4 and S5."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "casex (data)",
            "8'b1xxx_xxxx: result <= 1;",
            "endcase",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        missing = [s for s in smells if s.kind == SmellKind.CASE_MISSING_DEFAULT]
        casex = [s for s in smells if s.kind == SmellKind.CASEX_USAGE]
        assert len(missing) >= 1
        assert len(casex) >= 1

    def test_nonblocking_in_comb_plus_unsized_literal(self) -> None:
        """Nonblocking with unsized literal in combinational triggers S2 and S8."""
        source = "module top; always @* begin result <= 0; end endmodule"
        smells = self._smells(source)
        nb = [s for s in smells if s.kind == SmellKind.NONBLOCKING_IN_COMBINATIONAL]
        unsized = [s for s in smells if s.kind == SmellKind.UNSIZED_LITERAL]
        assert len(nb) >= 1
        assert len(unsized) >= 1

    def test_seq_block_multiple_smells(self) -> None:
        """Sequential block can trigger S1, S7, S8 simultaneously."""
        source = "module top; always @(posedge clk) begin count = 0; end endmodule"
        smells = self._smells(source)
        kinds = {s.kind for s in smells}
        assert SmellKind.BLOCKING_IN_SEQUENTIAL in kinds
        assert SmellKind.MISSING_RESET in kinds
        assert SmellKind.UNSIZED_LITERAL in kinds

    def test_empty_module_minimal_smells(self) -> None:
        """Module with empty always block only gets missing reset (INFO)."""
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin",
            "end",
            "endmodule",
        ])
        smells = self._smells(source)
        # Only missing reset — no assignments to trigger other smells
        assert all(s.kind == SmellKind.MISSING_RESET for s in smells)
        assert len(smells) == 1

    def test_smell_severity_levels(self) -> None:
        """Verify correct severity levels for each kind."""
        from vodor.application.smell_detectors import detect_module_smells
        source = "\n".join([
            "module top;",
            "always @(posedge clk) begin count = 0; end",
            "always @(posedge rst) begin count = 1; end",
            "endmodule",
        ])
        per_func, module = self._extract(source)
        all_smells = per_func + module

        error_kinds = {s.kind for s in all_smells if s.severity == SmellSeverity.ERROR}
        info_kinds = {s.kind for s in all_smells if s.severity == SmellSeverity.INFO}

        assert SmellKind.BLOCKING_IN_SEQUENTIAL in error_kinds
        assert SmellKind.MULTI_DRIVER_SIGNAL in error_kinds
        assert SmellKind.MISSING_RESET in info_kinds
        assert SmellKind.UNSIZED_LITERAL in info_kinds


class TestSmellLocationFields:
    """Verify that smell location fields are populated correctly."""

    def _smells(self, source: str) -> list:
        from vodor.application.smell_detectors import detect_smells
        su = SourceUnit(identifier=SourceUnitId("t.v"), location="t.v", content=source)
        diagram = AntlrVerilogControlFlowExtractor().extract(su)
        smells = []
        for f in diagram.functions:
            smells.extend(detect_smells(f))
        return smells

    def test_location_contains_block_name(self) -> None:
        source = "module top; always @(posedge clk) begin count = 0; end endmodule"
        smells = self._smells(source)
        for s in smells:
            assert s.location.block_name == "always_1"

    def test_location_step_label_has_content(self) -> None:
        source = "module top; always @(posedge clk) begin count = count + 1; end endmodule"
        smells = self._smells(source)
        blocking = [s for s in smells if s.kind == SmellKind.BLOCKING_IN_SEQUENTIAL]
        assert len(blocking) >= 1
        assert "count" in blocking[0].location.step_label

    def test_location_message_readable(self) -> None:
        source = "module top; always @(posedge clk) begin count = count + 1; end endmodule"
        smells = self._smells(source)
        blocking = [s for s in smells if s.kind == SmellKind.BLOCKING_IN_SEQUENTIAL]
        assert len(blocking) >= 1
        assert len(blocking[0].message) > 10
        assert "Blocking" in blocking[0].message


class TestSplitCaseLabel:
    """Tests for the _split_case_label helper in the extractor."""

    def test_simple_label(self) -> None:
        from vodor.infrastructure.antlr.control_flow_extractor import _split_case_label
        label, sep, after = _split_case_label("2'b00: x <= 0;")
        assert label == "2'b00"
        assert sep == ":"
        assert "x <= 0" in after

    def test_default_label(self) -> None:
        from vodor.infrastructure.antlr.control_flow_extractor import _split_case_label
        label, sep, after = _split_case_label("default: out = 0;")
        assert label == "default"

    def test_bus_index_label(self) -> None:
        from vodor.infrastructure.antlr.control_flow_extractor import _split_case_label
        label, sep, after = _split_case_label("data[31:0]: result = 1;")
        assert label == "data[31:0]"
        assert "result = 1" in after

    def test_nested_bus_index(self) -> None:
        from vodor.infrastructure.antlr.control_flow_extractor import _split_case_label
        label, sep, after = _split_case_label("mem[idx+1][7:0]: out = 1;")
        assert label == "mem[idx+1][7:0]"
        assert "out = 1" in after

    def test_no_colon(self) -> None:
        from vodor.infrastructure.antlr.control_flow_extractor import _split_case_label
        label, sep, after = _split_case_label("something")
        assert label == "something"
        assert sep == ""
        assert after == ""
