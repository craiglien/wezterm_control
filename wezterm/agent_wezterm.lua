-- Config for the dedicated agent WezTerm. Not your normal config: scripts/start_wezterm.sh launches
-- `wezterm --config-file` with this, and sets WEZ_CONTROL_DIR to the repo root.
local wezterm = require 'wezterm'
local agent = dofile(os.getenv('WEZ_CONTROL_DIR') .. '/wezterm/agent_layout.lua')

local config = wezterm.config_builder()
config.window_background_opacity = 1.0

wezterm.on('gui-startup', function(cmd)
  agent.spawn_window(wezterm.mux, cmd)
end)

-- The window title is the only GUI-side label; put the instance name in it.
wezterm.on('format-window-title', function()
  return 'AGENT: ' .. agent.name
end)

return config
