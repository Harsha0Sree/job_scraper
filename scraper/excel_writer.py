"""
Excel writer using openpyxl.

Produces a single .xlsx workbook with FOUR sheets:
  - Sheet "Zero Experience Jobs":  the qualifying jobs (formatted, hyperlinked)
  - Sheet "All Filtered Jobs":     every location+category-matched job (audit)
  - Sheet "All Scraped Jobs":      EVERY scraped job with filter outcome (full audit)
  - Sheet "Run Summary":           per-run stats and per-source breakdown
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.hyperlink import Hyperlink

from .data_model import ScrapedJob

log = logging.getLogger("scraper.excel")


HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)

ACCEPT_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")   # green
REJECT_FILL = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")   # orange
ERROR_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")    # yellow
LOC_MATCH_FILL = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")  # light blue

CELL_FONT = Font(name="Calibri", size=10)
CELL_ALIGN = Alignment(vertical="top", wrap_text=True)
LINK_FONT = Font(name="Calibri", size=10, color="0563C1", underline="single")

THIN_BORDER = Border(
    left=Side(style="thin", color="D9D9D9"),
    right=Side(style="thin", color="D9D9D9"),
    top=Side(style="thin", color="D9D9D9"),
    bottom=Side(style="thin", color="D9D9D9"),
)


# Columns for each sheet
QUALIFYING_COLUMNS = [
    ("Date Scraped",        "scraped_at",         20),
    ("Source",              "source",             18),
    ("Location Type",       "location_type",      16),
    ("Posted Date",         "posted_date",        14),
    ("Job Title",           "title",              40),
    ("Company",             "company",            28),
    ("Location",            "location",           30),
    ("Seniority",           "seniority",          14),
    ("ATS Provider",        "ats_provider",       14),
    ("Apply URL",           "ats_url",            50),
    ("Category Matched",    "category_signals",   32),
    ("Experience Matched",  "experience_signals", 30),
    ("Years Mentioned",     "years_mentioned",    30),
    ("Filter Reason",       "filter_reason",      36),
    ("Description Preview", "description_preview", 80),
]

ALL_FILTERED_COLUMNS = [
    ("Date Scraped",        "scraped_at",         20),
    ("Source",              "source",             18),
    ("Location Type",       "location_type",      16),
    ("Posted Date",         "posted_date",        14),
    ("Job Title",           "title",              40),
    ("Company",             "company",            28),
    ("Location",            "location",           30),
    ("Seniority",           "seniority",          14),
    ("ATS Provider",        "ats_provider",       14),
    ("Apply URL",           "ats_url",            50),
    ("Loc Match",           "is_location_match",  10),
    ("Cat Match",           "is_category_match",  10),
    ("Accepted (0 Yrs)",    "accepted",           14),
    ("Filter Reason",       "filter_reason",      50),
    ("Description Preview", "description_preview", 60),
]

ALL_SCRAPED_COLUMNS = [
    ("Date Scraped",        "scraped_at",         20),
    ("Source",              "source",             18),
    ("Posted Date",         "posted_date",        14),
    ("Job Title",           "title",              40),
    ("Company",             "company",            28),
    ("Location",            "location",           30),
    ("Seniority",           "seniority",          14),
    ("ATS Provider",        "ats_provider",       14),
    ("Apply URL",           "ats_url",            50),
    ("Loc Match",           "is_location_match",  10),
    ("Loc Type",            "location_type",      16),
    ("Cat Match",           "is_category_match",  10),
    ("Accepted",            "accepted",           10),
    ("Filter Reason",       "filter_reason",      50),
    ("Error",               "error",              30),
    ("Description Preview", "description_preview", 50),
]

SUMMARY_COLUMNS = [
    ("Metric", "metric", 32),
    ("Value",  "value",  50),
]


def write_workbook(
    path: Path,
    qualifying_jobs: List[ScrapedJob],
    all_jobs: List[ScrapedJob],
    run_summary: dict,
    all_scraped_jobs: List[ScrapedJob] = None,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        wb = load_workbook(path)
        _ensure_sheets(wb)
    else:
        wb = Workbook()
        _init_sheets(wb)

    existing_q = _existing_job_ids(wb["Zero Experience Jobs"])
    existing_a = _existing_job_ids(wb["All Filtered Jobs"])
    existing_s = _existing_job_ids(wb["All Scraped Jobs"])

    # Dedup within the input lists
    def _dedup(jobs):
        seen: set = set()
        out = []
        for j in jobs:
            if j.job_id in seen:
                continue
            seen.add(j.job_id)
            out.append(j)
        return out

    deduped_q = _dedup(qualifying_jobs)
    deduped_a = _dedup(all_jobs)
    deduped_s = _dedup(all_scraped_jobs or [])

    new_q = [j for j in deduped_q if j.job_id not in existing_q]
    new_a = [j for j in deduped_a if j.job_id not in existing_a]
    new_s = [j for j in deduped_s if j.job_id not in existing_s]

    _append_jobs(
        wb["Zero Experience Jobs"], new_q,
        columns=QUALIFYING_COLUMNS, highlight_fn=lambda j: ACCEPT_FILL,
    )
    _append_jobs(
        wb["All Filtered Jobs"], new_a,
        columns=ALL_FILTERED_COLUMNS,
        highlight_fn=lambda j: ACCEPT_FILL if j.accepted else REJECT_FILL,
    )
    if new_s:
        _append_jobs(
            wb["All Scraped Jobs"], new_s,
            columns=ALL_SCRAPED_COLUMNS,
            highlight_fn=lambda j: (
                ACCEPT_FILL if j.accepted
                else ERROR_FILL if j.error
                else LOC_MATCH_FILL if j.is_location_match
                else REJECT_FILL
            ),
        )

    _write_summary(wb["Run Summary"], run_summary)

    tmp_path = path.with_suffix(".tmp.xlsx")
    wb.save(tmp_path)
    tmp_path.replace(path)
    log.info(
        "excel saved: %s (qualifying=%d filtered=%d scraped=%d, new_q=%d new_a=%d new_s=%d)",
        path, len(qualifying_jobs), len(all_jobs), len(all_scraped_jobs or []),
        len(new_q), len(new_a), len(new_s),
    )


def _ensure_sheets(wb: Workbook) -> None:
    for name in ("Zero Experience Jobs", "All Filtered Jobs", "All Scraped Jobs", "Run Summary"):
        if name not in wb.sheetnames:
            ws = wb.create_sheet(name)
            _style_header_row(ws, _columns_for(name))


def _init_sheets(wb: Workbook) -> None:
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    for name in ("Zero Experience Jobs", "All Filtered Jobs", "All Scraped Jobs", "Run Summary"):
        ws = wb.create_sheet(name)
        _style_header_row(ws, _columns_for(name))


def _columns_for(sheet_name: str):
    if sheet_name == "Zero Experience Jobs":
        return QUALIFYING_COLUMNS
    if sheet_name == "All Filtered Jobs":
        return ALL_FILTERED_COLUMNS
    if sheet_name == "All Scraped Jobs":
        return ALL_SCRAPED_COLUMNS
    return SUMMARY_COLUMNS


def _style_header_row(ws, columns) -> None:
    for col_idx, (header, _attr, width) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "C2"


def _existing_job_ids(ws) -> set:
    url_col = None
    for cell in ws[1]:
        if cell.value == "Apply URL":
            url_col = cell.column
            break
    if url_col is None:
        return set()
    from .utils import job_id as compute_id
    ids = set()
    for row in ws.iter_rows(min_row=2, min_col=url_col, max_col=url_col):
        for cell in row:
            if cell.value:
                ids.add(compute_id(str(cell.value)))
    return ids


def _append_jobs(ws, jobs: List[ScrapedJob], columns, highlight_fn) -> None:
    if not jobs:
        return
    start_row = ws.max_row + 1
    for i, job in enumerate(jobs):
        row_idx = start_row + i
        row_fill = highlight_fn(job)
        for col_idx, (_header, attr, _width) in enumerate(columns, start=1):
            value = _cell_value(job, attr)
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = CELL_FONT
            cell.alignment = CELL_ALIGN
            cell.fill = row_fill
            cell.border = THIN_BORDER
            if attr == "ats_url" and value:
                cell.hyperlink = Hyperlink(ref=cell.coordinate, target=str(value))
                cell.font = LINK_FONT
        desc_len = len((job.description_preview or ""))
        ws.row_dimensions[row_idx].height = min(120, max(20, desc_len // 6))


def _cell_value(job: ScrapedJob, attr: str):
    if attr == "scraped_at":
        return job.scraped_at or ""
    if attr == "source":
        return job.source or ""
    if attr == "location_type":
        return job.location_type or ""
    if attr == "seniority":
        return job.seniority or ""
    if attr == "posted_date":
        return job.posted_date or ""
    if attr == "is_location_match":
        return "Yes" if job.is_location_match else "No"
    if attr == "is_category_match":
        return "Yes" if job.is_category_match else "No"
    if attr == "accepted":
        return "Yes" if job.accepted else "No"
    if attr == "category_signals":
        return "; ".join(job.category_signals) if job.category_signals else ""
    if attr == "experience_signals":
        return "; ".join(job.experience_signals) if job.experience_signals else ""
    if attr == "years_mentioned":
        return "; ".join(job.years_mentioned) if job.years_mentioned else ""
    if attr == "description_preview":
        return job.description_preview
    if attr == "error":
        return job.error or ""
    return getattr(job, attr, "") or ""


def _write_summary(ws, summary: dict) -> None:
    for row in ws.iter_rows():
        for cell in row:
            cell.value = None
            cell.fill = PatternFill(fill_type=None)
            cell.font = CELL_FONT
            cell.border = Border()
    _style_header_row(ws, SUMMARY_COLUMNS)
    rows = [
        ("Run timestamp",            summary.get("run_at", "")),
        ("Run mode",                 summary.get("mode", "")),
        ("Days back",                summary.get("days_back", "")),
        ("Sources scraped",          ", ".join(summary.get("sources_scraped", []))),
        ("Jobs parsed (total)",      summary.get("parsed_count", 0)),
    ]
    by_source = summary.get("by_source", {})
    for src, count in sorted(by_source.items()):
        rows.append((f"  - {src}", count))
    rows.extend([
        ("Location matches",         summary.get("location_match_count", 0)),
        ("Category matches",         summary.get("category_match_count", 0)),
        ("Zero-experience jobs",     summary.get("qualifying_count", 0)),
        ("Rejected (location)",      summary.get("not_location_count", 0)),
        ("Rejected (category)",      summary.get("wrong_category_count", 0)),
        ("Rejected (experience)",    summary.get("has_experience_count", 0)),
        ("Errors",                   summary.get("error_count", 0)),
        ("Newly written",            summary.get("new_written", 0)),
        ("Duration (seconds)",       round(summary.get("duration_seconds", 0.0), 2)),
    ])
    for i, (metric, value) in enumerate(rows, start=2):
        c1 = ws.cell(row=i, column=1, value=metric)
        c1.font = Font(name="Calibri", bold=True, size=10)
        c1.border = THIN_BORDER
        c2 = ws.cell(row=i, column=2, value=value)
        c2.font = CELL_FONT
        c2.border = THIN_BORDER
