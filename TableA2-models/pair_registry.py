import sys

from pages import pair_registry as _pair_registry

sys.modules[__name__] = _pair_registry
