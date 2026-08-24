"""
MAROON-ETL CLI Entry Point.

Usage:
    python -m maroon_etl run          # Run full pipeline
    python -m maroon_etl extract      # Run extract only
    python -m maroon_etl transform    # Run transform only
    python -m maroon_etl load         # Run load only
    python -m maroon_etl status       # Show pipeline status
    python -m maroon_etl --help       # Show help
"""

from __future__ import annotations

import argparse
import json
import sys

from .config.settings import ETLConfig
from .pipeline import Pipeline


def main():
    """CLI entry point for MAROON-ETL."""
    parser = argparse.ArgumentParser(
        prog="maroon_etl",
        description="MAROON-ETL: Stateless batch ETL pipeline for the Maroon data lake.",
        epilog="Budget target: UNDER $0.10/month. S3 + Athena only.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Pipeline commands")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run full pipeline (extract -> transform -> load)")
    run_parser.add_argument("--data-dir", default="data", help="Base data directory")

    # Extract command
    extract_parser = subparsers.add_parser("extract", help="Run extract phase only")
    extract_parser.add_argument("--output-dir", default="data/raw", help="Output directory for raw files")

    # Transform command
    transform_parser = subparsers.add_parser("transform", help="Run transform phase only")
    transform_parser.add_argument("--raw-dir", default="data/raw", help="Input raw directory")
    transform_parser.add_argument("--staged-dir", default="data/staged", help="Output staged directory")

    # Load command
    load_parser = subparsers.add_parser("load", help="Run load phase only")
    load_parser.add_argument("--staged-dir", default="data/staged", help="Input staged directory")
    load_parser.add_argument("--curated-dir", default="data/curated", help="Output curated directory")

    # Status command
    subparsers.add_parser("status", help="Show pipeline status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Initialize pipeline
    config = ETLConfig.from_env()
    pipeline = Pipeline(config)

    if args.command == "run":
        result = pipeline.run(data_dir=args.data_dir)
        print(json.dumps(result, indent=2, default=str))

    elif args.command == "extract":
        result = pipeline.run_extract(output_dir=args.output_dir)
        print(json.dumps(result, indent=2, default=str))

    elif args.command == "transform":
        result = pipeline.run_transform(raw_dir=args.raw_dir, staged_dir=args.staged_dir)
        print(json.dumps(result, indent=2, default=str))

    elif args.command == "load":
        result = pipeline.run_load(staged_dir=args.staged_dir, curated_dir=args.curated_dir)
        print(json.dumps(result, indent=2, default=str))

    elif args.command == "status":
        status = pipeline.status()
        print(json.dumps(status, indent=2, default=str))


if __name__ == "__main__":
    main()
