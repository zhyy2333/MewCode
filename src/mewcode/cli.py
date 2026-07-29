from __future__ import annotations

import sys

from .config import load_active_profile
from .conversation import Conversation
from .providers import ConfigError, ProviderError, create_provider
from .repl import Repl


def main(argv: list[str] | None = None) -> int:
    try:
        profile = load_active_profile()
        provider = create_provider(profile)
        conversation = Conversation(provider)
        return Repl(conversation).run()
    except (ConfigError, ProviderError) as exc:
        sys.stderr.write(f"Error: {exc.message}\n")
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        return 130
