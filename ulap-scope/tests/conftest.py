import sys, json
from pathlib import Path
import pytest

# make the package importable without installation (also works after `pip install -e .`)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ulap_scope.config import load_config   # noqa: E402


def sionna_available() -> bool:
    try:
        import sionna.rt  # noqa: F401
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture(scope="session")
def manifest(cfg):
    if not cfg.manifest_path.exists():
        pytest.skip(f"manifest not built at {cfg.manifest_path}")
    return json.loads(cfg.manifest_path.read_text())


def pytest_configure(config):
    config.addinivalue_line("markers", "rt: integration test that requires the Sionna RT env")
