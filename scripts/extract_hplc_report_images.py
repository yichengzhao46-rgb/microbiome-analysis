from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from PIL import Image, ImageOps


SUPPORTED_IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp'}
DEFAULT_MODEL = 'gpt-4.1-mini'
DEFAULT_API_URL = 'https://api.openai.com/v1/responses'

SYSTEM_PROMPT = """
You extract structured data from chromatography report screenshots.

Rules:
- Read only what is visible in the image.
- Do not infer missing numbers.
- Return null when a value is unreadable.
- Keep peak rows in the same order they appear in the peak table.
- Use warnings to record uncertainty, cropped text, blur, glare, or partial tables.
- If the image is not a chromatography report, return an empty peaks array and explain the issue in warnings.
""".strip()

USER_PROMPT = """
Extract the document-level metadata and the visible peak table from this chromatography report screenshot.

Focus especially on:
- report title and report name;
- sample name / id / type;
- processed date and reported date if visible;
- vial / volume / detector / method information if visible;
- every visible row from the peak table near the bottom of the report.
""".strip()

RESPONSE_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'additionalProperties': False,
    'properties': {
        'document': {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'report_title': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                'report_name': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                'data_path': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                'processed_date': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                'reported_date': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                'sample_name': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                'sample_id': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                'sample_type': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                'vial_number': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                'vial_type': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                'injection_volume': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                'detector': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                'method_name': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                'page_indicator': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
            },
            'required': [
                'report_title', 'report_name', 'data_path', 'processed_date', 'reported_date',
                'sample_name', 'sample_id', 'sample_type', 'vial_number', 'vial_type',
                'injection_volume', 'detector', 'method_name', 'page_indicator'
            ],
        },
        'peaks': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'peak_no': {'anyOf': [{'type': 'integer'}, {'type': 'null'}]},
                    'rt': {'anyOf': [{'type': 'number'}, {'type': 'null'}]},
                    'area': {'anyOf': [{'type': 'number'}, {'type': 'null'}]},
                    'conc': {'anyOf': [{'type': 'number'}, {'type': 'null'}]},
                    'bc': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                    'label': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                    'raw_row_text': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                },
                'required': ['peak_no', 'rt', 'area', 'conc', 'bc', 'label', 'raw_row_text'],
            },
        },
        'warnings': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['document', 'peaks', 'warnings'],
}


@dataclass
class PreparedImage:
    source_path: Path
    processed_bytes: bytes
    media_type: str
    original_size: tuple[int, int]
    processed_size: tuple[int, int]
    crop_box: tuple[int, int, int, int] | None
    sha256: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Extract structured chromatography report data from screenshots and export to Excel.'
    )
    parser.add_argument('--input-dir', type=Path, required=True, help='Folder containing report screenshots.')
    parser.add_argument('--output-xlsx', type=Path, required=True, help='Excel workbook to write.')
    parser.add_argument('--preview-dir', type=Path, default=None, help='Optional folder for saving preprocessed image previews.')
    parser.add_argument('--cache-dir', type=Path, default=Path('.cache') / 'hplc_report_extractions', help='Directory for cached extraction JSON files.')
    parser.add_argument('--model', default=DEFAULT_MODEL, help=f'OpenAI model to use (default: {DEFAULT_MODEL}).')
    parser.add_argument('--api-url', default=DEFAULT_API_URL, help='Responses API endpoint.')
    parser.add_argument('--api-key-env', default='OPENAI_API_KEY', help='Environment variable containing the API key.')
    parser.add_argument('--limit', type=int, default=None, help='Optional maximum number of images to process.')
    parser.add_argument('--refresh-cache', action='store_true', help='Ignore cached JSON and re-run extraction.')
    parser.add_argument('--no-crop', action='store_true', help='Skip automatic page cropping.')
    parser.add_argument('--dry-run', action='store_true', help='Do not call the API. Only preprocess images and write an inventory workbook.')
    return parser.parse_args()


def iter_images(input_dir: Path) -> list[Path]:
    return [path for path in sorted(input_dir.rglob('*')) if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES]


