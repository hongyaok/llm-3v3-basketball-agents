"""Jinja2 prompt builder with StrictUndefined and template hashing (WS3 §3.3)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from bball3x3.agents.observation import Observation, render_observation
from bball3x3.config import CourtConfig, PlayerProfileConfig, RosterConfig
from bball3x3.engine.abilities import default_abilities
from bball3x3.engine.court import ZONES, Court
from bball3x3.schemas.agent import CoordinationConfig
from bball3x3.schemas.state import Abilities

DEFAULT_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
TEMPLATE_FILES = (
    "system.j2",
    "profile.j2",
    "captain_addendum.j2",
    "observation.j2",
    "instruction.j2",
)


def _court_zones_meta(court_cfg: CourtConfig | None = None) -> list[dict[str, object]]:
    court = Court(court_cfg or CourtConfig())
    out: list[dict[str, object]] = []
    for name, pos in ZONES.items():
        out.append({"name": name, "pos": pos, "points": court.shot_value(pos)})
    return out


def resolve_player_profile(
    player_id: str, roster: RosterConfig | None = None
) -> tuple[str, Abilities, str]:
    """Return (name, abilities, playstyle) for ``player_id`` (e.g. A1 -> P1)."""
    slot = f"P{player_id[1:]}"
    if roster is not None:
        for p in roster.players:
            if p.slot.upper() == slot.upper():
                return (
                    p.name or player_id,
                    p.abilities,
                    p.playstyle or "balanced two-way 3x3 player",
                )
    return (player_id, default_abilities(6), "balanced two-way 3x3 player")


class PromptBuilder:
    """Renders static system + dynamic user prompts and hashes template sources."""

    def __init__(
        self,
        prompts_dir: str | Path | None = None,
        *,
        roster: RosterConfig | None = None,
        court_config: CourtConfig | None = None,
    ) -> None:
        self.prompts_dir = Path(prompts_dir) if prompts_dir is not None else DEFAULT_PROMPTS_DIR
        self.roster = roster
        self.court_zones = _court_zones_meta(court_config)
        self.env = Environment(
            loader=FileSystemLoader(str(self.prompts_dir)),
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )
        self._sources_blob = self._read_all_sources()

    def _read_all_sources(self) -> str:
        parts: list[str] = []
        for fname in TEMPLATE_FILES:
            fpath = self.prompts_dir / fname
            content = fpath.read_text(encoding="utf-8")
            parts.append(f"=== {fname} ===\n{content}")
        return "\n".join(parts)

    @staticmethod
    def variant_key(
        flags: CoordinationConfig,
        is_captain: bool,
        output_format: Literal["xml", "json"] = "xml",
        include_rationale: bool = True,
    ) -> str:
        return (
            f"comms={int(flags.comms)}|captain={int(flags.captain)}|"
            f"memwrite={int(flags.memory_write)}|iscap={int(is_captain)}|"
            f"fmt={output_format}|rat={int(include_rationale)}"
        )

    def template_hash(
        self,
        flags: CoordinationConfig | None = None,
        *,
        is_captain: bool = False,
        output_format: Literal["xml", "json"] = "xml",
        include_rationale: bool = True,
    ) -> str:
        cfg = flags or CoordinationConfig()
        vkey = self.variant_key(cfg, is_captain, output_format, include_rationale)
        payload = f"{self._sources_blob}\n=== VARIANT ===\n{vkey}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def render_system(
        self,
        player_id: str,
        *,
        flags: CoordinationConfig | None = None,
        is_captain: bool = False,
        profile: PlayerProfileConfig | None = None,
        output_format: Literal["xml", "json"] = "xml",
        include_rationale: bool = True,
    ) -> str:
        cfg = flags or CoordinationConfig()
        team = player_id[:1].upper()
        opp_team = "B" if team == "A" else "A"
        teammates = sorted(
            f"{team}{i}" for i in (1, 2, 3) if f"{team}{i}" != player_id.upper()
        )
        opponents = [f"{opp_team}1", f"{opp_team}2", f"{opp_team}3"]

        if profile is not None:
            prof_name = profile.name or player_id
            abilities = profile.abilities
            playstyle = profile.playstyle or "balanced two-way 3x3 player"
        else:
            prof_name, abilities, playstyle = resolve_player_profile(player_id, self.roster)

        common_vars = {
            "player_id": player_id.upper(),
            "team": team,
            "teammates": teammates,
            "opponents": opponents,
            "court_zones": self.court_zones,
            "is_captain": is_captain,
            "comms_enabled": cfg.comms,
            "captain_enabled": cfg.captain,
            "memory_write_enabled": cfg.memory_write,
            "output_format": output_format,
            "include_rationale": include_rationale,
            "profile_name": prof_name,
            "abilities": abilities,
            "playstyle": playstyle,
        }

        sys_text = self.env.get_template("system.j2").render(**common_vars).strip()
        prof_text = self.env.get_template("profile.j2").render(**common_vars).strip()
        sections = [sys_text, prof_text]

        if is_captain and cfg.captain:
            cap_text = self.env.get_template("captain_addendum.j2").render(**common_vars).strip()
            sections.append(cap_text)

        return "\n\n".join(sections)

    def render_user(
        self,
        obs: Observation,
        *,
        observation_text: str | None = None,
        output_format: Literal["xml", "json"] = "xml",
        include_rationale: bool = True,
    ) -> tuple[str, str]:
        obs_str = observation_text if observation_text is not None else render_observation(obs)
        cfg = obs.coordination_flags
        user_vars = {
            "player_id": obs.player_id,
            "team": obs.team,
            "role": obs.role,
            "is_captain": obs.is_captain,
            "comms_enabled": cfg.comms,
            "captain_enabled": cfg.captain,
            "memory_write_enabled": cfg.memory_write,
            "output_format": output_format,
            "include_rationale": include_rationale,
            "observation_text": obs_str,
        }
        obs_rendered = self.env.get_template("observation.j2").render(**user_vars).strip()
        inst_rendered = self.env.get_template("instruction.j2").render(**user_vars).strip()
        return f"{obs_rendered}\n\n{inst_rendered}", obs_str

    def messages(
        self,
        obs: Observation,
        *,
        profile: PlayerProfileConfig | None = None,
        output_format: Literal["xml", "json"] = "xml",
        include_rationale: bool = True,
    ) -> list[dict[str, str]]:
        msgs, _, _ = self.build(
            obs,
            profile=profile,
            output_format=output_format,
            include_rationale=include_rationale,
        )
        return msgs

    def build(
        self,
        obs: Observation,
        *,
        profile: PlayerProfileConfig | None = None,
        output_format: Literal["xml", "json"] = "xml",
        include_rationale: bool = True,
    ) -> tuple[list[dict[str, str]], str, str]:
        """Return (messages, observation_text, prompt_hash)."""
        sys_content = self.render_system(
            obs.player_id,
            flags=obs.coordination_flags,
            is_captain=obs.is_captain,
            profile=profile,
            output_format=output_format,
            include_rationale=include_rationale,
        )
        user_content, obs_str = self.render_user(
            obs,
            output_format=output_format,
            include_rationale=include_rationale,
        )
        p_hash = self.template_hash(
            obs.coordination_flags,
            is_captain=obs.is_captain,
            output_format=output_format,
            include_rationale=include_rationale,
        )
        return (
            [
                {"role": "system", "content": sys_content},
                {"role": "user", "content": user_content},
            ],
            obs_str,
            p_hash,
        )
