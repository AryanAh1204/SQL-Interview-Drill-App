import numpy as np
import pandas as pd

from db import compare_results


def test_null_equality_passes():
    # Simulate a LAG result: first row of the partition is NULL in both frames.
    ref = pd.DataFrame({"month": ["jan", "feb", "mar"], "prev": [np.nan, 10.0, 20.0]})
    user = pd.DataFrame({"month": ["jan", "feb", "mar"], "prev": [np.nan, 10.0, 20.0]})
    passed, reason = compare_results(ref, user, ["month", "prev"], order_matters=True)
    assert passed is True, reason


def test_order_insensitive_shuffled_passes():
    ref = pd.DataFrame({"name": ["a", "b", "c"], "n": [1, 2, 3]})
    user = ref.iloc[[2, 0, 1]].reset_index(drop=True)  # same rows, shuffled
    passed, reason = compare_results(ref, user, ["name", "n"], order_matters=False)
    assert passed is True, reason


def test_order_sensitive_wrong_order_fails():
    ref = pd.DataFrame({"name": ["a", "b", "c"], "n": [1, 2, 3]})
    user = ref.iloc[[2, 0, 1]].reset_index(drop=True)  # same rows, different order
    passed, reason = compare_results(ref, user, ["name", "n"], order_matters=True)
    assert passed is False


def test_reporter_no_crash_on_nonidentifier_column():
    # Column name with a leading digit and a space -> itertuples renames it positionally.
    ref = pd.DataFrame({"country": ["x", "y"], "2024 gdp": [100, 200]})
    user = pd.DataFrame({"country": ["x", "y"], "2024 gdp": [100, 999]})
    passed, reason = compare_results(ref, user, ["country", "2024 gdp"], order_matters=True)
    assert passed is False
    assert reason  # non-empty reason, did not raise
