-- Headless checks for linelore.nvim, run by tests/test_editors.py:
--   nvim --headless -u NONE -i NONE --cmd "set rtp^=editors/nvim" -l editors/nvim/test/smoke.lua CASES.json
-- CASES.json: { render = [{name, lore, want = {..}, links = {..}, absent = {..}}], live = {file, cmd} }
local cases = vim.json.decode(table.concat(vim.fn.readfile(arg[1]), "\n"), { luanil = { object = true, array = true } })
local ll = require("linelore")
local failures = 0

local function fail(name, msg)
  failures = failures + 1
  io.stderr:write(("FAIL %s: %s\n"):format(name, msg))
end

local function has_line(lines, needle)
  for _, l in ipairs(lines) do
    if l:find(needle, 1, true) then
      return true
    end
  end
  return false
end

local function check(name, lines, links, case)
  for _, w in ipairs(case.want or {}) do
    if not has_line(lines, w) then
      fail(name, "missing " .. vim.inspect(w) .. " in\n" .. table.concat(lines, "\n"))
    end
  end
  for _, w in ipairs(case.absent or {}) do
    if has_line(lines, w) then
      fail(name, "unexpected " .. vim.inspect(w))
    end
  end
  local got = {}
  for _, u in pairs(links or {}) do
    got[u] = true
  end
  for _, u in ipairs(case.links or {}) do
    if not got[u] then
      fail(name, "not clickable: " .. u)
    end
  end
end

-- 1. pure rendering of real linelore JSON
for _, case in ipairs(cases.render or {}) do
  local ok, r = pcall(ll.render, case.lore, 80)
  if not ok then
    fail(case.name, "render error: " .. tostring(r))
  else
    check(case.name, r.lines, r.links, case)
    for _, l in ipairs(r.lines) do
      if vim.fn.strdisplaywidth(l) > 80 and not l:find("https?://") then
        fail(case.name, "line wider than 80: " .. l)
      end
    end
    io.stdout:write(("ok   render %-22s %d lines, %d links\n"):format(case.name, #r.lines, vim.tbl_count(r.links)))
  end
end

-- 2. the real command: :Linelore and a :{range}Linelore in a scratch repo
local live = cases.live
if live then
  ll.setup({ cmd = live.cmd, args = live.args or {} })
  vim.o.columns, vim.o.lines = 120, 40
  for _, step in ipairs(live.steps) do
    vim.cmd("edit " .. vim.fn.fnameescape(live.file))
    local origin = vim.api.nvim_get_current_win()
    vim.cmd(step.ex)
    local float
    local done = vim.wait(15000, function()
      for _, w in ipairs(vim.api.nvim_list_wins()) do
        if vim.api.nvim_win_get_config(w).relative ~= "" then
          local text = table.concat(vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(w), 0, -1, false), "\n")
          if not text:find("looking up", 1, true) then
            float = w
            return true
          end
        end
      end
      return false
    end, 50)
    if not done then
      fail(step.ex, "no result float within 15 s")
    else
      local lines = vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(float), 0, -1, false)
      check(step.ex, lines, nil, step)
      if vim.api.nvim_get_current_win() ~= float then
        fail(step.ex, "focus did not move into the float")
      end
      vim.api.nvim_feedkeys("q", "x", false)
      if vim.api.nvim_win_is_valid(float) then
        fail(step.ex, "q did not close the float")
      end
      if vim.api.nvim_get_current_win() ~= origin then
        fail(step.ex, "focus did not return to the file")
      end
      io.stdout:write(("ok   live   %-22s %d lines\n"):format(step.ex, #lines))
    end
  end
end

if failures > 0 then
  io.stderr:write(failures .. " failure(s)\n")
  os.exit(1)
end
io.stdout:write("all nvim checks passed\n")
os.exit(0)
