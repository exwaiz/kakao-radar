"""Compatibility entry point for the Raspberry Pi profile configuration."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).with_name("configure_pi_profile.py")), run_name="__main__")
