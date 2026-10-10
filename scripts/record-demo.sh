#!/usr/bin/env bash
# How site/demo.gif is made: a real asciinema recording of linelore on a clone of psf/requests.
#   asciinema rec -c scripts/record-demo.sh demo.cast
#   agg --theme f3e9cf,2a2118,2a2118,b5452f,3d6b35,8a5a12,2f5a8a,8a3a6b,2f6b70,6b4a2b --font-family "DejaVu Sans Mono" --font-size 15 --idle-time-limit 4 --last-frame-duration 5 demo.cast site/demo.gif
# Terminal: 110x34. REQUESTS_DIR defaults to ./requests (git clone https://github.com/psf/requests).
cd "${REQUESTS_DIR:-requests}" || exit 1
type_cmd() { printf '\033[1;33mrequests\033[0m $ '; for ((i=0;i<${#1};i++)); do printf '%s' "${1:i:1}"; sleep 0.04; done; sleep 0.4; echo; }
unset NO_COLOR FORCE_COLOR; export TERM=xterm-256color
clear
type_cmd "git blame -L 420,420 src/requests/adapters.py"
git --no-pager blame -L 420,420 src/requests/adapters.py
sleep 2; echo
type_cmd "linelore src/requests/adapters.py:420"
linelore src/requests/adapters.py:420
sleep 4; echo
type_cmd "linelore src/requests/adapters.py:75"
linelore src/requests/adapters.py:75
sleep 5
