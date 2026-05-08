"""PHANTOM launcher.

Keeps the old entrypoint working while the application lives in src/phantom.
"""
from src.phantom.app.main import main


if __name__ == "__main__":
    main()
