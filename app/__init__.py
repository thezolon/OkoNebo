# Make app a proper Python package

# Single source of truth for the application version. main.py falls back to this
# when no OKONEBO_VERSION/APP_VERSION is set in the environment, which is the
# normal case for a self-hosted deployment. It previously fell back to a
# hardcoded literal that had drifted three releases behind, so the UI reported
# 1.3.0 on a 1.5.0 install.
__version__ = "1.5.0"
