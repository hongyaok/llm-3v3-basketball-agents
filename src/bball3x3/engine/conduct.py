"""Turn explicit player conduct signals into evidence for the referee.

Ordinary actions and contact alone never imply special misconduct. The signal
must survive action validation; unsportsmanlike contact must also match the
resolved contact's likely offender and the named opposing recipient.
"""

from bball3x3.schemas.actions import ActionProposal
from bball3x3.schemas.referee import ContactEvent
from bball3x3.schemas.state import GameState


def _contact_pair(contact: ContactEvent) -> tuple[str, str] | None:
    players = contact.players_involved
    if not contact.contact_detected or len(players) < 2:
        return None
    if contact.contact_type == "BODY_CONTACT_DRIVE":
        return players[1], players[0]
    if contact.contact_type == "REACH":
        return players[0], players[1]
    if contact.contact_type in {"SCREEN_CONTACT", "LOOSE_BALL"}:
        return (
            contact.details.get("contact_initiator", players[0]),
            contact.details.get("contact_recipient", players[1]),
        )
    return None


def collect_conduct_evidence(
    state: GameState,
    proposals: dict[str, ActionProposal],
    contact: ContactEvent,
) -> dict[str, object]:
    """Return referee event fields for one corroborated conduct signal."""
    pair = _contact_pair(contact)
    for player_id, proposal in proposals.items():
        if player_id not in state.players or proposal.player_id != player_id:
            continue
        if proposal.conduct == "TECHNICAL" and proposal.conduct_target is None:
            evidence = {
                "kind": "TECHNICAL", "actor": player_id,
                "action": proposal.action, "source": "ACTION_PROPOSAL",
            }
            return {"technical_conduct": True, "offender": player_id,
                    "conduct_evidence": evidence}
        if proposal.conduct != "UNSPORTSMANLIKE" or pair is None:
            continue
        offender, recipient = pair
        if (player_id != offender or proposal.conduct_target != recipient
                or recipient not in state.players
                or state.players[player_id].team == state.players[recipient].team):
            continue
        evidence = {
            "kind": "UNSPORTSMANLIKE", "actor": player_id,
            "target": recipient, "action": proposal.action,
            "contact_type": contact.contact_type,
            "source": "ACTION_PROPOSAL",
        }
        return {"unsportsmanlike_contact": True, "offender": player_id,
                "fouled_player": recipient, "conduct_evidence": evidence}
    return {}
