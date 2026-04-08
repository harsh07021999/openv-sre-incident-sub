"""
Scenario definitions for the SRE Incident Response Simulator.

Each scenario is a fully self-contained production incident with:
  - Alert metadata (severity, affected service, alert body)
  - Metrics snapshot (deterministic key metrics)
  - Recent event log
  - Runbook excerpt
  - Grading configuration (reward weights, correct fix spec, query keywords)
  - Query response templates (what the agent sees when it runs diagnostic queries)
  - Fix result messages (feedback after applying a remediation)

Scenario difficulty:
  - memory-leak-easy        (P3) — single-service OOMKill, explicit runbook
  - latency-spike-medium    (P2) — multi-service chain, must correlate two metrics
  - cascading-failure-hard  (P1) — 3-service cascade, red herring, sequence matters
"""

SCENARIOS: dict = {
    # ──────────────────────────────────────────────────────────────────────────
    # TASK 1 — EASY
    # A single microservice has a memory leak, pods are OOMKilling.
    # The runbook explicitly says: restart the deployment.
    # ──────────────────────────────────────────────────────────────────────────
    "memory-leak-easy": {
        "incident_id": "INC-2024-001",
        "severity": "P3",
        "service": "user-profile-svc",
        "alert_title": "P3: user-profile-svc memory usage critical (95.2%)",
        "alert_body": (
            "ALERT: user-profile-svc memory usage critically high\n"
            "Severity: P3 | Triggered: 2024-01-15 14:32:00 UTC\n\n"
            "Affected service: user-profile-svc (2 of 4 pods OOMKilled)\n"
            "Current memory: 95.2% (7.62 GB / 8 GB limit)\n"
            "Alert rule: container_memory_usage_bytes > 90% for 5 minutes\n\n"
            "Service info:\n"
            "  - Pods: 4 scheduled, 2 running, 2 OOMKilled (restart loop)\n"
            "  - Last deploy: 3 days ago (v1.8.2) — no recent code changes\n"
            "  - Error rate: 2.1% (elevated — 503s from OOMKilled pods)\n\n"
            "Runbook: https://wiki.internal/runbooks/memory-leak\n"
            "Dashboard: https://grafana.internal/d/user-profile"
        ),
        "metrics_snapshot": {
            "user_profile_svc.memory_usage_pct": 95.2,
            "user_profile_svc.memory_used_gb": 7.62,
            "user_profile_svc.memory_limit_gb": 8.0,
            "user_profile_svc.pod_restarts_30m": 3,
            "user_profile_svc.pods_running": 2,
            "user_profile_svc.pods_desired": 4,
            "user_profile_svc.request_latency_p95_ms": 450,
            "user_profile_svc.error_rate_pct": 2.1,
            "cluster.available_memory_gb": 24.5,
            "cluster.node_count": 3,
        },
        "recent_events": [
            "[14:28:44] user-profile-svc-788d4b-xk9p2: Memory usage crossed 90% threshold",
            "[14:30:01] user-profile-svc-788d4b-xk9p2: OOMKilled (exit code 137)",
            "[14:30:02] user-profile-svc-788d4b-xk9p2: Restarting (restart count: 3)",
            "[14:31:15] user-profile-svc-9f2c3a-mw7r1: OOMKilled (exit code 137)",
            "[14:31:16] user-profile-svc-9f2c3a-mw7r1: Restarting (restart count: 2)",
            "[14:31:58] kube-scheduler: Rescheduling 2 OOMKilled pods",
            "[14:32:00] alertmanager: FIRED P3 memory_usage_critical (user-profile-svc)",
            "[14:32:05] pagerduty: On-call SRE notified",
        ],
        "runbook": (
            "## Memory Leak Runbook — user-profile-svc\n\n"
            "### Symptoms:\n"
            "  - Steadily climbing memory usage\n"
            "  - OOMKilled pod events (exit code 137)\n"
            "  - Pod restart loops\n\n"
            "### Diagnosis:\n"
            "  1. Run query: memory usage trend for user-profile-svc\n"
            "  2. Check for recent code changes or config updates\n\n"
            "### Remediation:\n"
            "  Step 1 — If OOMKilled pods are present: restart the deployment\n"
            "           This clears in-memory state and recycles the pod process.\n"
            "           Action: restart_deployment on service: user-profile-svc\n"
            "  Step 2 — If memory climbs again within 30 min: escalate to platform-team\n"
            "  Step 3 — Schedule postmortem and add memory profiling to CI pipeline"
        ),
        "hint": "Pods are OOMKilled. The runbook has a clear first remediation step for this exact symptom.",
        "grading": {
            # Reward weights (designed to sum to 1.0 on a perfect run)
            "acknowledge_reward": 0.10,
            "query_reward": 0.10,          # per relevant query (max 1 rewarded)
            "max_rewarded_queries": 1,
            "correct_fix_reward": 0.55,
            "resolve_reward": 0.25,
            # Penalties
            "wrong_fix_penalty": -0.10,
            "early_resolve_penalty": -0.15,  # resolve before fixing
            "time_penalty_per_step": -0.02,
            "time_penalty_start_step": 5,
            # Correct fix specification (all required_params must match)
            "correct_fix": {
                "command": "apply_fix",
                "required_params": {
                    "action": "restart_deployment",
                    "service": "user-profile-svc",
                },
            },
            # Keywords for detecting relevant diagnostic queries
            "relevant_query_keywords": [
                "memory", "oom", "user-profile", "user_profile",
                "pod", "restart", "oomkill",
            ],
        },
        "query_responses": [
            {
                "keywords": ["memory", "oom", "user-profile", "user_profile", "pod", "restart", "oomkill"],
                "response": (
                    "QUERY RESULT [user-profile-svc — memory metrics]:\n"
                    "  memory_used:       7.62 GB / 8.00 GB (95.2%)\n"
                    "  memory_growth:     +800 MB/hour (steady leak pattern)\n"
                    "  oomkill_events:    3 in last 30 minutes\n"
                    "  pod_restart_count: 3 (CrashLoopBackOff imminent at 5)\n"
                    "  recent_deploys:    None in 3 days (v1.8.2 is stable elsewhere)\n"
                    "  \n"
                    "  Runbook guidance: OOMKilled pods → restart_deployment\n"
                    "  to clear in-memory state and restore service capacity."
                ),
            },
        ],
        "default_query_response": (
            "QUERY RESULT: No significant anomaly found for that target.\n"
            "  Suggestion: query 'user-profile-svc memory' or 'oom events' for relevant data."
        ),
        "fix_results": {
            "correct": (
                "SUCCESS: Deployment user-profile-svc restarted.\n"
                "  - All 4 pods scheduled and Running ✓\n"
                "  - Memory usage reset to 2.1% (baseline) ✓\n"
                "  - OOMKill events: 0 (last 5 minutes) ✓\n"
                "  - Error rate: 0.0% ✓\n"
                "  Monitor for 30 min to confirm leak does not recur."
            ),
            "wrong": (
                "ERROR: Applied fix had no effect on the memory issue.\n"
                "  - user-profile-svc memory still at 95.2%\n"
                "  - OOMKill events continuing\n"
                "  Hint: The runbook recommends restarting the deployment "
                "that is OOMKilling (user-profile-svc)."
            ),
        },
        "max_steps": 10,
    },

    # ──────────────────────────────────────────────────────────────────────────
    # TASK 2 — MEDIUM
    # API gateway latency spikes after a deploy. Root cause is PostgreSQL
    # connection pool exhaustion (not the gateway itself). Agent must run
    # two queries to correlate the evidence before applying the correct fix.
    # Red herring: a gateway deploy happened 45 min ago.
    # ──────────────────────────────────────────────────────────────────────────
    "latency-spike-medium": {
        "incident_id": "INC-2024-002",
        "severity": "P2",
        "service": "api-gateway",
        "alert_title": "P2: api-gateway P95 latency 2340ms (SLO: 500ms)",
        "alert_body": (
            "ALERT: api-gateway latency SLO violation\n"
            "Severity: P2 | Triggered: 2024-01-15 16:45:00 UTC\n\n"
            "Affected service: api-gateway\n"
            "  P95 latency:  2340 ms  (SLO threshold: 500 ms)\n"
            "  Error rate:   8.3%     (mostly 504 Gateway Timeout)\n"
            "  Throughput:   1247 RPS (normal: ~1200 RPS — traffic is not spiking)\n\n"
            "Recent changes:\n"
            "  16:00 UTC — api-gateway v3.2.1 deployed (adds user recommendation feature)\n"
            "  15:45 UTC — No other changes in the last 2 hours\n\n"
            "Service dependencies: auth-svc, user-svc, postgres-main, redis-cache\n"
            "Dashboard: https://grafana.internal/d/api-gateway"
        ),
        "metrics_snapshot": {
            "api_gateway.latency_p95_ms": 2340,
            "api_gateway.latency_p50_ms": 890,
            "api_gateway.error_rate_pct": 8.3,
            "api_gateway.rps": 1247,
            "api_gateway.current_version": "v3.2.1",
            "api_gateway.previous_version": "v3.2.0",
            "postgres_main.connections_used": 100,
            "postgres_main.connections_max": 100,
            "postgres_main.connections_waiting": 847,
            "postgres_main.avg_query_time_ms": 1840,
            "postgres_main.max_connections_setting": 100,
            "auth_svc.latency_p95_ms": 45,
            "auth_svc.error_rate_pct": 0.0,
            "user_svc.latency_p95_ms": 38,
            "user_svc.error_rate_pct": 0.1,
            "redis_cache.hit_rate_pct": 98.2,
            "redis_cache.latency_p95_ms": 2,
        },
        "recent_events": [
            "[16:00:15] api-gateway: Deploying v3.2.1 (new: user recommendation feature, direct DB calls)",
            "[16:02:30] api-gateway: v3.2.1 health checks PASSING — rollout complete",
            "[16:30:42] postgres-main: connection pool at capacity (100/100 active connections)",
            "[16:31:05] api-gateway: upstream read timeout (30 s) on postgres-main call",
            "[16:35:18] postgres-main: 847 connections queued, avg wait: 12.4 s",
            "[16:44:51] api-gateway: error rate crossed 5% alert threshold",
            "[16:44:58] alertmanager: FIRED P2 latency_slo_violation (api-gateway)",
            "[16:45:02] pagerduty: On-call SRE notified",
        ],
        "runbook": (
            "## API Gateway Latency Runbook\n\n"
            "### Common root causes:\n"
            "  1. Downstream dependency degraded (check each dependency's metrics)\n"
            "  2. Recent deployment introduced query amplification or missing DB index\n"
            "  3. Database connection pool exhaustion (pool full, requests stacking)\n"
            "  4. Cache miss storm causing DB pressure\n\n"
            "### Diagnosis steps:\n"
            "  1. Query api-gateway metrics: latency breakdown, upstream error codes\n"
            "  2. Query each downstream: auth-svc, user-svc, postgres-main, redis-cache\n"
            "  3. Correlate with recent deployments — which service changed last?\n\n"
            "### Remediation options:\n"
            "  - DB connection pool exhaustion: patch_config max_connections on postgres\n"
            "  - Slow downstream: apply rate limiting or circuit break\n"
            "  - Bad deploy causing DB pressure: patch config first, then evaluate rollback"
        ),
        "hint": (
            "Traffic is normal but latency is very high. "
            "Check the api-gateway upstream error codes, then check each downstream dependency."
        ),
        "grading": {
            # Reward weights (sum to 1.0 on perfect run)
            "acknowledge_reward": 0.05,
            "gateway_query_reward": 0.10,
            "db_query_reward": 0.10,
            "max_rewarded_gateway_queries": 1,
            "max_rewarded_db_queries": 1,
            "correct_fix_reward": 0.50,
            "resolve_reward": 0.25,
            # Penalties
            "wrong_fix_penalty": -0.10,
            "early_resolve_penalty": -0.15,
            "time_penalty_per_step": -0.02,
            "time_penalty_start_step": 5,
            # Correct fix: patch postgres max_connections
            "correct_fix": {
                "command": "apply_fix",
                "required_params": {
                    "action": "patch_config",
                    "service": "postgres",
                },
            },
            # Keyword buckets for per-type query reward tracking
            "relevant_query_keywords_gateway": [
                "latency", "gateway", "api-gateway", "api_gateway",
                "timeout", "error_rate", "upstream",
            ],
            "relevant_query_keywords_db": [
                "postgres", "postgresql", "db", "database",
                "connection", "pool", "conn", "pg",
            ],
        },
        "query_responses": [
            {
                "keywords": [
                    "latency", "gateway", "api-gateway", "api_gateway",
                    "timeout", "upstream", "error_rate",
                ],
                "response": (
                    "QUERY RESULT [api-gateway — latency breakdown]:\n"
                    "  P95 latency:   2340 ms  (SLO: 500 ms)\n"
                    "  P50 latency:    890 ms\n"
                    "  Error type:    504 Gateway Timeout (8.3%)\n"
                    "  Upstream breakdown:\n"
                    "    auth-svc      →   45 ms ✓\n"
                    "    user-svc      →   38 ms ✓\n"
                    "    redis-cache   →    2 ms ✓\n"
                    "    postgres-main → TIMEOUT (>30 s) ✗\n"
                    "  Slow endpoint: /api/v1/recommendations (added in v3.2.1)\n"
                    "  → postgres-main is the degraded upstream."
                ),
            },
            {
                "keywords": [
                    "postgres", "postgresql", "db", "database",
                    "connection", "pool", "conn", "pg",
                ],
                "response": (
                    "QUERY RESULT [postgres-main — connection pool]:\n"
                    "  connections_used:    100 / 100  (POOL EXHAUSTED)\n"
                    "  connections_waiting: 847\n"
                    "  avg_wait_time:       12.4 s\n"
                    "  avg_query_time:      1840 ms  (normal: 12 ms)\n"
                    "  max_connections:     100  (server default — too low)\n"
                    "  \n"
                    "  Root cause: api-gateway v3.2.1 added direct DB calls for\n"
                    "  recommendations without going through the connection pooler.\n"
                    "  Fix: patch_config max_connections on postgres to 200."
                ),
            },
            {
                "keywords": ["auth", "redis", "cache", "user-svc", "user_svc"],
                "response": (
                    "QUERY RESULT [auth-svc + redis-cache + user-svc — health]:\n"
                    "  auth-svc    P95:  45 ms  ✓  error rate: 0.0% ✓\n"
                    "  user-svc    P95:  38 ms  ✓  error rate: 0.1% ✓\n"
                    "  redis-cache P95:   2 ms  ✓  hit rate:  98.2% ✓\n"
                    "  → These services are healthy. Not the bottleneck."
                ),
            },
        ],
        "default_query_response": (
            "QUERY RESULT: No significant anomaly for that target.\n"
            "  Suggestion: query 'api-gateway latency' then 'postgres connections' "
            "to trace the upstream bottleneck."
        ),
        "fix_results": {
            "correct": (
                "SUCCESS: postgres-main max_connections patched to 200.\n"
                "  - Connection pool:  45 / 200  (no longer exhausted) ✓\n"
                "  - Connections waiting: 0 ✓\n"
                "  - api-gateway P95 latency: 2340 ms → 87 ms ✓\n"
                "  - Error rate: 8.3% → 0.1% ✓\n"
                "  Recommendation: add PgBouncer as a permanent connection pooler."
            ),
            "wrong": (
                "ERROR: Applied fix had no impact on the latency.\n"
                "  - api-gateway latency still 2340 ms\n"
                "  - postgres-main connection pool still exhausted (100/100)\n"
                "  Hint: The timeout is happening on postgres-main calls. "
                "Query the database connection pool metrics."
            ),
        },
        "max_steps": 12,
    },

    # ──────────────────────────────────────────────────────────────────────────
    # TASK 3 — HARD
    # P1 cascading failure: payment-svc → inventory-svc → order-svc.
    # Root cause: payment-svc v2.2.0 broke the gRPC proto contract (added a
    # required field). Agent must acknowledge, run 3 targeted queries across
    # services, identify the culprit deploy, and roll back payment-svc to v2.1.4.
    # Red herring: a k8s node pool patch happened 5 minutes before the deploy.
    # ──────────────────────────────────────────────────────────────────────────
    "cascading-failure-hard": {
        "incident_id": "INC-2024-003",
        "severity": "P1",
        "service": "payment-svc,inventory-svc,order-svc",
        "alert_title": "P1 CRITICAL: 3 services down — payment/inventory/order cascade",
        "alert_body": (
            "ALERT: CRITICAL — Multiple production services down\n"
            "Severity: P1 | Triggered: 2024-01-15 20:15:00 UTC\n\n"
            "AFFECTED SERVICES:\n"
            "  ✗ payment-svc   — 100% error rate  (gRPC status: UNIMPLEMENTED)\n"
            "  ✗ inventory-svc —  87% error rate  (circuit breaker OPEN)\n"
            "  ✗ order-svc     — 100% error rate  (upstream cascade failure)\n\n"
            "TIMELINE:\n"
            "  20:00 — k8s node pool patch applied (worker-1, worker-2, worker-3)\n"
            "  20:02 — k8s patch COMPLETED — all nodes healthy\n"
            "  20:05 — payment-svc v2.2.0 deployed (gRPC proto update: PaymentRequest v2)\n"
            "  20:07 — payment-svc health checks PASSING\n"
            "  20:12 — inventory-svc: gRPC UNIMPLEMENTED calling payment-svc\n"
            "  20:14 — order-svc: 100% error rate (inventory unavailable)\n"
            "  20:15 — P1 alert fired\n\n"
            "Revenue impact: ~$12,000 / minute\n"
            "Runbook: https://wiki.internal/runbooks/cascading-failure"
        ),
        "metrics_snapshot": {
            "order_svc.error_rate_pct": 100.0,
            "order_svc.rps": 0.0,
            "order_svc.last_success_ago_sec": 180,
            "inventory_svc.error_rate_pct": 87.3,
            "inventory_svc.grpc_error_code": "UNIMPLEMENTED",
            "inventory_svc.circuit_breaker_state": "OPEN",
            "payment_svc.error_rate_pct": 100.0,
            "payment_svc.rps": 0.0,
            "payment_svc.current_version": "v2.2.0",
            "payment_svc.previous_stable_version": "v2.1.4",
            "payment_svc.deploy_minutes_ago": 10,
            "k8s.node_pool_patch_status": "completed",
            "k8s.nodes_ready": 3,
            "k8s.nodes_total": 3,
            "k8s.pod_evictions_last_hour": 0,
        },
        "recent_events": [
            "[20:00:15] k8s: Node pool patch STARTED (worker-1, worker-2, worker-3)",
            "[20:02:30] k8s: Node pool patch COMPLETED — all 3 nodes Ready, 0 evictions",
            "[20:05:11] payment-svc: Deploying v2.2.0 (gRPC proto PaymentRequest v2: adds required loyalty_points field)",
            "[20:07:23] payment-svc: v2.2.0 health checks PASSING — rollout complete",
            "[20:12:05] inventory-svc: gRPC error UNIMPLEMENTED calling payment-svc.ProcessPayment",
            "[20:12:06] inventory-svc: circuit breaker OPEN for payment-svc (error threshold exceeded)",
            "[20:13:45] order-svc: CreateOrder failed — inventory-svc returned DEADLINE_EXCEEDED",
            "[20:14:01] order-svc: error rate 100% — circuit breaker OPEN",
            "[20:14:58] alertmanager: P1 CRITICAL — cascade detected (payment→inventory→order)",
            "[20:15:02] pagerduty: CRITICAL page sent to on-call SRE + Engineering Manager",
        ],
        "runbook": (
            "## P1 Cascading Failure Runbook\n\n"
            "### IMMEDIATE ACTIONS (< 1 min):\n"
            "  1. ACKNOWLEDGE the alert\n"
            "  2. DO NOT rollback everything blindly — identify the root trigger\n"
            "  3. Check the failure timeline for the first affected service\n\n"
            "### Diagnosis:\n"
            "  - gRPC UNIMPLEMENTED = proto contract mismatch between caller and callee\n"
            "  - Pattern: cascade failures start from a single root-cause service\n"
            "  - Check: which service deployed just BEFORE errors started?\n"
            "  - Note: k8s node patches are infrastructure — check if pods were disrupted\n\n"
            "### Rollback decision:\n"
            "  - If recent service deploy is culprit → rollback to last stable version\n"
            "  - k8s patch completed with 0 evictions — infrastructure is NOT the cause\n"
            "  - payment-svc v2.1.4 is the last known-good version\n\n"
            "### Rollback procedure:\n"
            "  apply_fix with action=rollback, service=<service>, to_version=<version>\n\n"
            "### Post-incident (within 24 h):\n"
            "  - Add proto breaking-change detection to CI pipeline\n"
            "  - Enforce backward-compatibility windows for gRPC proto changes"
        ),
        "hint": (
            "Two events happened before the cascade: a k8s node patch (finished cleanly) "
            "and a payment-svc deploy. The gRPC UNIMPLEMENTED error points to a proto "
            "contract break. Query each affected service to trace the cascade."
        ),
        "grading": {
            # Reward weights (sum to 1.0 on perfect run)
            "acknowledge_reward": 0.05,
            "payment_query_reward": 0.08,
            "inventory_query_reward": 0.07,
            "order_query_reward": 0.05,
            "max_rewarded_payment_queries": 1,
            "max_rewarded_inventory_queries": 1,
            "max_rewarded_order_queries": 1,
            "correct_fix_reward": 0.50,
            "resolve_reward": 0.25,
            # Penalties
            "wrong_fix_penalty": -0.15,   # steeper for P1
            "early_resolve_penalty": -0.15,
            "time_penalty_per_step": -0.03,   # steeper — P1 urgency
            "time_penalty_start_step": 6,
            # Correct fix: rollback payment-svc to v2.1.4
            "correct_fix": {
                "command": "apply_fix",
                "required_params": {
                    "action": "rollback",
                    "service": "payment-svc",
                    "to_version": "v2.1.4",
                },
            },
            # Keyword buckets per service
            "relevant_query_keywords_payment": [
                "payment", "payment-svc", "payment_svc",
            ],
            "relevant_query_keywords_inventory": [
                "inventory", "inventory-svc", "inventory_svc",
            ],
            "relevant_query_keywords_order": [
                "order", "order-svc", "order_svc",
            ],
        },
        "query_responses": [
            {
                "keywords": ["payment", "payment-svc", "payment_svc"],
                "response": (
                    "QUERY RESULT [payment-svc — error analysis]:\n"
                    "  error_rate:         100%\n"
                    "  grpc_error:         UNIMPLEMENTED\n"
                    "  current_version:    v2.2.0  (deployed 10 min ago)\n"
                    "  previous_stable:    v2.1.4\n"
                    "  v2.2.0 changelog:   'PaymentRequest proto v2 — added required field\n"
                    "                       loyalty_points (integer). Callers must update.'\n"
                    "  callers_not_updated: inventory-svc, checkout-svc (still on proto v1)\n"
                    "  \n"
                    "  → ROOT CAUSE: v2.2.0 introduced a breaking proto change.\n"
                    "    Rollback to v2.1.4 will restore compatibility."
                ),
            },
            {
                "keywords": ["inventory", "inventory-svc", "inventory_svc"],
                "response": (
                    "QUERY RESULT [inventory-svc — error analysis]:\n"
                    "  error_rate:          87.3%\n"
                    "  grpc_error:          UNIMPLEMENTED (calling payment-svc.ProcessPayment)\n"
                    "  circuit_breaker:     OPEN for payment-svc\n"
                    "  inventory-svc_deploy: 3 days ago (v4.1.0 — stable)\n"
                    "  \n"
                    "  → inventory-svc is a victim, not the root cause.\n"
                    "    It cannot call payment-svc due to the proto mismatch."
                ),
            },
            {
                "keywords": ["order", "order-svc", "order_svc"],
                "response": (
                    "QUERY RESULT [order-svc — error analysis]:\n"
                    "  error_rate:       100%\n"
                    "  failure_chain:    order-svc → inventory-svc (unavailable) → payment-svc (UNIMPLEMENTED)\n"
                    "  order-svc_deploy: 5 days ago (v6.3.2 — stable)\n"
                    "  \n"
                    "  → order-svc is a victim of the cascade.\n"
                    "    Root cause is upstream: fix payment-svc to restore the chain."
                ),
            },
            {
                "keywords": ["k8s", "node", "kubernetes", "cluster", "worker", "infrastructure", "infra"],
                "response": (
                    "QUERY RESULT [k8s cluster — node health]:\n"
                    "  node_patch_status:  COMPLETED at 20:02:30 ✓\n"
                    "  nodes_ready:        3 / 3 ✓\n"
                    "  pod_evictions:      0 during patch ✓\n"
                    "  pod_disruptions:    0 ✓\n"
                    "  \n"
                    "  → k8s node patch is NOT the root cause.\n"
                    "    Infrastructure is fully healthy."
                ),
            },
        ],
        "default_query_response": (
            "QUERY RESULT: No significant anomaly for that target.\n"
            "  Suggestion: query 'payment-svc', 'inventory-svc', or 'order-svc' "
            "to trace the cascade root cause."
        ),
        "fix_results": {
            "correct": (
                "SUCCESS: payment-svc rolled back to v2.1.4.\n"
                "  - payment-svc error rate:   100% → 0%  ✓\n"
                "  - inventory-svc CB:          OPEN → CLOSED ✓\n"
                "  - inventory-svc error rate:  87% → 0.2% ✓\n"
                "  - order-svc error rate:      100% → 0.0% ✓\n"
                "  All services nominal. Revenue impact resolved.\n"
                "  Action required: file postmortem + add proto compat checks to CI."
            ),
            "wrong": (
                "ERROR: Applied fix did not stop the cascade.\n"
                "  - payment-svc still returning UNIMPLEMENTED\n"
                "  - inventory-svc circuit breaker still OPEN\n"
                "  - order-svc still failing\n"
                "  Hint: The gRPC UNIMPLEMENTED errors point to a proto contract break "
                "in the most recently deployed service. Roll back that service to its "
                "previous stable version."
            ),
        },
        "max_steps": 15,
    },
}

# Ordered list for the inference script
TASK_NAMES = list(SCENARIOS.keys())
