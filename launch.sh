#!/usr/bin/env bash
# ---------------------------------------------------------------------------------------------
#  General Autonomy x Ouster live lidar perception demo: single-file launcher
# ---------------------------------------------------------------------------------------------
#  QUICK START (Linux PC wired to the sensor)
#
#      ./launch.sh                       # start (uses OUSTER_SOURCE from .env, else 169.254.43.8)
#      ./launch.sh 192.168.1.50          # start against a specific sensor IP / hostname
#      -> open  http://genauto.localhost          (any *.localhost name resolves to this PC)
#         other machine on the LAN:  http://<this-pc-ip>
#
#  OTHER COMMANDS
#      ./launch.sh stop                  # turn it off
#      ./launch.sh status                # is it running / streaming?
#      ./launch.sh logs                  # follow logs
#      ./launch.sh doctor [ip]           # step-by-step connection diagnosis (DNS/ping/HTTP/UDP/SDK)
#      ./launch.sh discover              # find Ouster sensors on the network
#      ./launch.sh native [ip]           # no Docker: run in a local Python venv instead
#
#  REQUIREMENTS    Docker (with the compose plugin), or Python >= 3.9 for `native`.
#                  Sensor reachable from this PC (ping it). Direct cable with no DHCP => the sensor uses
#                  a link-local 169.254.x.x address; `ip neigh` / `./launch.sh discover` shows it.
#  NOTES
#    * The container uses host networking (required for sensor UDP), so it is Linux-only.
#    * Port 80 is used by default. Change it with PORT=8080 ./launch.sh  (then use http://genauto.localhost:8080).
#    * Sensor firmware < 2.2 (e.g. 2.1.2) only works with ouster-sdk 0.12.0 - already pinned.
#    * Troubleshooting playbook: docs/LAB_DEBUG.md
# ---------------------------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

DEFAULT_SENSOR="169.254.43.8"
PORT="${PORT:-80}"
IMAGE_CONTAINER="ouster-demo"

say()  { printf '\033[1;38;5;208m▌\033[0m %s\n' "$*"; }
die()  { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
need_docker() {
  command -v docker >/dev/null || die "docker not found. Install Docker, or use: ./launch.sh native"
  docker info >/dev/null 2>&1 || die "cannot talk to the Docker daemon (is it running? are you in the 'docker' group?)"
}
env_get() { [ -f .env ] && grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }
resolve_sensor() {
  local s="${1:-}"
  [ -z "$s" ] && s="${OUSTER_SOURCE:-}"
  [ -z "$s" ] && s="$(env_get OUSTER_SOURCE)"
  [ -z "$s" ] && s="$DEFAULT_SENSOR"
  echo "$s"
}
write_env() {  # persist the choice so a plain `./launch.sh` next time reuses it
  printf 'OUSTER_SOURCE=%s\nPORT=%s\n' "$1" "$PORT" > .env
}
url() { [ "$PORT" = "80" ] && echo "http://genauto.localhost" || echo "http://genauto.localhost:$PORT"; }

wait_streaming() {
  say "waiting for the sensor stream (the SDK reconfigures the sensor on first connect, ~10-30 s)..."
  for _ in $(seq 1 60); do
    st="$(curl -fsS "http://127.0.0.1:$PORT/api/status" 2>/dev/null || true)"
    state="$(printf '%s' "$st" | sed -n 's/.*"state":"\([a-z]*\)".*/\1/p')"
    case "$state" in
      streaming) say "STREAMING  ->  $(url)"; return 0 ;;
      error)     printf '%s\n' "$st" | sed -n 's/.*"message":"\([^"]*\)".*/\1/p' | sed 's/^/   sensor error: /'; ;;
    esac
    sleep 2
  done
  say "not streaming yet. Check:  ./launch.sh logs   or   ./launch.sh doctor"
  return 1
}

cmd="${1:-start}"
case "$cmd" in
  stop)
    need_docker
    docker compose down 2>/dev/null || docker rm -f "$IMAGE_CONTAINER" 2>/dev/null || true
    pkill -f "ouster-demo --source" 2>/dev/null || true
    say "stopped"
    ;;
  status)
    if curl -fsS "http://127.0.0.1:$PORT/api/status" 2>/dev/null; then echo; else say "not running (or not on port $PORT)"; fi
    command -v docker >/dev/null && docker ps --filter "name=$IMAGE_CONTAINER" --format 'container: {{.Names}} {{.Status}}' || true
    ;;
  logs)
    need_docker; docker compose logs -f --tail=100
    ;;
  doctor)
    need_docker
    S="$(resolve_sensor "${2:-}")"
    docker build -q -t ouster-demo:latest . >/dev/null
    docker rm -f "$IMAGE_CONTAINER" >/dev/null 2>&1 || true   # free UDP 7502 for the test
    docker run --rm --network host ouster-demo:latest doctor "$S" --sdk
    ;;
  discover)
    need_docker
    docker build -q -t ouster-demo:latest . >/dev/null
    echo "ARP neighbours that look like Ouster (MAC prefix bc:0f:a7):"; ip neigh | grep -i "bc:0f:a7" || echo "  (none seen yet)"
    docker run --rm --network host ouster-demo:latest discover || true
    ;;
  native)
    S="$(resolve_sensor "${2:-}")"
    [ -d .venv ] || { say "creating venv"; python3 -m venv .venv; .venv/bin/pip install -q -U pip; .venv/bin/pip install -q -e .; }
    say "starting natively against $S  ->  $(url)"
    exec .venv/bin/ouster-demo --source "$S" --port "$PORT"
    ;;
  start|up|*)
    need_docker
    if [ "$cmd" = "start" ] || [ "$cmd" = "up" ]; then ARG="${2:-}"; else ARG="$cmd"; fi   # ./launch.sh [<ip>]
    S="$(resolve_sensor "$ARG")"
    say "sensor: $S   port: $PORT"
    if command -v ping >/dev/null && ! ping -c1 -W2 "$S" >/dev/null 2>&1; then
      say "WARNING: $S does not answer ping. Check cable/power/IP (./launch.sh discover). Starting anyway; the UI will show the error."
    fi
    write_env "$S"
    docker compose up -d --build
    wait_streaming || true
    ;;
esac
