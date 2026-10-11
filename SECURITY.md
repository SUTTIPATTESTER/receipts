# Security policy

receipts runs code that came from strangers. Security reports are therefore welcome and taken seriously.

## Reporting a vulnerability

Please **do not open a public issue** for a vulnerability.
Use GitHub's private reporting: **Security tab → "Report a vulnerability"** on this repository.

Helpful details: the version or commit, what you did, what you expected, and what happened.
A proof-of-concept receipt is ideal; it is, after all, the native format.

## What is in scope

- Escaping the sandbox, or reading anything outside the working tree from a receipt.
- Getting a receipt's output to break out of the PR comment (mention pings, markdown/HTML injection).
- Smuggling a forged `verdict.json` past `receipts render`.
- Path traversal in receipt files, overlays, embedded files or archive extraction.
- Making a PR influence the policy that governs it.
- Anything that lets PR code reach a write-scoped token.

Out of scope: the documented [known limitations](docs/threat-model.md#what-receipts-does-not-do)
(for example a receipt that passes but measures something meaningless), and the `local` sandbox,
which is documented as not being a security boundary.

## Supported versions

Only the latest `0.x` release receives fixes while the project is in alpha.

## Hardening checklist for adopters

See [docs/threat-model.md](docs/threat-model.md#hardening-checklist).
