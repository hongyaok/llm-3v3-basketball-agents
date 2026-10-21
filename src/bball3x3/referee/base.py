from typing import Protocol

from ..schemas.referee import RefereeDecision, RefereeState


# anything that judges a resolved state: the rule-based or the llm referee
class Referee(Protocol):
    def judge(self, state: RefereeState) -> RefereeDecision: ...
