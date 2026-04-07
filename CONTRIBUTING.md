# Contributing to OkoNebo

Thanks for your interest in contributing. OkoNebo is MIT-licensed and welcomes issues and pull requests.

**Project status**: OkoNebo is a solo-maintained hobby project. Issues and PRs are reviewed regularly, though response times may vary depending on other commitments. If you're interested in contributing, please be patient and understand that this is not a full-time effort.

## Ground Rules

- Be respectful and constructive.  See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- Search existing issues before opening a new one.
- One feature or fix per pull request. Smaller diffs are easier to review and merge.
- New PRs should not break the test harness (`bash scripts/test_harness.sh`).

## Development Setup

### Prerequisites
- Docker + Docker Compose (required)
- Python 3.11+ (optional, only for backend-only local development)

### Local Quickstart

```bash
# Clone the repo
git clone https://github.com/thezolon/OkoNebo.git
cd OkoNebo

# Copy and edit sample config
cp config.yaml.example config.yaml   # edit lat/lon at minimum

# Run the full test harness (venv created automatically)
bash scripts/test_harness.sh

# Optional: backend-only run for API debugging
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://localhost:8000`. On a fresh run, the first-run setup screen appears.

### Environment variables

Secrets can be passed via a `.env` file in the project root (never commit this file):

```
WEATHERAPI_API_KEY=your_key_here
TOMORROW_API_KEY=your_key_here
VISUALCROSSING_API_KEY=your_key_here
OWM_API_KEY=your_key_here
METEOMATICS_API_KEY=user:password
AUTH_TOKEN_SECRET=some-random-secret
```

All keys can also be entered through the in-app Setup panel and are encrypted at rest.

## Code Style

- **Python**: follow PEP 8; no line-length police, but keep lines sensible.
- **JavaScript**: vanilla ES2020 — no build step, no frameworks.
- **HTML/CSS**: semantic HTML5; CSS custom properties for theming.

## Testing

```bash
# Unit tests only (no Docker required)
source .venv-test/bin/activate
python -m unittest discover -s tests -p "test_*.py" -v

# Full harness (Docker required)
bash scripts/test_harness.sh

# Skip Docker steps
HARNESS_SKIP_DOCKER=1 bash scripts/test_harness.sh
```

All PRs are gated on CI (`.github/workflows/ci.yml`). Failing checks block merge.

## Documentation Maintenance

When adding or changing features, update docs in the same PR:

1. Update user-facing behavior in [README.md](README.md) and feature docs under [docs/](docs/README.md).
2. Update endpoint changes in [docs/api-reference.md](docs/api-reference.md).
3. Update implementation details in [docs/implementation.md](docs/implementation.md) when architecture/runtime behavior changes.
4. Run markdown link validation locally before pushing:

```bash
python scripts/check_markdown_links.py
```

## Pull Request Process

1. Fork and create a branch: `git checkout -b feature/my-thing`.
2. Commit with clear messages referencing the related [GitHub Issue](https://github.com/thezolon/OkoNebo/issues) when applicable (`fixes #42`).
3. Open a PR against `main`.
4. CI must pass.
5. At least one review approval from a maintainer is required to merge.

## Reporting Bugs

Open a [GitHub Issue](https://github.com/thezolon/OkoNebo/issues) and fill in the bug report template.  For security issues, see [SECURITY.md](SECURITY.md) instead.

## Feature Requests

Open an issue and include:
- What you want to achieve
- Whether you want to implement it yourself

Features tracked in [GitHub Issues](https://github.com/thezolon/OkoNebo/issues) will be prioritised.
