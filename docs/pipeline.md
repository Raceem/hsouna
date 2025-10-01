# Pipeline Runbook

This guide explains how to execute the automation pipeline, interpret its outputs, and recover from the most common failure modes.

## Daily Execution Checklist
1. Ensure devices are connected via ADB (`adb devices -l`) and Appium servers are running on the configured ports (`config.DEVICES`).
2. Update `config.local.py` with the target folder (e.g. `FOLDER_NAME = "09_23__2025"`) and reservation date (`TARGET_DATE = "23/09"`).
3. Stage the input PDF in a safe location. If multiple PDFs must be merged, run `python utils.py` or call `utils.merge_pdfs_in_folder` manually.
4. Populate or refresh email/phone pools with `utils.save_variants_to_json` and `utils.save_saudi_numbers_to_json`.
5. Activate the virtual environment and install missing dependencies.
6. Launch the pipeline: `python automation.py data\input.pdf --folder 2025_09_23 --target-date 23/09`.
7. Monitor `logs/automation_runner.log` and the Flask dashboard `/status` page for live progress.
8. After completion, archive the run folder under `BASE_DIR` and clear sensitive logs before pushing code.

## Stage Breakdown
### 1. Preparation (`utils.py`)
- Ensures CSV headers match `config.FIELDNAMES` and that per-gender CSVs exist in the run folder.
- Optional helpers can top up variant JSON files and generate derived assets (e.g. annotated calendar screenshots).

### 2. PDF Extraction (`pdf.py`)
- Reads the provided PDF with `pdfplumber`, normalises casing, dates, and MRZ-derived passport numbers.
- Allocates email and phone variants using `pop_first_variant`, guarded by `rowstore.with_variant_lock` to prevent duplicates.
- Writes consolidated data to `ALL.csv` (path defined by `config.CSV_FILE` or override env vars).
- Adds metadata columns (`CREATION`, `RESERVATION`, `CONFIRMATION`, `date_reservation`, `heure`) if missing.

### 3. Account Creation (`CreationReservation.py`)
- Spawns Appium sessions per device using the capabilities defined in `config.py`.
- Claims CSV rows via `rowstore.claim_next_row`, prioritising unfinished entries when `prioritize_existing=True`.
- Automates login/registration flows, updating the CSV with generated emails, phone numbers, and `CREATION` markers.
- Captures screenshots and writes them into the run folder for audit purposes.

### 4. Reservation Retry (`login.py`)
- Revisits rows where `RESERVATION` is missing or flagged for retry.
- Applies helper routines (`safe_click`, `safe_send_keys`, `update_fast_settings`) to navigate the app reliably.
- Marks successful rows with `RESERVATION = "1"` and logs confirmations to assist later reconciliation.

### 5. Confirmation (`confirmation.py`, `confirmation2.py`)
- Dedicated workers can be launched to finalise outstanding confirmations, particularly after manual corrections.
- Utilises similar locking patterns to claim rows and write back proof-of-success metadata.

## Worker Coordination
- All worker types inherit from base classes defined in `workers.py` and update device state through `set_device_status`.
- Device snapshots include `processed`, `success`, `state`, `note`, and `last_error`. The Flask UI merges this data with ADB discovery so missing devices are visible immediately.
- When a worker crashes or a device disconnects, the claimed row is re-queued via `rowstore.finalize_row(..., requeue=True)` to keep data consistent.

## Error Handling
- **Pipeline step failure**: `automation.py` surfaces the exception message in `automation.get_status()['last_error']`. Fix the underlying issue, then relaunch the pipeline; previously generated CSV data remains intact.
- **Appium crash / instrumentation loss**: `_is_uia2_crash` in `workers.py` detects UiAutomator2 process deaths and triggers `hard_reset_app` for a clean restart.
- **CSV corruption**: `rowstore.load_df` defaults to an empty DataFrame on read errors. Restore from backup or regenerate via `pdf.py` before restarting workers.
- **Variant pool exhaustion**: `pdf.pop_first_variant` prints when JSON lists are empty. Refill the pool before rerunning extraction to avoid missing contact details.

## Observability
- Every pipeline step logs to `logs/automation_runner.log` with timestamps and step names.
- Web endpoints `/status`, `/jobs`, `/devices`, and `/folders/<name>` expose machine-readable data for dashboards or alerting.
- CSV stats are computed via `automation_web.get_csv_stats()` and highlight total rows, accounts created, and confirmed reservations.

## Pausing and Canceling Runs
- Call `automation.cancel_current()` (via the dashboard or an interactive Python shell) to terminate the active subprocess. The state is marked as cancelled and workers stop gracefully.
- Because CSV writes are atomic, a rerun after cancellation simply resumes outstanding rows.

## Maintenance Tasks
- Rotate variant JSON files periodically to avoid stale data.
- Purge old screenshots and debug pages from `BASE_DIR` to reclaim disk space.
- Keep Appium servers updated and ensure each device reports a unique `systemPort` in `config.DEVICES`.
- Synchronise `config.local.py` across machines securely if multiple operators share the workload.

## Related References
- `docs/architecture.md` for a component view of the system.
- `docs/operations.md` for troubleshooting recipes and device care checklists.
