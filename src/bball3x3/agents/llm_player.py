"""LLMPlayer agent and DecisionResult container (WS3 §3.5)."""

from __future__ import annotations

from dataclasses import dataclass, field

from bball3x3.agents.filtering import SuppressedItems, apply_flags
from bball3x3.agents.observation import Observation
from bball3x3.agents.prompting import PromptBuilder
from bball3x3.agents.xml_io import (
    RESPONSE_JSON_SCHEMA,
    ParseContext,
    make_json_parser,
    make_xml_parser,
)
from bball3x3.config import LLMPlayersConfig, PlayerProfileConfig
from bball3x3.llm.base import LLMBackend, LLMResponse
from bball3x3.llm.repair import complete_with_repair
from bball3x3.schemas.agent import AgentOutput, CoordinationConfig

PARSE_FAIL_PLACEHOLDER = "__PARSE_FAIL__"


@dataclass
class DecisionResult:
    """Complete record of one player's LLM decision, including repair attempts and filtering."""

    output: AgentOutput
    kept: AgentOutput
    suppressed: SuppressedItems
    observation_text: str
    raw_attempts: list[str] = field(default_factory=list)
    responses: list[LLMResponse] = field(default_factory=list)
    prompt_hash: str = ""

    @property
    def prompt_tokens(self) -> int:
        return sum(r.prompt_tokens for r in self.responses)

    @property
    def completion_tokens(self) -> int:
        return sum(r.completion_tokens for r in self.responses)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.responses)

    @property
    def latency_ms(self) -> float:
        return sum(r.latency_ms for r in self.responses)

    @property
    def repaired(self) -> bool:
        return len(self.responses) > 1


class LLMPlayer:
    """Async LLM-driven 3x3 player agent."""

    def __init__(
        self,
        player_id: str,
        llm: LLMBackend,
        params: LLMPlayersConfig | None = None,
        *,
        prompt_builder: PromptBuilder | None = None,
        profile: PlayerProfileConfig | None = None,
        flags: CoordinationConfig | None = None,
        is_captain: bool = False,
    ) -> None:
        self.player_id = player_id.upper()
        self.team = self.player_id[:1]
        self.llm = llm
        self.params = params or LLMPlayersConfig()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.profile = profile
        self.flags = flags or CoordinationConfig()
        self.is_captain = is_captain

    async def decide(self, obs: Observation) -> DecisionResult:
        """Render prompts, call LLM with repair, and filter by coordination flags."""
        msgs, obs_text, p_hash = self.prompt_builder.build(
            obs,
            profile=self.profile,
            output_format=self.params.output_format,
            include_rationale=self.params.include_rationale,
        )

        ctx = ParseContext(
            player_id=self.player_id,
            known_memory_ids=frozenset(m.id.upper() for m in obs.shared_memory),
            known_cs_keys=frozenset(c.key for c in obs.cs_table),
        )

        if self.params.output_format == "json":
            parser = make_json_parser(ctx)
            resp_fmt = RESPONSE_JSON_SCHEMA
        else:
            parser = make_xml_parser(ctx)
            resp_fmt = None

        repair_res = await complete_with_repair(
            self.llm,
            msgs,
            self.params,
            parser,
            response_format=resp_fmt,
        )

        raw_attempts = [r.text for r in repair_res.responses]
        if not repair_res.ok:
            failed_output = AgentOutput(
                action=PARSE_FAIL_PLACEHOLDER,
                target=None,
                raw_text=raw_attempts[-1] if raw_attempts else "",
                parse_ok=False,
                parse_errors=list(repair_res.errors),
            )
            return DecisionResult(
                output=failed_output,
                kept=failed_output,
                suppressed=SuppressedItems(),
                observation_text=obs_text,
                raw_attempts=raw_attempts,
                responses=repair_res.responses,
                prompt_hash=p_hash,
            )

        kept, suppressed = apply_flags(
            repair_res.parsed,
            obs.coordination_flags,
            obs.is_captain,
        )
        return DecisionResult(
            output=repair_res.parsed,
            kept=kept,
            suppressed=suppressed,
            observation_text=obs_text,
            raw_attempts=raw_attempts,
            responses=repair_res.responses,
            prompt_hash=p_hash,
        )
