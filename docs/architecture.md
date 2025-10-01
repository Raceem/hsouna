# Architecture Overview

This document explains how the automation toolkit is put together, what each core component owns, and how data travels between them.

## System Topology
```
PDF input -> automation.py (runner)
              |-- utils.py (prepare CSVs, merge inputs)
              |-- pdf.py (extract travellers, assign variants)
              |-- CreationReservation.py (device automation)
              |-- login.py (retry reservations)
              |
              +-> BASE_DIR/<run-folder>/ (CSV, screenshots, logs)

Flask dashboard (automation_web.py)
    |-- Invokes automation.run_pipeline_async
    |-- Polls automation.get_status
    |-- Reads CSV stats and device status via workers.py
```

## Components
- **automation.py** orchestrates the four pipeline stages, maintains a shared `_RunnerState`, and exposes `get_status()` plus cancellation hooks for the dashboard.
- **automation_web.py** wraps the runner in a Flask app. It renders HTML forms, exposes JSON status endpoints, and serves generated artifacts (CSVs, zipped archives, screenshots).
- **workers.py** manages per-device worker threads. It distributes CSV rows, tracks Appium sessions, and aggregates live device telemetry for the UI.
- **Device automation modules** (`CreationReservation.py`, `login.py`, `confirmation.py`, `Creation.py`) open Appium sessions, drive the mobile UI, and write back progress markers (CREATION/RESERVATION/CONFIRMATION columns).
- **Data helpers** (`pdf.py`, `rowstore.py`, `gender_sort.py`, `sort.py`, `utils.py`) provide ingestion, normalization, and safe file mutation utilities so the rest of the code can focus on automation logic.
- **Configuration** is driven by `config.py` defaults plus optional `config.local.py`. Environment variables (e.g. `APP_PACKAGE`, `EMAIL_JSON_FILE_OVERRIDE`) allow per-run overrides without editing source files.

## Data Flow
1. **Ingestion**: `automation.py` copies the source PDF into a dated run folder under `BASE_DIR` and updates configuration with the folder name, target date, and file name.
2. **Preparation**: `utils.py` ensures CSV skeletons exist and merges any staged PDFs. Optional helpers can seed email/phone variant pools.
3. **Extraction**: `pdf.py` parses the manifest, normalizes fields (names, passport numbers, genders), and appends rows to the shared `ALL.csv`. Email/phone variants are popped atomically from JSON files to avoid reuse.
4. **Creation**: `CreationReservation.py` builds accounts on connected devices. Each worker claims a row via `rowstore.claim_next_row`, pushes updates (CREATION column), and stores screenshots in the run folder.
5. **Reservation retries**: `login.py` revisits rows where reservations failed or require confirmation, updating RESERVATION/CONFIRMATION columns accordingly.
6. **Confirmation**: `confirmation.py` is invoked by specialised workers or manual runs to finish outstanding steps and to capture proof artifacts.
7. **Monitoring**: `automation_web.py` reads CSV stats, merges them with Appium worker telemetry, and presents the state in the dashboard. Logs rotate under `logs/` for postmortem analysis.

## Concurrency Guarantees
- `rowstore.py` wraps CSV/JSON writes in file locks (`portalocker`) so multiple worker threads or processes never write simultaneously.
- `_RunnerState` in `automation.py` uses a threading lock to keep UI status consistent and to prevent overlapping pipeline executions.
- `workers.py` maintains an in-memory device registry guarded by `_STATUS_LOCK` and refreshes it with the latest ADB discovery.
- Appium driver instances are created per-device with isolated `systemPort` values so multiple Android devices can run in parallel without socket clashes.

## External Dependencies
- **Flask**, **pandas**, **pdfplumber/PyPDF2** for the dashboard and PDF parsing.
- **appium-python-client** for mobile automation.
- **portalocker** (optional but recommended) for portable file locking.
- **OpenCV** (via `cv2`) and **numpy** in `utils.py` for image-based calendar parsing.

## Filesystem Contracts
- `BASE_DIR` must contain `ALL.csv`, per-gender CSVs, JSON variant pools, and run folders named `MM_DD__YYYY` by default.
- Each run folder contains gender-specific subfolders (`hommes`, `femmes`), merged PDFs, screenshots, and CSV exports.
- `logs/` (in the repo) stores application logs; clean it before pushing branches to avoid leaking sensitive data.

## Extension Points
- Add new pipeline steps by editing `automation.py:run_pipeline` (e.g. insert custom validation between existing steps).
- Define new worker types in `workers.py` by extending the base `DeviceWorker` to process specialised CSV queues.
- Use environment overrides to run the same codebase against staging devices or alternate Appium servers without modifying `config.py`.

## Related Documents
- `docs/pipeline.md` — runbooks for operating the pipeline day-to-day.
- `docs/operations.md` — troubleshooting checklists and maintenance tips.
