"""
Demo Script — SRE Incident Response Simulator
=============================================

This script demonstrates how an agent interacts with the environment.
To satisfy the baseline submission requirements, it plays out the optimal
sequence of actions for the "cascading-failure-hard" task to show
what a successful interaction loop looks like.

To test an actual LLM agent against the benchmark, use `inference.py`.

Usage:
    python demo.py
"""

import sys
import time

# Force UTF-8 encoding for standard output (fixes issues on Windows with cp1252).
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

try:
    from models import SREAction
    from server.environment import SREIncidentEnvironment
except ImportError:
    print("Please run this script from the project root: python demo.py")
    sys.exit(1)


def main():
    print("="*60)
    print(" SRE Incident Response Simulator - Demo Script ")
    print("="*60)
    
    # We will instantiate the hardest task to demo the environment's capabilities
    task_name = "cascading-failure-hard"
    print(f"\n[INFO] Starting Environment: {task_name}\n")
    
    env = SREIncidentEnvironment(task_name=task_name)
    obs = env.reset()
    
    print(f"[{obs.severity} ALERT] {obs.alert_title}")
    print(f"Service: {obs.service}")
    print("-"*60)
    print(f"ALERT BODY:\n{obs.alert_body}")
    print("-"*60)
    
    # Define a hardcoded "perfect" agent action sequence for this task
    actions = [
        SREAction(command="acknowledge", parameters={}),
        SREAction(command="run_query", parameters={"target": "payment-svc errors"}),
        SREAction(command="run_query", parameters={"target": "inventory-svc errors"}),
        SREAction(command="run_query", parameters={"target": "order-svc errors"}),
        SREAction(command="apply_fix", parameters={"action": "rollback", "service": "payment-svc", "to_version": "v2.1.4"}),
        SREAction(command="resolve", parameters={}),
    ]
    
    for i, action in enumerate(actions, 1):
        time.sleep(1) # Small pause for readability
        print(f"\n>>> STEP {i}")
        print(f"Agent Action: {action.command} | params: {action.parameters}")
        
        obs = env.step(action)
        
        time.sleep(1)
        print(f"Env Result : {obs.last_action_result.splitlines()[0][:80]}...") # Print first line of result
        print(f"Step Reward: +{obs.reward:.2f}")
        
        if obs.done:
            print("\n[INFO] Episode Terminated by Environment (done=True)")
            break

    print("="*60)
    print(f"Final Score: {env.get_episode_score():.3f} / 1.000")
    print("="*60)
    print("\nDemo complete. Try running the actual baseline LLM loop with `inference.py`!")

if __name__ == "__main__":
    main()
