;;; linelore.el --- Why is this line like this? -*- lexical-binding: t; -*-

;; Copyright (C) 2026 linelore contributors
;; Author: linelore contributors
;; URL: https://github.com/Blackman99/linelore
;; Version: 0.4.0
;; Package-Requires: ((emacs "27.1"))
;; Keywords: vc, tools
;; SPDX-License-Identifier: MIT

;;; Commentary:

;; `M-x linelore' runs `linelore --json FILE:LINE' (or FILE:START-END when
;; the region is active) in the background and shows the commit, the pull
;; request that merged it, the issues it closed and the review comments in a
;; *linelore* buffer.  Links are buttons: RET or a click opens them.
;;
;; In *linelore*: RET open link, TAB / S-TAB next / previous link,
;; o open the pull request, w copy the link, g look up again, q quit.
;;
;; Needs the linelore CLI 0.4+ on `exec-path':
;;   pipx install git+https://github.com/Blackman99/linelore

;;; Code:

(require 'button)
(require 'json)
(require 'subr-x)

(defgroup linelore nil
  "Show the pull request, issues and review behind a line of code."
  :group 'vc
  :prefix "linelore-")

(defcustom linelore-command '("linelore")
  "Command that runs linelore, as a list: program and leading arguments."
  :type '(repeat string))

(defcustom linelore-extra-arguments nil
  "Extra arguments for every lookup, e.g. (\"--offline\") or (\"--rev\" \"v1\")."
  :type '(repeat string))

(defcustom linelore-summarize nil
  "When non-nil, pass --summarize.
linelore then hands its facts to the model command in
LINELORE_SUMMARIZE_CMD and the answer is shown in its own section,
labelled as model-generated."
  :type 'boolean)

(defface linelore-title '((t :inherit bold)) "Path and line.")
(defface linelore-code '((t :inherit font-lock-string-face)) "The line's code.")
(defface linelore-label '((t :inherit font-lock-keyword-face)) "commit, PR, fixes, review.")
(defface linelore-sha '((t :inherit font-lock-constant-face)) "Commit sha.")
(defface linelore-muted '((t :inherit shadow)) "Secondary text.")
(defface linelore-summary '((t :inherit warning)) "The model summary label.")

(defconst linelore--label-width 10)

(defvar-local linelore--primary-url nil "The first link in the buffer (the pull request).")
(defvar-local linelore--refresh nil "Function that repeats the last lookup.")

;;;; Rendering (pure: inserts into the current buffer)

(defun linelore--str (v)
  "V as a string, or nil for JSON null/false/missing."
  (cond ((or (null v) (eq v :null) (eq v :false)) nil)
        ((stringp v) v)
        (t (format "%s" v))))

(defun linelore--get (obj &rest keys)
  "Follow KEYS (symbols) through alists starting at OBJ."
  (while (and keys obj)
    (setq obj (and (listp obj) (alist-get (car keys) obj))
          keys (cdr keys)))
  obj)

(defun linelore--oneline (text &optional limit)
  "TEXT on one line, shortened to LIMIT characters."
  (let ((s (string-trim (replace-regexp-in-string "[ \t\n\r]+" " " (or (linelore--str text) "")))))
    (if (and limit (> (length s) limit))
        (concat (substring s 0 (1- limit)) "…")
      s)))

(defun linelore--date (v)
  "A YYYY-MM-DD date from an epoch number or an ISO string V."
  (cond ((numberp v) (format-time-string "%Y-%m-%d" (seconds-to-time v) t))
        ((linelore--str v) (substring (linelore--str v) 0 (min 10 (length (linelore--str v)))))))

(defun linelore--compact (lines)
  "LINES (numbers) as \"10–12, 15\"."
  (let ((ns (sort (copy-sequence lines) #'<)) parts)
    (while ns
      (let ((a (car ns)) (b (car ns)))
        (setq ns (cdr ns))
        (while (and ns (= (car ns) (1+ b)))
          (setq b (car ns) ns (cdr ns)))
        (push (if (= a b) (number-to-string a) (format "%d–%d" a b)) parts)))
    (string-join (nreverse parts) ", ")))

(defun linelore--label (label &optional face)
  "Insert LABEL padded to the label column."
  (insert (propertize label 'face (or face 'linelore-label))
          (make-string (max 1 (- linelore--label-width (length label))) ?\s)))

(defun linelore--wrap (text width)
  "Split TEXT into lines of at most WIDTH columns, breaking only at spaces."
  (let (lines cur)
    (dolist (w (split-string text " +" t))
      (if (and cur (> (+ (string-width cur) 1 (string-width w)) width))
          (progn (push cur lines) (setq cur w))
        (setq cur (if cur (concat cur " " w) w))))
    (nreverse (if cur (cons cur lines) lines))))

(defun linelore--line (label text &optional text-face label-face)
  "Insert LABEL and TEXT, wrapped under the text column.
The label column is kept as is (`fill-region' would squeeze its padding)."
  (linelore--label label label-face)
  (let ((width (max 30 (- (window-width) linelore--label-width 2)))
        (first t))
    (dolist (ln (or (linelore--wrap text width) (list "")))
      (unless first (insert (make-string linelore--label-width ?\s)))
      (setq first nil)
      (insert (if text-face (propertize ln 'face text-face) ln) "\n"))))

(defun linelore--link (url)
  "Insert URL as a button on its own line."
  (when-let ((u (linelore--str url)))
    (unless (string-empty-p u)
      (insert (make-string linelore--label-width ?\s))
      (insert-text-button u 'action (lambda (_) (browse-url u)) 'follow-link t
                          'help-echo (concat "open " u) 'linelore-url u)
      (insert "\n")
      (unless linelore--primary-url (setq linelore--primary-url u)))))

(defun linelore--commit (b)
  "Insert the commit block for blame B."
  (unless (eq (linelore--get b 'uncommitted) t)
    (let ((sha (substring (or (linelore--str (linelore--get b 'sha)) "?") 0
                          (min 10 (length (or (linelore--str (linelore--get b 'sha)) "?"))))))
      (linelore--label "commit")
      (insert (propertize sha 'face 'linelore-sha) " · "
              (string-join (delq nil (list (linelore--date (linelore--get b 'author_time))
                                           (linelore--str (linelore--get b 'author))))
                           " · ")
              "\n")
      (when-let ((s (linelore--str (linelore--get b 'summary))))
        (linelore--line "" (linelore--oneline s))))))

(defun linelore--pulls (pulls forge seen)
  "Insert PULLS; SEEN is a hash of PR numbers already shown."
  (let ((noun (if (equal forge "gitlab") "MR !" "PR #")))
    (dolist (pr pulls)
      (let* ((n (linelore--str (linelore--get pr 'number)))
             (label (concat noun n)))
        (if (gethash n seen)
            (linelore--line label (concat (linelore--oneline (linelore--get pr 'title) 50)
                                          "  (same " (substring noun 0 2) " as above)")
                            'linelore-muted)
          (puthash n t seen)
          (linelore--line label (linelore--oneline (linelore--get pr 'title)))
          (let ((who (delq nil (list (when-let ((a (linelore--str (linelore--get pr 'author)))) (concat "@" a))
                                     (cond ((linelore--str (linelore--get pr 'merged_at))
                                            (concat "merged " (linelore--date (linelore--get pr 'merged_at))))
                                           ((equal (linelore--get pr 'state) "open") "still open")
                                           ((equal (linelore--get pr 'state) "closed") "closed without merging"))))))
            (when who (linelore--line "" (string-join who " · ") 'linelore-muted)))
          (linelore--link (linelore--get pr 'url))
          (let ((body (linelore--oneline (linelore--get pr 'body) 240)))
            (unless (string-empty-p body)
              (linelore--line "" (concat "“" body "”") 'linelore-muted)))
          (dolist (i (linelore--get pr 'issues))
            (let ((st (or (when-let ((s (linelore--str (linelore--get i 'state)))) (downcase s))
                          (when (eq (linelore--get i 'promoted) t) "mentioned"))))
              (linelore--line "fixes" (concat "#" (linelore--str (linelore--get i 'number)) " "
                                              (linelore--oneline (linelore--get i 'title))
                                              (if st (format " [%s]" st) "")))
              (linelore--link (linelore--get i 'url))))
          (when-let ((m (linelore--get pr 'mentions)))
            (linelore--line "mentions" (string-join (mapcar #'linelore--str m) ", ") 'linelore-muted))
          (dolist (c (linelore--get pr 'review_comments))
            (let* ((line (linelore--str (linelore--get c 'line)))
                   (where (cond ((not (eq (linelore--get c 'near) :false)) (concat "line " (or line "?")))
                                (line (format "elsewhere in this file, line %s at review time" line))
                                (t "elsewhere in this file, outdated diff"))))
              (linelore--line "review" (format "@%s (%s): %s" (or (linelore--str (linelore--get c 'author)) "?")
                                               where (linelore--oneline (linelore--get c 'body) 400))))))))))

(defun linelore--notes (notes &optional skip-count)
  "Insert NOTES; SKIP-COUNT drops the range's commit count (it is in the title)."
  (dolist (n notes)
    (let ((s (linelore--oneline n)))
      (unless (and skip-count (string-match-p "\\`[0-9]+ unique commits in lines" s))
        (linelore--line "note" s 'linelore-muted 'linelore-muted)))))

(defun linelore-render (lore)
  "Insert LORE, the parsed output of `linelore --json', at point."
  (let ((seen (make-hash-table :test #'equal))
        (forge (linelore--str (linelore--get lore 'forge)))
        (path (or (linelore--str (linelore--get lore 'path)) "?"))
        (range (linelore--get lore 'range)))
    (setq linelore--primary-url nil)
    (if range
        (let ((commits (linelore--get lore 'commits)))
          (insert (propertize (format "%s:%s–%s" path (linelore--get range 'start) (linelore--get range 'end))
                              'face 'linelore-title)
                  (propertize (format "  ·  %d unique commit%s" (length commits) (if (= (length commits) 1) "" "s"))
                              'face 'linelore-muted)
                  "\n")
          (dolist (c commits)
            (insert "\n" (propertize (concat "lines " (linelore--compact (linelore--get c 'lines))) 'face 'linelore-muted))
            (let ((code (linelore--oneline (linelore--get c 'blame 'content) 70)))
              (unless (string-empty-p code) (insert "  " (propertize code 'face 'linelore-code))))
            (insert "\n")
            (linelore--commit (linelore--get c 'blame))
            (linelore--pulls (linelore--get c 'pulls) forge seen)
            (linelore--notes (linelore--get c 'notes))))
      (let ((b (linelore--get lore 'blame)))
        (insert (propertize (format "%s:%s" path (or (linelore--str (linelore--get b 'line)) "?")) 'face 'linelore-title) "\n")
        (let ((code (linelore--oneline (linelore--get b 'content))))
          (unless (string-empty-p code) (insert (propertize code 'face 'linelore-code) "\n")))
        (insert "\n")
        (linelore--commit b)
        (linelore--pulls (linelore--get lore 'pulls) forge seen)))
    (linelore--notes (linelore--get lore 'notes) range)
    ;; The model's summary: its own section, labelled, never mixed into the facts.
    (when-let ((s (linelore--get lore 'model_summary)))
      (insert "\n")
      (if-let ((text (linelore--str (linelore--get s 'text))))
          (let ((start (point)))
            (insert (propertize (format "Summary (generated by %s, may be wrong; not checked by linelore)"
                                        (or (linelore--str (linelore--get s 'by)) "your command"))
                                'face 'linelore-summary)
                    "\n")
            (setq start (point))
            (insert text "\n")
            (let ((fill-prefix "  ") (fill-column (max 40 (- (window-width) 2))))
              (indent-rigidly start (point) 2)
              (fill-region start (point))))
        (insert (propertize (concat "No summary: " (linelore--oneline (linelore--get s 'error)))
                            'face 'error)
                "\n")))))

(defun linelore-parse (string)
  "Parse linelore's JSON STRING into alists and lists."
  (if (fboundp 'json-parse-string)
      (json-parse-string string :object-type 'alist :array-type 'list :null-object nil :false-object :false)
    (let ((json-object-type 'alist) (json-array-type 'list) (json-false :false) (json-null nil))
      (json-read-from-string string))))

;;;; The *linelore* buffer

(defvar linelore-mode-map
  (let ((m (make-sparse-keymap)))
    (define-key m (kbd "TAB") #'forward-button)
    (define-key m (kbd "<backtab>") #'backward-button)
    (define-key m (kbd "o") #'linelore-open-pull-request)
    (define-key m (kbd "w") #'linelore-copy-link)
    m)
  "Keymap for `linelore-mode'.")

(define-derived-mode linelore-mode special-mode "linelore"
  "Shows what linelore found.  RET opens a link, o the pull request, q quits."
  (setq-local revert-buffer-function (lambda (&rest _) (when linelore--refresh (funcall linelore--refresh))))
  (setq truncate-lines nil))

(defun linelore-open-pull-request ()
  "Open the pull request (the first link) in the browser."
  (interactive)
  (if linelore--primary-url (browse-url linelore--primary-url) (message "linelore: no pull request here")))

(defun linelore-copy-link ()
  "Copy the link at point, or the pull request's."
  (interactive)
  (let ((u (or (get-text-property (point) 'linelore-url) linelore--primary-url)))
    (if (not u) (message "linelore: no link here")
      (kill-new u) (message "Copied %s" u))))

(defun linelore--target ()
  "FILE:LINE or FILE:START-END for point or the active region."
  (unless buffer-file-name (user-error "linelore: this buffer is not visiting a file"))
  (let* ((file (file-local-name buffer-file-name))
         (lines (if (use-region-p)
                    (let ((beg (region-beginning)) (end (region-end)))
                      ;; a region that ends at the start of a line doesn't include it
                      (when (and (> end beg) (save-excursion (goto-char end) (bolp)))
                        (setq end (1- end)))
                      (cons (line-number-at-pos beg) (line-number-at-pos end)))
                  (cons (line-number-at-pos) (line-number-at-pos)))))
    (if (= (car lines) (cdr lines))
        (format "%s:%d" file (car lines))
      (format "%s:%d-%d" file (car lines) (cdr lines)))))

(defun linelore--show (modified lore)
  "Display LORE; MODIFIED means the file's buffer had unsaved changes."
  (let ((buf (get-buffer-create "*linelore*")))
    (with-current-buffer buf
      (let ((inhibit-read-only t))
        (unless (derived-mode-p 'linelore-mode) (linelore-mode))
        (erase-buffer)
        (when modified
          (push "this buffer has unsaved changes; line numbers are from the file on disk"
                (alist-get 'notes lore)))
        (linelore-render lore)
        (goto-char (point-min))))
    (display-buffer buf '((display-buffer-reuse-window display-buffer-below-selected)
                          (window-height . fit-window-to-buffer)))
    buf))

;;;###autoload
(defun linelore (&optional summarize)
  "Show why the current line (or region) is the way it is.
With a prefix argument SUMMARIZE, also ask for a model summary
\(see `linelore-summarize')."
  (interactive "P")
  (linelore--run (linelore--target) default-directory (or summarize linelore-summarize) (buffer-modified-p)))

(defun linelore--run (target dir summarize modified)
  "Look up TARGET from DIR in the background and show it."
  (let* ((cmd (append linelore-command linelore-extra-arguments '("--json" "--no-color")
                      (when summarize '("--summarize"))
                      (list target)))
         (out (generate-new-buffer " *linelore-out*"))
         (err (generate-new-buffer " *linelore-err*")))
    (unless (executable-find (car cmd))
      (kill-buffer out) (kill-buffer err)
      (user-error "linelore: `%s' is not installed (pipx install git+https://github.com/Blackman99/linelore)" (car cmd)))
    (message "linelore: looking up %s…" (file-name-nondirectory target))
    (let* ((default-directory dir)
           (proc (make-process
                  :name "linelore" :buffer out :stderr err :command cmd :noquery t
                  :sentinel
                  (lambda (proc _event)
                    (unless (process-live-p proc)
                      (linelore--finish proc out err target dir summarize modified))))))
      (when-let ((ep (get-buffer-process err))) (set-process-query-on-exit-flag ep nil))
      proc)))

(defun linelore--finish (proc out err target dir summarize modified)
  "Parse what PROC wrote to OUT and ERR and show it."
  (unwind-protect
      (let* ((ep (get-buffer-process err))
             (_ (while (and ep (process-live-p ep)) (accept-process-output ep 0.05)))
             (stdout (with-current-buffer out (buffer-string)))
             (stderr (string-trim (with-current-buffer err (buffer-string))))
             (lore (condition-case nil (linelore-parse stdout) (error nil))))
        (if (not (consp lore))
            (message "linelore: %s" (if (string-empty-p stderr)
                                        (format "exit %d, no JSON on stdout" (process-exit-status proc))
                                      (car (last (split-string stderr "\n" t)))))
          (with-current-buffer (linelore--show modified lore)
            (setq linelore--refresh (lambda () (linelore--run target dir summarize modified))))
          (message "linelore: %s  (RET open link, o pull request, q quit)" (file-name-nondirectory target))))
    (kill-buffer out)
    (kill-buffer err)))

(provide 'linelore)
;;; linelore.el ends here
