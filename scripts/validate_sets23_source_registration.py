"""Raw-free validator for the tracked IMS Set 2/3 source-registration evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.data.sets23_source_registration import SourcePackageRegistrationError, validate_evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate tracked IMS Set 2/3 source-registration evidence without raw archives.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, default=Path("configs/datasets/ims_sets23_source_packages_v1.json"))
    parser.add_argument("--artifacts", type=Path, default=Path("data/manifests/ims_sets23_source_packages/v1"))
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    config = args.config if args.config.is_absolute() else root / args.config
    artifacts = args.artifacts if args.artifacts.is_absolute() else root / args.artifacts
    try:
        result = validate_evidence(root, config, artifacts)
    except SourcePackageRegistrationError as error:
        print(f"source package evidence validation failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
