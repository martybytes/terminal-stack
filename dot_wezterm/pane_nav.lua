-- pane_nav.lua — directional nav-or-split pane keys for WezTerm.
-- Deployed to ~/.wezterm/pane_nav.lua (macOS, via chezmoi).
-- Keep in sync with windows/.wezterm/pane_nav.lua (Windows sync deploy).
--
-- F1..F4 (and Leader+1..4) are directions: F1=Left F2=Right F3=Down F4=Up.
--   * a pane exists in that direction -> focus it.
--   * no pane that way               -> split one there (50/50), focus it.
-- F5 (Leader+5) = PaneSelect overlay: labelled jump to any pane.
-- F6 (Leader+6) = PaneSelect swap: pick a pane to trade places with.
-- Shift+F1..F4 = always split in that direction, into a fuzzy-picked domain.
--
-- Replaced the old strict-build-order 3x2 grid (pane_grid.lua): the grid
-- silently no-opped on out-of-order presses (F3 with one pane did nothing) and
-- its cell labels shifted when the layout crossed 4 -> 5 panes. Directions are
-- stateless, so every press does something predictable in any layout.

local wezterm = require 'wezterm'
local act = wezterm.action

local M = {}

-- F-key number -> ActivatePaneDirection / tab:get_pane_direction direction.
local DIRS = { [1] = 'Left', [2] = 'Right', [3] = 'Down', [4] = 'Up' }
-- ...and the pane:split() direction for the same key ('Down'/'Up' differ).
local SPLIT_DIRS = { Left = 'Left', Right = 'Right', Down = 'Bottom', Up = 'Top' }

local function unzoom(tab)
  for _, it in ipairs(tab:panes_with_info()) do
    if it.is_zoomed then tab:set_zoomed(false); return end
  end
end

-- Press F<n>: focus the neighbour in DIRS[n], or split one into existence.
-- leaf_domain is set only for the Shift+F variant, which ALWAYS splits (its
-- point is "new pane in this direction in that domain").
function M.go(window, pane, n, leaf_domain)
  local dir = DIRS[n]
  if not dir then return end
  local tab = pane:tab()
  if not tab then return end
  unzoom(tab)
  if not leaf_domain and tab:get_pane_direction(dir) then
    window:perform_action(act.ActivatePaneDirection(dir), pane)
    return
  end
  local ok, err = pcall(function()
    pane:split {
      direction = SPLIT_DIRS[dir],
      size = 0.5,
      domain = leaf_domain or 'CurrentPaneDomain',
    }
  end)
  if not ok then
    wezterm.log_error('pane_nav: split ' .. dir .. ' failed: ' .. tostring(err))
  end
end

local function domain_choices()
  local choices = {}
  for _, d in ipairs(wezterm.mux.all_domains()) do
    table.insert(choices, { id = d:name(), label = d:name() })
  end
  table.sort(choices, function(a, b) return a.label < b.label end)
  return choices
end

-- Bind F1..F6 + Leader+1..6 (+ Shift+F1..F4 domain-picked splits).
-- phys:F* because key_map_preference defaults to Mapped and bare F-keys may not
-- match on Windows.
function M.bind_keys(keys, wezterm_mod)
  for n = 1, 4 do
    local num = n                      -- fresh per iteration -> safe to close over
    local plain = wezterm_mod.action_callback(function(w, p) M.go(w, p, num, nil) end)
    table.insert(keys, { key = 'phys:F' .. n, mods = 'NONE',   action = plain })
    table.insert(keys, { key = tostring(n),   mods = 'LEADER', action = plain })

    local pick = wezterm_mod.action_callback(function(w, p)
      w:perform_action(act.InputSelector {
        title = 'Split ' .. DIRS[num]:lower() .. ' into domain',
        choices = domain_choices(),
        fuzzy = true,
        action = wezterm_mod.action_callback(function(win, p2, id)
          if id then M.go(win, p2, num, { DomainName = id }) end
        end),
      }, p)
    end)
    table.insert(keys, { key = 'phys:F' .. n, mods = 'SHIFT', action = pick })
  end

  local select = act.PaneSelect { alphabet = '1234567890', mode = 'Activate' }
  local swap   = act.PaneSelect { alphabet = '1234567890', mode = 'SwapWithActive' }
  table.insert(keys, { key = 'phys:F5', mods = 'NONE',   action = select })
  table.insert(keys, { key = '5',       mods = 'LEADER', action = select })
  table.insert(keys, { key = 'phys:F6', mods = 'NONE',   action = swap })
  table.insert(keys, { key = '6',       mods = 'LEADER', action = swap })
end

return M
