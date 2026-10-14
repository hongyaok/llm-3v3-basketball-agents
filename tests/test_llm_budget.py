import pytest

from bball3x3.llm.budget import BudgetExceededError, BudgetTracker


def test_budget_accumulates_cost_and_tokens():
    budget = BudgetTracker(max_usd=1.0)
    budget.charge(0.25, prompt_tokens=100, completion_tokens=20)
    budget.charge(0.5, prompt_tokens=50, completion_tokens=10)
    assert budget.spent_usd == pytest.approx(0.75)
    assert budget.prompt_tokens == 150
    assert budget.completion_tokens == 30
    assert budget.calls == 2


def test_budget_check_raises_once_limit_reached():
    budget = BudgetTracker(max_usd=0.5)
    budget.check()  # under budget: no error
    budget.charge(0.5)
    with pytest.raises(BudgetExceededError):
        budget.check()


def test_budget_without_limit_never_raises():
    budget = BudgetTracker(max_usd=None)
    budget.charge(1_000_000.0)
    budget.check()
