# Repository Guidelines

## Project Structure & Module Organization
The automation toolkit centers on `automation.py` (PDF-to-reservation CLI pipeline) and `automation_web.py` (Flask administration UI). Supporting modules such as `workers.py`, `utils.py`, `gender_sort.py`, `rowstore.py`, `pdf.py`, and `sort.py` stay at the repository root for straightforward imports. Default paths, country settings, and device constants live in `config.py`; stage personal overrides in an untracked `config.local.py` instead of editing defaults. UI templates render from `templates/`, screenshots live in `images/`, diagnostic captures in `debug_pages/`, and rolling execution logs collect under `logs/`.

## Build, Test, and Development Commands
Create a virtual environment before installing dependencies: `python -m venv .venv` followed by `.\\.venv\\Scripts\\activate`. Install third-party packages referenced in imports with `pip install pandas flask PyPDF2 appium-python-client`. Run the end-to-end batch processor using `python automation.py data\\input.pdf --folder 2025_09_23 --target-date 23/09`. For the web dashboard, export `FLASK_APP=automation_web:app` and launch `flask run --debug` for reloadable development. Use `python automation_web.py` only when starting the bundled background workers directly.

## Coding Style & Naming Conventions
Stick to Python 3.11+ conventions: four-space indentation, type hints on new public functions, and f-strings for formatting. Name modules and functions with `snake_case`, reserve `PascalCase` for classes, and keep constants uppercase. Preserve structured logging through the shared `logger` instances so multi-device runs stay traceable inside `logs/`. Comments should clarify automation timing or device quirks, not restate code.

## Testing Guidelines
Automated coverage is minimal; add Pytest modules under `tests/` named `test_<module>.py` whenever you touch pure helpers or parsing logic. Use fixture PDFs and CSV snippets stored outside the repo to avoid sensitive data. After code changes that manipulate devices, perform a dry run with a small PDF and confirm generated CSVs in a scratch folder. For UI updates, hit `/status` and `/jobs` with `curl` to confirm JSON payloads before merging.

## Commit & Pull Request Guidelines
Prefer descriptive commit subjects such as `feat: improve device retry backoff` and include validation commands in the body. Pull requests should summarize scope, link to tracking tickets, list manual test evidence, and attach UI screenshots when Flask templates change. Request review from another maintainer whenever schema changes or worker coordination is affected.

## Environment & Security Notes
Do not commit real PDFs, credentials, device identifiers, or absolute workstation paths. Configure the Flask `secret_key`, Appium URLs, and base directories through environment variables or ignored config files. Empty the `logs/` directory before publishing branches, and share sanitized samples only over approved channels.
