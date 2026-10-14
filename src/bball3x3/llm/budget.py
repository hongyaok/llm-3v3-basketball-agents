class BudgetExceededError(RuntimeError):
    pass

# cumulative token/cost accounting with a hard stop
class BudgetTracker:
    def __init__(self, max_usd: float | None = None):
        self.max_usd = max_usd
        self.spent_usd = 0.0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.calls = 0

    def charge(self, cost_usd: float, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        self.spent_usd += cost_usd
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.calls += 1

    def check(self) -> None:
        if self.max_usd is not None and self.spent_usd >= self.max_usd:
            raise BudgetExceededError(
                f"spent ${self.spent_usd:.4f} of ${self.max_usd:.2f} budget"
            )
