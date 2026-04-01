from pathlib import Path


def test_repository_structure_exists() -> None:
    base = Path(__file__).resolve().parents[1]
    assert (base / "data").exists()
    assert (base / "scripts").exists()
    assert (base / "results").exists()
