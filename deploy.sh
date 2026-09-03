#!/usr/bin/env bash
#
# Cold Storage — single-container deploy behind an existing reverse proxy.
#
# Writes .env (generating a secret key on first run), joins the proxy's Docker
# network, brings the stack up, waits for it to report healthy, and prints the
# Caddyfile block to paste into your existing Caddyfile.
#
# Safe to re-run: an existing secret key is never regenerated, and an existing
# .env is only added to, never rewritten.
#
#   ./deploy.sh                                 # interactive on first run
#   ./deploy.sh --domain coldstorage.example.com
#   ./deploy.sh --domain cs.example.com --network my-proxy-net
#   ./deploy.sh --host-port                     # proxy runs on the host
#
set -euo pipefail

cd "$(dirname "$0")"

ENV_FILE=".env"
ADDENDUM_FILE="Caddyfile.addendum"
COMPOSE_FILES=(-f docker-compose.yml)

DOMAIN=""
NETWORK=""
HOST_PORT=0
DO_BUILD=1

# --- output helpers --------------------------------------------------------
if [ -t 1 ]; then
    B=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
    RED=$'\033[31m'; R=$'\033[0m'
else
    B=""; DIM=""; GREEN=""; YELLOW=""; RED=""; R=""
fi
step() { printf '%s==>%s %s\n' "$B" "$R" "$*"; }
ok()   { printf '  %s✓%s %s\n' "$GREEN" "$R" "$*"; }
warn() { printf '  %s!%s %s\n' "$YELLOW" "$R" "$*" >&2; }
die()  { printf '%serror:%s %s\n' "$RED" "$R" "$*" >&2; exit 1; }

usage() {
    sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --domain)    DOMAIN="${2:-}"; shift 2 ;;
        --domain=*)  DOMAIN="${1#*=}"; shift ;;
        --network)   NETWORK="${2:-}"; shift 2 ;;
        --network=*) NETWORK="${1#*=}"; shift ;;
        --host-port) HOST_PORT=1; shift ;;
        --no-build)  DO_BUILD=0; shift ;;
        -h|--help)   usage 0 ;;
        *)           printf 'unknown option: %s\n\n' "$1" >&2; usage 1 ;;
    esac
done

[ "$HOST_PORT" -eq 1 ] && COMPOSE_FILES+=(-f docker-compose.hostport.yml)

# --- preflight -------------------------------------------------------------
step "Checking prerequisites"
command -v docker >/dev/null 2>&1 || die "docker is not installed or not on PATH."
docker compose version >/dev/null 2>&1 \
    || die "the docker compose plugin is missing (this needs Compose v2, not docker-compose)."
docker info >/dev/null 2>&1 \
    || die "cannot reach the Docker daemon. Is it running, and can this user talk to it?"
ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '(version unknown)')"

# --- .env helpers ----------------------------------------------------------
env_get() {
    # Read a value from .env without sourcing it — .env is data, not script.
    [ -f "$ENV_FILE" ] || return 0
    sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1
}
env_set() {
    local key="$1" value="$2"
    if [ -f "$ENV_FILE" ] && grep -q "^${key}=" "$ENV_FILE"; then
        # Rewrite in place via a temp file; sed -i is not portable to BSD.
        awk -v k="$key" -v v="$value" \
            'BEGIN{FS=OFS="="} $1==k {print k "=" v; next} {print}' \
            "$ENV_FILE" > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
    else
        printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    fi
}

generate_secret_key() {
    if command -v python3 >/dev/null 2>&1; then
        python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
    elif command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 64 | tr -d '\n=' | tr '+/' '-_'
    else
        die "need python3 or openssl to generate a secret key, or set DJANGO_SECRET_KEY in $ENV_FILE yourself."
    fi
}

# --- detect the reverse proxy ---------------------------------------------
detect_proxy_container() {
    docker ps --format '{{.Names}}\t{{.Image}}' 2>/dev/null \
        | awk -F'\t' 'tolower($1) ~ /caddy/ || tolower($2) ~ /caddy/ {print $1; exit}'
}
container_network() {
    # First attached network that is not one of Docker's built-ins.
    docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' "$1" 2>/dev/null \
        | grep -vE '^(bridge|host|none)$' | head -n1
}

step "Configuring"

# Domain -------------------------------------------------------------------
if [ -z "$DOMAIN" ]; then
    existing_hosts="$(env_get DJANGO_ALLOWED_HOSTS)"
    # First entry of ALLOWED_HOSTS is the public domain.
    DOMAIN="${existing_hosts%%,*}"
