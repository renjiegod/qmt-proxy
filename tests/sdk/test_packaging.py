import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SDK_ROOT = PROJECT_ROOT / "libs" / "qmt_proxy_sdk"
SDK_PARENT = SDK_ROOT.parent


def test_sdk_has_standalone_pyproject():
    assert (SDK_ROOT / "pyproject.toml").exists(), "Standalone SDK package must define its own pyproject.toml"


def test_sdk_can_import_without_repo_root_on_pythonpath(tmp_path):
    script = (
        "import qmt_proxy_sdk; "
        "from qmt_proxy_sdk.models import AccountType, MarketDataResponse; "
        "print(qmt_proxy_sdk.__name__); "
        "print(AccountType.SECURITY.value); "
        "print(MarketDataResponse.__name__)"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SDK_PARENT)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines() == [
        "qmt_proxy_sdk",
        "SECURITY",
        "MarketDataResponse",
    ]
