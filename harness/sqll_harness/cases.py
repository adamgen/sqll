"""The result of one test case for one tool."""

from dataclasses import dataclass, field

PASS = "pass"
FAIL = "fail"
ERROR = "error"
SKIP = "skip"


@dataclass
class CaseResult:
    """status is "pass" only if all checks are true.

    "error" means that the harness or the tool did not complete the case,
    or that the harness cannot know the result of a check.
    "skip" means that the fixture tells the test to skip the case.
    tags give facts about the case that are not results, for example
    "needs_python".
    """

    id: str
    suite: str
    tool: str
    status: str
    checks: dict[str, bool] = field(default_factory=dict)
    reason: str = ""
    duration_ms: int = 0
    tags: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == PASS

    @property
    def skipped(self) -> bool:
        return self.status == SKIP
