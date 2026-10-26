;;; linelore-test.el --- Batch tests for linelore.el -*- lexical-binding: t; -*-

;; Run by tests/test_editors.py:
;;   LINELORE_EDITOR_CASES=cases.json emacs --batch -Q -L editors/emacs \
;;     -l editors/emacs/test/linelore-test.el -f ert-run-tests-batch-and-exit
;; cases.json is the same file the Neovim smoke test reads.

;;; Code:

(require 'ert)
(require 'linelore)

(defvar linelore-test-cases
  (let ((f (getenv "LINELORE_EDITOR_CASES")))
    (and f (with-temp-buffer
             (insert-file-contents f)
             (json-parse-buffer :object-type 'alist :array-type 'list :null-object nil :false-object :false)))))

(defun linelore-test--rendered (lore)
  "LORE rendered to a string, and the list of button URLs."
  (with-temp-buffer
    (linelore-mode)
    (let ((inhibit-read-only t)) (linelore-render lore))
    (let (urls)
      (save-excursion
        (goto-char (point-min))
        (let (b) (while (setq b (next-button (point)))
                   (push (button-get b 'linelore-url) urls)
                   (goto-char (button-end b)))))
      (cons (buffer-string) urls))))

(defun linelore-test--check (name text urls case)
  (dolist (w (alist-get 'want case))
    (should (or (string-search w text) (error "%s: missing %S in\n%s" name w text))))
  (dolist (w (alist-get 'absent case))
    (should-not (string-search w text)))
  (dolist (u (alist-get 'links case))
    (should (or (member u urls) (error "%s: not a button: %s" name u))))
  ;; labels and continuation lines keep the text in one column
  (dolist (ln (split-string text "\n"))
    (when (or (string-match-p "\\`\\(commit\\|PR #\\|MR !\\|fixes\\|review\\|mentions\\|note\\) " ln)
              (string-prefix-p (make-string linelore--label-width ?\s) ln))
      (should (or (and (> (length ln) linelore--label-width)
                       (eq (aref ln (1- linelore--label-width)) ?\s)
                       (not (eq (aref ln linelore--label-width) ?\s)))
                  (error "%s: text not in the column: %S" name ln))))))

(ert-deftest linelore-render-real-json ()
  (should linelore-test-cases)
  (dolist (case (alist-get 'render linelore-test-cases))
    (let* ((r (linelore-test--rendered (alist-get 'lore case))))
      (linelore-test--check (alist-get 'name case) (car r) (cdr r) case)
      (message "ok   render %s" (alist-get 'name case)))))

(ert-deftest linelore-target-point-and-region ()
  (let ((f (make-temp-file "linelore" nil ".py" "a\nb\nc\nd\n")))
    (unwind-protect
        (with-current-buffer (find-file-noselect f)
          (goto-char (point-min)) (forward-line 1)
          (should (string-suffix-p ".py:2" (linelore--target)))
          ;; region over lines 2-3, ending at the start of line 4: line 4 is not included
          (transient-mark-mode 1)
          (push-mark (point) t t) (forward-line 2)
          (should (string-suffix-p ".py:2-3" (linelore--target)))
          (kill-buffer))
      (delete-file f))))

(ert-deftest linelore-live-lookup ()
  (let ((live (alist-get 'live linelore-test-cases)))
    (skip-unless live)
    (let ((linelore-command (alist-get 'cmd live))
          (linelore-extra-arguments (alist-get 'args live)))
      (dolist (step (alist-get 'steps live))
        (when-let ((b (get-buffer "*linelore*"))) (kill-buffer b))
        (with-current-buffer (find-file-noselect (alist-get 'file live))
          (goto-char (point-min))
          (forward-line (1- (alist-get 'line step)))
          (when (alist-get 'to step)
            (transient-mark-mode 1)
            (push-mark (point) t t)
            (forward-line (- (alist-get 'to step) (alist-get 'line step)))
            (end-of-line))
          (let ((proc (linelore)))
            (with-timeout (15 (error "no answer from linelore within 15 s"))
              (while (process-live-p proc) (accept-process-output proc 0.05)))
            (with-timeout (5 (error "*linelore* was not shown"))
              (while (not (get-buffer "*linelore*")) (accept-process-output nil 0.05))))
          (deactivate-mark))
        (with-current-buffer "*linelore*"
          (should (derived-mode-p 'linelore-mode))
          (should buffer-read-only)
          (linelore-test--check (alist-get 'ex step) (buffer-string) nil step)
          (message "ok   live   %s" (alist-get 'ex step)))))))

(provide 'linelore-test)
;;; linelore-test.el ends here
