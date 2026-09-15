import argparse, hashlib, json, statistics, subprocess, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from openai import OpenAI
from jsonschema import Draft202012Validator
from app import ai, db, repository
from app.config import settings as application_settings
from evals.graders import grade, validate_dimensions
from evals.judge import JUDGE_PROMPT_VERSION, judge
from evals.metrics import estimated_cost, percentile
from evals.scenarios import RUNNERS
from evals.schemas import DatasetManifest, EvalCase, ExperimentMetadata
from evals.baseline import write_candidate

ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET_ROOT = ROOT / "datasets" / "v2"
SUITES = ("planning", "teaching", "assessment", "workflow", "recommendation")
MODEL_SUITES = {"planning", "teaching", "assessment"}

def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT.parent, text=True, capture_output=True, check=False)
    return result.stdout.strip() or "unknown"

def _git_success(*args: str) -> bool:
    return subprocess.run(["git", *args], cwd=ROOT.parent, capture_output=True, check=False).returncode == 0

def load_manifest(dataset_root: Path = DEFAULT_DATASET_ROOT) -> DatasetManifest:
    return DatasetManifest.model_validate_json((dataset_root/"manifest.json").read_text(encoding="utf-8"))

def load_cases(suite: str, split: str, dataset_root: Path = DEFAULT_DATASET_ROOT) -> list[EvalCase]:
    return [case for line in (dataset_root/f"{suite}.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip() and (case := EvalCase.model_validate_json(line)).split == split]

def load_jsonl(suite: str) -> list[dict]:
    path = ROOT/"datasets"/f"{suite}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

def dataset_hash(dataset_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(dataset_root.glob("*")):
        if path.is_file(): digest.update(path.name.encode()); digest.update(path.read_bytes())
    return digest.hexdigest()

def validate_report_schema(report: dict, schema_path: Path = ROOT/"report.schema.json") -> None:
    schema=json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors=sorted(Draft202012Validator(schema).iter_errors(report), key=lambda item:list(item.path))
    if errors:
        first=errors[0]; location="/".join(str(item) for item in first.absolute_path) or "$"
        raise ValueError(f"report schema validation failed at {location}: {first.message}")

def validate_dataset(dataset_root: Path) -> list[EvalCase]:
    manifest = load_manifest(dataset_root); all_cases = []
    for suite in manifest.suites:
        path = dataset_root/f"{suite}.jsonl"
        if not path.is_file(): raise ValueError(f"missing dataset file: {path}")
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            case = EvalCase.model_validate_json(line)
            if case.suite != suite: raise ValueError(f"suite mismatch for {case.id}")
            if case.split not in manifest.splits: raise ValueError(f"undeclared split for {case.id}: {case.split}")
            if (case.coverage_status == "active" and case.suite in MODEL_SUITES
                    and not case.expected_logical_operations):
                raise ValueError(f"missing expected logical operations for {case.id}")
            validate_dimensions(case); all_cases.append(case)
    ids = [case.id for case in all_cases]
    if len(ids) != len(set(ids)): raise ValueError("dataset case IDs must be globally unique")
    for split in manifest.splits:
        if not any(c.split == split for c in all_cases): raise ValueError(f"empty dataset split: {split}")
    return all_cases

def quality_claim(live: bool, runtimes: list[dict], judge_failures: int) -> str:
    authentic=bool(runtimes) and all(r["provider"]=="openai" and r["final_status"]=="SUCCEEDED"
        and r["model_call_succeeded"] and not r["fallback_used"] and not r["schema_parsing_failure"] for r in runtimes)
    if not live: return "engineering_regression_only"
    return "real_model_quality_sample" if authentic and judge_failures==0 else "invalid_live_run"

def _runtime(runs: list[dict], requires_model: bool, logical_rows: list[dict] | None = None,
             expected_operations: list[str] | None = None) -> dict:
    if not requires_model:
        return {"provider":"not_applicable", "model":"not_applicable", "final_status":"NOT_APPLICABLE",
                "fallback_used":False, "model_call_succeeded":False, "schema_parsing_failure":False,
                "input_tokens":0,"output_tokens":0,"estimated_cost":0.0,"retry_count":0,"logical_requests":0,
                "operations":[],"missing_operations":[],"unexpected_operations":[]}
    logical: dict[str,list[dict]]={}
    for run in runs:
        key=run.get("logical_request_id") or f"unattributed:{run['id']}"
        logical.setdefault(key,[]).append(run)
    final_runs=[items[-1] for items in logical.values()]
    outcomes=[row.get("final_outcome") for row in (logical_rows or [])]
    statuses = [r["status"] for r in final_runs]
    fallback = "FALLBACK_SUCCESS" in outcomes or "FALLBACK" in statuses
    failed = "TOTAL_FAILURE" in outcomes or "FAILED" in statuses
    providers = {row.get("final_provider") for row in (logical_rows or []) if row.get("final_provider")} or {r.get("provider") for r in final_runs if r.get("provider")}
    successful_models = {r["model"] for r in final_runs if r["status"] == "SUCCEEDED"}
    models = {r["model"] for r in final_runs}
    operation_rows=[]
    for row in logical_rows or []:
        related=logical.get(row["logical_request_id"],[])
        operation_rows.append({"operation":row["logical_request_id"],
            "logical_request_id":row["logical_request_id"],"provider":row.get("final_provider") or "unknown",
            "model":row.get("final_model") or "none","attempt_count":int(row.get("attempt_count") or 0),
            "final_outcome":row.get("final_outcome"),"fallback":row.get("final_outcome")=="FALLBACK_SUCCESS",
            "schema_failure":bool(row.get("schema_failure"))})
    expected=set(expected_operations or []); actual_ops={item["operation"] for item in operation_rows}
    return {"provider": next(iter(providers)) if len(providers)==1 else ("mixed" if providers else "unknown"),
            "model": next(iter(models)) if len(models)==1 else ("mixed" if models else "none"),
            "final_status":"FALLBACK" if fallback else ("FAILED" if failed else "SUCCEEDED"),
            "fallback_used":fallback, "model_call_succeeded":bool(successful_models) and not failed,
            "schema_parsing_failure":any(bool(row.get("schema_failure")) for row in (logical_rows or [])) or any(r["status"] in ("FAILED","SCHEMA_FAILURE") and any(marker in (r.get("error") or "").lower()
                for marker in ("validation failed","json","expecting value","decode")) for r in runs),
            "input_tokens":sum(int(r.get("input_tokens") or 0) for r in runs),
            "output_tokens":sum(int(r.get("output_tokens") or 0) for r in runs),
            "estimated_cost":round(sum(float(r.get("estimated_cost") or 0) for r in runs),8),
            "retry_count":sum(int(r.get("retry_count",0)) for r in runs),
            "logical_requests":len(logical_rows or []),"operations":operation_rows,
            "missing_operations":sorted(expected-actual_ops),"unexpected_operations":sorted(actual_ops-expected) if expected else []}

def execute_suite(suite: str, split: str, repetitions: int, live: bool, judge_model: str,
                  database_root: Path, dataset_root: Path) -> dict:
    cases = load_cases(suite, split, dataset_root)
    active = [case for case in cases if case.coverage_status == "active"]
    pending = [{"id":c.id, "reason":"integration_pending", "tags":c.tags} for c in cases if c.coverage_status != "active"]
    if not active: raise ValueError(f"suite {suite} has no active cases for split {split}")
    if not any(case.required for case in active): raise ValueError(f"suite {suite} has no required case for split {split}")
    results=[]; suite_started=time.monotonic()
    client = OpenAI(api_key=application_settings.openai_api_key, timeout=60) if live else None
    for case in active:
        case_runs=[]
        for run_index in range(max(repetitions, case.repetitions)):
            correlation_id=f"eval:{suite}:{case.id}:{run_index}:{uuid4()}"
            db.settings.database_path = database_root/f"{suite}-{case.id}-{run_index}.db"; db.init_db()
            started=time.monotonic(); judge_failure=None; judged_meta=None
            try:
                with ai.ai_run_context(correlation_id):
                    output=RUNNERS[suite](case)
                checks,evaluated=grade(case, output)
                ai_runs=repository.list_ai_runs_for_correlation(correlation_id)
                logical_rows=repository.list_ai_logical_requests_for_correlation(correlation_id)
                actual=_runtime(ai_runs, suite in MODEL_SUITES,logical_rows,case.expected_logical_operations)
                authenticity_ok=True
                if live and suite in MODEL_SUITES:
                    authenticity_ok=(actual["provider"]=="openai" and actual["final_status"]=="SUCCEEDED"
                        and actual["model_call_succeeded"] and not actual["fallback_used"]
                        and not actual["schema_parsing_failure"] and not actual["missing_operations"]
                        and not actual["unexpected_operations"])
                    checks.append({"name":"live_authenticity", "passed":authenticity_ok,
                        "score":float(authenticity_ok), "detail":str(actual), "grader_type":"rule"})
                    if authenticity_ok:
                        try:
                            judged=judge(client, judge_model, case, json.dumps(output, ensure_ascii=False), 0.0)
                            for item in judged.output.dimensions:
                                checks.append({"name":item.name, "passed":item.score>=.7, "score":item.score,
                                    "detail":item.reason, "grader_type":"llm_judge"})
                            checks.append({"name":"judge_passed", "passed":judged.output.passed,
                                "score":float(judged.output.passed), "detail":judged.output.summary, "grader_type":"llm_judge"})
                            judged_meta={"model":judged.model,"prompt_version":JUDGE_PROMPT_VERSION,
                                "latency_ms":judged.latency_ms,"input_tokens":judged.input_tokens,
                                "output_tokens":judged.output_tokens}
                        except Exception as exc:
                            judge_failure=f"{type(exc).__name__}: {str(exc)[:400]}"
                            checks.append({"name":"judge_failure", "passed":False,"score":0.0,
                                           "detail":judge_failure,"grader_type":"llm_judge"})
                error=None
            except Exception as exc:
                output={"raw_production_output":{},"raw_schema_validation":{"passed":False,"detail":str(exc)[:500]},
                        "normalized_observation":{},"normalization_errors":[f"{type(exc).__name__}: {str(exc)[:400]}"]}
                evaluated=[]; actual=_runtime(repository.list_ai_runs_for_correlation(correlation_id), suite in MODEL_SUITES,
                    repository.list_ai_logical_requests_for_correlation(correlation_id),case.expected_logical_operations)
                checks=[{"name":"execution","passed":False,"score":0.0,"detail":str(exc)[:500],"grader_type":"rule"}]
                error=f"{type(exc).__name__}: {str(exc)[:400]}"
            missing=sorted(set(case.scoring_dimensions)-set(evaluated))
            if missing: checks.append({"name":"missing_dimensions","passed":False,"score":0.0,"detail":str(missing),"grader_type":"rule"})
            case_runs.append({"passed":all(c["passed"] for c in checks),"checks":checks,"error":error,
                "judge_failure":judge_failure,"judge":judged_meta,"actual_runtime":actual,
                "execution":output,
                "declared_dimensions":case.scoring_dimensions,"evaluated_dimensions":evaluated,
                "missing_dimensions":missing,"correlation_id":correlation_id,
                "latency_ms":round((time.monotonic()-started)*1000)})
        scores=[statistics.mean(c["score"] for c in r["checks"]) for r in case_runs]
        results.append({"id":case.id,"required":case.required,"passed":all(r["passed"] for r in case_runs),
            "score_mean":statistics.mean(scores),"score_variance":statistics.pvariance(scores),"runs":case_runs,"tags":case.tags})
    return {"suite":suite,"cases":len(results),"pending_cases":pending,"passed":sum(r["passed"] for r in results),
        "pass_rate":sum(r["passed"] for r in results)/len(results),"latency_ms":round((time.monotonic()-suite_started)*1000),"results":results}

def evaluate_gate(report: dict, baseline: dict) -> tuple[bool,list[str]]:
    failures=[]; total=sum(s["cases"] for s in report["suites"]); passed=sum(s["passed"] for s in report["suites"])
    report["overall_pass_rate"]=passed/total if total else 0.0; report["baseline_diff"]={}
    if not total: failures.append("no active evaluation cases executed")
    if report["overall_pass_rate"]<baseline["minimum_overall_pass_rate"]: failures.append("overall pass rate below minimum")
    for suite in report["suites"]:
        minimum=baseline["minimum_suite_pass_rate"].get(suite["suite"],1.0)
        old=baseline.get("suite_scores",{}).get(suite["suite"],minimum); delta=suite["pass_rate"]-old
        report["baseline_diff"][suite["suite"]]=round(delta,6)
        if suite["pass_rate"]<minimum: failures.append(f"{suite['suite']} pass rate below minimum")
        if delta < -baseline.get("maximum_allowed_regression",0): failures.append(f"{suite['suite']} regressed")
        if any(c["required"] and not c["passed"] for c in suite["results"]): failures.append(f"{suite['suite']} required case failed")
    for name,score in report.get("dimension_scores",{}).items():
        previous=baseline.get("dimension_scores",{}).get(name)
        if previous is not None and score-previous < -baseline.get("maximum_allowed_regression",0):
            failures.append(f"dimension {name} regressed")
    schema=[c for s in report["suites"] for case in s["results"] for run in case["runs"] for c in run["checks"] if c["name"]=="schema_validity"]
    raw_schema=[c for s in report["suites"] for case in s["results"] for run in case["runs"] for c in run["checks"] if c["name"]=="raw_schema_validity"]
    executed=sum(len(case["runs"]) for s in report["suites"] for case in s["results"])
    report["schema_failure_rate"]=sum(not c["passed"] for c in schema)/executed if executed else 1.0
    report["observation_schema_failure_rate"]=report["schema_failure_rate"]
    report["raw_schema_failure_rate"]=sum(not c["passed"] for c in raw_schema)/executed if executed else 1.0
    if len(schema)!=executed or report["schema_failure_rate"]: failures.append("observation schema grader missing or failed")
    if len(raw_schema)!=executed or report["raw_schema_failure_rate"]: failures.append("raw schema grader missing or failed")
    return not failures,sorted(set(failures))

def _baseline_candidate(report:dict)->dict:
    return {"approval_status":"CANDIDATE_REQUIRES_HUMAN_REVIEW","experiment_id":report["metadata"]["experiment_id"],
        "source_git_commit":report["metadata"]["git_commit"],"dataset_version":report["metadata"]["dataset_version"],
        "dataset_hash":report["metadata"]["dataset_hash"],"generated_at":report["metadata"]["generated_at"],
        "quality_claim":"engineering_regression_only",
        "minimum_overall_pass_rate":report["overall_pass_rate"],"minimum_suite_pass_rate":{s["suite"]:s["pass_rate"] for s in report["suites"]},
        "suite_scores":{s["suite"]:s["pass_rate"] for s in report["suites"]},"dimension_scores":report["dimension_scores"],"maximum_allowed_regression":0.02}

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--suite",choices=(*SUITES,"all"),default="all")
    p.add_argument("--split",choices=("dev","regression","public_test","private_holdout"),default="regression")
    p.add_argument("--dataset-root",type=Path,default=DEFAULT_DATASET_ROOT); p.add_argument("--live",action="store_true")
    p.add_argument("--repetitions",type=int,default=1); p.add_argument("--no-gate",action="store_true")
    p.add_argument("--output-dir",type=Path,default=ROOT/"reports"); p.add_argument("--write-baseline-candidate",type=Path)
    p.add_argument("--baseline",type=Path,default=ROOT/"baseline.json")
    args=p.parse_args()
    if args.live and not application_settings.openai_api_key: p.error("--live requires OPENAI_API_KEY")
    all_cases=validate_dataset(args.dataset_root); manifest=load_manifest(args.dataset_root)
    suites=SUITES if args.suite=="all" else (args.suite,)
    eval_settings=SimpleNamespace(database_path=None,database_url=None,openai_api_key=application_settings.openai_api_key if args.live else None,
        openai_model=application_settings.openai_model,ai_input_cost_per_million=getattr(application_settings,"ai_input_cost_per_million",0),
        ai_output_cost_per_million=getattr(application_settings,"ai_output_cost_per_million",0),openai_temperature=0.0)
    original_db,original_ai=db.settings,ai.settings; db.settings=ai.settings=eval_settings
    try:
        with tempfile.TemporaryDirectory(prefix="mission-control-eval-") as directory:
            suite_reports=[execute_suite(s,args.split,args.repetitions,args.live,application_settings.eval_judge_model,
                Path(directory),args.dataset_root) for s in suites]
    finally: db.settings,ai.settings=original_db,original_ai
    dhash=dataset_hash(args.dataset_root); experiment_id=str(uuid4()); generated=datetime.now(timezone.utc).isoformat()
    runtimes=[run["actual_runtime"] for s in suite_reports for c in s["results"] for run in c["runs"] if s["suite"] in MODEL_SUITES]
    live_valid=bool(runtimes) and all(r["provider"]=="openai" and r["final_status"]=="SUCCEEDED" and not r["fallback_used"] for r in runtimes)
    metadata=ExperimentMetadata(experiment_id=experiment_id,generated_at=generated,git_commit=_git("rev-parse","HEAD"),
        branch=_git("branch","--show-current"),dirty=bool(_git("status","--porcelain") not in ("","unknown")),dataset_version=manifest.version,
        dataset_hash=dhash,split=args.split,mode="real-model" if args.live else "offline-fallback",
        provider="openai" if args.live and live_valid else ("invalid" if args.live else "local"),
        model=application_settings.openai_model if args.live else "local-fallback",judge_model=application_settings.eval_judge_model if args.live else None,
        same_model_judge=bool(args.live and application_settings.eval_judge_model==application_settings.openai_model),
        prompt_versions={"planning":ai.PLAN_PROMPT_VERSION,"teaching":ai.QUESTION_PROMPT_VERSION,
                         "assessment":ai.ASSESS_PROMPT_VERSION,"judge":JUDGE_PROMPT_VERSION},temperature=0.0,repetitions=args.repetitions)
    checks=[c for s in suite_reports for case in s["results"] for run in case["runs"] for c in run["checks"]]
    dimensions={name:round(statistics.mean(c["score"] for c in checks if c["name"]==name),6) for name in sorted({c["name"] for c in checks})}
    latencies=[r["latency_ms"] for s in suite_reports for c in s["results"] for r in c["runs"]]
    judge_runs=[r["judge"] for s in suite_reports for c in s["results"] for r in c["runs"] if r["judge"]]
    judge_failures=sum(bool(r["judge_failure"]) for s in suite_reports for c in s["results"] for r in c["runs"])
    claim=quality_claim(args.live,runtimes,judge_failures); claim_valid=claim=="real_model_quality_sample"
    report={"report_schema_version":"2.0","metadata":metadata.model_dump(),"suites":suite_reports,"dimension_scores":dimensions,
        "latency_ms":{"p50":percentile(latencies,.5),"p95":percentile(latencies,.95),"samples":len(latencies)},
        "fallback_rate":sum(r["fallback_used"] for r in runtimes)/len(runtimes) if runtimes else None,
        "judge_failure_count":judge_failures,
        "input_tokens":sum(r["input_tokens"] for r in runtimes)+sum(r["input_tokens"] for r in judge_runs),
        "output_tokens":sum(r["output_tokens"] for r in runtimes)+sum(r["output_tokens"] for r in judge_runs),
        "estimated_cost":round(sum(r["estimated_cost"] for r in runtimes)+estimated_cost(
            sum(r["input_tokens"] for r in judge_runs),sum(r["output_tokens"] for r in judge_runs),
            getattr(application_settings,"ai_input_cost_per_million",0),getattr(application_settings,"ai_output_cost_per_million",0)),8),
        "retry_count":sum(r["retry_count"] for r in runtimes),
        "quality_claim":claim}
    baseline_status="MISSING"; baseline_reason=None
    try:
        baseline=json.loads(args.baseline.read_text(encoding="utf-8"))
        baseline_status=baseline.get("approval_status","REJECTED")
        if baseline_status not in {"CANDIDATE_REQUIRES_HUMAN_REVIEW","APPROVED","REJECTED","STALE"}:
            baseline_status="REJECTED"; baseline_reason="baseline has an invalid approval status"
        if baseline.get("dataset_version")!=manifest.version or baseline.get("dataset_hash")!=dhash:
            baseline_status="STALE"; baseline_reason="baseline dataset version or hash is stale"
        source=baseline.get("source_git_commit")
        if not source or _git("cat-file","-t",source)!="commit" or not _git_success("merge-base","--is-ancestor",source,"HEAD"):
            baseline_status="STALE"; baseline_reason="baseline source commit is unavailable or not an ancestor of HEAD"
        report["gate_passed"],report["gate_failures"]=evaluate_gate(report,baseline)
    except (OSError,json.JSONDecodeError,KeyError,TypeError) as exc:
        baseline={}; report["gate_passed"]=False; report["gate_failures"]=[f"baseline unavailable: {type(exc).__name__}"]
        baseline_reason="baseline is missing or invalid"
    if baseline_status!="APPROVED":
        report["gate_passed"]=False
        baseline_reason=baseline_reason or f"baseline status {baseline_status} is not APPROVED"
        report["gate_failures"].append(baseline_reason)
    report["baseline_approval_status"]=baseline_status
    report["baseline_reason"]=baseline_reason
    if args.live and not claim_valid: report["gate_passed"]=False; report["gate_failures"].append("live authenticity or judge failure")
    validate_report_schema(report)
    args.output_dir.mkdir(parents=True,exist_ok=True); serialized=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    (args.output_dir/f"{experiment_id}.json").write_text(serialized); (args.output_dir/"latest.json").write_text(serialized)
    markdown=(f"# Evaluation {experiment_id}\n\n- Gate: {'PASS' if report['gate_passed'] else 'FAIL'}\n"
              f"- Claim: `{report['quality_claim']}`\n- Dataset: `{manifest.version}` / `{args.split}`\n"
              f"- Active cases: {sum(s['cases'] for s in suite_reports)}\n- Pending cases: {sum(len(s['pending_cases']) for s in suite_reports)}\n")
    (args.output_dir/f"{experiment_id}.md").write_text(markdown); (args.output_dir/"latest.md").write_text(markdown)
    if args.write_baseline_candidate: write_candidate(_baseline_candidate(report),args.write_baseline_candidate)
    print(json.dumps({"experiment_id":experiment_id,"gate_passed":report["gate_passed"],"quality_claim":report["quality_claim"],
        "overall_pass_rate":report["overall_pass_rate"],"pending_cases":sum(len(s["pending_cases"]) for s in suite_reports)},ensure_ascii=False))
    return 0 if report["gate_passed"] or args.no_gate else 1

if __name__=="__main__": sys.exit(main())
