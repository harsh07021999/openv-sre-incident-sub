"""
Inference Script — SRE Incident Response Simulator
===================================================

Runs a baseline LLM agent against all three SRE incident response tasks
and emits structured evaluation logs to stdout.

ENVIRONMENT VARIABLES (required for LLM calls):
    HF_TOKEN      — Hugging Face / API key  (also read from OPENAI_API_KEY)
    API_BASE_URL  — LLM API endpoint         (default: HuggingFace router)
    MODEL_NAME    — Model identifier          (default: Qwen/Qwen2.5-72B-Instruct)

STDOUT FORMAT:
    [START] task=<task_name> env=sre-incident-sim model=<model>
    [STEP]  step=<n> action=<json> reward=<0.00> done=<true|false> error=<msg|null>
    [END]   success=<true|false> steps=<n> score=<0.000> rewards=<r1,r2,...>

USAGE:
    python inference.py

    # Override model / endpoint
    API_BASE_URL=https://api.openai.com/v1 MODEL_NAME=gpt-4o HF_TOKEN=sk-... python inference.py
"""

import json
import os
import sys
import textwrap
from typing import List, Optional, Tuple

from openai import OpenAI

# Allow direct imports from the project root regardless of CWD
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import SREAction, SREObservation          # noqa: E402
from server.environment import SREIncidentEnvironment  # noqa: E402
from server.scenarios import TASK_NAMES                # noqa: E402

# ── Configuration ─────────────────────────────────────────────────────────────
API_KEY: Optional[str] = os.getenv("HF_TOKEN") or os.getenv("OPENAI_API_KEY")
API_BASE_URL: str = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME: str = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")

BENCHMARK: str = "sre-incident-sim"
TASKS: List[str] = TASK_NAMES          # ["memory-leak-easy", "latency-spike-medium", "cascading-failure-hard"]
MAX_STEPS: int = 10                    # max steps per episode
TEMPERATURE: float = 0.2              # low temperature for reproducible baseline
MAX_TOKENS: int = 256
SUCCESS_SCORE_THRESHOLD: float = 0.5  # score >= 0.5 counts as success

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT: str = textwrap.dedent("""
    You are an expert Site Reliability Engineer (SRE) responding to a production incident.
    You receive an incident observation as JSON and must respond with exactly one JSON action.

    AVAILABLE COMMANDS:

    1. acknowledge — Always do this first.
       {"command": "acknowledge", "parameters": {}}

    2. run_query — Run a diagnostic query to gather more information.
       {"command": "run_query", "parameters": {"target": "<service or metric>", "query_type": "metrics"}}
       Examples:
         {"command": "run_query", "parameters": {"target": "user-profile-svc memory", "query_type": "metrics"}}
         {"command": "run_query", "parameters": {"target": "postgres connection pool", "query_type": "metrics"}}
         {"command": "run_query", "parameters": {"target": "payment-svc error rate", "query_type": "metrics"}}

    3. apply_fix — Apply a remediation.
       {"command": "apply_fix", "parameters": {"action": "<action_type>", "service": "<service_name>", ...}}
       Action types:
         restart_deployment  → {"action": "restart_deployment", "service": "svc-name"}
         rollback            → {"action": "rollback", "service": "svc-name", "to_version": "vX.Y.Z"}
         patch_config        → {"action": "patch_config", "service": "svc-name", "param": "key", "value": val}
         scale_up            → {"action": "scale_up", "service": "svc-name", "replicas": N}

    4. resolve — Mark incident resolved (only after applying the correct fix).
       {"command": "resolve", "parameters": {}}

    5. escalate — Page another team.
       {"command": "escalate", "parameters": {"team": "team-name", "reason": "reason"}}

    6. add_annotation — Record a postmortem note.
       {"command": "add_annotation", "parameters": {"note": "your note"}}

    7. no_op — Do nothing this step.
       {"command": "no_op", "parameters": {}}

    STRATEGY:
      Step 1: Always acknowledge immediately.
      Step 2: Run diagnostic queries to identify the root cause service and issue.
      Step 3: Apply the correct fix (match the symptom to the right remediation).
      Step 4: Resolve the incident.

    IMPORTANT: Respond with ONLY a valid JSON object. No explanation, no markdown fences,
    no extra text — just the raw JSON action.
""").strip()


# ── Logging helpers (mandatory format) ────────────────────────────────────────

def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(
    step: int,
    action: str,
    reward: float,
    done: bool,
    error: Optional[str],
) -> None:
    error_val = error if error else "null"
    done_val = str(done).lower()
    print(
        f"[STEP] step={step} action={action} "
        f"reward={reward:.2f} done={done_val} error={error_val}",
        flush=True,
    )


def log_end(
    success: bool,
    steps: int,
    score: float,
    rewards: List[float],
) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} "
        f"score={score:.3f} rewards={rewards_str}",
        flush=True,
    )


# ── Prompt builders ────────────────────────────────────────────────────────────

