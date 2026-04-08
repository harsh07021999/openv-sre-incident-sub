"""
Data models for the SRE Incident Response Simulator.

Defines the typed Action and Observation Pydantic models that agents
interact with when responding to production incidents.
"""

import json
from typing import Any, Dict, List, Literal

from pydantic import Field, model_validator
from openenv.core.env_server.types import Action, Observation


class SREAction(Action):
    """
    Action for the SRE Incident Response environment.

    An agent submits one action per step, choosing from the set of
    commands available to an on-call SRE.

    Example::

        SREAction(command="acknowledge", parameters={})
        SREAction(command="run_query", parameters={"target": "user-profile-svc memory", "query_type": "metrics"})
        SREAction(command="apply_fix", parameters={"action": "restart_deployment", "service": "user-profile-svc"})
        SREAction(command="resolve", parameters={})
    """

    command: Literal[
        "run_query",      # Run a PromQL/log/trace diagnostic query
        "acknowledge",    # Acknowledge the alert (always do this first)
        "escalate",       # Page another team
        "apply_fix",      # Apply a remediation action
        "add_annotation", # Add a postmortem note to the incident
        "resolve",        # Mark the incident as resolved
        "no_op",          # No action this step
    ] = Field(..., description="The SRE command to execute")

    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Command-specific parameters. "
            "run_query: {target, query_type}. "
            "apply_fix: {action, service, ...}. "
            "escalate: {team, reason}. "
            "add_annotation: {note}. "
            "Others: {}."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def parse_parameters(cls, data: Any) -> Any:
        if isinstance(data, dict):
            params = data.get("parameters")
            if isinstance(params, str):
                try:
                    data["parameters"] = json.loads(params)
                except json.JSONDecodeError:
                    pass
        return data


class SREObservation(Observation):
    """
    Observation from the SRE Incident Response environment.

    Contains the full incident context an agent needs to diagnose
    and remediate a production incident.
    """

    incident_id: str = Field(..., description="Unique incident identifier (e.g. INC-2024-001)")
    severity: str = Field(..., description="Incident severity: P1 (critical), P2 (high), P3 (medium)")
    service: str = Field(..., description="Primary affected service(s)")
    alert_title: str = Field(..., description="Short alert title")
    alert_body: str = Field(..., description="Full alert description with timeline and context")
    metrics_snapshot: Dict[str, Any] = Field(
        default_factory=dict,
        description="Current key metric values (latency, error rate, resource usage, etc.)",
    )
    recent_events: List[str] = Field(
        default_factory=list,
        description="Recent log lines, deployment events, and alerts in chronological order",
    )
    runbook: str = Field(
        default="",
        description="Relevant runbook excerpt for this incident type",
    )
    acknowledged: bool = Field(
        default=False,
        description="Whether the on-call SRE has acknowledged the alert",
    )
    resolved: bool = Field(
        default=False,
        description="Whether the incident has been marked resolved",
    )
    time_elapsed_seconds: int = Field(
        default=0,
        description="Simulated seconds elapsed since incident was triggered",
    )
    task_name: str = Field(
        default="",
        description="Active task name (e.g. memory-leak-easy)",
    )
    hint: str = Field(
        default="",
        description="Contextual hint to guide the agent toward the correct diagnostic path",
    )
    last_action_result: str = Field(
        default="",
        description="Detailed result message from the previous action (query output, fix result, etc.)",
    )
