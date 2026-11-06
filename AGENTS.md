# Repository Guidelines

## Project structure & module organization

Use `README.md`, `docs/INSTALLATION.md`, and `docs/USER_GUIDE.md` for project scope, installation, and usage. CLI, configuration, deployment recovery, exports, installation, and tests exist.

Current and planned layout:

- `install.sh`: Bash installer; `main.py`: Python CLI entry point.
- `sbmanager/core/`: state, configuration, routing, transactions, and backups.
- `sbmanager/inbound/`: REALITY, Hysteria2, and VLESS WebSocket.
- `sbmanager/egress/`: registry and protocol drivers, initially SOCKS5.
- `sbmanager/modules/`: users, bindings, exports, and certificates.
- `sbmanager/system/`: sing-box, systemd, networking, and logging.
- `config/`, `tests/`, and `docs/`: defaults, tests, and documentation.

## Build, test, and development commands

Run the CLI and tests with Python 3. Validate installer syntax without executing it:

- `bash -n install.sh`: check installer syntax without executing it.
- `python3 main.py`: launch the CLI on a supported Linux host.
- `python3 -m unittest discover -s tests -p 'test_*.py'`: run tests when available.
- `sbmanager`: installed user-facing command.

Test installation and service operations in disposable Debian/Ubuntu environments.

## Coding style & naming conventions

Use Python 3 for business logic and Bash for installation. Prefer Python's standard library. Use four-space Python indentation, `snake_case` functions/modules, `PascalCase` classes, and `UPPER_SNAKE_CASE` constants. Quote shell variable expansions. No formatter or linter is configured.

Keep CLI, protocol drivers, and state transactions separate. Generate configurations from business state.

## Testing guidelines

Tests use `unittest`; no coverage threshold is configured. Name files `test_*.py`. Cover authorization isolation, bindings, UDP blocking, invalid configurations, concurrency, and coordinated state/configuration rollback. Verify installation, repeat installation, upgrade failures, certificates, and client connectivity on supported systems.

## Commit & pull request guidelines

No Git history is available to establish conventions. Write concise English imperative commit subjects, such as `fix: install from main`. PRs should link relevant issues or requirements, explain behavior changes, and include validation results and sanitized CLI transcripts when useful.

The default delivery target is `main`. Feature branches are temporary working branches, not the final delivery destination. Commit and push only when authorized by the user. When branch-based work is required, merge into `main` and push it once authorized; remove the temporary local and remote branches when requested. If changes have not reached `main`, explicitly report that they have not yet been delivered to the main branch.

## Distribution & security requirements

Install and update directly from this repository's `main` branch. Do not create project Git tags, GitHub Releases, or release attachments. The installer accepts only `OWNER/REPOSITORY`. Resolve `main` to its current commit through GitHub's `git/ref/heads/main` API, download complete source over HTTPS from `codeload.github.com/OWNER/REPO/tar.gz/COMMIT`, and validate archive contents before extraction.

Fetch `install.sh` from `main`. Each invocation downloads current source and installs into a fresh directory under `/opt/sbmanager/builds/`, then switches `/opt/sbmanager/current`. Record the source commit in `.source-commit`; do not skip updates because a previous installation exists. No legacy installation layout compatibility is required. Continue downloading sing-box from its official GitHub Releases and verifying official digests. The supported sing-box range is 1.14.x.

Installation must prepare dependencies automatically and expose `sbmanager`; upgrades must preserve data and support rollback. Open the main menu after installation when an interactive terminal is available; let users select nodes explicitly instead of configuring all nodes by default. Do not describe unverified behavior as verified.

Protect sensitive files with `0600` and directories with `0700`. Never commit credentials or log complete sharing links. Validate before applying configurations, block unsupported UDP, and delegate ACME to sing-box.
