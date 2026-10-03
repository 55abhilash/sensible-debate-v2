"""
Sensible Debate has no accounts in v1 - the point is to talk to a stranger
about a topic, not to build a profile. Each browser generates its own
anonymous id (see static/js/identity.js) and asks this module for a
friendly display name to go with it, e.g. "Thoughtful Heron".
"""
import random

_ADJECTIVES = [
    "Thoughtful", "Curious", "Patient", "Candid", "Measured", "Open-minded",
    "Attentive", "Calm", "Earnest", "Reflective", "Fair-minded", "Steady",
    "Level-headed", "Considerate", "Deliberate", "Even-handed",
]

_NOUNS = [
    "Heron", "Otter", "Fox", "Owl", "Falcon", "Badger", "Wren", "Lynx",
    "Magpie", "Hare", "Raven", "Deer", "Sparrow", "Beaver", "Crane", "Wolf",
]


def suggest_name() -> str:
    return f"{random.choice(_ADJECTIVES)} {random.choice(_NOUNS)}"
