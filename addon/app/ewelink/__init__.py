"""eWeLink cloud client for the standalone OpenSonoffMQTT add-on.

``base.py`` and ``cloud.py`` are copied verbatim from
``custom_components/sonoff/core/ewelink``; the add-on Docker image only ships
the ``addon/`` folder, hence the duplication.  Public entry point:
``EWeLinkClient`` (see ``client.py``).
"""

from .client import AuthError, EWeLinkClient

__all__ = ["AuthError", "EWeLinkClient"]