def detect_report_box(image: Image.Image, brightness_threshold: int = 185) -> tuple[int, int, int, int] | None:
    gray = ImageOps.autocontrast(image.convert('L'))
    data = np.array(gray)
    bright = data > brightness_threshold
    col_ratio = bright.mean(axis=0)
    row_ratio = bright.mean(axis=1)
    cols = np.where(col_ratio > 0.55)[0]
    rows = np.where(row_ratio > 0.35)[0]
    if len(cols) == 0 or len(rows) == 0:
        return None
    left = max(int(cols[0]) - 20, 0)
    top = max(int(rows[0]) - 20, 0)
    right = min(int(cols[-1]) + 20, image.width)
    bottom = min(int(rows[-1]) + 20, image.height)
    if right - left < image.width * 0.25 or bottom - top < image.height * 0.25:
        return None
    return left, top, right, bottom


def prepare_image(path: Path, preview_dir: Path | None = None, crop: bool = True) -> PreparedImage:
    image = ImageOps.exif_transpose(Image.open(path)).convert('RGB')
    original_size = image.size
    crop_box = detect_report_box(image) if crop else None
    if crop_box:
        image = image.crop(crop_box)
    if max(image.size) > 1600:
        ratio = 1600 / max(image.size)
        image = image.resize((int(image.width * ratio), int(image.height * ratio)))
    buffer = BytesIO()
    image.save(buffer, format='JPEG', quality=92, optimize=True)
    processed_bytes = buffer.getvalue()
    sha256 = hashlib.sha256(processed_bytes).hexdigest()
    if preview_dir is not None:
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_path = preview_dir / f'{path.stem}__prepared.jpg'
        preview_path.write_bytes(processed_bytes)
    return PreparedImage(
        source_path=path,
        processed_bytes=processed_bytes,
        media_type='image/jpeg',
        original_size=original_size,
        processed_size=image.size,
        crop_box=crop_box,
        sha256=sha256,
    )


def build_request_body(model: str, image_data_url: str) -> dict[str, Any]:
    return {
        'model': model,
        'input': [
            {'role': 'system', 'content': [{'type': 'input_text', 'text': SYSTEM_PROMPT}]},
            {'role': 'user', 'content': [
                {'type': 'input_text', 'text': USER_PROMPT},
                {'type': 'input_image', 'image_url': image_data_url, 'detail': 'high'},
            ]},
        ],
        'text': {
            'format': {
                'type': 'json_schema',
                'name': 'chromatography_report_extraction',
                'strict': True,
                'schema': RESPONSE_SCHEMA,
            }
        },
    }


def encode_image_data_url(prepared: PreparedImage) -> str:
    encoded = base64.b64encode(prepared.processed_bytes).decode('ascii')
    return f'data:{prepared.media_type};base64,{encoded}'


def extract_output_text(response_json: dict[str, Any]) -> str:
    if isinstance(response_json.get('output_text'), str) and response_json['output_text'].strip():
        return response_json['output_text']
    texts: list[str] = []
    for item in response_json.get('output', []):
        if item.get('type') != 'message':
            continue
        for content in item.get('content', []):
            content_type = content.get('type')
            if content_type == 'output_text' and isinstance(content.get('text'), str):
                texts.append(content['text'])
            elif content_type == 'text':
                text_value = content.get('text')
                if isinstance(text_value, str):
                    texts.append(text_value)
                elif isinstance(text_value, dict) and isinstance(text_value.get('value'), str):
                    texts.append(text_value['value'])
    if texts:
        return '\n'.join(texts)
    raise RuntimeError('Could not find structured text in the API response.')


def call_openai(prepared: PreparedImage, model: str, api_url: str, api_key: str) -> dict[str, Any]:
    response = requests.post(
        api_url,
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json=build_request_body(model=model, image_data_url=encode_image_data_url(prepared)),
        timeout=180,
    )
    response.raise_for_status()
    payload = response.json()
    text = extract_output_text(payload)
    return json.loads(text)


def cache_path_for(prepared: PreparedImage, cache_dir: Path) -> Path:
    return cache_dir / f'{prepared.sha256}.json'


def ensure_schema_shape(result: dict[str, Any]) -> dict[str, Any]:
    document = result.get('document') or {}
    peaks = result.get('peaks') or []
    warnings = result.get('warnings') or []
    normalized = {
        'document': {
            key: document.get(key)
            for key in [
                'report_title', 'report_name', 'data_path', 'processed_date', 'reported_date',
                'sample_name', 'sample_id', 'sample_type', 'vial_number', 'vial_type',
                'injection_volume', 'detector', 'method_name', 'page_indicator',
            ]
        },
        'peaks': [],
        'warnings': [str(item) for item in warnings],
    }
    for peak in peaks:
        normalized['peaks'].append({
            'peak_no': peak.get('peak_no'),
            'rt': peak.get('rt'),
            'area': peak.get('area'),
            'conc': peak.get('conc'),
            'bc': peak.get('bc'),
            'label': peak.get('label'),
            'raw_row_text': peak.get('raw_row_text'),
        })
    return normalized


