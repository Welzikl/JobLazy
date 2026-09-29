"""Explicit dashboard model choices; never upgrade to another model on failure."""

PRESETS = {
    'personal': {'search': 'gpt-6-luna', 'review': 'gpt-6-astra', 'application': 'gpt-5.6-terra'},
    'friend': {'search': 'gpt-6-luna', 'review': 'gpt-6-luna', 'application': 'gpt-6-luna'},
}


def model_preset(name):
    try:
        return dict(PRESETS[name])
    except (KeyError, TypeError):
        raise ValueError('Unknown model preset. Choose personal or friend.') from None
