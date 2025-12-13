# =========================
# SERVER CONFIG
# =========================

GUILD_ID = 696394226920849409

# =========================
# ROLES
# =========================

ROLE_INVITE_ID = 1449451819561521315
ROLE_MEMBRE_ID = 1449450755512729811
ROLE_CONFIANCE_ID = 696813923613016075

# =========================
# CHANNELS
# =========================

CHANNEL_VALIDATION_ID = 1449450508988317816
CHANNEL_RULES_ID = 1449448870646911148  # pure info, le bot n'en dépend pas
CHANNEL_LOGS_ID = 1449456760598433812

# =========================
# VERIFICATION RULES
# =========================

APPROVALS_REQUIRED = 1
DENY_REQUIRED = 1
VOTE_WINDOW_SECONDS = 60

ACTIVITY_THRESHOLD = 5  # Nombre de messages à envoyer en 7 jours
MIN_MEMBERSHIP_DAYS = 0  # Nombre de jours minimum sur le serveur

# Optionnels (tu peux laisser comme ça)
KICK_GRACE_SECONDS = 30 # petite marge avant kick auto
KICK_AUDIT_REASON = "Verification timeout"


# =========================
# MESSAGES
# =========================

VOTE_MESSAGE_TEMPLATE = (
    "🔐 **Nouvel invité**\n\n"
    "Utilisateur: {user}\n"
    "Votes requis: {required}\n"
    "Expiration: <t:{expires_at}:R>\n\n"
    "Votes actuels: {current}/{required}"
)

VOTE_APPROVED_MESSAGE = "✅ **Validé** — accès accordé."
VOTE_DENIED_MESSAGE = "❌ **Refusé** — accès refusé."

KICK_DM_MESSAGE = (
    "Tu as été retiré du serveur.\n"
    "Raison: validation non obtenue dans le délai imparti.\n"
    "Serveur privé à intérêt commun."
)

KICK_AUDIT_REASON = "Verification timeout"

# =========================
# INTERNAL SAFETY
# =========================

DEBUG = True
