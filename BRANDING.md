# OkoNebo Branding

## Logo

The OkoNebo logo is a polar weather radar/compass design symbolizing the project's focus on real-time location-based weather data integration from multiple providers.

### Logo Files

- **Full Logo with Text**: `app/static/okonebo-logo.svg` (400x480px)
- **Icon Only**: `app/static/okonebo-icon.svg` (256x256px, scalable)
- **Design**: Eight-point compass with weather icons (sun, rain) and polar grid overlay
- **Colors**: Charcoal (#1a1a1a) on light background (#f5f5f5)
- **Symbolism**:
  - **Polar Grid**: Real-time data collection and localized weather patterns
  - **Compass Center**: Multi-provider convergence and deterministic fallback routing
  - **Weather Icons**: Sun and rain representing observation and alert capabilities
  - **Eight Points**: Full 360° environmental awareness

### Usage

#### Web Integration
- **Favicon**: All HTML pages include `<link rel="icon" type="image/svg+xml" href="okonebo-icon.svg">`
- **Branding Elements**: Dashboard and admin pages display compact compass icon in headers
- **Documentation**: Full logo displayed in README.md

#### Docker
- **Image Labels**: Dockerfile includes OCI-compliant metadata with branding:
  - `org.opencontainers.image.title="OkoNebo"`
  - `org.opencontainers.image.description`, `url`, `documentation`, etc.

#### Repository
- **GitHub Badges**: CI/CD workflow badges in README
- **Social**: Use `okonebo-logo.svg` for GitHub profile and releases

## Font & Typography

- **Logo Text**: Arial, sans-serif, letter-spacing: 2px
- **Project Name**: "OkoNebo" (always in full, no abbreviations in formal contexts)
- **Tagline**: "Self-hosted weather dashboard and local API"

## Color Palette

| Element | Color | Hex | Usage |
|---------|-------|-----|-------|
| Icon/Text | Charcoal | #1a1a1a | Primary foreground |
| Background | Off-white | #f5f5f5 | Logo background/fill |
| Grid | Light Gray | #e0e0e0 | Polar grid overlay |

## License

OkoNebo is distributed under the MIT License. Logo is part of the project and subject to the same license.
