"""
Entry point for `python3 -m adwi.simlab`.

Usage:
    python3 -m adwi.simlab --full            # full session (all scenarios)
    python3 -m adwi.simlab --nightly         # nightly mode (70% fraction)
    python3 -m adwi.simlab --budget 30       # cap to 30 minutes
"""

from adwi.simlab.idle_orchestrator import _cli_main

_cli_main()
