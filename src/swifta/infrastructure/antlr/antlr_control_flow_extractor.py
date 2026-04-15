"""Basic ANTLR-based control flow extraction for Verilog."""

from __future__ import annotations

from antlr4 import CommonTokenStream, InputStream, ParseTreeWalker
from antlr4.tree.Tree import ParseTreeListener

from swifta.domain.control_flow import (
    ActionFlowStep,
    ControlFlowDiagram,
    FunctionControlFlow,
    StructDeclarationFlowStep,
    StructFieldAccessFlowStep,
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
        """Debug and dispatch: called for every rule."""
        rule_index = ctx.getRuleIndex()
        rule_name = self._get_rule_name(ctx)
        print(f"DEBUG: Entered {rule_name}: {ctx.getText()[:30]}...")

        # Dispatch to specific handlers based on rule index
        if rule_index == VerilogParser.RULE_always_construct:
            self._handle_always_enter(ctx)
        elif rule_index == VerilogParser.RULE_nonblocking_assignment:
            self._handle_nonblocking_enter(ctx)
        elif rule_index == VerilogParser.RULE_blocking_assignment:
            self._handle_blocking_enter(ctx)
        elif rule_index == VerilogParser.RULE_loop_statement:
            self._handle_loop_statement_enter(ctx)
        # Note: struct handling is primarily a Swift/software concept
        # For Verilog, we'd look for parameter definitions or similar constructs

    def exitEveryRule(self, ctx):
        """Dispatch on exit: called for every rule."""
        rule_index = ctx.getRuleIndex()
        rule_name = self._get_rule_name(ctx)
        print(f"DEBUG: Exiting {rule_name}")

        if rule_index == VerilogParser.RULE_always_construct:
            self._handle_always_exit(ctx)

    def _get_rule_name(self, ctx):
        """Get rule name from context."""
        return VerilogParser.ruleNames[ctx.getRuleIndex()] if ctx.getRuleIndex() >= 0 else "unknown"

    # --- Verilog-specific handlers ---

    def _handle_loop_statement_enter(self, ctx):
        """Handle loop statements (forever, repeat)."""
        loop_text = ctx.getText()
        # Simple handling: treat as an action step
        # A full implementation would distinguish forever vs repeat
        self.current_function_name = "loop_block"
        self.current_function_signature = "loop"
        self.current_statements = []
        self.current_statements.append(ActionFlowStep(loop_text))
        print(f"DEBUG: Started collecting loop: {loop_text}")

    def _handle_always_enter(self, ctx):
        """Handle always blocks."""
        always_type = "always"
        function_name = f"{always_type}_block"
        function_signature = f"{always_type} block"

        self.current_function_name = function_name
        self.current_function_signature = function_signature
        self.current_statements = []
        print(f"DEBUG: Started collecting for function: {function_name}")

    def _handle_always_exit(self, ctx):
        """Finalize always block."""
        if self.current_function_name:
            self._function_data.append((
                self.current_function_name,
                self.current_function_signature,
                self.current_statements.copy(),
            ))
            print(
                f"DEBUG: Added function data: {self.current_function_name} with {len(self.current_statements)} steps"
            )
            self.current_function_name = None
            self.current_function_signature = None
            self.current_statements = []

    def _handle_nonblocking_enter(self, ctx):
        """Handle nonblocking assignments."""
        if not self.current_function_name:
            return
        assignment_text = ctx.getText()
        print(f"DEBUG: Adding nonblocking assignment: {assignment_text}")
        self.current_statements.append(ActionFlowStep(assignment_text))

    def _handle_blocking_enter(self, ctx):
        """Handle blocking assignments."""
        if not self.current_function_name:
            return
        assignment_text = ctx.getText()
        print(f"DEBUG: Adding blocking assignment: {assignment_text}")
        self.current_statements.append(ActionFlowStep(assignment_text))

    # --- Struct handling (placeholder for Swift-side usage) ---

    def _handle_struct_declaration_enter(self, ctx):
        """Handle struct declaration (primarily for Swift parsing)."""
        print("DEBUG: Struct declaration encountered (Swift focus)")
        # In a full implementation, this would extract struct name, fields, types

    def _handle_struct_member_enter(self, ctx):
        """Handle struct member definition (primarily for Swift parsing)."""
        print("DEBUG: Struct member encountered (Swift focus)")