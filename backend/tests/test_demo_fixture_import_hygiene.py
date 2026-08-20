"""A production worker must never parse the demo fixture module.

``app/core/seed.py`` is the fictional tenant_acme dataset. It is only ever
needed when ``SEED_DEMO_DATA`` is on and the environment is not production-like,
so ``app/main.py`` imports it inside that branch rather than at module scope.
main.py is its only app-side importer, so that one lazy import is what keeps it
out of a production process entirely.

The regression this guards is silent: an import-sorter, an IDE "organize
imports", or a careless edit hoists ``from app.core.seed import seed_database``
back to the top of main.py and nothing fails. Hence the assert.

Runs in a subprocess because the check is "did importing app.main pull it in",
and other tests in the same session import app.core.seed directly.
"""
import os
import subprocess
import sys

import pytest

_PROBE = (
    "import sys; import app.main; "
    "print('LOADED' if 'app.core.seed' in sys.modules else 'ABSENT')"
)


@pytest.mark.timeout(120)
def test_importing_main_does_not_load_demo_fixtures():
    # Inherit the real environment (site-packages resolution depends on it) and
    # only pin the settings app.core.config requires at import time.
    env = {
        **os.environ,
        "SECRET_KEY": "ci-test-secret-key-do-not-use-in-production",
        "DEV_MODE": "true",
        "ENVIRONMENT": "ci",
    }
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True, text=True, timeout=110, env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert proc.returncode == 0, f"import app.main failed:\n{proc.stderr[-2000:]}"
    assert "ABSENT" in proc.stdout, (
        "app.core.seed (the 62KB demo fixture module) was imported just by "
        "importing app.main. Keep `from app.core.seed import seed_database` "
        "inside the SEED_DEMO_DATA branch of the lifespan, not at module scope."
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
