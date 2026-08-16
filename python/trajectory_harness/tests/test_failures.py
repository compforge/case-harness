from trajectory_harness import llm_failure


def test_llm_failure_uses_common_dimensions():
    failure = llm_failure(
        "request",
        "timeout",
        code="deadline_exceeded",
        message="provider deadline exceeded",
    )

    assert failure.key == "llm.request.timeout"
    assert failure.to_dict() == {
        "kind": "llm",
        "phase": "request",
        "error_type": "timeout",
        "code": "deadline_exceeded",
        "message": "provider deadline exceeded",
    }
