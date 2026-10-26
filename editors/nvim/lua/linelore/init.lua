-- linelore.nvim: ask why the line under the cursor (or a visual range) is the
-- way it is, and read the answer in a float with clickable links.
--
-- It runs `linelore --json FILE:LINE` (or FILE:START-END) asynchronously and
-- renders the JSON; nothing is fetched by the plugin itself.
-- Works on Neovim 0.9+ (0.10+ gets a footer and vim.ui.open).

local M = {}

M.config = {
  -- the executable, or a list such as { "uvx", "linelore" }
  cmd = "linelore",
  -- extra arguments, e.g. { "--rev", "v1.2" } or { "--offline" }
  args = {},
  -- add --summarize (needs LINELORE_SUMMARIZE_CMD); the summary is shown in
  -- its own labelled section, below the facts
  summarize = false,
  border = "single",
  max_width = 96,
  -- a key for normal and visual mode, e.g. "<leader>gl"; nil sets none
  keymap = nil,
}

local ns = vim.api.nvim_create_namespace("linelore")
local LABEL_W = 10

local function set_hl()
  local links = {
    LineloreTitle = "Title",
    LineloreCode = "String",
    LineloreLabel = "Statement",
    LineloreSha = "Constant",
    LineloreUrl = "Underlined",
    LineloreMuted = "Comment",
    LineloreNote = "Comment",
    LineloreSummary = "WarningMsg",
    LineloreError = "ErrorMsg",
  }
  for name, target in pairs(links) do
    vim.api.nvim_set_hl(0, name, { link = target, default = true })
  end
end

-- ---------------------------------------------------------------- render ---

local function str(v)
  if v == nil or v == vim.NIL then
    return nil
  end
  return tostring(v)
end

