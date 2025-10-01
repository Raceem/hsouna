# Automation Toolkit

This repository automates converting PDF manifests into confirmed reservations through a mix of command-line tooling, Appium-powered device workers, and a Flask web dashboard. The goal of this documentation set is to help new contributors get productive quickly and give operators the context needed to troubleshoot live runs.

## Key Capabilities
- Batch pipeline that parses PDF manifests, enriches traveller data, and drives mobile reservations end-to-end.
- Flask web dashboard to launch runs, monitor progress, and inspect generated CSV assets.
- Multi-device worker pool with safe CSV locking so automation can scale horizontally.
- Shared logging, screenshots, and debug captures to diagnose flaky device behaviour.

## Quick Start
1. `python -m venv .venv`
2. `.\.venv\Scripts\activate`
3. `pip install -r requirements.txt` (or `pip install pandas flask PyPDF2 appium-python-client pdfplumber portalocker`)
4. Duplicate `config.py` to `config.local.py` and adjust paths, device information, and credentials. The automation always prefers local overrides when present.
5. Run the full pipeline: `python automation.py path\to\input.pdf --folder 2025_09_23 --target-date 23/09`
6. Start the dashboard: set `FLASK_APP=automation_web:app` then `flask run --debug`

## Repository Layout
- `automation.py` � CLI entry point for the four-stage batch pipeline (prepare CSVs, extract PDF data, create accounts, retry reservations).
- `automation_web.py` � Flask app exposing forms, live status endpoints, and download helpers for generated assets.
- `workers.py` � Threaded device coordinator that assigns CSV rows to creation/reservation/confirmation workers and tracks live device state.
- `config.py` � Default paths, device metadata, CSV headers, and Appium capabilities. Override safely in `config.local.py` (ignored by git).
- `pdf.py` � PDF parsing, data normalization, and allocation of email/phone variants stored in JSON pools.
- `rowstore.py` � Locking and CSV mutation helpers (claim/rotate/finalize rows, JSON variant locking) used across workers.
- `login.py`, `CreationReservation.py`, `confirmation.py`, `Creation.py`, `creation_batch.py` � Appium automation steps for account creation, reservation retries, and confirmation flows.
- `gender_sort.py`, `sort.py` � CSV preprocessing helpers for gender splits and deterministic ordering before device runs.
- `templates/` � HTML templates rendered by the Flask dashboard.
- `images/`, `debug_pages/`, `logs/` � Captured screenshots, saved HTML snapshots, and rotating execution logs respectively.

A deeper architectural breakdown is available in `docs/architecture.md` alongside runbooks in `docs/pipeline.md`.

## Configuration
- Use environment variables or `config.local.py` to override sensitive values (Appium servers, credentials, base directories). Never edit `config.py` directly for personal setups.
- Ensure `BASE_DIR` has subdirectories for daily folders, screenshots, logs, and CSV exports. The pipeline creates missing folders on demand.
- Email and phone pools live in JSON files next to the CSVs. They are consumed atomically through `pdf.pop_first_variant` so concurrent workers cannot reuse values.

## Running the Pipeline
1. Prepare CSVs and variant pools using `utils.py` (optional helpers to build base lists and merge inbound PDFs).
2. Launch `automation.py` with the desired PDF and target date. The runner copies the PDF into a per-run folder, updates configuration, then executes:
   - `utils.py` for CSV prep and PDF merging.
   - `pdf.py` to extract traveller rows from the manifest into `ALL.csv`.
   - `CreationReservation.py` to drive account creation and initial reservation attempts on connected devices.
   - `login.py` to retry failed reservations or complete additional slots.
3. Monitor progress via the CLI logs (`logs/automation_runner.log`) or the `/status` endpoint exposed by `automation_web.py`.
4. Inspect generated CSVs under `BASE_DIR/<run-folder>`; per-gender files and screenshots are nested inside.

## Web Dashboard Highlights
- `/` � Launch new runs by uploading PDFs or referencing files already in `BASE_DIR`.
- `/status` � JSON snapshot from `automation.get_status()` showing the active step and error messages.
- `/jobs` � Summaries of historical folders with counts of created and confirmed reservations.
- `/devices` � Live device state aggregated from `workers.py` (connected ADB devices plus active worker stats).
- `/downloads` � Helpers to fetch CSV outputs, merged PDFs, or zipped run artifacts.

The Flask app can also spawn background workers via `automation.run_pipeline_async`, keeping the UI responsive while the pipeline executes.

## Worker Model
- Device workers claim rows from CSVs under file locks, preventing duplicate processing across threads or machines.
- `CreationDeviceWorker` and `DeviceWorker` run the heavy Appium flows. `ConfirmationWorker` revisits pending reservations (typically after manual corrections).
- Workers write structured status updates that the dashboard polls, including processed counts, last error, and the active user.
- Hard resets and app restarts are abstracted through helpers in `config.py` so device-specific quirks can be patched without touching worker logic.

## Logging, Artifacts, and Debugging
- Structured logs: each module uses a named logger so messages land in `logs/` with rotation enabled.
- Screenshots and HTML dumps: stored under `images/` and `debug_pages/` to aid triage after UI changes.
- When a pipeline step fails, the runner records the traceback and keeps the process state in `automation.get_status()` for the dashboard to display.
- Clear the `logs/` directory before publishing branches to avoid leaking operational data.

## Testing and Validation
- Add pytest modules in `tests/` using the `test_<module>.py` convention for pure helpers (parsers, formatters, allocation logic).
- Avoid storing real PDFs or credentials in the repository. Use anonymized fixtures kept outside of git.
- Before large merges, perform a dry run with a short PDF and confirm the generated CSVs in a scratch folder. For UI changes, curl `/status` and `/jobs` to confirm JSON payloads remain stable.

