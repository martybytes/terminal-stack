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
# Then it execs the agentmemory CLI under gosu as the unprivileged
# `node` user.

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
      sampling_ratio: 1.0
      metrics_enabled: true
      logs_enabled: true
      logs_console_output: true
EOF
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

exec gosu "$RUN_AS" agentmemory "$@"
