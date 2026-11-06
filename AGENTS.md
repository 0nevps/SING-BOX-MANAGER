# Repository Guidelines

## Project structure & module organization

The project has an implementation awaiting Linux acceptance. The local, Git-ignored `Sing-Box Manager.md` contains the V1 requirements; public contributors should use `README.md` and `docs/VALIDATION.md` for published scope and outstanding checks. CLI, configuration, deployment recovery, exports, installation, and tests exist.

Current and planned layout:

- `install.sh`: Bash installer; `main.py`: Python CLI entry point.
- `sbmanager/core/`: state, configuration, routing, transactions, and backups.
- `sbmanager/inbound/`: REALITY, Hysteria2, and VLESS WebSocket.
- `sbmanager/egress/`: registry and protocol drivers, initially SOCKS5.
- `sbmanager/modules/`: users, bindings, exports, and certificates.
- `sbmanager/system/`: sing-box, systemd, networking, and logging.
- `config/`, `tests/`, and `docs/`: defaults, tests, and documentation.

## Build, test, and development commands

Run the current preview and tests with Python 3. Validate installer syntax without executing it:

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

No Git history is available to establish conventions. Write concise English imperative commit subjects, such as `Add release installer`. PRs should link relevant issues or requirements, explain behavior changes, and include validation results and sanitized CLI transcripts when useful.

## Release & security requirements

After Linux acceptance, publish versioned GitHub Releases with SHA-256 checksums. Document a real installation URL only after verification. Installation must prepare dependencies automatically and expose `sbmanager`; upgrades must preserve data and support rollback.

Protect sensitive files with `0600` and directories with `0700`. Never commit credentials or log complete sharing links. Validate before applying configurations, block unsupported UDP, and delegate ACME to sing-box.
