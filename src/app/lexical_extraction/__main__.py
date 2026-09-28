"""Thin CLI for lexical extraction publication (L13).

Usage (PowerShell)::

    poetry run python -m app.lexical_extraction `
      --config .\\examples\\lexical_extraction\\execution-config.example.yaml

Exit codes
----------
0  extraction completed and final manifest published
1  extraction partial and final manifest published
2  extraction failed (or pre-validation) with a truthful final manifest, or
   extraction failed without publication when identities cannot be claimed
3  publication failed or interrupted (no completed publication claim), or
   configuration / CLI usage error before a sealed published run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.lexical_extraction.configuration import ConfigurationError
from app.lexical_extraction.publication import (
    format_cli_summary,
    publish_lexical_run,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.lexical_extraction",
        description=(
            "Run bounded lexical extraction from an L02 YAML config and publish "
            "versioned per-component artifacts plus a final run manifest."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to the L02 execution YAML (reviewed HTML, snapshot, output, selection).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = args.config
    try:
        result, publication = publish_lexical_run(config_path)
    except ConfigurationError as exc:
        print(f"configuration_error={type(exc).__name__}", file=sys.stderr)
        print(f"message={exc}", file=sys.stderr)
        return 3
    except OSError as exc:
        print(f"cli_error={type(exc).__name__}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - CLI boundary maps unexpected failures
        print(f"cli_error={type(exc).__name__}", file=sys.stderr)
        return 3

    # Operator may see the configured output path; no source block text.
    print(format_cli_summary(result, publication))
    return publication.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
