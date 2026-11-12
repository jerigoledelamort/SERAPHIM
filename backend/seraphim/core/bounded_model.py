"""Bound waiting for model adapters; a late response has no dispatch authority."""
from __future__ import annotations

import threading

from seraphim.model_layer.errors import provider_timeout_error


def generate_bounded(provider, request):
    box = {}

    def run():
        try:
            box["response"] = provider.generate(request)
        except BaseException as exc:
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(request.timeout_seconds)
    if worker.is_alive():
        raise provider_timeout_error(provider.provider_id)
    if "error" in box:
        raise box["error"]
    return box["response"]
