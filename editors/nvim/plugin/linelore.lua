-- Defines :Linelore with defaults; call require("linelore").setup({...}) to change them.
if vim.g.loaded_linelore then
  return
end
vim.g.loaded_linelore = true
require("linelore").setup(vim.g.linelore or {})
