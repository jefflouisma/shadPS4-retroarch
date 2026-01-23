from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

from .models import TestDefinition
from .runner import TestRunner
from .utils import setup_logging


mcp = FastMCP("retroarch-mcp")


def _load_test_file(path: str) -> Dict[str, Any]:
    test_path = Path(path).expanduser()
    if not test_path.exists():
        raise FileNotFoundError(f"Test definition not found: {test_path}")
    return json.loads(test_path.read_text(encoding="utf-8"))


def _run_test_payload(payload: Dict[str, Any], env_path: Optional[str]) -> Dict[str, Any]:
    definition = TestDefinition.model_validate(payload)
    runner = TestRunner(env_path=env_path)
    result = runner.run(definition)
    return result.model_dump()


@mcp.tool()
def run_test_file(path: str, env_path: Optional[str] = None) -> Dict[str, Any]:
    """Run a RetroArch test definition from a JSON file path."""
    payload = _load_test_file(path)
    return _run_test_payload(payload, env_path)


@mcp.tool()
def run_test_payload(payload: Dict[str, Any], env_path: Optional[str] = None) -> Dict[str, Any]:
    """Run a RetroArch test definition provided as a JSON object."""
    return _run_test_payload(payload, env_path)


@mcp.tool()
def test_definition_schema() -> Dict[str, Any]:
    """Return the JSON schema for RetroArch test definitions."""
    return TestDefinition.model_json_schema()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RetroArch MCP test runner")
    parser.add_argument(
        "--run",
        dest="run_path",
        help="Path to a JSON test definition to run locally",
    )
    parser.add_argument(
        "--env",
        dest="env_path",
        help="Path to .env file with OPENROUTER_API_KEY",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Print the JSON schema for test definitions and exit",
    )
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Run MCP server over stdio (default when no other args)",
    )
    return parser.parse_args()


def main() -> None:
    setup_logging()
    logging.getLogger(__name__).info("Starting retroarch-mcp")

    args = _parse_args()
    if args.schema:
        print(json.dumps(TestDefinition.model_json_schema(), indent=2))
        return

    if args.run_path:
        payload = _load_test_file(args.run_path)
        result = _run_test_payload(payload, args.env_path)
        print(json.dumps(result, indent=2))
        return

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
