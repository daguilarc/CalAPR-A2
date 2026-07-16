import sys

from pages import pipeline_context as _pipeline_context

sys.modules[__name__] = _pipeline_context
