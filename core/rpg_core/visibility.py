"""Player event views exclude private entropy and untriggered plot candidates."""
INTERNAL_KINDS = frozenset({'item.registered','worldbook.proposal.receipt','npc.import.receipt','npc.roster.configured','npc.entrance.planned','worldbook.updated','worldbook.rejected','dice.seeded','dice.resolved','director.proposed','director.checkpoint','director.failed','adjudication.proposed','adjudication.decided'})

def player_visible(event) -> bool:
    return event.kind not in INTERNAL_KINDS and event.payload.get('visibility') != 'internal'

def player_events(events) -> list[dict]:
    return [e.model_dump(mode='json') for e in events if player_visible(e)]
