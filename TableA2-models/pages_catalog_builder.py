import sys

from pages import catalog_builder as _catalog_builder

sys.modules[__name__] = _catalog_builder
