# OkoNebo Branding

## Canonical Source

- Source artwork: `OKONEBO.svg` (root of repository)
- Authoring tool: Adobe Illustrator (user-provided export)

## Runtime Asset Paths

- Full logo: `app/static/okonebo-logo.svg`
- Icon/favicons/header mark: `app/static/okonebo-icon.svg`

Both runtime asset paths are intentionally kept in sync with `OKONEBO.svg` so existing HTML references continue to work without further code changes.

## Usage

### Web Integration

- Favicon path: `okonebo-icon.svg`
- Header icon path: `okonebo-icon.svg`
- README image path: `app/static/okonebo-logo.svg`

### Docker Metadata

Docker image OCI labels in `Dockerfile` remain the source for project branding metadata (`title`, `description`, `url`, `documentation`, `source`, `version`).

## License

OkoNebo is distributed under the MIT License. Logo assets in this repository are part of the project.
