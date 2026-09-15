from evals.run import evaluate_gate, load_jsonl


def test_eval_datasets_have_stable_unique_ids():
    total = 0
    for suite in ("planning", "teaching", "assessment", "recommendation"):
        cases = load_jsonl(suite)
        assert cases
        assert len({case["id"] for case in cases}) == len(cases)
        total += len(cases)
    assert total >= 20


def test_eval_gate_rejects_suite_regression():
    report = {
        "suites": [
            {"suite": "planning", "cases": 4, "passed": 4, "pass_rate": 1.0},
            {"suite": "assessment", "cases": 8, "passed": 6, "pass_rate": .75},
        ]
    }
    baseline = {
        "minimum_overall_pass_rate": .9,
        "minimum_suite_pass_rate": {"planning": 1.0, "assessment": 1.0},
    }
    passed, failures = evaluate_gate(report, baseline)
    assert not passed
    assert any("assessment" in failure for failure in failures)


def test_eval_gate_accepts_baseline():
    report = {
        "suites": [
            {"suite": "teaching", "cases": 6, "passed": 6, "pass_rate": 1.0},
        ]
    }
    baseline = {
        "minimum_overall_pass_rate": .95,
        "minimum_suite_pass_rate": {"teaching": .8},
    }
    passed, failures = evaluate_gate(report, baseline)
    assert passed
    assert failures == []
