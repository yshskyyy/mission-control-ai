import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

VALID_STATUSES = {"CANDIDATE_REQUIRES_HUMAN_REVIEW", "APPROVED", "REJECTED", "STALE"}
REQUIRED_PROVENANCE = ("experiment_id", "source_git_commit", "dataset_version", "dataset_hash",
                       "generated_at", "suite_scores", "dimension_scores")


def approve(candidate_path: Path, output_path: Path, reviewer: str, approval_source: str) -> dict:
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    if candidate.get("approval_status") != "CANDIDATE_REQUIRES_HUMAN_REVIEW":
        raise ValueError("only a baseline candidate can be approved")
    if candidate.get("quality_claim") != "engineering_regression_only":
        raise ValueError("offline baseline quality_claim must be engineering_regression_only")
    missing=[name for name in REQUIRED_PROVENANCE if not candidate.get(name)]
    if missing:
        raise ValueError(f"candidate missing provenance: {missing}")
    approved = {**candidate, "approval_status": "APPROVED", "reviewer": reviewer.strip(),
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "approval_source": approval_source.strip()}
    if not approved["reviewer"] or not approved["approval_source"]:
        raise ValueError("reviewer and approval_source are required")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(approved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return approved


def write_candidate(candidate: dict, path: Path) -> None:
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("approval_status") == "APPROVED":
            raise ValueError("refusing to overwrite an approved baseline with a candidate")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(candidate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("approve")
    command.add_argument("--candidate", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--reviewer", required=True)
    command.add_argument("--approval-source", required=True)
    args = parser.parse_args()
    approve(args.candidate, args.output, args.reviewer, args.approval_source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
