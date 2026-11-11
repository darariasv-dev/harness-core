from harness_core.failures import Budget, FailureClass, classify_headless_failure


class _FakeExc(Exception):
    def __init__(self, message, likely_quota_exhausted=False):
        super().__init__(message)
        self.likely_quota_exhausted = likely_quota_exhausted


def test_classify_quota_exhausted_first():
    exc = _FakeExc("some timeout-looking text", likely_quota_exhausted=True)
    assert classify_headless_failure(exc) == FailureClass.RATE_LIMITED


def test_classify_timeout():
    assert classify_headless_failure(_FakeExc("headless call timed out")) == FailureClass.TIMEOUT


def test_classify_invalid_response():
    assert classify_headless_failure(_FakeExc("missing required key: foo")) == FailureClass.INVALID_RESPONSE
    assert classify_headless_failure(_FakeExc("bad json schema")) == FailureClass.INVALID_RESPONSE


def test_classify_unavailable_fallback():
    assert classify_headless_failure(_FakeExc("connection refused")) == FailureClass.UNAVAILABLE


def test_budget_decrements_only_on_success():
    budget = Budget(total=2)
    assert budget.has_remaining()
    budget.record_failure(FailureClass.TIMEOUT)
    assert budget.remaining == 2
    budget.record_success()
    assert budget.remaining == 1
    budget.record_success()
    assert budget.remaining == 0
    assert not budget.has_remaining()


def test_budget_raises_past_exhaustion():
    budget = Budget(total=1)
    budget.record_success()
    try:
        budget.record_success()
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
