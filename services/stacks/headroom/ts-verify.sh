#!/usr/bin/env bash
# ts-verify.sh — headroom: prove the proxy is not just up, but enforcing.
# Run by `tstack services test`; safe to run by hand. Exit 0 = pass.
#
# Windows twin: ts-verify.ps1. Change one, change the other.
#
# "Up (healthy)" is not evidence for this stack. The interesting failure is a
# proxy that answers /readyz while accepting UNAUTHENTICATED /v1 traffic, which
# looks perfectly healthy from the outside and is an open data plane.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
# shellcheck source=../../_stack.sh
. "$ROOT/_stack.sh"

PROXY="${HEADROOM_PROXY_URL:-http://127.0.0.1:8787}"
DASH="${HEADROOM_DASHBOARD_URL:-http://127.0.0.1:8788}"
rc=0

token="$(tss_env_value "$(dirname -- "${BASH_SOURCE[0]}")/.env" HEADROOM_PROXY_TOKEN 2>/dev/null || true)"
[ -n "${token:-}" ] || token="${HEADROOM_PROXY_TOKEN:-}"

# 1. Readiness. /readyz is a genuine readiness endpoint, so 2xx is the right test
#    -- unlike a reachability probe, where any HTTP response means "answering".
if tss_wait_http "$PROXY/readyz" 10 2xx; then pass 'proxy /readyz is 2xx'
else fail "proxy /readyz did not answer 2xx at $PROXY"; rc=1; fi

# 2. The token is ENFORCED. Assert on the BODY, not the status: a refused
#    connection also produces a non-2xx, and would otherwise read as a pass.
body="$(curl -s --max-time 8 -X POST "$PROXY/v1/chat/completions" \
        -H 'content-type: application/json' -d '{"model":"x","messages":[]}' 2>/dev/null || true)"
case "$body" in
    *unauthorized*|*Unauthorized*)
        pass 'unauthenticated /v1 is refused by the proxy' ;;
    '')
        fail 'unauthenticated /v1 returned an empty body — that is a refused connection, not a refusal'
        rc=1 ;;
    *api*key*|*API*key*)
        # Headroom refusing you and the UPSTREAM provider refusing headroom are
        # different outcomes, and only one of them is this stack's problem.
        fail 'unauthenticated /v1 reached the upstream provider — the proxy is NOT enforcing its token'
        rc=1 ;;
    *)
        fail "unauthenticated /v1 answered with something unexpected: $(printf '%.120s' "$body")"
        rc=1 ;;
esac

# 3. The token WORKS.
if [ -z "$token" ]; then
    warn 'no HEADROOM_PROXY_TOKEN in .env or the environment — skipping the authenticated check'
else
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 \
            -H "X-Headroom-Proxy-Token: $token" "$PROXY/stats" 2>/dev/null || echo 000)"
    case "$code" in
        2??) pass 'authenticated /stats is 2xx' ;;
        000) fail "no response from $PROXY/stats"; rc=1 ;;
        *)   fail "authenticated /stats answered $code — the token in .env does not match the running proxy"; rc=1 ;;
    esac
fi

# 4. The dashboard gateway injects the token server-side, so it must work with NO
#    headers set. That is the whole reason it exists.
if tss_wait_http "$DASH/dashboard" 8 2xx; then pass 'dashboard is reachable without a token'
else fail "dashboard did not answer 2xx at $DASH/dashboard"; rc=1; fi

exit $rc
