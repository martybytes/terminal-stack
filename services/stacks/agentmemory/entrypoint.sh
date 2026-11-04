#!/bin/sh
# agentmemory first-boot entrypoint.
#
# Runs as root so it can:
#   1. Overwrite the npm-bundled iii-config.yaml (which binds 127.0.0.1
#      and uses relative ./data paths) with a deploy-tuned version that
#      binds 0.0.0.0 and uses absolute /data paths.
#   2. chown the platform-mounted /data volume to the runtime user
#      (managed platforms mount volumes root-owned 755 by default).
#   3. Generate the HMAC secret on first boot and persist it to
#      /data/.hmac (chmod 600) so the secret survives restarts.
#
# Then it runs the agentmemory CLI under gosu as the unprivileged
# `node` user and stays as its supervisor: if the iii engine dies, the
# script exits so the container's restart policy brings it back.

set -eu

DATA_DIR="${AGENTMEMORY_DATA_DIR:-/data}"
HMAC_FILE="${AGENTMEMORY_HMAC_FILE:-/data/.hmac}"
RUN_AS="node:node"
III_CONFIG="/opt/agentmemory/node_modules/@agentmemory/agentmemory/dist/iii-config.yaml"

mkdir -p "$DATA_DIR"
chown -R "$RUN_AS" "$DATA_DIR"

cat > "$III_CONFIG" <<'EOF'
workers:
  - name: iii-http
    config:
      port: 3111
      host: 0.0.0.0
      default_timeout: 180000
      cors:
        allowed_origins:
          - "http://localhost:3111"
          - "http://localhost:3113"
          - "http://127.0.0.1:3111"
          - "http://127.0.0.1:3113"
        allowed_methods: [GET, POST, PUT, DELETE, OPTIONS]
  - name: iii-state
    config:
      adapter:
        name: kv
        config:
          store_method: file_based
          file_path: /data/state_store.db
  - name: iii-queue
    config:
      queue_configs:
        agentmemory-llm:
          max_retries: 3
          concurrency: 2
          type: standard
          backoff_ms: 30000
          poll_interval_ms: 100
      adapter:
        name: builtin
        config:
          mode: concurrent
          max_attempts: 3
          backoff_ms: 30000
          concurrency: 2
          poll_interval_ms: 100
          store_method: file_based
          file_path: /data/queue_store
          save_interval_ms: 1000
  - name: iii-pubsub
    config:
      adapter:
        name: local
  - name: iii-cron
    config:
      adapter:
        name: kv
  - name: iii-stream
    config:
      port: 3112
      host: 0.0.0.0
      adapter:
        name: kv
        config:
          store_method: file_based
          file_path: /data/stream_store
  - name: iii-observability
    config:
      enabled: true
      service_name: agentmemory
      exporter: memory
      sampling_ratio: 0.1
      metrics_enabled: true
      logs_enabled: true
      logs_console_output: false
EOF
# The two observability values above match the npm package's own
# iii-config.yaml (upstream #519). At 1.0 with console output on, the
# engine's in-memory exporter grew to 27-29 GB and the kernel OOM killer
# took it three times; agentmemory's own log lines go straight to stderr
# and do not depend on logs_console_output.
chown "$RUN_AS" "$III_CONFIG"

if [ ! -s "$HMAC_FILE" ]; then
  SECRET="$(openssl rand -hex 32)"
  umask 077
  printf '%s\n' "$SECRET" > "$HMAC_FILE"
  chmod 600 "$HMAC_FILE"
  chown "$RUN_AS" "$HMAC_FILE"
  echo "================================================================"
  echo "agentmemory: generated HMAC secret on first boot"
  echo "AGENTMEMORY_SECRET=$SECRET"
  echo "Copy this value now. It will not be printed again."
  echo "Stored at: $HMAC_FILE (chmod 600)"
  echo "To rotate: delete $HMAC_FILE on the persistent volume and restart."
  echo "================================================================"
fi

AGENTMEMORY_SECRET="$(cat "$HMAC_FILE")"
export AGENTMEMORY_SECRET

SKIP_RECOVERY_FILE="/data/.skip-next-llm-recovery"
if [ -e "$SKIP_RECOVERY_FILE" ]; then
  [ -f "$SKIP_RECOVERY_FILE" ] && [ ! -L "$SKIP_RECOVERY_FILE" ] || {
    echo "agentmemory: refusing invalid one-shot recovery marker" >&2
    exit 1
  }
  rm "$SKIP_RECOVERY_FILE"
  AGENTMEMORY_SKIP_STARTUP_RECOVERY_ONCE=true
  export AGENTMEMORY_SKIP_STARTUP_RECOVERY_ONCE
  echo "agentmemory: consumed one-shot startup recovery skip marker"
fi

# Supervise rather than exec. The CLI spawns the iii engine detached and never
# respawns it, so when the engine dies the node worker keeps reconnecting
# forever: the container stays "Up (unhealthy)", restart: unless-stopped never
# fires, and every hook's capture is dropped silently. That ran for 12 days.
# Exiting when the engine is gone hands recovery to the restart policy.
#
# Process death only, never livez: a busy node event loop misses livez for
# whole minutes while healthy (see the healthcheck in docker-compose.yml).
WATCH_SECONDS="${AGENTMEMORY_ENGINE_WATCH_SECONDS:-10}"
START_SECONDS="${AGENTMEMORY_ENGINE_START_SECONDS:-180}"

# No procps in node:22-slim, so read /proc. A pid can vanish mid-scan.
engine_running() {
  for cmdline in /proc/[0-9]*/cmdline; do
    case "$({ tr '\0' ' ' < "$cmdline"; } 2>/dev/null || true)" in
      iii\ --config*|*/iii\ --config*) return 0 ;;
    esac
  done
  return 1
}

stop_agent() {
  kill -TERM "$AGENT_PID" 2>/dev/null || true
  waited=0
  while kill -0 "$AGENT_PID" 2>/dev/null && [ "$waited" -lt 8 ]; do
    sleep 1
    waited=$((waited + 1))
  done
  kill -KILL "$AGENT_PID" 2>/dev/null || true
}

gosu "$RUN_AS" agentmemory "$@" &
AGENT_PID=$!
trap 'stop_agent; exit 143' TERM INT

seen=0
misses=0
elapsed=0
while kill -0 "$AGENT_PID" 2>/dev/null; do
  if engine_running; then
    seen=1
    misses=0
  elif [ "$seen" = 1 ]; then
    # Two consecutive misses, so a scan racing a respawn is not a death.
    misses=$((misses + 1))
    if [ "$misses" -ge 2 ]; then
      echo "agentmemory: iii engine exited; stopping so the restart policy recovers it" >&2
      stop_agent
      exit 1
    fi
  elif [ "$elapsed" -ge "$START_SECONDS" ]; then
    echo "agentmemory: iii engine not running ${START_SECONDS}s after start; stopping" >&2
    stop_agent
    exit 1
  fi
  # Backgrounded so a TERM interrupts the wait instead of queueing behind it.
  sleep "$WATCH_SECONDS" &
  wait $! || true
  elapsed=$((elapsed + WATCH_SECONDS))
done

status=0
wait "$AGENT_PID" || status=$?
exit "$status"