def build_user_prompt(step: int, obs: SREObservation, max_steps: int) -> str:
    """Format the current observation as a user-turn prompt for the LLM."""
    obs_dict = {
        "incident_id": obs.incident_id,
        "severity": obs.severity,
        "affected_service": obs.service,
        "alert_title": obs.alert_title,
        "alert_body": obs.alert_body,
        "metrics_snapshot": obs.metrics_snapshot,
        "recent_events": obs.recent_events[-6:],      # last 6 events
        "runbook_excerpt": obs.runbook[:600] if obs.runbook else "",
        "acknowledged": obs.acknowledged,
        "resolved": obs.resolved,
        "hint": obs.hint,
        "last_action_result": obs.last_action_result,
    }
    obs_json = json.dumps(obs_dict, indent=2)
    return (
        f"Step {step}/{max_steps}. Current incident state:\n"
        f"{obs_json}\n\n"
        "What is your next SRE action? Respond with a single JSON object only."
    )


def get_model_action(
    client: OpenAI,
    step: int,
    obs: SREObservation,
    history: List[dict],
) -> Tuple[str, str]:
    """
    Call the LLM to get the next action.

    Returns:
        (raw_response_text, user_prompt_text)
    """
    user_prompt = build_user_prompt(step, obs, MAX_STEPS)

    # Build message list (include last 3 history turns for context)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history[-3:]:
        messages.append({"role": "user",      "content": turn["prompt"]})
        messages.append({"role": "assistant", "content": turn["response"]})
    messages.append({"role": "user", "content": user_prompt})

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            stream=False,
        )
        text = (completion.choices[0].message.content or "").strip()
        return text, user_prompt
    except Exception as exc:
        print(f"[DEBUG] LLM request failed: {exc}", flush=True)
        return '{"command": "no_op", "parameters": {}}', user_prompt


def parse_action(response_text: str) -> Tuple[SREAction, str, Optional[str]]:
    """
    Parse LLM response text into an SREAction.

    Returns:
        (SREAction, compact_action_str, error_str_or_None)
    """
    text = response_text.strip()

    # Strip markdown code fences if the model added them
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("{") or part.startswith("json\n{"):
                text = part.replace("json\n", "").strip()
                break

    try:
        data = json.loads(text)
        action = SREAction(**data)
        action_str = json.dumps({"command": action.command, "parameters": action.parameters},
                                separators=(",", ":"))
        return action, action_str, None
    except Exception as exc:
        fallback = SREAction(command="no_op", parameters={"parse_error": str(exc)[:80]})
        action_str = '{"command":"no_op","parameters":{}}'
        return fallback, action_str, str(exc)[:120]


# ── Task runner ────────────────────────────────────────────────────────────────

def run_task(client: OpenAI, task_name: str) -> float:
    """
    Run one full episode for the given task.

    Emits [START] → N×[STEP] → [END] to stdout.
    Returns the normalised episode score in [0.0, 1.0].
    """
    rewards: List[float] = []
    steps_taken: int = 0
    success: bool = False
    score: float = 0.0
    history: List[dict] = []

    log_start(task=task_name, env=BENCHMARK, model=MODEL_NAME)

    env = SREIncidentEnvironment(task_name=task_name)

    try:
        obs = env.reset()

        for step in range(1, MAX_STEPS + 1):
            if obs.done:
                break

            # Get LLM action
            response_text, user_prompt = get_model_action(client, step, obs, history)

            # Parse action
            action, action_str, parse_error = parse_action(response_text)

            # Step the environment
            obs = env.step(action)

            reward: float = obs.reward if obs.reward is not None else 0.0
            done: bool = obs.done

            history.append({"prompt": user_prompt, "response": response_text})
            rewards.append(reward)
            steps_taken = step

            log_step(
                step=step,
                action=action_str,
                reward=reward,
                done=done,
                error=parse_error,
            )

            if done:
                break

        score = env.get_episode_score()
        success = score >= SUCCESS_SCORE_THRESHOLD

    except Exception as exc:
        print(f"[DEBUG] Episode error: {exc}", flush=True)
        score = min(max(sum(rewards), 0.0), 1.0)
        success = score >= SUCCESS_SCORE_THRESHOLD

    finally:
        log_end(
            success=success,
            steps=steps_taken,
            score=score,
            rewards=rewards,
        )

    return score


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    if not API_KEY:
        print(
            "[ERROR] No API key found. Set HF_TOKEN or OPENAI_API_KEY environment variable.",
            flush=True,
        )
        sys.exit(1)

    client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)

    all_scores: List[float] = []

    for task_name in TASKS:
        score = run_task(client, task_name)
        all_scores.append(score)

    # Summary (informational — not part of the mandatory log format)
    avg = sum(all_scores) / len(all_scores) if all_scores else 0.0
    print("", flush=True)
    print(f"[SUMMARY] tasks={','.join(TASKS)}", flush=True)
    print(f"[SUMMARY] scores={','.join(f'{s:.3f}' for s in all_scores)}", flush=True)
    print(f"[SUMMARY] average={avg:.3f}", flush=True)


if __name__ == "__main__":
    main()
