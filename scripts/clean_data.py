from pathlib import Path


def main() -> None:
    base = Path(__file__).resolve().parents[1]
    raw_dir = base / "data" / "raw"
    processed_dir = base / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    print(f"Raw data directory: {raw_dir}")
    print(f"Processed data directory: {processed_dir}")
    print("Implement repository-specific cleaning logic here.")


if __name__ == "__main__":
    main()
