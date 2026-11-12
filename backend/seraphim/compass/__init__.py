# SERAPHIM COMPASS — deterministic, explainable model routing (S15).
#
# COMPASS chooses which configured provider/model serves a request.  It is a
# pure decision function over declared candidates: it never opens a socket,
# never changes AEGIS permissions and never reads CORE/WINGS.  Every rejected
# candidate carries the reason it was rejected, so the choice is reproducible
# and explainable (spec §4.4).

from seraphim.compass.router import Candidate, ModelRouter, RoutingDecision, RoutingMode

__all__ = [
    "Candidate",
    "ModelRouter",
    "RoutingDecision",
    "RoutingMode",
]
