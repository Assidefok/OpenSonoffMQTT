"""Test configuration for the OpenSonoffMQTT add-on tests.

Adds the ``addon`` folder to ``sys.path`` (so ``app`` is importable) and stubs
the optional third-party packages that are not installed in a bare dev
environment. In CI the real packages come from ``addon/requirements.txt``.
"""

import importlib.util
import sys
import types
from pathlib import Path

ADDON = Path(__file__).resolve().parents[1]
if str(ADDON) not in sys.path:
    sys.path.insert(0, str(ADDON))


def _missing(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is None
    except (ImportError, AttributeError, ValueError):
        return True


def _module(name: str, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


# --------------------------------------------------------------------- paho
if _missing("paho"):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def reconnect_delay_set(self, *args, **kwargs):
            pass

        def username_pw_set(self, *args, **kwargs):
            pass

        def tls_set(self, *args, **kwargs):
            pass

        def connect(self, *args, **kwargs):
            pass

        def connect_async(self, *args, **kwargs):
            pass

        def loop_start(self):
            pass

        def loop_stop(self):
            pass

        def disconnect(self):
            pass

        def publish(self, *args, **kwargs):
            pass

        def subscribe(self, *args, **kwargs):
            pass

    _module("paho")
    _module("paho.mqtt")
    _module("paho.mqtt.client", Client=_Client)

# ----------------------------------------------------------------- zeroconf
if _missing("zeroconf"):
    class _Zeroconf:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    class _Browser:
        def __init__(self, *args, **kwargs):
            pass

        async def async_cancel(self):
            pass

    class _Info:
        def __init__(self, *args, **kwargs):
            pass

    class _StateChange:
        Removed = 0
        Added = 1
        Updated = 2

    zc = _module("zeroconf", Zeroconf=_Zeroconf, ServiceStateChange=_StateChange)
    zc.asyncio = _module(
        "zeroconf.asyncio", AsyncServiceBrowser=_Browser, AsyncServiceInfo=_Info
    )

# ------------------------------------------------------------- cryptography
if _missing("cryptography"):
    class _Dummy:
        def __init__(self, *args, **kwargs):
            pass

        def update(self, data):
            return data

        def finalize(self):
            return b""

        def encryptor(self):
            return _Dummy()

        def decryptor(self):
            return _Dummy()

        def padder(self):
            return _Dummy()

        def unpadder(self):
            return _Dummy()

    class _Cipher:
        def __init__(self, *args, **kwargs):
            pass

        def encryptor(self):
            return _Dummy()

        def decryptor(self):
            return _Dummy()

    crypto = _module("cryptography")
    hazmat = _module("cryptography.hazmat")
    primitives = _module("cryptography.hazmat.primitives")
    padding = _module("cryptography.hazmat.primitives.padding", PKCS7=_Dummy)
    ciphers = _module(
        "cryptography.hazmat.primitives.ciphers",
        Cipher=_Cipher,
        algorithms=types.SimpleNamespace(AES=_Dummy),
        modes=types.SimpleNamespace(CBC=_Dummy),
    )

    crypto.hazmat = hazmat
    hazmat.primitives = primitives
    primitives.padding = padding
    primitives.ciphers = ciphers
