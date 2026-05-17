# Benchmarking

Nulm now includes a repeatable benchmark command to measure indexing and relevance regressions.

## Quick Usage

```bash
nulm benchmark --project-dir . --path src --query "auth session login"
```

For machine-readable output:

```bash
nulm benchmark --project-dir . --path src --query "auth session login" --json
```

To run with a profile file:

```bash
nulm benchmark --project-dir /path/to/repo --profile-file benchmarks/profiles/django_auth.json
```

## Baseline Comparison

If you provide a baseline file, the command checks duration, minimum file count, and expected top ranks:

```bash
nulm benchmark \
  --project-dir . \
  --path src \
  --query "login auth session" \
  --baseline-file benchmarks/example_baseline.json
```

When using a profile, `baseline_file` can also be automatically loaded from within the profile.

## What Is Measured

- Initial indexing duration
- Repeated relevance query durations
- Parser backends used
- Top-ranked results

## Practical Tips

- Run the same benchmark regularly across a few large repositories.
- Track variants with and without Tree-sitter installed separately.
- Add queries from real bug reports to your golden dataset.
- Populate the open-source repository profiles under `benchmarks/profiles/` with your local clones and update baselines with real measurements.
