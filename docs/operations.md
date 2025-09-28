# Operations Guide

This guide focuses on day-to-day support actions, troubleshooting tips, and operational hygiene for the automation toolkit.

## Environment Management
- **Virtual environment**: Always activate `.venv` before running scripts. Re-install dependencies when switching machines to ensure consistent versions.
- **Configuration**: Keep `config.local.py` out of version control. Store secrets (emails, Appium URLs, device UDIDs) in environment variables or secure vaults.
- **Device roster**: Update `config.DEVICES` when adding or replacing phones. Each device requires a unique `systemPort` and, if using multiple Appium servers, its own `appiumServer` URL.

## Monitoring Checklist
- Verify `adb devices -l` shows every expected device before launching the pipeline.
- Confirm Appium servers log successful sessions when workers boot; failures often mean port clashes or missing drivers.
- Watch `logs/automation_runner.log` plus per-module logs under `logs/` for stack traces.
- Use the dashboard `/devices` endpoint to check live worker progress and recent errors.

## Common Issues
### Appium Session Fails to Start
- Ensure the device screen is unlocked and `USB debugging` is enabled.
- Restart the Appium server tied to the device and retry. `workers._new_driver_for` falls back to `config.APPIUM_SERVER`, so confirm both URLs respond.
- If the error mentions instrumentation not running, the code will attempt `hard_reset_app`. You can manually trigger `adb shell pm clear <package>` and relaunch.

### CSV Rows Stuck in WORKER State
- Inspect the CSV for rows where the `WORKER` column is populated but timestamps are stale.
- Run a rescue script (Python shell) to call `rowstore.finalize_row(path, worker_name, row_dict, requeue=True)` so the row re-enters the queue.
- Validate that the worker thread is still alive; if not, restart the pipeline stage or relaunch the dashboard.

### Variant Pools Empty
- Logs from `pdf.pop_first_variant` print "La liste est vide" when no emails or numbers remain.
- Re-run `utils.save_variants_to_json` or `utils.save_saudi_numbers_to_json` with fresh seed data, then reprocess the affected rows.

### Pipeline Cancels Immediately
- `automation._RunnerState` will prevent overlapping runs. Check `/status` for `last_error`. If the previous run crashed, call `automation.cancel_current()` to reset state before launching again.

## Data Hygiene
- Sanitize PDFs, CSVs, and screenshots before sharing outside approved channels.
- Delete or archive old run folders under `BASE_DIR` once bookings are reconciled.
- Empty the repository `logs/` directory before creating branches or pull requests.

## Extending the System
- Add new dashboard views by creating templates in `templates/` and wiring routes in `automation_web.py`. Reuse helper functions like `_count_rows` to keep CSV handling consistent.
- When introducing new worker behaviour, extend the classes in `workers.py` and register additional status fields through `set_device_status` so they appear in the UI automatically.
- Document any new automation quirks in this file to keep the operations knowledge base current.

## Incident Response
1. Capture logs (`logs/automation_runner.log`, device-specific traces) and any relevant screenshots.
2. Note the exact row or PDF causing trouble and preserve a copy in a safe location.
3. File an issue describing the failure mode, recent code changes, and manual mitigation steps.
4. Update `docs/operations.md` once the root cause is understood so future runs have clear guidance.

## Useful Commands
- `flask run --debug` — Start the dashboard with auto-reload.
- `python automation.py ... --folder <MM_DD__YYYY> --target-date DD/MM` — Run the full pipeline.
- `adb devices -l` — Confirm device connectivity.
- `rg "ERROR" logs` — Quickly surface exceptions in log files.

Keep this playbook close to the operators who run devices each day. When you discover new edge cases or recovery steps, add them here to keep the team aligned.
