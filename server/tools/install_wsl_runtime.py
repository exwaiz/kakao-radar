"""Compatibility entry point for the portable native Linux installer.

The installer is safe to re-run: it creates missing roles/databases and service
files, and never drops a database or removes application data.
"""
from install_pi_runtime import main

if __name__ == "__main__":
    main()