## Contributing
- Follow the style conventions captured in `AGENTS.md` (type hints on new public functions, four-space indentation, f-strings for formatting).
- Name branches and commits descriptively, e.g. `feat: improve device retry backoff`. Include manual validation steps in the commit body.
- Request review when you touch schema changes, worker coordination, or anything that impacts device stability.

For additional operational notes, examples, and troubleshooting tips, review `docs/pipeline.md` and `docs/operations.md`.

# NusukFlow_V3



## Getting started

To make it easy for you to get started with GitLab, here's a list of recommended next steps.

Already a pro? Just edit this README.md and make it your own. Want to make it easy? [Use the template at the bottom](#editing-this-readme)!

## Add your files

- [ ] [Create](https://docs.gitlab.com/ee/user/project/repository/web_editor.html#create-a-file) or [upload](https://docs.gitlab.com/ee/user/project/repository/web_editor.html#upload-a-file) files
- [ ] [Add files using the command line](https://docs.gitlab.com/topics/git/add_files/#add-files-to-a-git-repository) or push an existing Git repository with the following command:

```
cd existing_repo
git remote add origin https://gitlab.com/kobbihsouna-group/NusukFlow/nusukflow_v3.git
git branch -M main
git push -uf origin main
```

## Integrate with your tools

- [ ] [Set up project integrations](https://gitlab.com/kobbihsouna-group/NusukFlow/nusukflow_v3/-/settings/integrations)

## Collaborate with your team

- [ ] [Invite team members and collaborators](https://docs.gitlab.com/ee/user/project/members/)
- [ ] [Create a new merge request](https://docs.gitlab.com/ee/user/project/merge_requests/creating_merge_requests.html)
- [ ] [Automatically close issues from merge requests](https://docs.gitlab.com/ee/user/project/issues/managing_issues.html#closing-issues-automatically)
- [ ] [Enable merge request approvals](https://docs.gitlab.com/ee/user/project/merge_requests/approvals/)
- [ ] [Set auto-merge](https://docs.gitlab.com/user/project/merge_requests/auto_merge/)

## Test and Deploy

Use the built-in continuous integration in GitLab.

- [ ] [Get started with GitLab CI/CD](https://docs.gitlab.com/ee/ci/quick_start/)
- [ ] [Analyze your code for known vulnerabilities with Static Application Security Testing (SAST)](https://docs.gitlab.com/ee/user/application_security/sast/)
- [ ] [Deploy to Kubernetes, Amazon EC2, or Amazon ECS using Auto Deploy](https://docs.gitlab.com/ee/topics/autodevops/requirements.html)
- [ ] [Use pull-based deployments for improved Kubernetes management](https://docs.gitlab.com/ee/user/clusters/agent/)
- [ ] [Set up protected environments](https://docs.gitlab.com/ee/ci/environments/protected_environments.html)

***

# Editing this README

When you're ready to make this README your own, just edit this file and use the handy template below (or feel free to structure it however you want - this is just a starting point!). Thanks to [makeareadme.com](https://www.makeareadme.com/) for this template.

## Suggestions for a good README

Every project is different, so consider which of these sections apply to yours. The sections used in the template are suggestions for most open source projects. Also keep in mind that while a README can be too long and detailed, too long is better than too short. If you think your README is too long, consider utilizing another form of documentation rather than cutting out information.

## Name
Choose a self-explaining name for your project.

## Description
Let people know what your project can do specifically. Provide context and add a link to any reference visitors might be unfamiliar with. A list of Features or a Background subsection can also be added here. If there are alternatives to your project, this is a good place to list differentiating factors.

## Badges
On some READMEs, you may see small images that convey metadata, such as whether or not all the tests are passing for the project. You can use Shields to add some to your README. Many services also have instructions for adding a badge.

## Visuals
Depending on what you are making, it can be a good idea to include screenshots or even a video (you'll frequently see GIFs rather than actual videos). Tools like ttygif can help, but check out Asciinema for a more sophisticated method.

## Installation
Within a particular ecosystem, there may be a common way of installing things, such as using Yarn, NuGet, or Homebrew. However, consider the possibility that whoever is reading your README is a novice and would like more guidance. Listing specific steps helps remove ambiguity and gets people to using your project as quickly as possible. If it only runs in a specific context like a particular programming language version or operating system or has dependencies that have to be installed manually, also add a Requirements subsection.

## Usage
Use examples liberally, and show the expected output if you can. It's helpful to have inline the smallest example of usage that you can demonstrate, while providing links to more sophisticated examples if they are too long to reasonably include in the README.

## Support
Tell people where they can go to for help. It can be any combination of an issue tracker, a chat room, an email address, etc.

## Roadmap
If you have ideas for releases in the future, it is a good idea to list them in the README.

## Contributing
State if you are open to contributions and what your requirements are for accepting them.

For people who want to make changes to your project, it's helpful to have some documentation on how to get started. Perhaps there is a script that they should run or some environment variables that they need to set. Make these steps explicit. These instructions could also be useful to your future self.

You can also document commands to lint the code or run tests. These steps help to ensure high code quality and reduce the likelihood that the changes inadvertently break something. Having instructions for running tests is especially helpful if it requires external setup, such as starting a Selenium server for testing in a browser.

## Authors and acknowledgment
Show your appreciation to those who have contributed to the project.

## License
For open source projects, say how it is licensed.

## Project status
If you have run out of energy or time for your project, put a note at the top of the README saying that development has slowed down or stopped completely. Someone may choose to fork your project or volunteer to step in as a maintainer or owner, allowing your project to keep going. You can also make an explicit request for maintainers.
