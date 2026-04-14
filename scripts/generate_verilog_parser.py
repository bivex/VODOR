"""Generate Python parser artifacts from the Verilog grammar."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from urllib.request import urlretrieve


ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "build" / "tools"
GRAMMAR_DIR = ROOT / "resources" / "grammars" / "verilog"
OUTPUT_DIR = ROOT / "src" / "swifta" / "infrastructure" / "antlr" / "generated" / "verilog"
ANTLR_VERSION = "4.13.2"
ANTLR_JAR = TOOLS_DIR / f"antlr-{ANTLR_VERSION}-complete.jar"
ANTLR_JAR_URL = f"https://www.antlr.org/download/antlr-{ANTLR_VERSION}-complete.jar"
GRAMMAR_URLS = {
    "VerilogLexer.g4": "https://raw.githubusercontent.com/antlr/grammars-v4/master/verilog/verilog/VerilogLexer.g4",
    "VerilogParser.g4": "https://raw.githubusercontent.com/antlr/grammars-v4/master/verilog/verilog/VerilogParser.g4",
}


def main() -> None:
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    GRAMMAR_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    _ensure_grammar_exists()
    _ensure_antlr_jar_exists()
    _generate_parser()
    _ensure_package_files()


def _ensure_grammar_exists() -> None:
    for filename, url in GRAMMAR_URLS.items():
        target = GRAMMAR_DIR / filename
        if target.exists():
            continue
        print(f"Downloading {filename}...")
        urlretrieve(url, target)


def _ensure_antlr_jar_exists() -> None:
    if ANTLR_JAR.exists():
        return
    print(f"Downloading ANTLR {ANTLR_VERSION}...")
    urlretrieve(ANTLR_JAR_URL, ANTLR_JAR)


def _generate_parser() -> None:
    command = [
        "java",
        "-jar",
        str(ANTLR_JAR),
        "-Dlanguage=Python3",
        "-visitor",
        "-no-listener",
        "-o",
        str(OUTPUT_DIR),
        str(GRAMMAR_DIR / "VerilogLexer.g4"),
        str(GRAMMAR_DIR / "VerilogParser.g4"),
    ]
    subprocess.run(command, check=True, cwd=ROOT)


def _ensure_package_files() -> None:
    init_file = OUTPUT_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text('"""Generated Verilog ANTLR parser."""\n', encoding="utf-8")


if __name__ == "__main__":
    main()
