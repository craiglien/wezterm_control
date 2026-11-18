#!/usr/bin/env bash
# Start a dedicated agent WezTerm (one window, one bash pane titled `agent`) under a unique name, and print the
# prompt to paste into the Claude Code session that will drive it.
#   start_wezterm.sh [NAME]     start instance NAME (default: default); fails if NAME is already running
#   start_wezterm.sh --list     show running instances
# Run it from a terminal OUTSIDE WezTerm. The instance runs with `--class wezctl-NAME`; the helper finds it by that.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
state_dir="${WEZ_STATE_DIR:-$HOME/.cache/wez_expect}"

command -v wezterm >/dev/null || { echo "wezterm not found on PATH" >&2; exit 1; }

# Socket of the GUI started with --class wezctl-NAME ("--always-new-process" makes no class symlink, so match the process).
sock_for() {
  local pid
  pid="$(ps -axo pid=,command= | awk -v c="--class wezctl-$1" 'index($0,"wezterm-gui") && substr($0,length($0)-length(c)+1)==c {print $1; exit}')"
  [[ -n "$pid" && -S "$HOME/.local/share/wezterm/gui-sock-$pid" ]] && echo "$HOME/.local/share/wezterm/gui-sock-$pid"
}
running() { [[ -n "$(sock_for "$1")" ]]; }
wcli() { WEZTERM_UNIX_SOCKET="$(sock_for "$name")" wezterm cli --no-auto-start "$@"; }

if [[ "${1:-}" == "--list" ]]; then
  ps -axo command= | awk 'index($0,"wezterm-gui") && match($0,/--class wezctl-[A-Za-z0-9_-]+$/) {print substr($0,RSTART+15)}'
  exit 0
fi

name="${1:-default}"
[[ "$name" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "bad name '$name': use letters, digits, - and _" >&2; exit 1; }
[[ -z "${WEZTERM_PANE:-}" ]] || { echo "run this from a terminal outside WezTerm" >&2; exit 1; }
mkdir -p "$state_dir"

if running "$name"; then
  echo "instance '$name' is already running; pick another name (running: $(bash "$0" --list | tr '\n' ' '))" >&2
  exit 1
fi

WEZ_CONTROL_DIR="$root" nohup wezterm --config-file "$root/wezterm/agent_wezterm.lua" \
  start --always-new-process --class "wezctl-$name" >"$state_dir/wezterm.$name.log" 2>&1 &
disown

# Verify the layout: exactly one pane, titled agent, running bash.
panes=""
for _ in $(seq 1 40); do
  panes="$(wcli list --format json 2>/dev/null || true)"
  [[ "$panes" == *'"title": "agent"'* ]] && break
  sleep 0.5
done
count="$(grep -c '"pane_id"' <<<"$panes" || true)"
tty="$(grep -o '"tty_name": "[^"]*"' <<<"$panes" | head -1 | cut -d'"' -f4)"
cmd="$(ps -t "${tty#/dev/}" -o command= 2>/dev/null | head -1)"
if [[ "$count" != 1 || "$cmd" != bash* ]]; then
  echo "UNEXPECTED layout: panes=$count tty=$tty process='$cmd' (log: $state_dir/wezterm.$name.log)" >&2
  exit 1
fi
echo "OK: instance '$name', 1 pane titled 'agent' on $tty running: $cmd"

prompt="$state_dir/$name.prompt"
cat >"$prompt" <<EOF
Use the WezTerm instance "$name". Read $root/AGENTS.md first.
Every helper call must carry WEZ_INSTANCE=$name; start each task with:
  P=\$(WEZ_INSTANCE=$name uv run --no-project python3 -I $root/scripts/wez_expect.py ensure --cwd "\$PWD")
Stop and ask me before any destructive command, and on any unexpected prompt or timeout.
EOF
echo
echo "--- paste into the Claude Code session (also saved to $prompt) ---"
cat "$prompt"
