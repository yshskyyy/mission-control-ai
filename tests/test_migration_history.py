from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_initial_migration_has_no_runtime_metadata_dependency():
    source=(ROOT/"migrations/versions/20260914_0001_initial.py").read_text(encoding="utf-8")
    assert "app.models" not in source
    assert "metadata.create_all" not in source
    assert "op.create_table" in source


def test_historical_0005_chain_does_not_import_runtime_models():
    for name in (
        "20260914_0001_initial.py",
        "20260914_0002_ingestion_reliability.py",
        "20260914_0003_evidence_teaching.py",
        "20260915_0004_teaching_runtime.py",
        "20260915_0005_daily_scheduling.py",
    ):
        source=(ROOT/"migrations/versions"/name).read_text(encoding="utf-8")
        assert "from app.models" not in source
