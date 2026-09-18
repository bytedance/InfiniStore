import subprocess
import sys
from pathlib import Path


def test_help_exits():
    benchmark = Path(__file__).parents[1] / "infinistore" / "benchmark.py"
    runner = """
import runpy
import sys
import types

sys.modules["infinistore"] = types.ModuleType("infinistore")
sys.modules["torch"] = types.ModuleType("torch")
benchmark = sys.argv[1]
sys.argv = [benchmark, "--help"]
runpy.run_path(benchmark, run_name="__main__")
"""

    result = subprocess.run(
        [sys.executable, "-c", runner, str(benchmark)],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert "--rdma" in result.stdout
