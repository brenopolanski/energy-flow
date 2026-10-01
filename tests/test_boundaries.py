from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"


def _source(package: str) -> str:
    return "\n".join(path.read_text() for path in (ROOT / package).rglob("*.py"))


def test_services_do_not_import_each_others_application_code() -> None:
    ingestion = _source("ingestion_service")
    processing = _source("processing_service")
    results = _source("results_service")

    assert "processing_service" not in ingestion
    assert "results_service" not in ingestion
    assert "ingestion_service" not in processing
    assert "results_service" not in processing
    assert "processing_service" not in results
    assert "ingestion_service" not in results
    assert "split_power" not in ingestion
    assert "split_power" not in results
