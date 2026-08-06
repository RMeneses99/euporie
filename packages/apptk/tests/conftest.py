"""Configure test collection for the apptk package.

Adds this directory to ``sys.path`` so that sibling helper modules - such as
``helix_utils`` - can be imported by name from test modules.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
