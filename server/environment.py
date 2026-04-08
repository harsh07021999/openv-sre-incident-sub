"""
SRE Incident Response Simulator — Core Environment Logic.

Implements the OpenEnv Environment interface for a production incident
response simulation. An AI agent receives alert context and must diagnose
and remediate the incident through structured SRE actions.

Tasks (easy → hard):
  - memory-leak-easy        (P3) single-service OOMKill
  - latency-spike-medium    (P2) DB pool exhaustion behind gateway
  - cascading-failure-hard  (P1) gRPC proto-break cascade across 3 services
"""

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

try:
    from ..models import SREAction, SREObservation
    from .scenarios import SCENARIOS, TASK_NAMES
except ImportError:
    # Running as a script or installed package — ensure project root is on path
    _root = str(Path(__file__).resolve().parent.parent)
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from models import SREAction, SREObservation          # type: ignore[no-redef]
    from server.scenarios import SCENARIOS, TASK_NAMES    # type: ignore[no-redef]


class SREIncidentEnvironment(Environment):
    """
    SRE Incident Response Simulator.

    Simulates real-world production incidents an AI agent must diagnose
    and remediate. The environment exposes full incident context (alerts,
    metrics, runbooks, event logs) through observations and evaluates
    agent actions with shaped rewards.

    Reward structure:
        - Acknowledging the alert:           +0.05 – +0.10 (task-dependent)
        - Running a relevant query:          +0.05 – +0.10 per query type
        - Applying the correct fix:          +0.50 – +0.55
        - Resolving after correct fix:       +0.25
        - Wrong fix applied:                 −0.10 to −0.15
        - Resolving without fixing:          −0.15
        - Each extra step (after threshold): −0.02 to −0.03

    A perfect episode accumulates rewards summing to 1.0. Final score is
    clamped to [0.0, 1.0].

    Example::

        env = SREIncidentEnvironment(task_name="memory-leak-easy")
        obs = env.reset()
        obs = env.step(SREAction(command="acknowledge", parameters={}))
        obs = env.step(SREAction(
            command="run_query",
            parameters={"target": "user-profile-svc memory", "query_type": "metrics"},
        ))
        obs = env.step(SREAction(
            command="apply_fix",
            parameters={"action": "restart_deployment", "service": "user-profile-svc"},
        ))
        obs = env.step(SREAction(command="resolve", parameters={}))
        print(f"Done: {obs.done}, Reward this step: {obs.reward}")
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self, task_name: str = None):
        """
        Initialize the environment.

        Args:
            task_name: One of the available task names. Falls back to the
                       SRE_TASK environment variable, then 'memory-leak-easy'.
        """
        self._task_name = task_name or os.getenv("SRE_TASK", "memory-leak-easy")
        if self._task_name not in SCENARIOS:
            raise ValueError(
                f"Unknown task '{self._task_name}'. "
                f"Available tasks: {TASK_NAMES}"
            )
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._session: dict = {}

    # ──────────────────────────────────────────────────────────────────────────
    # OpenEnv Interface
    # ──────────────────────────────────────────────────────────────────────────

    def reset(self) -> SREObservation:
        """
        Reset the environment for a new episode.

        Loads the configured scenario and returns the initial observation
        (full incident alert context, zero cumulative reward).

        Returns:
            SREObservation with the incident details and empty action history.
        """
        scenario = SCENARIOS[self._task_name]
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._session = {
            "acknowledged": False,
            "resolved": False,
            "correct_fix_applied": False,
            "cumulative_reward": 0.0,
            # Track which query categories have been rewarded (prevents double-rewarding)
            "queries_rewarded": set(),
            "last_action_result": (
                f"Incident detected. ID: {scenario['incident_id']}. "
                "Awaiting first SRE response action."
            ),
        }
        return self._build_observation(scenario, reward=0.0, done=False)

    def step(self, action: SREAction) -> SREObservation:  # type: ignore[override]
        """
        Execute one SRE action and return the resulting observation.

        Args:
            action: SREAction with command and parameters.

        Returns:
            SREObservation with updated incident state, step reward, and done flag.
        """
        # Auto-reset if called before reset()
        if not self._session:
            self.reset()

        self._state.step_count += 1
        scenario = SCENARIOS[self._task_name]
        grading = scenario["grading"]

        # ── Time penalty for steps beyond threshold ────────────────────────
        reward = 0.0
        if self._state.step_count > grading["time_penalty_start_step"]:
            reward += grading["time_penalty_per_step"]

        # ── Dispatch action ────────────────────────────────────────────────
        cmd = action.command
        action_result = ""

        if cmd == "acknowledge":
            action_result, r = self._handle_acknowledge(grading)
            reward += r

        elif cmd == "run_query":
            action_result, r = self._handle_query(action, scenario, grading)
            reward += r

        elif cmd == "apply_fix":
            action_result, r = self._handle_fix(action, scenario, grading)
            reward += r

        elif cmd == "resolve":
            action_result, r = self._handle_resolve(scenario, grading)
            reward += r

        elif cmd == "escalate":
            team = action.parameters.get("team", "unknown team")
            reason = action.parameters.get("reason", "no reason provided")
            action_result = (
                f"Escalated to {team}: '{reason}'. "
                "Continuing incident response — escalation noted in timeline."
            )
            # Neutral: no reward, no penalty

        elif cmd == "add_annotation":
            note = action.parameters.get("note", "")
            action_result = f"Annotation recorded: '{note[:150]}'"

        elif cmd == "no_op":
            action_result = "No action taken this step. Time is passing."

        else:
            action_result = f"Unknown command '{cmd}'. No action taken."

        # ── Update session ─────────────────────────────────────────────────
        self._session["cumulative_reward"] += reward
        self._session["last_action_result"] = action_result

        done = (
            self._session["resolved"]
            or self._state.step_count >= scenario["max_steps"]
        )

        return self._build_observation(scenario, reward=reward, done=done)

    @property
    def state(self) -> State:
        """Return current episode state (episode_id, step_count)."""
        return self._state

    # ──────────────────────────────────────────────────────────────────────────
    # Action Handlers
    # ──────────────────────────────────────────────────────────────────────────

    def _handle_acknowledge(self, grading: dict) -> tuple[str, float]:
        if not self._session["acknowledged"]:
            self._session["acknowledged"] = True
            return (
                "Alert acknowledged. Incident response clock started. "
                "Begin diagnosing the root cause.",
                grading["acknowledge_reward"],
            )
        return "Alert was already acknowledged.", 0.0

    def _handle_query(
        self, action: SREAction, scenario: dict, grading: dict
    ) -> tuple[str, float]:
        # Build a lookup string from all action parameters
        params_str = json.dumps(action.parameters, default=str).lower()
        target = str(action.parameters.get("target", action.parameters.get("query", ""))).lower()
        lookup = f"{params_str} {target}"

        # Match against scenario query response templates
        response = None
        for qr in scenario.get("query_responses", []):
            if any(kw in lookup for kw in qr["keywords"]):
                response = qr["response"]
                break

        if response is None:
            response = scenario.get("default_query_response", "QUERY RESULT: No data found.")

        reward = self._compute_query_reward(lookup, grading)
        return response, reward

    def _compute_query_reward(self, lookup: str, grading: dict) -> float:
        """Compute per-query reward, avoiding double-rewarding the same category."""
        task = self._task_name
        rewarded = self._session["queries_rewarded"]

        if task == "memory-leak-easy":
            kws = grading.get("relevant_query_keywords", [])
            if any(kw in lookup for kw in kws) and "memory" not in rewarded:
                if len(rewarded) < grading.get("max_rewarded_queries", 1):
                    rewarded.add("memory")
                    return grading.get("query_reward", 0.0)

        elif task == "latency-spike-medium":
            gw_kws = grading.get("relevant_query_keywords_gateway", [])
            db_kws = grading.get("relevant_query_keywords_db", [])
            # DB query is more insightful — check it first
            if any(kw in lookup for kw in db_kws) and "db" not in rewarded:
                rewarded.add("db")
                return grading.get("db_query_reward", 0.0)
            if any(kw in lookup for kw in gw_kws) and "gateway" not in rewarded:
                rewarded.add("gateway")
                return grading.get("gateway_query_reward", 0.0)

        elif task == "cascading-failure-hard":
            pay_kws = grading.get("relevant_query_keywords_payment", [])
            inv_kws = grading.get("relevant_query_keywords_inventory", [])
            ord_kws = grading.get("relevant_query_keywords_order", [])
            if any(kw in lookup for kw in pay_kws) and "payment" not in rewarded:
                rewarded.add("payment")
                return grading.get("payment_query_reward", 0.0)
            if any(kw in lookup for kw in inv_kws) and "inventory" not in rewarded:
                rewarded.add("inventory")
                return grading.get("inventory_query_reward", 0.0)
            if any(kw in lookup for kw in ord_kws) and "order" not in rewarded:
                rewarded.add("order")
                return grading.get("order_query_reward", 0.0)

        return 0.0

    def _handle_fix(
        self, action: SREAction, scenario: dict, grading: dict
    ) -> tuple[str, float]:
        is_correct = self._check_correct_fix(action, grading)

        if is_correct:
            if not self._session["correct_fix_applied"]:
                self._session["correct_fix_applied"] = True
                return (
                    scenario["fix_results"]["correct"],
                    grading.get("correct_fix_reward", 0.0),
                )
            return "Fix already applied. Metrics are stabilising — consider resolving.", 0.0

        # Wrong fix
        return (
            scenario["fix_results"]["wrong"],
            grading.get("wrong_fix_penalty", 0.0),
        )

    def _handle_resolve(self, scenario: dict, grading: dict) -> tuple[str, float]:
        if self._session["resolved"]:
            return "Incident already marked as resolved.", 0.0

        if self._session["correct_fix_applied"]:
            self._session["resolved"] = True
            return (
                (
                    f"Incident {scenario['incident_id']} RESOLVED. "
                    "All metrics normalised. Post-mortem recommended within 48 h."
                ),
                grading.get("resolve_reward", 0.0),
            )

        # Resolve attempted without fixing
        return (
            (
                "RESOLVE REJECTED: Metrics still indicate active degradation.\n"
                f"  {scenario['service']} is still in a degraded state.\n"
                "Apply the correct remediation before resolving."
            ),
            grading.get("early_resolve_penalty", 0.0),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _check_correct_fix(self, action: SREAction, grading: dict) -> bool:
        """Return True only when all required_params match the action."""
        spec = grading["correct_fix"]
        if action.command != spec["command"]:
            return False
        for key, expected in spec["required_params"].items():
            actual = str(action.parameters.get(key, "")).lower().strip()
            if actual != str(expected).lower().strip():
                return False
        return True

    def _build_observation(
        self, scenario: dict, reward: float, done: bool
    ) -> SREObservation:
        return SREObservation(
            incident_id=scenario["incident_id"],
            severity=scenario["severity"],
            service=scenario["service"],
            alert_title=scenario["alert_title"],
            alert_body=scenario["alert_body"],
            metrics_snapshot=scenario["metrics_snapshot"],
            recent_events=scenario["recent_events"],
            runbook=scenario["runbook"],
            acknowledged=self._session.get("acknowledged", False),
            resolved=self._session.get("resolved", False),
            time_elapsed_seconds=self._state.step_count * 60,
            task_name=self._task_name,
            hint=scenario["hint"],
            last_action_result=self._session.get("last_action_result", ""),
            reward=reward,
            done=done,
            metadata={
                "step": self._state.step_count,
                "cumulative_reward": round(self._session.get("cumulative_reward", 0.0), 4),
                "correct_fix_applied": self._session.get("correct_fix_applied", False),
                "queries_rewarded": list(self._session.get("queries_rewarded", set())),
                "available_tasks": TASK_NAMES,
            },
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Grader (public helper for external evaluation)
    # ──────────────────────────────────────────────────────────────────────────

    def get_episode_score(self) -> float:
        """
        Return the final normalised episode score in [0.0, 1.0].

        Sums all step rewards accumulated since the last reset() and
        clamps the result to [0.0, 1.0].
        """
        raw = self._session.get("cumulative_reward", 0.0)
        return float(min(max(raw, 0.0), 1.0))


# ──────────────────────────────────────────────────────────────────────────────
# Smoke-test when run directly
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":  # pragma: no cover
    # Ensure project root is importable when run as `python server/environment.py`
    _root = str(Path(__file__).resolve().parent.parent)
    if _root not in sys.path:
        sys.path.insert(0, _root)
    print("=== SRE Incident Response Simulator — smoke test ===\n")

    for task in TASK_NAMES:
        env = SREIncidentEnvironment(task_name=task)
        obs = env.reset()
        print(f"Task: {task}")
        print(f"  Alert : {obs.alert_title}")
        print(f"  Hint  : {obs.hint}")

        # Perfect agent: ack -> query -> fix -> resolve
        obs = env.step(SREAction(command="acknowledge", parameters={}))
        print(f"  [ack]    reward={obs.reward:.2f}")

        # Task-specific correct fix
        if task == "memory-leak-easy":
            obs = env.step(SREAction(
                command="run_query",
                parameters={"target": "user-profile-svc memory"},
            ))
            print(f"  [query]  reward={obs.reward:.2f}  -> {obs.last_action_result[:60]}...")
            obs = env.step(SREAction(
                command="apply_fix",
                parameters={"action": "restart_deployment", "service": "user-profile-svc"},
            ))
        elif task == "latency-spike-medium":
            obs = env.step(SREAction(
                command="run_query",
                parameters={"target": "postgres connection pool"},
            ))
            print(f"  [query]  reward={obs.reward:.2f}  -> {obs.last_action_result[:60]}...")
            obs = env.step(SREAction(
                command="apply_fix",
                parameters={"action": "patch_config", "service": "postgres", "param": "max_connections", "value": 200},
            ))
        elif task == "cascading-failure-hard":
            obs = env.step(SREAction(
                command="run_query",
                parameters={"target": "payment-svc errors"},
            ))
            print(f"  [query]  reward={obs.reward:.2f}  -> {obs.last_action_result[:60]}...")
            obs = env.step(SREAction(
                command="apply_fix",
                parameters={"action": "rollback", "service": "payment-svc", "to_version": "v2.1.4"},
            ))

        print(f"  [fix]    reward={obs.reward:.2f}  -> {obs.last_action_result[:60]}...")
        obs = env.step(SREAction(command="resolve", parameters={}))
        print(f"  [resolve] reward={obs.reward:.2f}  done={obs.done}")
        print(f"  SCORE    = {env.get_episode_score():.3f}\n")
