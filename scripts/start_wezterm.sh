#!/usr/bin/env bash
# Start the dedicated agent WezTerm (one window, one bash pane titled `agent`) and record it for wez_expect.py.
# Run it from a terminal OUTSIDE WezTerm. Refuses if the dedicated instance is already running.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
state_dir="${WEZ_STATE_DIR:-$HOME/.cache/wez_expect}"
state="$state_dir/instance"      # two lines: pid, socket path
sockdir="$HOME/.local/share/wezterm"

command -v wezterm >/dev/null || { echo "wezterm not found on PATH" >&2; exit 1; }
[[ -z "${WEZTERM_PANE:-}" ]] || { echo "run this from a terminal outside WezTerm" >&2; exit 1; }
mkdir -p "$state_dir"

if [[ -f "$state" ]] && kill -0 "$(sed -n 1p "$state")" 2>/dev/null; then
  echo "dedicated WezTerm already running (pid $(sed -n 1p "$state")); quit it first" >&2
  exit 1
fi
rm -f "$state"

before="$(ls "$sockdir"/gui-sock-* 2>/dev/null || true)"
WEZ_CONTROL_DIR="$root" nohup wezterm --config-file "$root/wezterm/agent_wezterm.lua" start --always-new-process \
  >"$state_dir/wezterm.log" 2>&1 &
disown

# The new GUI process creates its own socket; find it by diffing the socket directory.
sock=""
for _ in $(seq 1 40); do
  sock="$(comm -13 <(echo "$before" | sort) <(ls "$sockdir"/gui-sock-* 2>/dev/null | sort) | head -1)"
  [[ -n "$sock" ]] && break
  sleep 0.5
done
[[ -n "$sock" ]] || { echo "WezTerm did not come up; see $state_dir/wezterm.log" >&2; exit 1; }
pid="${sock##*gui-sock-}"
printf '%s\n%s\n' "$pid" "$sock" >"$state"

# Verify the layout: exactly one pane, titled agent, running bash.
panes=""
for _ in $(seq 1 20); do
  panes="$(WEZTERM_UNIX_SOCKET="$sock" wezterm cli list --format json 2>/dev/null || true)"
  [[ "$panes" == *'"title": "agent"'* ]] && break
  sleep 0.5
done
count="$(grep -c '"pane_id"' <<<"$panes" || true)"
tty="$(grep -o '"tty_name": "[^"]*"' <<<"$panes" | head -1 | cut -d'"' -f4)"
cmd="$(ps -t "${tty#/dev/}" -o command= 2>/dev/null | head -1)"
if [[ "$count" == 1 && "$cmd" == bash* ]]; then
  echo "OK: dedicated WezTerm pid $pid, 1 pane titled 'agent' on $tty running: $cmd"
else
  echo "UNEXPECTED layout: panes=$count tty=$tty process='$cmd' (log: $state_dir/wezterm.log)" >&2
  exit 1
fi
