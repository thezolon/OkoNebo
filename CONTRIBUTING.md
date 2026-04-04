# Contributing to OkoNebo

Thank you for your interest in contributing!  This project is MIT-licensed and welcomes issues and pull requests from the community.

## Ground Rules

- Be respectful and constructive.  See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- Search existing issues before opening a new one.
- One feature or fix per pull request — keep the diff reviewable.
- New PRs should not break the test harness (`bash scripts/test_harness.sh`).

## Development Setup

### Prerequisites
- Docker + Docker Compose (required)
- Python 3.11+ (optional, only for backend-only local development)

### Local quickstart

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

Open `http://localhost:8000` — the first-run wizard will appear on a new install.

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
python -m pytest tests/ -v

# Full harness (Docker required)
bash scripts/test_harness.sh

# Skip Docker steps
HARNESS_SKIP_DOCKER=1 bash scripts/test_harness.sh
```

All PRs are gated on CI (`.github/workflows/ci.yml`).  Failing CI blocks merge.

## Pull Request Process

1. Fork and create a branch: `git checkout -b feature/my-thing`.
2. Commit with clear messages referencing task IDs from [V1_0_EXECUTION_BOARD.md](V1_0_EXECUTION_BOARD.md) when applicable (`T5.4: Add Meteomatics adapter`).
3. Open a PR against `main`.
4. CI must pass.
5. At least one review approval from a maintainer is required to merge.

## Reporting Bugs

Open a [GitHub Issue](https://github.com/thezolon/OkoNebo/issues) and fill in the bug report template.  For security issues, see [SECURITY.md](SECURITY.md) instead.

## Feature Requests

Open an issue and describe:
- What you want to achieve.
- Whether you would like to implement it yourself.

Features that align with the [v1.0 Execution Board](V1_0_EXECUTION_BOARD.md) will be prioritised.
