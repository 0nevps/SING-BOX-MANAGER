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

No Git history is available to establish conventions. Write concise English imperative commit subjects, such as `fix: install from Git tags`. PRs should link relevant issues or requirements, explain behavior changes, and include validation results and sanitized CLI transcripts when useful.

## Versioning & security requirements

Version this project with Git tags only; do not create GitHub Releases or project release attachments. The installer accepts an optional `vMAJOR.MINOR.PATCH` tag. Without one, select the highest semantic version from GitHub's `git/matching-refs/tags/v` API. Resolve lightweight and annotated tags to commits, download source over HTTPS from `codeload.github.com/OWNER/REPO/tar.gz/COMMIT`, and validate archive contents before extraction. Do not require project `SHA256SUMS` files or local release packaging.

Installation commands should fetch `install.sh` from `main`, even when selecting a source tag such as `v0.1.0`; historical tags do not necessarily contain later installer changes. Continue downloading sing-box from its official GitHub Releases and verifying official digests. Keep compatibility with the local `/opt/sbmanager/releases/` directory; its name does not imply GitHub Releases. The supported sing-box range is 1.14.x.

Installation must prepare dependencies automatically and expose `sbmanager`; upgrades must preserve data and support rollback. Open the main menu after installation when an interactive terminal is available; let users select nodes explicitly instead of configuring all nodes by default. Do not describe unverified behavior as verified.

Protect sensitive files with `0600` and directories with `0700`. Never commit credentials or log complete sharing links. Validate before applying configurations, block unsupported UDP, and delegate ACME to sing-box.
