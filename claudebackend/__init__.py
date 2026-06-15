"""ClaudeBackend — universal multi-agent backend development system.

A deterministic Planner -> Coder -> Verifier pipeline that takes an arbitrary
objective (e.g. "Add JWT authentication") and implements it on a new git branch.
"""

import logging

__version__ = "0.3.0"

# Library best practice: attach a no-op handler so importing the package never
# configures logging or emits output. Applications (the CLI) opt in to a real
# handler via claudebackend.cli._configure_logging.
logging.getLogger("claudebackend").addHandler(logging.NullHandler())
