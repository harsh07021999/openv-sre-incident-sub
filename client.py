"""SRE Incident Response Simulator — HTTP/WebSocket client."""

from typing import Dict

from openenv.core import EnvClient
from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State

from .models import SREAction, SREObservation


class SREIncidentEnv(EnvClient[SREAction, SREObservation, State]):
    """
    Client for the SRE Incident Response Simulator environment.

    Maintains a persistent WebSocket connection to the environment server
    for efficient multi-step interactions.

    Example — connect to a running server::

        with SREIncidentEnv(base_url="http://localhost:8000") as env:
            result = env.reset()
            print(result.observation.alert_title)
            result = env.step(SREAction(command="acknowledge", parameters={}))
            print(result.reward)

    Example — start a container automatically::

        client = SREIncidentEnv.from_docker_image("sre-incident-sim:latest")
        try:
            result = client.reset()
            result = client.step(SREAction(
                command="apply_fix",
                parameters={"action": "restart_deployment", "service": "user-profile-svc"},
            ))
        finally:
            client.close()
    """

    def _step_payload(self, action: SREAction) -> Dict:
        """Serialise SREAction → JSON body for the step endpoint."""
        return {
            "command": action.command,
            "parameters": action.parameters,
        }

    def _parse_result(self, payload: Dict) -> StepResult[SREObservation]:
        """Deserialise server JSON response → StepResult[SREObservation]."""
        obs_data = payload.get("observation", {})
        observation = SREObservation(
            incident_id=obs_data.get("incident_id", ""),
            severity=obs_data.get("severity", "P3"),
            service=obs_data.get("service", ""),
            alert_title=obs_data.get("alert_title", ""),
            alert_body=obs_data.get("alert_body", ""),
            metrics_snapshot=obs_data.get("metrics_snapshot", {}),
            recent_events=obs_data.get("recent_events", []),
            runbook=obs_data.get("runbook", ""),
            acknowledged=obs_data.get("acknowledged", False),
            resolved=obs_data.get("resolved", False),
            time_elapsed_seconds=obs_data.get("time_elapsed_seconds", 0),
            task_name=obs_data.get("task_name", ""),
            hint=obs_data.get("hint", ""),
            last_action_result=obs_data.get("last_action_result", ""),
            done=payload.get("done", False),
            reward=payload.get("reward"),
            metadata=obs_data.get("metadata", {}),
        )
        return StepResult(
            observation=observation,
            reward=payload.get("reward"),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: Dict) -> State:
        """Deserialise server JSON response → State."""
        return State(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
        )
