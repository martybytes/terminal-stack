ARG HEADROOM_IMAGE=ghcr.io/headroomlabs-ai/headroom:0.36.5
FROM ${HEADROOM_IMAGE}

# Headroom 0.36.5 checks the provider Authorization bearer before its dedicated
# proxy-token header. OAuth clients therefore cannot authenticate to both the
# proxy and provider. Apply the reviewed one-function fix without rebuilding
# the large upstream image from source.
RUN python -c 'from pathlib import Path; p = Path("/usr/local/lib/python3.13/site-packages/headroom/proxy/server.py"); s = p.read_text(); old = """    def _extract_proxy_token(headers) -> str | None:\n        auth = str(headers.get(\"authorization\") or \"\")\n        if auth.lower().startswith(\"bearer \"):\n            return auth[7:].strip() or None\n        raw = headers.get(\"x-headroom-proxy-token\")\n        return str(raw) if raw else None\n"""; new = """    def _extract_proxy_token(headers) -> str | None:\n        raw = headers.get(\"x-headroom-proxy-token\")\n        if raw:\n            return str(raw)\n        auth = str(headers.get(\"authorization\") or \"\")\n        if auth.lower().startswith(\"bearer \"):\n            return auth[7:].strip() or None\n        return None\n"""; assert s.count(old) == 1, "upstream auth gate changed; review patch"; p.write_text(s.replace(old, new))'
