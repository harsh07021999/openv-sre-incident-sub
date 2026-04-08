"""
FastAPI application for the SRE Incident Response Simulator.

Exposes the SREIncidentEnvironment over HTTP and WebSocket endpoints
via the openenv-core create_app helper. Compatible with EnvClient.

Endpoints (created by openenv-core):
    POST /reset        — Reset environment, return initial observation
    POST /step         — Execute an action, return observation + reward
    GET  /state        — Get current episode state
    GET  /schema       — Action/observation JSON schema
    GET  /health       — Health check
    WS   /ws           — WebSocket endpoint for low-latency sessions
    GET  /web          — Interactive web UI (from openenv-core)

Task selection:
    Set the SRE_TASK environment variable before starting the server:
        SRE_TASK=memory-leak-easy        (default)
        SRE_TASK=latency-spike-medium
        SRE_TASK=cascading-failure-hard

Usage:
    # Development
    uvicorn server.app:app --reload --host 0.0.0.0 --port 8000

    # Production
    uvicorn server.app:app --host 0.0.0.0 --port 8000 --workers 4
"""

import os
os.environ['ENABLE_WEB_INTERFACE'] = 'true'

try:
    from openenv.core.env_server.http_server import create_app
except Exception as e:  # pragma: no cover
    raise ImportError(
        "openenv-core is required. Install with:\n    pip install openenv-core[core]"
    ) from e

import sys
from pathlib import Path

try:
    from ..models import SREAction, SREObservation
    from .environment import SREIncidentEnvironment
except (ImportError, ValueError):
    _root = str(Path(__file__).resolve().parent.parent)
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from models import SREAction, SREObservation                    # type: ignore[no-redef]
    from server.environment import SREIncidentEnvironment           # type: ignore[no-redef]


app = create_app(
    SREIncidentEnvironment,
    SREAction,
    SREObservation,
    env_name="sre-incident-sim",
    max_concurrent_envs=4,  # allow up to 4 concurrent WebSocket sessions
)


def main(host: str = "0.0.0.0", port: int = 8000):
    import uvicorn
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    main(port=args.port)
