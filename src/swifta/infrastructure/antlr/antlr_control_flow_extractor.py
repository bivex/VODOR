"""Basic ANTLR-based control flow extraction for Verilog."""

from __future__ import annotations

from antlr4 import CommonTokenStream, InputStream, ParseTreeWalker
from antlr4.tree.Tree import ParseTreeListener

from swifta.domain.control_flow import (
    ActionFlowStep,
    ControlFlowDiagram,
    FunctionControlFlow,
)
from swifta.domain.model import SourceUnit
from swifta.domain.ports import VerilogControlFlowExtractor
from swifta.infrastructure.antlr.generated.verilog.VerilogLexer import VerilogLexer
from swifta.infrastructure.antlr.generated.verilog.VerilogParser import VerilogParser


class AntlrVerilogControlFlowExtractor(VerilogControlFlowExtractor):
    """Basic ANTLR-based control flow extractor."""

    def extract(self, source_unit: SourceUnit) -> ControlFlowDiagram:
        print("DEBUG: Starting ANTLR extract")
        # Parse with ANTLR
        lexer = VerilogLexer(InputStream(source_unit.content))
        parser = VerilogParser(CommonTokenStream(lexer))
        tree = parser.source_text()
        print("DEBUG: Parsed tree successfully")

        # Walk the tree with our listener
        listener = BasicVerilogCFGListener()
        walker = ParseTreeWalker()
        print("DEBUG: Starting tree walk")
        walker.walk(listener, tree)
        print("DEBUG: Tree walk completed")

        # Finalize any pending functions
        if listener.current_function_name:
            listener._function_data.append((
                listener.current_function_name,
                listener.current_function_signature,
                listener.current_statements.copy()
            ))
            print(f"DEBUG: Finalized pending function: {listener.current_function_name} with {len(listener.current_statements)} steps")

        print(f"DEBUG: Function data collected: {len(listener._function_data)}")
        functions = listener.functions
        print(f"DEBUG: Final functions: {len(functions)}")

        return ControlFlowDiagram(
            source_location=source_unit.location,
            functions=tuple(functions),
        )
            )
            print(
                f"DEBUG: Finalized pending function: {listener.current_function_name} with {len(listener.current_statements)} steps"
            )

        print(f"DEBUG: Function data collected: {len(listener._function_data)}")
        functions = listener.functions
        print(f"DEBUG: Final functions: {len(functions)}")

        return ControlFlowDiagram(
            source_location=source_unit.location,
            functions=tuple(functions),
        )


class BasicVerilogCFGListener(ParseTreeListener):
    """Basic listener that extracts always blocks and simple statements."""

    def __init__(self):
        self._function_data = []  # List of (name, signature, statements) tuples
        self.current_function_name = None
        self.current_function_signature = None
        self.current_statements = []

    @property
    def functions(self):
        """Convert collected data to FunctionControlFlow objects."""
        return [
            FunctionControlFlow(
                name=name, signature=signature, container=None, steps=tuple(statements)
            )
            for name, signature, statements in self._function_data
        ]

    def enterEveryRule(self, ctx):
        """Debug: called for every rule."""
        rule_name = self._get_rule_name(ctx)
        print(f"DEBUG: Entered {rule_name}: {ctx.getText()[:30]}...")

    def _get_rule_name(self, ctx):
        """Get rule name from context."""
        return VerilogParser.ruleNames[ctx.getRuleIndex()] if ctx.getRuleIndex() >= 0 else "unknown"

    def enterAlways_construct(self, ctx):
        """Handle always blocks."""
        print(f"DEBUG: Entered always_construct: {ctx.getText()[:50]}...")
        always_type = "always"  # Default
        function_name = f"{always_type}_block"
        function_signature = f"{always_type} block"

        self.current_function_name = function_name
        self.current_function_signature = function_signature
        self.current_statements = []
        print(f"DEBUG: Started collecting for function: {function_name}")

    def exitAlways_construct(self, ctx):
        """Finalize always block."""
        print(f"DEBUG: Exiting always_construct")
        if self.current_function_name:
            self._function_data.append(
                (
                    self.current_function_name,
                    self.current_function_signature,
                    self.current_statements.copy(),
                )
            )
            print(
                f"DEBUG: Added function data: {self.current_function_name} with {len(self.current_statements)} steps"
            )
        self.current_function_name = None
        self.current_function_signature = None
        self.current_statements = []

    def enterNonblocking_assignment(self, ctx):
        """Handle nonblocking assignments."""
        if not self.current_function:
            return
        assignment_text = ctx.getText()
        print(f"DEBUG: Adding nonblocking assignment: {assignment_text}")
        self.current_statements.append(ActionFlowStep(assignment_text))

    def enterBlocking_assignment(self, ctx):
        """Handle blocking assignments."""
        if not self.current_function:
            return
        assignment_text = ctx.getText()
        self.current_statements.append(ActionFlowStep(assignment_text))
