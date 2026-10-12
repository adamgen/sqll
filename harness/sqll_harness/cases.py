"""The result of one test case for one tool."""

from dataclasses import dataclass, field

PASS = "pass"
FAIL = "fail"
ERROR = "error"
SKIP = "skip"


@dataclass
class CaseResult:
    """status is "pass" only if all checks are true.

    "error" means that the harness or the tool did not complete the case.
    "skip" means that the fixture tells the test to skip the case.
    """

    id: str
    suite: str
    tool: str
    status: str
    checks: dict[str, bool] = field(default_factory=dict)
    reason: str = ""
    duration_ms: int = 0

    @property
    def passed(self) -> bool:
        return self.status == PASS

    @property
    def skipped(self) -> bool:
        return self.status == SKIP
