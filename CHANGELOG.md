# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0] - 2026-10-11

First public alpha.

### Added
- Receipt format v1 (`spec/RECEIPT.md`): `bug` and `fix` receipts in TOML.
- Verifier with eleven verdicts, fail-to-pass semantics and anti-cheat rules
  (failure signature required for bugs and never echoed by the command, a PR must change more than its receipt).
- Docker sandbox (no network, no capabilities, read-only root, resource limits) and an opt-in local sandbox for trusted input.
- Maintainer policy read only from the base branch.
- Two-workflow GitHub Action pattern: an unprivileged verifier and a privileged reporter that never runs PR code.
- `receipts` CLI: `verify`, `extract`, `init`, `lint`, `render`, `bench`.
- Benchmark corpus of 19 cases, including two documented known limitations.
