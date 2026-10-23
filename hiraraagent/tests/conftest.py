from __future__ import annotations

import os
import tempfile

# The service builds its Toolset at import; point it at a throwaway database
# before any test imports it, so the suite never touches ~/.hirara.
os.environ.setdefault("HG_DB", os.path.join(tempfile.mkdtemp(prefix="hiraraagent-test-"), "agent.db"))
