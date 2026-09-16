from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

Split = Literal["dev", "regression", "public_test", "private_holdout"]

class DatasetManifest(StrictModel):
    name: str; version: str; created_at: str; description: str
    suites: list[str]; splits: list[Split]

class EvalCase(StrictModel):
    id: str
    suite: Literal["teaching", "planning", "assessment", "workflow", "recommendation"]
    split: Split
    scenario: str
    input: dict[str, Any]
    injected_failure: str | None = None
    expected_behavior: list[str] = Field(min_length=1)
    forbidden_behavior: list[str] = Field(default_factory=list)
    scoring_dimensions: list[str] = Field(min_length=1)
    tags: list[str] = Field(min_length=1)
    required: bool = True
    coverage_status: Literal["active", "integration_pending"] = "active"
    repetitions: int = Field(default=1, ge=1, le=10)
    expected_logical_operations: list[str] = Field(default_factory=list)

class PlanTaskOutput(StrictModel):
    id: str; title: str = Field(min_length=2); description: str = Field(min_length=2)
    estimated_minutes: int = Field(gt=0); deliverable: str = Field(min_length=2)
    acceptance_criteria: list[str] = Field(min_length=2); scheduled_date: str
    week_number: int = Field(ge=1, le=4); position: int = Field(ge=1)
    status: str; plan_version_id: str; created_at: str

class PlanningOutput(StrictModel):
    outcome: Literal["SUCCEEDED", "REJECTED"]
    daily_hours: float = Field(ge=.5, le=12); study_weekdays: list[int] = Field(min_length=1)
    deadline: str; tasks: list[PlanTaskOutput]; planning_risks: list[dict[str, Any]]
    adjustment_suggestions: list[str]; error_code: str | None = None

class TeachingOutput(StrictModel):
    section_count: int = Field(ge=2); specific_answer: str = Field(min_length=30)
    ambiguous_answer: str = Field(min_length=30); previous_teacher_message: str = Field(min_length=20)
    reteach_strategies: list[str] = Field(min_length=2); weak_points: list[str]
    quiz_versions: list[int]; mastery_before: int = Field(ge=0, le=100)
    mastery_after: int = Field(ge=0, le=100); final_status: str
    attempt_count: int = Field(ge=2); mastery_record_count: int = Field(ge=1)

class CriterionOutput(StrictModel):
    criterion: str; passed: bool; reason: str

class AssessmentOutput(StrictModel):
    result: Literal["PASSED", "NEEDS_REVISION"]; score: int = Field(ge=0, le=100)
    feedback: str = Field(min_length=1); criterion_results: list[CriterionOutput] = Field(min_length=1)

class TraceEvent(StrictModel):
    sequence: int = Field(ge=1); event: str = Field(min_length=2)
    job_status: str | None = None; side_effect_count: int = Field(ge=0)

class WorkflowOutput(StrictModel):
    events: list[TraceEvent] = Field(min_length=2); collect_calls: int = Field(ge=0)
    final_status: str; side_effect_count: int = Field(ge=0); duplicate_side_effect_count: int = Field(ge=0)

class CheckpointEvidence(StrictModel):
    checkpoint_exists: bool
    snapshot_next: list[str]
    history: list[dict[str, Any]]
    limitation: str

class WorkflowEvidence(StrictModel):
    before_failure: CheckpointEvidence
    after_failure: CheckpointEvidence
    after_recovery: CheckpointEvidence
    after_duplicate_resume: CheckpointEvidence
    job_statuses: list[str] = Field(min_length=4)
    collect_calls: int = Field(ge=0)
    side_effect_counts: list[int] = Field(min_length=3)

class ScenarioExecution(StrictModel):
    raw_production_output: Any
    raw_schema_validation: dict[str, Any]
    normalized_observation: dict[str, Any]
    normalization_errors: list[str]

class RecommendationItem(StrictModel):
    external_id: str; title: str; summary: str; topics: list[str]
    quality_score: int; trend_score: int; score: int = Field(ge=0, le=100)
    breakdown: dict[str, int]; reason: str = Field(min_length=1)

class RecommendationOutput(StrictModel):
    items: list[RecommendationItem] = Field(min_length=1)

SUITE_OUTPUT_SCHEMAS = {"planning": PlanningOutput, "teaching": TeachingOutput,
    "assessment": AssessmentOutput, "workflow": WorkflowOutput, "recommendation": RecommendationOutput}

RAW_OUTPUT_SCHEMAS = {**SUITE_OUTPUT_SCHEMAS, "workflow": WorkflowEvidence}

class JudgeDimension(StrictModel):
    name: str; score: float = Field(ge=0, le=1); reason: str = Field(min_length=1)

class JudgeOutput(StrictModel):
    dimensions: list[JudgeDimension] = Field(min_length=1); passed: bool; summary: str = Field(min_length=1)
    def validate_dimensions(self, declared: list[str]) -> None:
        names = [item.name for item in self.dimensions]
        if len(names) != len(set(names)): raise ValueError("judge returned duplicate dimensions")
        if set(names) != set(declared):
            raise ValueError(f"judge dimensions mismatch: declared={declared}, actual={names}")

class ExperimentMetadata(StrictModel):
    experiment_id: str; generated_at: str; git_commit: str; branch: str; dirty: bool
    dataset_version: str; dataset_hash: str; split: str
    mode: Literal["offline-fallback", "real-model"]; provider: str; model: str
    judge_model: str | None; same_model_judge: bool; prompt_versions: dict[str, str]
    temperature: float; repetitions: int