-- first_width: room on the first line when something precedes it
local function wrap(text, width, first_width)
  local out = {}
  for para in (text .. "\n"):gmatch("(.-)\n") do
    local line = ""
    for word in para:gmatch("%S+") do
      local room = (#out == 0 and first_width) or width
      if line == "" then
        line = word
      elseif vim.fn.strdisplaywidth(line .. " " .. word) <= room then
        line = line .. " " .. word
      else
        table.insert(out, line)
        line = word
      end
    end
    if line ~= "" then
      table.insert(out, line)
    end
  end
  if #out == 0 then
    out = { "" }
  end
  return out
end

local function oneline(text, limit)
  text = (str(text) or ""):gsub("%s+", " "):gsub("^ ", ""):gsub(" $", "")
  if limit and vim.fn.strchars(text) > limit then
    text = vim.fn.strcharpart(text, 0, limit - 1) .. "…"
  end
  return text
end

local function short_date(s)
  s = str(s)
  return s and s:sub(1, 10) or nil
end

local function utc_date(epoch)
  epoch = tonumber(str(epoch))
  return epoch and os.date("!%Y-%m-%d", epoch) or nil
end

-- {10, 11, 12, 15} -> "10–12, 15", like the terminal output
local function compact(lines)
  local ns_ = {}
  for _, l in ipairs(lines or {}) do
    table.insert(ns_, tonumber(l))
  end
  table.sort(ns_)
  local parts, i = {}, 1
  while i <= #ns_ do
    local j = i
    while j < #ns_ and ns_[j + 1] == ns_[j] + 1 do
      j = j + 1
    end
    table.insert(parts, i == j and tostring(ns_[i]) or (ns_[i] .. "–" .. ns_[j]))
    i = j + 1
  end
  return table.concat(parts, ", ")
end

local NOUN = { gitlab = { "MR", "!" } }

--- Turn linelore's JSON into lines, highlights and links.
--- Pure function: no buffers, no windows (tested headless).
--- @param lore table decoded `linelore --json`
--- @param width integer|nil text width (default 88)
--- @return table { lines = {string}, hls = {{row, col, end_col, group}}, links = {[row]=url}, primary = url|nil }
function M.render(lore, width)
  width = width or 88
  local body_w = math.max(20, width - LABEL_W)
  local R = { lines = {}, hls = {}, links = {}, primary = nil }
  local seen_pr = {}
  local noun = NOUN[str(lore.forge) or ""] or { "PR", "#" }

  local function add(text, group)
    table.insert(R.lines, text)
    if group then
      table.insert(R.hls, { #R.lines - 1, 0, #text, group })
    end
    return #R.lines - 1
  end
  -- "LABEL   text" with the label highlighted and the text wrapped under itself
  local function labelled(label, text, label_group, text_group)
    local pad = string.rep(" ", LABEL_W)
    local first = label .. string.rep(" ", math.max(1, LABEL_W - #label))
    for i, piece in ipairs(wrap(text, body_w, width - #first)) do
      local prefix = i == 1 and first or pad
      local row = add(prefix .. piece)
      if i == 1 then
        table.insert(R.hls, { row, 0, #label, label_group or "LineloreLabel" })
      end
      if text_group then
        table.insert(R.hls, { row, #prefix, #prefix + #piece, text_group })
      end
    end
  end
  local function url(u)
    u = str(u)
    if not u then
      return
    end
    local row = add(string.rep(" ", LABEL_W) .. u)
    table.insert(R.hls, { row, LABEL_W, LABEL_W + #u, "LineloreUrl" })
    R.links[row] = u
    R.primary = R.primary or u
  end
  local function quote(text)
    text = oneline(text, 240)
    if text ~= "" then
      labelled("", "“" .. text .. "”", nil, "LineloreMuted")
    end
  end

  local function commit(b)
    if b.uncommitted == true then
      return -- linelore adds a "not committed yet" note
    end
    local sha = (str(b.sha) or ""):sub(1, 10)
    local meta = table.concat(vim.tbl_filter(function(x)
      return x ~= nil
    end, { sha, utc_date(b.author_time), str(b.author) }), " · ")
    local row = #R.lines
    labelled("commit", meta)
    table.insert(R.hls, { row, LABEL_W, LABEL_W + #sha, "LineloreSha" })
    if str(b.summary) then
      labelled("", oneline(b.summary))
    end
  end

  local function pulls(list)
    for _, pr in ipairs(list or {}) do
      local n = str(pr.number)
      local label = noun[1] .. " " .. noun[2] .. n
      if seen_pr[n] then
        labelled(label, oneline(pr.title, 50) .. "  (same " .. noun[1] .. " as above)", nil, "LineloreMuted")
      else
        seen_pr[n] = true
        labelled(label, oneline(pr.title))
        local who = {}
        if str(pr.author) then
          table.insert(who, "@" .. str(pr.author))
        end
        if short_date(pr.merged_at) then
          table.insert(who, "merged " .. short_date(pr.merged_at))
        elseif str(pr.state) == "open" then
          table.insert(who, "still open")
        elseif str(pr.state) == "closed" then
          table.insert(who, "closed without merging")
        end
        if #who > 0 then
          labelled("", table.concat(who, " · "), nil, "LineloreMuted")
        end
        url(pr.url)
        quote(pr.body)
        for _, iss in ipairs(pr.issues or {}) do
          local st = str(iss.state) and str(iss.state):lower() or (iss.promoted == true and "mentioned" or nil)
          labelled("fixes", "#" .. str(iss.number) .. "  " .. oneline(iss.title) .. (st and (" [" .. st .. "]") or ""))
          url(iss.url)
        end
        if pr.mentions and #pr.mentions > 0 then
          local ms = {}
          for _, m in ipairs(pr.mentions) do
            table.insert(ms, str(m))
          end
          labelled("mentions", table.concat(ms, ", "), nil, "LineloreMuted")
        end
        for _, c in ipairs(pr.review_comments or {}) do
          local where
          if c.near ~= false then
            where = "line " .. (str(c.line) or "?")
          elseif str(c.line) then
            where = "elsewhere in this file, line " .. str(c.line) .. " at review time"
          else
            where = "elsewhere in this file, outdated diff"
          end
          local head = "@" .. (str(c.author) or "?") .. " (" .. where .. ")"
          labelled("review", head .. ": " .. oneline(c.body, 400))
        end
      end
    end
  end

  local function notes(list, skip_count)
    for _, n in ipairs(list or {}) do
      n = oneline(n)
      if not (skip_count and n:match("^%d+ unique commits in lines")) then
        labelled("note", n, "LineloreNote", "LineloreNote")
      end
    end
  end

  -- header
  local path = str(lore.path) or "?"
  if lore.range then
    local count = #(lore.commits or {})
    add(("%s:%s–%s  ·  %d unique commit%s"):format(path, str(lore.range.start), str(lore.range["end"]), count, count == 1 and "" or "s"), "LineloreTitle")
    for _, c in ipairs(lore.commits or {}) do
      add("")
      local head = "lines " .. compact(c.lines)
      local code = oneline((c.blame or {}).content, width - #head - 2)
      local row = add(head .. (code ~= "" and ("  " .. code) or ""))
      table.insert(R.hls, { row, 0, #head, "LineloreMuted" })
      table.insert(R.hls, { row, #head, -1, "LineloreCode" })
      commit(c.blame or {})
      pulls(c.pulls)
      notes(c.notes)
    end
  else
    local b = lore.blame or {}
    add(path .. ":" .. (str(b.line) or "?"), "LineloreTitle")
    local code = oneline(b.content, width)
    if code ~= "" then
      add(code, "LineloreCode")
    end
    add("")
    commit(b)
    pulls(lore.pulls)
  end
  notes(lore.notes, lore.range ~= nil)

  -- the model's summary: separate, labelled, never mixed with the facts
  local s = lore.model_summary
  if type(s) == "table" then
    add("")
    local by = str(s.by) or "your command"
    if str(s.text) then
      add("Summary (generated by " .. by .. ", may be wrong; not checked by linelore)", "LineloreSummary")
      for _, piece in ipairs(wrap(str(s.text), width - 2)) do
        add("  " .. piece)
      end
    else
      for i, piece in ipairs(wrap("No summary: " .. oneline(s.error or "unknown error"), width - 2)) do
        add((i == 1 and "" or "  ") .. piece, "LineloreError")
      end
    end
  end
  return R
end

-- ------------------------------------------------------------------ run ---

local function argv(target)
  local cfg = M.config
  local cmd = type(cfg.cmd) == "table" and vim.deepcopy(cfg.cmd) or { cfg.cmd }
  vim.list_extend(cmd, cfg.args or {})
  vim.list_extend(cmd, { "--json", "--no-color" })
  if cfg.summarize then
    table.insert(cmd, "--summarize")
  end
  table.insert(cmd, target)
  return cmd
end

local function run(cmd, cwd, on_done)
  if vim.system then
    vim.system(cmd, { cwd = cwd, text = true }, function(res)
      vim.schedule(function()
        on_done(res.code, res.stdout or "", res.stderr or "")
      end)
    end)
    return
  end
  local out, err = {}, {}
  local ok = vim.fn.jobstart(cmd, {
    cwd = cwd,
    stdout_buffered = true,
    stderr_buffered = true,
    on_stdout = function(_, d) out = d end,
    on_stderr = function(_, d) err = d end,
    on_exit = function(_, code)
      vim.schedule(function()
        on_done(code, table.concat(out, "\n"), table.concat(err, "\n"))
      end)
    end,
  })
  if ok <= 0 then
    on_done(127, "", "could not start " .. cmd[1])
  end
end

function M.open_url(u)
  if not u then
    vim.notify("linelore: no link here", vim.log.levels.INFO)
    return
  end
  if vim.ui.open then
    vim.ui.open(u)
    return
  end
  local opener = vim.fn.has("mac") == 1 and { "open", u }
    or vim.fn.has("win32") == 1 and { "cmd", "/c", "start", "", u }
    or { "xdg-open", u }
  vim.fn.jobstart(opener, { detach = true })
end

-- ---------------------------------------------------------------- float ---

local state = { win = nil, buf = nil, links = {}, primary = nil, token = 0 }

local function close()
  if state.win and vim.api.nvim_win_is_valid(state.win) then
    vim.api.nvim_win_close(state.win, true)
  end
  state.win, state.buf = nil, nil
end

local function url_at_cursor()
  local row = vim.api.nvim_win_get_cursor(0)[1] - 1
  -- the link on this line, else the nearest one below it in the same block
  for r = row, row + 3 do
    if state.links[r] then
      return state.links[r]
    end
  end
  return state.primary
end

local function show(lines, hls, opts)
  opts = opts or {}
  local width = 0
  for _, l in ipairs(lines) do
    width = math.max(width, vim.fn.strdisplaywidth(l))
  end
  width = math.min(width + 2, M.config.max_width, vim.o.columns - 4)
  local height = math.min(#lines, math.max(3, math.floor(vim.o.lines * 0.6)))

  if not (state.buf and vim.api.nvim_buf_is_valid(state.buf)) then
    state.buf = vim.api.nvim_create_buf(false, true)
    vim.bo[state.buf].bufhidden = "wipe"
    vim.bo[state.buf].filetype = "linelore"
  end
  local buf = state.buf
  -- one column of padding inside the border
  local padded = {}
  for i, l in ipairs(lines) do
    padded[i] = l == "" and "" or (" " .. l)
  end
  vim.bo[buf].modifiable = true
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, padded)
  vim.bo[buf].modifiable = false
  vim.api.nvim_buf_clear_namespace(buf, ns, 0, -1)
  for _, h in ipairs(hls or {}) do
    pcall(vim.api.nvim_buf_add_highlight, buf, ns, h[4], h[1], h[2] + 1, h[3] < 0 and -1 or h[3] + 1)
  end

  -- below the cursor, or above it when there is no room
  local screen_row = vim.fn.screenrow()
  local below = screen_row + height + 2 <= vim.o.lines - 1
  local win_opts = {
    relative = "cursor",
    row = below and 1 or 0,
    col = 0,
    anchor = below and "NW" or "SW",
    width = width,
    height = height,
    style = "minimal",
    border = M.config.border,
    title = " linelore ",
    title_pos = "left",
  }
  if vim.fn.has("nvim-0.10") == 1 and opts.footer then
    win_opts.footer = opts.footer
    win_opts.footer_pos = "left"
  end
  if state.win and vim.api.nvim_win_is_valid(state.win) then
    win_opts.relative, win_opts.row, win_opts.col, win_opts.anchor = nil, nil, nil, nil
    vim.api.nvim_win_set_config(state.win, win_opts)
  else
    state.win = vim.api.nvim_open_win(buf, opts.enter ~= false, win_opts)
    vim.wo[state.win].wrap = false
    vim.wo[state.win].cursorline = true
    local map = function(lhs, fn)
      vim.keymap.set("n", lhs, fn, { buffer = buf, nowait = true, silent = true })
    end
    map("q", close)
    map("<Esc>", close)
    map("<CR>", function() M.open_url(url_at_cursor()) end)
    map("gx", function() M.open_url(url_at_cursor()) end)
    map("o", function() M.open_url(state.primary) end)
    map("y", function()
      local u = url_at_cursor()
      if u then
        vim.fn.setreg("+", u)
        vim.fn.setreg('"', u)
        vim.notify("linelore: copied " .. u)
      end
    end)
    vim.api.nvim_create_autocmd("WinLeave", { buffer = buf, once = true, callback = close })
  end
end

--- Look up FILE:LINE or FILE:START-END for the current buffer.
function M.lore(line1, line2)
  local file = vim.api.nvim_buf_get_name(0)
  if file == "" or vim.bo.buftype ~= "" then
    vim.notify("linelore: this buffer is not a file", vim.log.levels.WARN)
    return
  end
  local cmd = argv(file .. ":" .. (line1 == line2 and line1 or (line1 .. "-" .. line2)))
  if vim.fn.executable(cmd[1]) == 0 then
    vim.notify(
      ("linelore: `%s` is not on PATH (pipx install git+https://github.com/Blackman99/linelore)"):format(cmd[1]),
      vim.log.levels.ERROR
    )
    return
  end
  local modified = vim.bo.modified
  local label = vim.fn.fnamemodify(file, ":t") .. ":" .. (line1 == line2 and line1 or (line1 .. "-" .. line2))

  close()
  state.token = state.token + 1
  local token = state.token
  show({ "looking up " .. label .. " …" }, { { 0, 0, -1, "LineloreMuted" } }, { enter = false })

  run(cmd, vim.fn.fnamemodify(file, ":h"), function(code, stdout, stderr)
    if token ~= state.token then
      return -- superseded or closed
    end
    local ok, lore = pcall(vim.json.decode, stdout, { luanil = { object = true, array = true } })
    if not ok or type(lore) ~= "table" then
      close()
      local msg = vim.trim(stderr) ~= "" and vim.trim(stderr) or ("exit " .. code .. ", no JSON on stdout")
      vim.notify("linelore: " .. msg, vim.log.levels.ERROR)
      return
    end
    if modified then
      lore.notes = lore.notes or {}
      table.insert(lore.notes, "this buffer has unsaved changes; line numbers are from the file on disk")
    end
    local width = math.min(M.config.max_width, vim.o.columns - 4) - 2
    local r = M.render(lore, width)
    state.links, state.primary = r.links, r.primary
    close()
    show(r.lines, r.hls, { footer = r.primary and " ⏎ open link · o open PR · y copy · q close " or " q close " })
  end)
end

function M.setup(opts)
  M.config = vim.tbl_deep_extend("force", M.config, opts or {})
  set_hl()
  vim.api.nvim_create_user_command("Linelore", function(c)
    M.lore(c.line1, c.line2)
  end, { range = true, desc = "linelore: why is this line (or range) like this?" })
  if M.config.keymap then
    vim.keymap.set("n", M.config.keymap, function()
      local l = vim.api.nvim_win_get_cursor(0)[1]
      M.lore(l, l)
    end, { desc = "linelore: this line" })
    vim.keymap.set("x", M.config.keymap, ":Linelore<CR>", { desc = "linelore: these lines", silent = true })
  end
end

return M
