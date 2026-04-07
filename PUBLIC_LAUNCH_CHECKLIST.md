# Public Launch Checklist

This checklist covers what's done programmatically and what requires manual GitHub UI configuration.

## ✅ Already Complete

- [x] Code quality: MIT License, SECURITY.md, CODE_OF_CONDUCT.md, CONTRIBUTING.md
- [x] Documentation: Comprehensive README, ARCHITECTURE.md, docs/ folder
- [x] Testing: CI/CD pipeline (GitHub Actions), test suite
- [x] Repository: Issue templates, PR template, CODEOWNERS
- [x] Releases: v1.2.1 tag with release notes, RELEASE_PROCESS.md
- [x] Funding: FUNDING.md created for GitHub Sponsors
- [x] Screenshot: Dashboard screenshot added to README for better onboarding

## 📋 TODO: Manual GitHub UI Configuration

### 1. Repository Settings → General
Go to: https://github.com/thezolon/OkoNebo/settings

**About Section (right sidebar):**
- [ ] **Description**: "A self-hosted web interface for staying weather aware."
- [ ] **Website**: Leave blank (no dedicated site)
- [ ] **Topics**: Add these 12 tags:
  - `weather`
  - `dashboard`
  - `docker`
  - `self-hosted`
  - `python`
  - `weather-api`
  - `weatherapi`
  - `nws`
  - `ai-agent`
  - `mcp`
  - `home-assistant`
  - `homelab`

### 2. Repository Settings → Visibility
- [ ] Change repository visibility to **Public**

### 3. Repository Settings → Branch Protection Rules
Go to: https://github.com/thezolon/OkoNebo/settings/branches

- [ ] Click "Add rule"
- [ ] Branch name pattern: `main`
- [ ] Enable:
  - [x] Require a pull request before merging
  - [x] Require approvals (1 approval)
  - [x] Require status checks to pass (select `ci` workflow)
  - [x] Include administrators in restrictions (optional, for enforcement)

### 4. Repository Settings → Discussions
Go to: https://github.com/thezolon/OkoNebo/settings

- [ ] Scroll to "Features" section
- [ ] Enable **Discussions**
- [ ] This creates a Q&A space alongside Issues (great for community questions)

### 5. Optional: Social Preview Image
Go to: https://github.com/thezolon/OkoNebo/settings

- [ ] Under "Social preview", upload `docs/images/OkoNebo-ScreenCapture.png` as the preview image for social media shares

## 🚀 Post-Launch

After going public:
- [ ] Pin important issues/discussions
- [ ] Monitor new issues and provide timely responses
- [ ] Keep docs updated with user feedback
- [ ] Review pull requests promptly if you get contributions

## Notes

- **GitHub Sponsors**: Link is in FUNDING.md; no ongoing time commitment unless you want to actively promote it
- **Branch protection**: Will require PRs on `main`; you can approve your own PRs as repo owner
- **Discussions**: Great for "How do I...?" questions; Issues stay for bugs and features
- **CI badge**: Already in README; will update automatically as tests run