def load_or_extract(prepared: PreparedImage, *, cache_dir: Path, refresh_cache: bool, dry_run: bool, model: str, api_url: str, api_key: str | None) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path_for(prepared, cache_dir)
    if path.exists() and not refresh_cache:
        return json.loads(path.read_text(encoding='utf-8'))
    if dry_run:
        result = {'document': {}, 'peaks': [], 'warnings': ['dry_run: API call skipped']}
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return result
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY is not set and dry-run mode is disabled.')
    result = ensure_schema_shape(call_openai(prepared, model=model, api_url=api_url, api_key=api_key))
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def flatten_results(items: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    document_rows: list[dict[str, Any]] = []
    peak_rows: list[dict[str, Any]] = []
    issue_rows: list[dict[str, Any]] = []
    for item in items:
        prepared: PreparedImage = item['prepared']
        result: dict[str, Any] = item['result']
        document = result.get('document', {})
        warnings = result.get('warnings', [])
        document_rows.append({
            'image_name': prepared.source_path.name,
            'relative_path': item['relative_path'],
            'sha256': prepared.sha256,
            'original_width': prepared.original_size[0],
            'original_height': prepared.original_size[1],
            'processed_width': prepared.processed_size[0],
            'processed_height': prepared.processed_size[1],
            'crop_box': json.dumps(prepared.crop_box),
            'warning_count': len(warnings),
            'warnings': ' | '.join(warnings),
            **document,
        })
        peaks = result.get('peaks', [])
        if peaks:
            for peak in peaks:
                peak_rows.append({
                    'image_name': prepared.source_path.name,
                    'relative_path': item['relative_path'],
                    'sample_name': document.get('sample_name'),
                    'sample_id': document.get('sample_id'),
                    **peak,
                })
        else:
            issue_rows.append({
                'image_name': prepared.source_path.name,
                'relative_path': item['relative_path'],
                'issue_type': 'no_peaks_extracted',
                'details': ' | '.join(warnings) if warnings else 'No peak rows returned.',
            })
        for warning in warnings:
            issue_rows.append({
                'image_name': prepared.source_path.name,
                'relative_path': item['relative_path'],
                'issue_type': 'warning',
                'details': warning,
            })
    return pd.DataFrame(document_rows), pd.DataFrame(peak_rows), pd.DataFrame(issue_rows)


def write_excel(output_path: Path, documents_df: pd.DataFrame, peaks_df: pd.DataFrame, issues_df: pd.DataFrame) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        documents_df.to_excel(writer, sheet_name='documents', index=False)
        peaks_df.to_excel(writer, sheet_name='peaks', index=False)
        issues_df.to_excel(writer, sheet_name='issues', index=False)


def main() -> None:
    args = parse_args()
    api_key = os.getenv(args.api_key_env)
    images = iter_images(args.input_dir)
    if args.limit is not None:
        images = images[: args.limit]
    if not images:
        raise SystemExit(f'No supported images found under {args.input_dir}')

    items: list[dict[str, Any]] = []
    for image_path in images:
        prepared = prepare_image(image_path, preview_dir=args.preview_dir, crop=not args.no_crop)
        result = load_or_extract(
            prepared,
            cache_dir=args.cache_dir,
            refresh_cache=args.refresh_cache,
            dry_run=args.dry_run,
            model=args.model,
            api_url=args.api_url,
            api_key=api_key,
        )
        items.append({
            'prepared': prepared,
            'relative_path': image_path.relative_to(args.input_dir).as_posix(),
            'result': ensure_schema_shape(result),
        })

    documents_df, peaks_df, issues_df = flatten_results(items)
    write_excel(args.output_xlsx, documents_df, peaks_df, issues_df)
    print(f'Wrote {args.output_xlsx}')
    print(f'Processed images: {len(items)}')
    print(f'Document rows: {len(documents_df)} | Peak rows: {len(peaks_df)} | Issues: {len(issues_df)}')


if __name__ == '__main__':
    main()
