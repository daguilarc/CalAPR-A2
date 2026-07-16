import sys

from pages import export as _pages_export

sys.modules[__name__] = _pages_export
