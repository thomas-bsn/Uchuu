"""Candidats vocaux pour le Picker Shameless."""


def pick_voice_candidates(guild):
    """Vocal avec le plus d'humains du serveur -> {channel_id, member_ids}.

    IDs en string (snowflakes > 2^53, sinon cassés côté JS).
    """
    best_channel = None
    best_ids = []
    # tri par ID -> égalité résolue au plus petit ID de salon (stable, indépendant du cache)
    for channel in sorted(guild.voice_channels, key=lambda c: c.id):
        ids = [m.id for m in channel.members if not m.bot]
        if len(ids) > len(best_ids):
            best_channel, best_ids = channel, ids

    return {
        "channel_id": str(best_channel.id) if best_channel else None,
        "member_ids": [str(i) for i in sorted(best_ids)],
    }
