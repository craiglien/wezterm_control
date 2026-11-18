-- Startup layout for the agent bridge: one window, one pane, and it is the agent's (bash, titled `agent`).
-- Used by wezterm/agent_wezterm.lua, which scripts/start_wezterm.sh launches as a dedicated WezTerm instance.
-- Keep the command below in sync with DEFAULT_CMD in scripts/wez_expect.py (tests/test_wez_expect.py checks it).
local M = {}

M.title = 'agent'
M.args = {
  'bash', '-c',
  "printf '\\033]2;agent\\007'; printf '== AGENT PANE (bash) ==\\n'; "
    .. "exec env 'PS1=[wez]$ ' bash --norc --noprofile",
}

-- Opens the single agent window. `cmd` is the gui-startup spawn command, if any. Returns the window.
function M.spawn_window(mux, cmd)
  local spawn = cmd or {}
  spawn.args = M.args
  local _, _, window = mux.spawn_window(spawn)
  return window
end

return M
