from __future__ import annotations

from dataclasses import dataclass

import pytest

from vodor.domain.errors import InputValidationError
from vodor.domain.control_flow import (
    ActionFlowStep,
    DelayFlowStep,
    EventWaitFlowStep,
    ForInFlowStep,
    ForkJoinFlowStep,
    ForeverFlowStep,
    DisableFlowStep,
    IfFlowStep,
    RepeatWhileFlowStep,
    SwitchFlowStep,
    WaitConditionFlowStep,
    WhileFlowStep,
)
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
