#!/usr/bin/env bash
# configure-openai-billing.sh — validate a dedicated OpenAI billing project and
# write non-secret console settings.
# macOS/Linux twin of configure-openai-billing.ps1 (canonical). Port both ways.
#
# Usage:  ./configure-openai-billing.sh --admin-key-file <path> --project-id <proj_...> [--apply]
#         ./configure-openai-billing.sh --refresh-hints [--apply]
# When:   Setting up project-scoped cost reconciliation, or after rotating
#         either key. Not needed on a vLLM deployment, which bills nothing.
# Note:   Preview by default. No key is printed or copied into .billing.env —
#         only masked fingerprints (first six characters and last four), which
#         cannot authenticate. --refresh-hints re-derives those after a rotation
#         with no Admin key and no network call, so the Admin key's Organization
#         Administration permission can stay at None.
set -euo pipefail

_self="${BASH_SOURCE[0]}"
while [ -L "$_self" ]; do
    _d="$(cd -- "$(dirname -- "$_self")" && pwd)"; _self="$(readlink "$_self")"
    case "$_self" in /*) ;; *) _self="$_d/$_self" ;; esac
done
SCRIPT_DIR="$(cd -- "$(dirname -- "$_self")" && pwd -P)"
# shellcheck source=../../_stack.sh
. "$SCRIPT_DIR/../../_stack.sh"

admin_key_file=''; project_id=''; refresh_hints=0
while [ $# -gt 0 ]; do
    arg="$(tss_normalise_flag "$1")"
    if tss_parse_common_flag "$arg" "${2:-}"; then shift "$TSS_FLAG_CONSUMED"; continue; fi
    case "$arg" in
        --admin-key-file)     admin_key_file="${2:?--admin-key-file needs a value}"; shift 2 ;;
        --project-id)         project_id="${2:?--project-id needs a value}"; shift 2 ;;
        --refresh-hints)      refresh_hints=1; shift ;;
        --inference-key-file) warn '--inference-key-file is deprecated and ignored. Billing is scoped to the dedicated OpenAI project, and the inference key fingerprint is read from the repo-root .env.'; shift 2 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
done

# PowerShell gets mutually exclusive parameter sets for free; bash does not.
if [ "$refresh_hints" = 1 ]; then
    [ -z "$admin_key_file" ] && [ -z "$project_id" ] \
        || die '--refresh-hints takes no --admin-key-file or --project-id (it re-derives fingerprints in place).'
else
    [ -n "$admin_key_file" ] && [ -n "$project_id" ] \
        || die 'need --admin-key-file <path> and --project-id <proj_...>, or --refresh-hints (try --help)'
fi

stack_dir="$SCRIPT_DIR"
output_path="$stack_dir/.billing.env"
root_env_path="$(dirname "$stack_dir")/.env"

# Masked fingerprint for display in the console: the key's own `sk-<role>-`
# prefix, six identifying characters, an ellipsis, and the last four. The same
# head-and-tail shape provider dashboards use, and enough to tell two keys apart
# during a rotation. Not a secret: 10 of ~164 characters.
key_hint() {                              # <key>
    node -e '
      const v=process.argv[1]||"";
      const ell="…";
      const m=v.match(/^(sk-[A-Za-z0-9]+-)(.+)$/);
      const prefix=m?m[1]:"", body=m?m[2]:v;
      // Never emit a fingerprint that covers most of a short or unexpected value.
      process.stdout.write(body.length<24 ? prefix+ell
        : prefix+body.slice(0,6)+ell+body.slice(-4));
    ' "$1"
}

# The inference key has exactly one untracked source: the repo-root .env. Read
# it for its fingerprint only — the key itself never enters .billing.env.
inference_key_hint() {
    local v
    v="$(tss_env_value "$root_env_path" OPENAI_API_KEY 2>/dev/null || true)"
    v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
    [ -n "$v" ] || return 1
    case "$v" in *replace-me*|'sk-proj-...'*) return 1 ;; esac
    key_hint "$v"
}

# One writer so line order stays stable and a rotation produces a minimal diff.
# LF, not [Environment]::NewLine (CRLF on Windows): .billing.env is gitignored
# so it never reaches the repo, but keeping it LF here means the file does not
# flip line endings when the same machine is driven from both script sets.
write_billing_env() {                     # <id> <name-json> <admin-host-path> <admin-hint> <inference-hint>
    {
        printf 'OPENAI_BILLING_PROJECT_ID=%s\n' "$1"
        printf 'OPENAI_BILLING_PROJECT_NAME=%s\n' "$2"
        printf 'OPENAI_ADMIN_KEY_FILE=/run/secrets/openai-admin-key\n'
        printf 'OPENAI_ADMIN_KEY_FILE_HOST=%s\n' "$3"
        [ -n "$4" ] && printf 'LLM_ADMIN_KEY_HINT=%s\n' "$4"
        [ -n "$5" ] && printf 'LLM_API_KEY_HINT=%s\n' "$5"
        true
    } > "$output_path"
}

# ---------------------------------------------------------------------------
# --refresh-hints: re-derive both fingerprints in place after a key rotation.
# ---------------------------------------------------------------------------
if [ "$refresh_hints" = 1 ]; then
    [ -f "$output_path" ] || die "No $output_path to refresh. Run this script with --admin-key-file and --project-id first."
    existing_id="$(tss_env_value "$output_path" OPENAI_BILLING_PROJECT_ID 2>/dev/null || true)"
    existing_name="$(tss_env_value "$output_path" OPENAI_BILLING_PROJECT_NAME 2>/dev/null || true)"
    admin_host_path="$(tss_env_value "$output_path" OPENAI_ADMIN_KEY_FILE_HOST 2>/dev/null || true)"
    [ -n "$existing_id" ] || die "$output_path has no OPENAI_BILLING_PROJECT_ID — re-run full configuration."
    [ -n "$admin_host_path" ] || die "$output_path has no OPENAI_ADMIN_KEY_FILE_HOST — re-run full configuration."
    [ -n "$existing_name" ] || existing_name="$(json_str 'OpenAI project')"

    admin_hint=''
    if [ -f "$admin_host_path" ]; then
        admin_value="$(tss_read_raw_secret "$admin_host_path" 'Admin key')" || die 'Admin key file rejected.'
        admin_hint="$(key_hint "$admin_value")"
    else
        warn "Admin key file not found at $admin_host_path — leaving LLM_ADMIN_KEY_HINT unset."
    fi
    inference_hint="$(inference_key_hint || true)"
    [ -n "$inference_hint" ] || warn "No usable OPENAI_API_KEY in $root_env_path — leaving LLM_API_KEY_HINT unset."

    info "Inference key fingerprint: ${inference_hint:-(none)}"
    info "Admin key fingerprint:     ${admin_hint:-(none)}"
    if [ "$TSS_APPLY" != 1 ]; then
        printf '%sPreview only. Re-run with --apply to update .billing.env.%s\n' "$C_YELLOW" "$C_RESET"
        exit 0
    fi
    write_billing_env "$existing_id" "$existing_name" "$admin_host_path" "$admin_hint" "$inference_hint"
    printf '%sRefreshed key fingerprints in %s.%s\n' "$C_GREEN" "$output_path" "$C_RESET"
    printf '%sRecreate the console to pick them up:%s\n' "$C_GREEN" "$C_RESET"
    printf '%sts-stack up agent007memory%s\n' "$C_CYAN" "$C_RESET"
    exit 0
fi

# ---------------------------------------------------------------------------
case "$project_id" in
    proj_*) : ;;
    *) die 'project-id must be an OpenAI project ID beginning with proj_.' ;;
esac
printf '%s' "$project_id" | grep -qE '^proj_[A-Za-z0-9]+$' \
    || die 'project-id must be an OpenAI project ID beginning with proj_.'

admin_value="$(tss_read_raw_secret "$admin_key_file" 'Admin key')" || die 'Admin key file rejected.'
admin_path="$(tss_realpath "$admin_key_file")"

escaped_project_id="$(node -e 'process.stdout.write(encodeURIComponent(process.argv[1]))' "$project_id")"

# This is the one script that puts a real OpenAI Admin key on the wire, so the
# bearer goes in via a curl config file on stdin and never onto argv.
project_json="$(http_get_auth "https://api.openai.com/v1/organization/projects/$escaped_project_id" "$admin_value" 30)" \
    || die 'OpenAI project lookup failed — check the Admin key and the project id.'

read -r got_id got_status <<EOF
$(printf '%s' "$project_json" | node -e '
  let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
    try{const j=JSON.parse(s);process.stdout.write(`${j.id||""} ${j.status||""}`);}
    catch{process.stdout.write(" ");}
  });')
EOF
[ "$got_id" = "$project_id" ] || die 'OpenAI returned a different project than requested.'
[ "$got_status" = active ] || die "OpenAI project is not active (status: $got_status)."

project_name="$(printf '%s' "$project_json" | node -e '
  let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
    try{const j=JSON.parse(s);const n=String(j.name||"").trim();
      if(/[\r\n]/.test(n)) { process.stderr.write("linebreak"); process.exit(3); }
      process.stdout.write(n||"OpenAI project");}
    catch{process.stdout.write("OpenAI project");}
  });')" || die 'OpenAI project name contains unsupported line breaks.'

# Yesterday..midnight-UTC-today, computed in node: the shell has no portable
# way to do UTC date arithmetic (GNU date -d is absent on macOS, BSD date -j -f
# is absent on Linux).
read -r start_time end_time <<EOF
$(node -e '
  const end=Math.floor(Date.parse(new Date().toISOString().slice(0,10)+"T00:00:00Z")/1000);
  process.stdout.write(`${end-86400} ${end}`);')
EOF
cost_url="https://api.openai.com/v1/organization/costs?start_time=$start_time&end_time=$end_time&bucket_width=1d&limit=1&group_by=project_id&project_ids=$escaped_project_id"
http_get_auth "$cost_url" "$admin_value" 30 >/dev/null \
    || die 'project-scoped Costs API call failed — the Admin key needs Organization Administration read at least once.'

admin_hint="$(key_hint "$admin_value")"
inference_hint="$(inference_key_hint || true)"
[ -n "$inference_hint" ] || warn "No usable OPENAI_API_KEY in $root_env_path — leaving LLM_API_KEY_HINT unset."

printf '%sValidated active OpenAI project '\''%s'\'' and project-scoped Costs API access.%s\n' "$C_GREEN" "$project_name" "$C_RESET"
info "Billing settings: $output_path"
info "Inference key fingerprint: ${inference_hint:-(none)}"
info "Admin key fingerprint:     $admin_hint"
if [ "$TSS_APPLY" != 1 ]; then
    printf '%sPreview only. Re-run with --apply to write .billing.env.%s\n' "$C_YELLOW" "$C_RESET"
    exit 0
fi

write_billing_env "$project_id" "$(json_str "$project_name")" "$admin_path" "$admin_hint" "$inference_hint"
printf '%sWrote non-secret project billing settings. Organization Administration may now return to None.%s\n' "$C_GREEN" "$C_RESET"
printf '%sDeploy with:%s\n' "$C_GREEN" "$C_RESET"
printf '%sts-stack up agent007memory%s\n' "$C_CYAN" "$C_RESET"
