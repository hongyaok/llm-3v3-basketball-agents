# Basketball Simulation Engine (WS1)

## Overview

This directory contains the core simulation engine for the 3v3 basketball multi-agent project.

The engine manages court geometry, random events, game state, clocks, action validation, basketball outcomes, and rule enforcement.

The implementation reuses the shared Pydantic schemas defined in `bball3x3.schemas` and configuration models defined in `bball3x3.config`.

## 1. Implemented Modules

### `court.py` — Court Geometry

Implements the `Court` class and predefined court zones.

Features:
- Validates player positions against court boundaries.
- Calculates distances between positions in metres.
- Calculates distance from a position to the basket.
- Determines whether a position is beyond the two-point arc.
- Determines whether a shot is worth one or two points.
- Provides predefined positions for court zones such as TOP, LEFT_WING, RIGHT_WING, PAINT, and LEFT_BLOCK.

Uses `CourtConfig` from `config.py`.

Tests: `tests/test_court.py`.

### `rng.py` — Reproducible Randomness

Implements the `GameRNG` class using NumPy random generators and `SeedSequence`.

Features:
- Creates independent random streams for shooting, passing, driving, rebounding, contact, free throws, and first possession.
- Supports deterministic simulations using fixed seeds.
- Provides random sampling, Bernoulli trials, and random choice.
- Ensures consuming randomness from one stream does not affect another stream.

Main methods:
- `GameRNG.from_seed(seed)`
- `rng.random(stream)`
- `rng.bernoulli(stream, probability)`
- `rng.choice(stream, options)`

Tests: `tests/test_rng.py`.

### `state.py` — Game State Management

Implements initialization and basic state transitions using the existing `GameState`, `PlayerState`, and `BallState` schemas.

Features:
- Initializes three players for each team.
- Assigns initial player positions and defensive matchups.
- Selects the first offensive team.
- Initializes scores, team fouls, game clock, and shot clock.
- Assigns ball possession to a player.
- Switches offensive possession and resets the shot clock.
- Updates player positions and ball position.

Main functions:
- `create_initial_state(config, rng, first_possession=None)`
- `set_ball_holder(state, player_id)`
- `switch_possession(state, new_offense, config, needs_clear=True)`
- `move_player(state, player_id, new_pos, court)`

Current limitations:
- Initial positions and player IDs are hardcoded as A1–A3 and B1–B3.
- Player roster configuration and abilities are not yet integrated.
- Possession changes leave the ball loose until a subsequent event assigns a holder.

Tests: `tests/test_engine_state.py`.

### `clock.py` — Game and Shot Clocks

Implements time progression for simulated basketball actions.

Features:
- Supports a 600-second regulation game clock.
- Supports a 12-second shot clock.
- Uses configurable action durations.
- Advances clocks without allowing negative values.
- Stops clocks during dead-ball and free-throw phases.
- Supports overtime without decrementing the regulation clock.
- Provides shot-clock reset and expiration checks.

Main functions:
- `get_action_duration(action, config)`
- `advance_clocks(state, elapsed_s)`
- `advance_action_clock(state, action, config)`
- `reset_shot_clock(state, config)`
- `is_shot_clock_violation(state)`
- `is_regulation_expired(state)`

Important: Clock expiration does not automatically cause a turnover or end the game. These decisions must be handled by the rules engine.

Tests: `tests/test_clock.py`.

### `actions.py` — Action Validation and Remapping

Implements legal-action checks and deterministic fallbacks for invalid agent proposals.

Features:
- Supports all 24 actions defined in `schemas/actions.py`.
- Separates actions into ball-holder, off-ball offense, and defensive categories.
- Checks action legality based on team possession and player role.
- Validates player targets for passes, screens, and defensive actions.
- Prevents shooting before the ball is cleared.
- Remaps invalid actions to `HOLD`.
- Records invalid-action reasons using the existing `RemappedAction` schema.

Main functions:
- `get_legal_actions(state, player_id)`
- `validate_action(state, proposal)`
- `remap_invalid_action(state, proposal)`

Current limitations:
- Detailed movement feasibility and defender proximity checks are not implemented.
- `SWITCH` target semantics need to be agreed upon.
- Action timing and physical outcomes must be integrated with the resolver and rules modules.

Tests: `tests/test_engine_actions.py`.

## 2. Remaining WS1 Modules

| Module | Responsibility |
|---|---|
| `shot_quality.py` | Calculate shot quality, contest effects, and scoring probabilities |
| `resolvers.py` | Resolve shooting, passing, driving, rebounds, and other action outcomes |
| `contact.py` | Simulate physical contact and foul events |
| `rules.py` | Enforce 3x3 rules, possession changes, fouls, scoring, and game completion |
| `invariants.py` | Check state consistency and prevent invalid simulation states |

These modules should reuse the existing engine interfaces wherever possible.

## 3. Running Tests

From the repository root:

```powershell
uv run pytest tests/test_court.py tests/test_rng.py tests/test_engine_state.py tests/test_clock.py tests/test_engine_actions.py -v
```

To run the entire project test suite:

```powershell
uv run pytest -v
```

Tests should be run after integrating the remaining WS1 modules.

## 4. Integration Notes

- `schemas/state.py` defines the shared game-state data structures.
- `schemas/actions.py` defines action proposals and remapping records.
- `config.py` provides simulation configuration.
- `court.py` provides geometry utilities for action resolution.
- `rng.py` provides reproducible random streams for probabilistic outcomes.
- `state.py` provides state initialization and basic mutations.
- `clock.py` advances simulation time but does not apply referee decisions.
- `actions.py` validates agent proposals before they reach the resolver.

**Important:** These modules provide foundational functionality but do not yet constitute a complete playable simulation.

## 5. Remaining Integration and Validation Work

After implementing the remaining five modules:

1. Integrate the action resolver with the game-state and clock modules.
2. Implement scoring, fouls, clearing, turnovers, and possession transitions.
3. Integrate player abilities from the configured team rosters.
4. Connect the engine to heuristic and LLM agents.
5. Run complete simulated games.
6. Verify deterministic replay with fixed random seeds.
7. Run 1,000 random-agent games and verify zero invariant violations.

The final WS1 implementation should support a complete 3v3 basketball game under the project's simulation rules.