fi
if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "coldstorage.example.com" ]; then
    if [ -t 0 ]; then
        printf '  Public domain the proxy will serve (e.g. coldstorage.example.com): '
        read -r DOMAIN
    fi
fi
[ -n "$DOMAIN" ] || die "no domain given. Pass --domain <host>, or set DJANGO_ALLOWED_HOSTS in $ENV_FILE."
case "$DOMAIN" in
    *://*) die "give a bare hostname, not a URL: ${DOMAIN#*://}" ;;
    */*)   die "give a bare hostname, without a path: ${DOMAIN%%/*}" ;;
esac

# Only now that the input is good is anything written to disk.
[ -f "$ENV_FILE" ] && ok "using existing $ENV_FILE" || ok "creating $ENV_FILE"
ok "domain: $DOMAIN"

# Secret key ---------------------------------------------------------------
if [ -n "$(env_get DJANGO_SECRET_KEY)" ]; then
    ok "secret key: keeping the existing one"
else
    env_set DJANGO_SECRET_KEY "$(generate_secret_key)"
    ok "secret key: generated a new one"
fi

# Hosts and CSRF -----------------------------------------------------------
# localhost stays in the list so the container's own healthcheck is not
# rejected with 400 DisallowedHost.
env_set DJANGO_ALLOWED_HOSTS "${DOMAIN},localhost,127.0.0.1"
env_set DJANGO_CSRF_TRUSTED_ORIGINS "https://${DOMAIN}"
env_set DJANGO_DEBUG "0"
ok "allowed hosts + CSRF origin set for https://${DOMAIN}"

# Proxy network ------------------------------------------------------------
PROXY_CONTAINER=""
if [ "$HOST_PORT" -eq 1 ]; then
    ok "host-port mode: publishing on ${PUBLISH_BIND:-127.0.0.1}:${PUBLISH_PORT:-8000}"
    # No shared proxy network in this mode, but compose still needs a network
    # to attach the service to, so let it create and own a private one.
    NETWORK="${NETWORK:-$(env_get PROXY_NETWORK)}"
    NETWORK="${NETWORK:-coldstorage-internal}"
    env_set PROXY_NETWORK "$NETWORK"
    env_set PROXY_NETWORK_EXTERNAL "false"
else
    if [ -z "$NETWORK" ]; then
        NETWORK="$(env_get PROXY_NETWORK)"
    fi
    if [ -z "$NETWORK" ]; then
        PROXY_CONTAINER="$(detect_proxy_container)"
        if [ -n "$PROXY_CONTAINER" ]; then
            NETWORK="$(container_network "$PROXY_CONTAINER")"
            [ -n "$NETWORK" ] && ok "found proxy container '$PROXY_CONTAINER' on network '$NETWORK'"
        fi
    fi
    if [ -z "$NETWORK" ]; then
        NETWORK="caddy"
        warn "no running Caddy container found; defaulting to network '$NETWORK'."
        warn "override with --network <name> if your proxy uses a different one."
    fi

    if docker network inspect "$NETWORK" >/dev/null 2>&1; then
        env_set PROXY_NETWORK_EXTERNAL "true"
        ok "network '$NETWORK' exists — joining it"
    else
        docker network create "$NETWORK" >/dev/null
        env_set PROXY_NETWORK_EXTERNAL "true"
        ok "network '$NETWORK' did not exist — created it"
        warn "your proxy is not on it yet: docker network connect $NETWORK <your-caddy-container>"
    fi
    env_set PROXY_NETWORK "$NETWORK"
fi

SERVICE_NAME="$(env_get COMPOSE_SERVICE_NAME)"
[ -n "$SERVICE_NAME" ] || { SERVICE_NAME="coldstorage"; env_set COMPOSE_SERVICE_NAME "$SERVICE_NAME"; }

chmod 600 "$ENV_FILE"

# --- bring it up -----------------------------------------------------------
if [ "$DO_BUILD" -eq 1 ]; then
    step "Building the image"
    docker compose "${COMPOSE_FILES[@]}" build
fi

step "Starting the container"
docker compose "${COMPOSE_FILES[@]}" up -d --remove-orphans

# --- wait for health -------------------------------------------------------
step "Waiting for the container to report healthy"
CID="$(docker compose "${COMPOSE_FILES[@]}" ps -q "$SERVICE_NAME" 2>/dev/null || true)"
[ -n "$CID" ] || CID="$(docker compose "${COMPOSE_FILES[@]}" ps -q coldstorage 2>/dev/null || true)"

if [ -z "$CID" ]; then
    warn "could not resolve the container id; skipping the health wait."
else
    deadline=$(( $(date +%s) + 120 ))
    status="starting"
    while [ "$(date +%s)" -lt "$deadline" ]; do
        status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CID" 2>/dev/null || echo gone)"
        case "$status" in
            healthy) break ;;
            none)    break ;;
            gone|unhealthy)
                printf '\n'
                docker compose "${COMPOSE_FILES[@]}" logs --tail 40 "$SERVICE_NAME" || true
                die "container is $status. Logs above."
                ;;
        esac
        printf '.'
        sleep 3
    done
    printf '\n'
    case "$status" in
        healthy) ok "healthy" ;;
        none)    warn "image reports no healthcheck; assuming it started." ;;
        *)       docker compose "${COMPOSE_FILES[@]}" logs --tail 40 "$SERVICE_NAME" || true
                 die "timed out waiting for a healthy container. Logs above." ;;
    esac
fi

# --- superuser -------------------------------------------------------------
if [ -t 0 ]; then
    has_user="$(docker compose "${COMPOSE_FILES[@]}" exec -T "$SERVICE_NAME" \
        python manage.py shell -c \
        'from django.contrib.auth import get_user_model; print(get_user_model().objects.filter(is_superuser=True).exists())' \
        2>/dev/null | tr -d '\r\n' || echo unknown)"
    if [ "$has_user" = "False" ]; then
        step "No admin account exists yet"
        printf '  Create one now? [Y/n] '
        read -r reply
        case "$reply" in
            ''|[Yy]*) docker compose "${COMPOSE_FILES[@]}" exec "$SERVICE_NAME" \
                          python manage.py createsuperuser || warn "superuser creation did not complete." ;;
            *) warn "skipped. Later: docker compose exec $SERVICE_NAME python manage.py createsuperuser" ;;
        esac
    fi
fi

# --- the Caddyfile addendum ------------------------------------------------
if [ "$HOST_PORT" -eq 1 ]; then
    UPSTREAM="127.0.0.1:${PUBLISH_PORT:-8000}"
    UPSTREAM_NOTE="# The app publishes 127.0.0.1:${PUBLISH_PORT:-8000} on this host."
else
    UPSTREAM="${SERVICE_NAME}:8000"
    UPSTREAM_NOTE="# Caddy must be attached to the '${NETWORK}' Docker network to resolve
# '${SERVICE_NAME}' by name. If it is not:
#     docker network connect ${NETWORK} <your-caddy-container>"
fi

cat > "$ADDENDUM_FILE" <<EOF
# ---------------------------------------------------------------------------
# Cold Storage — add this block to your Caddyfile, then: caddy reload
#
${UPSTREAM_NOTE}
#
# Caddy sets X-Forwarded-Proto automatically, which is what lets Django know
# the original request was HTTPS. Without it the app redirects every request
# back to https:// and the proxy loops.
# ---------------------------------------------------------------------------
${DOMAIN} {
	reverse_proxy ${UPSTREAM}

	encode zstd gzip

	# Uncomment if you upload large archives through the web UI; Caddy streams
	# request bodies but this caps them explicitly.
	# request_body {
	# 	max_size 10GB
	# }
}
EOF

printf '\n'
step "Deployed"
if [ "$HOST_PORT" -eq 1 ]; then
    printf '  %sservice%s   %s (published on %s — reachable from this host only)\n' \
        "$DIM" "$R" "$SERVICE_NAME" "$UPSTREAM"
else
    printf '  %sservice%s   %s (no host port; reachable at %s on the %s network)\n' \
        "$DIM" "$R" "$SERVICE_NAME" "$UPSTREAM" "$NETWORK"
fi
printf '  %surl%s       https://%s\n' "$DIM" "$R" "$DOMAIN"
printf '  %shealth%s    https://%s/healthz/\n' "$DIM" "$R" "$DOMAIN"
printf '  %sadmin%s     https://%s/admin/\n' "$DIM" "$R" "$DOMAIN"
printf '  %slogs%s      docker compose logs -f %s\n' "$DIM" "$R" "$SERVICE_NAME"
printf '\n'
step "Caddyfile addendum ${DIM}(also written to ${ADDENDUM_FILE})${R}"
printf '\n'
cat "$ADDENDUM_FILE"
printf '\n'
