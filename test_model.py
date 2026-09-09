"""Smallest check that fails if the model pipeline breaks: run `uv run python test_model.py`."""
import json, subprocess, sys
from pathlib import Path
subprocess.run([sys.executable, "model.py"], check=True, capture_output=True)
d = json.loads(Path("site/data.json").read_text())
for f in ("pb95", "pb98", "on"):
    F = d["fuels"][f]; e = F["eval"]
    assert e["n_test"] > 100, f
    assert e["mae_model_gr"] < e["mae_naive_gr"], f"{f}: model no better than naive {e}"
    assert 0.3 < e["hit_rate"] < 1, f
    assert all(0 < p < 1 for p in F["passthrough"]) and F["passthrough"] == sorted(F["passthrough"]), f"{f} passthrough {F['passthrough']}"
    assert 3 < F["last_gross"] < 15, f
    pred = sum(F["beta"][k] * F["last_features"][k] for k in F["beta"])
    assert abs(pred) < 0.05, f"{f}: implausible next-day move {pred}"
for f in ("pb95", "on"):
    assert -0.1 < d["margins"][f]["current"] < 1.0, d["margins"][f]
print("ok")
