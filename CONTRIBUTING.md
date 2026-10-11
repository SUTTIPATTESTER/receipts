# Contributing

Thank you for helping! This project asks contributors to do exactly what it asks of everyone else:
**bring a receipt.**

## Quick start

```bash
git clone https://github.com/SUTTIPATTESTER/receipts && cd receipts
python -m unittest discover -s tests -t .      # needs Python 3.11+, no dependencies
PYTHONPATH=src python -m receipts bench        # the benchmark
```

## Bug reports

Use the bug template and paste a `receipt` block. `receipts init --kind bug` writes one for you.
A report that reproduces on `main` skips the queue.

## Pull requests

1. Add a test that **fails before** your change and **passes after** it.
2. Describe it in `.receipts/<name>.toml` (`receipts init --kind fix`) and run `receipts lint` on it.
3. If you change verifier behaviour, add or update a case under `bench/cases/`. A case is a directory with
   `case.toml` (`expect = "<verdict>"`), a `base/` tree, and a `head/` tree or `receipt.toml`.
4. Keep the core dependency-free. If you think you need a dependency, open an issue first.

## Using AI tools

Welcome. Contributions written with Codex, Claude, Copilot and friends are judged exactly like any other:
by whether the receipt verifies and whether a human maintainer finds the change sound.
You remain responsible for what you submit.

## Security issues

Please follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
