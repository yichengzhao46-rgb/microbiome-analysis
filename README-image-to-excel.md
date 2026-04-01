# HPLC Image To Excel Workflow

This workflow is designed for chromatography report screenshots like the HPLC images you showed earlier.

It does four things:
- finds all report screenshots in a folder;
- crops the white report page out of the monitor photo;
- sends the cleaned page image to the OpenAI Responses API for structured extraction;
- writes the extracted metadata and peak table rows into an Excel workbook.

## Expected Input

The workflow works best for images that contain:
- one report page per image;
- a visible metadata block near the top;
- a visible peak table near the bottom;
- moderate blur but still readable text.

## Files

- `scripts/extract_hplc_report_images.py`: main extraction script.
- `requirements-image-to-excel.txt`: Python dependencies for this workflow.

## Setup

```bash
python -m pip install -r requirements-image-to-excel.txt
```

Set your API key:

```bash
set OPENAI_API_KEY=your_key_here
```

## Usage

```bash
python scripts/extract_hplc_report_images.py ^
  --input-dir data/raw/hplc_images ^
  --output-xlsx results/hplc_report_extracted.xlsx ^
  --preview-dir results/previews
```

## Dry Run

Use this to verify image discovery, cropping, cache generation, and Excel writing without making API calls:

```bash
python scripts/extract_hplc_report_images.py ^
  --input-dir data/raw/hplc_images ^
  --output-xlsx results/hplc_report_inventory.xlsx ^
  --preview-dir results/previews ^
  --dry-run
```

## Output Workbook

The script writes three sheets:

- `documents`: one row per image with extracted report metadata and warnings.
- `peaks`: one row per extracted peak table entry.
- `issues`: warnings, unreadable images, and images where no peak rows were returned.

## Recommended Repo Layout

```text
data/
  raw/
    hplc_images/
results/
  previews/
scripts/
```

## Notes

- The script caches model outputs under `.cache/hplc_report_extractions` so re-runs are cheaper.
- If your report screenshots use a different layout, adjust the prompt or schema inside the script.
- If you later want to support plain tables instead of chromatography reports, build a second extractor instead of overloading this one.
