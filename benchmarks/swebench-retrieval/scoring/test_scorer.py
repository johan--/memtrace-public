"""
Unit tests for the SWE-bench retrieval scorer.

Run from the benchmark folder root:
    .venv/bin/python -m scoring.test_scorer
or under pytest if installed:
    .venv/bin/pytest scoring/test_scorer.py -v

No network. No API. Tests run against in-memory fixtures plus one real
Verified instance pulled from the pinned parquet.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from scoring.scorer import (
    bootstrap_ci,
    gold_files_from_patch,
    per_instance_hit,
    per_instance_recall,
    score_row,
    wilson_ci,
)


# ---------- gold extraction ----------

FIXTURE_PATCH_BASIC = """\
diff --git a/django/db/models/query.py b/django/db/models/query.py
index 1234567..89abcde 100644
--- a/django/db/models/query.py
+++ b/django/db/models/query.py
@@ -100,7 +100,7 @@
-    return None
+    return value
diff --git a/django/db/models/manager.py b/django/db/models/manager.py
index aaaaaa..bbbbbb 100644
--- a/django/db/models/manager.py
+++ b/django/db/models/manager.py
@@ -200,3 +200,4 @@
+    new_line
"""

FIXTURE_PATCH_RENAME = """\
diff --git a/old/path.py b/new/path.py
similarity index 99%
rename from old/path.py
rename to new/path.py
--- a/old/path.py
+++ b/new/path.py
"""

FIXTURE_PATCH_CREATE = """\
diff --git a/brand_new.py b/brand_new.py
new file mode 100644
--- /dev/null
+++ b/brand_new.py
@@ -0,0 +1,3 @@
+import os
+print(os.path)
"""

FIXTURE_PATCH_DELETE = """\
diff --git a/legacy.py b/legacy.py
deleted file mode 100644
--- a/legacy.py
+++ /dev/null
@@ -1,3 +0,0 @@
-import os
-print(os.path)
"""


def test_gold_basic_two_files() -> None:
    gold = gold_files_from_patch(FIXTURE_PATCH_BASIC)
    assert gold == frozenset({"django/db/models/query.py", "django/db/models/manager.py"})


def test_gold_rename_captures_both() -> None:
    gold = gold_files_from_patch(FIXTURE_PATCH_RENAME)
    assert "old/path.py" in gold
    assert "new/path.py" in gold


def test_gold_create_drops_dev_null() -> None:
    gold = gold_files_from_patch(FIXTURE_PATCH_CREATE)
    assert gold == frozenset({"brand_new.py"})


def test_gold_delete_drops_dev_null() -> None:
    gold = gold_files_from_patch(FIXTURE_PATCH_DELETE)
    assert gold == frozenset({"legacy.py"})


def test_gold_empty_patch() -> None:
    assert gold_files_from_patch("") == frozenset()
    assert gold_files_from_patch(None) == frozenset()  # type: ignore[arg-type]


# ---------- recall ----------

def test_recall_perfect() -> None:
    gold = frozenset({"a.py", "b.py"})
    retrieved = frozenset({"a.py", "b.py", "c.py"})
    assert per_instance_recall(gold, retrieved) == 1.0
    assert per_instance_hit(gold, retrieved) is True


def test_recall_partial() -> None:
    gold = frozenset({"a.py", "b.py"})
    retrieved = frozenset({"a.py", "c.py"})
    assert per_instance_recall(gold, retrieved) == 0.5
    assert per_instance_hit(gold, retrieved) is False


def test_recall_zero() -> None:
    gold = frozenset({"a.py"})
    retrieved = frozenset({"x.py"})
    assert per_instance_recall(gold, retrieved) == 0.0
    assert per_instance_hit(gold, retrieved) is False


def test_recall_empty_gold_returns_zero() -> None:
    assert per_instance_recall(frozenset(), frozenset({"a.py"})) == 0.0
    assert per_instance_hit(frozenset(), frozenset({"a.py"})) is False


# ---------- Wilson CI ----------

def test_wilson_known_value() -> None:
    # 60% (15/25) — matches the slide's headline number. Reference value from
    # the standard Wilson interval: 40.7% to 76.6% per online calculators.
    ci = wilson_ci(15, 25)
    assert ci.point == 0.6
    assert abs(ci.low - 0.4071) < 0.005
    assert abs(ci.high - 0.7659) < 0.005
    assert ci.n == 25


def test_wilson_zero_n() -> None:
    ci = wilson_ci(0, 0)
    assert ci.point == 0.0 and ci.low == 0.0 and ci.high == 0.0


def test_wilson_88_percent_n25() -> None:
    # 22/25 = 88% — our Memtrace target band. CI should be roughly [70, 96].
    ci = wilson_ci(22, 25)
    assert abs(ci.point - 0.88) < 1e-9
    assert 0.68 < ci.low < 0.72
    assert 0.95 < ci.high < 0.97


# ---------- bootstrap CI ----------

def test_bootstrap_all_ones() -> None:
    ci = bootstrap_ci([1.0] * 25)
    assert ci.point == 1.0
    assert ci.low == 1.0 and ci.high == 1.0


def test_bootstrap_seed_determinism() -> None:
    vals = [0.0, 0.5, 1.0, 0.25, 0.75, 0.5, 1.0, 0.0, 1.0, 0.5]
    a = bootstrap_ci(vals, seed=42)
    b = bootstrap_ci(vals, seed=42)
    assert a.low == b.low and a.high == b.high


# ---------- end-to-end on a real Verified instance ----------

def test_real_verified_instance() -> None:
    """Pull one Verified instance from the pinned parquet, fabricate a
    perfect-retrieval row, verify scoring gives hit-rate=1.0."""
    parquet = Path(__file__).parent.parent / "data" / "verified_500.parquet"
    assert parquet.exists(), "data/verified_500.parquet missing — run 05_repro.sh sample"

    df = pd.read_parquet(parquet)
    # Take the first 3 instances for a tiny end-to-end check.
    sample = df.head(3).copy()
    rows = []
    for _, row in sample.iterrows():
        gold = gold_files_from_patch(row["patch"])
        rows.append({"instance_id": row["instance_id"], "retrieved_files": sorted(gold)})
    per_instance = pd.DataFrame(rows)

    score, detail = score_row("test-oracle", per_instance, sample)
    assert score.hit_rate.point == 1.0, f"expected oracle hit-rate 1.0, got {score.hit_rate}"
    assert (detail["hit"]).all()
    assert len(detail) == 3


# ---------- test runner ----------

def _run_all() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERR  {fn.__name__}: {type(e).__name__}: {e}")
    total = len(tests)
    print(f"\n{total - failed}/{total} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_all())
