;;; build-contract.el --- generate contract.json from the reference tables -*- lexical-binding: t; -*-

;; The contract projector (PLAN-ebp-extraction.md's Option A: the elisp
;; stays the generator).  The wire vocabulary is authored as the reference
;; client's hand-reviewed lint tables; this script projects them into
;; `contract.json' beside this repo's spec.  It therefore runs inside a
;; checkout that CONSUMES this repo as a submodule and provides those
;; tables — from that checkout's root:
;;
;;   emacs --batch -l ebp/tools/build-contract.el -f ebp-contract-write
;;
;; The reference checkout is assumed to be the submodule's parent
;; directory; set EBP_REFERENCE_ROOT to point somewhere else.
;;
;; `contract.json' publishes the *static* wire vocabulary a renderer or
;; authoring tool validates emissions against — node types, the authored
;; per-node key schema and JSON-RPC method table with error codes
;; (contract_format 5, Spec 2.0-draft), action-hook keys, the offline
;; policies, the toolbar vocabulary, and a discriminated action schema,
;; plus the api/protocol/spec versions.  It is STATIC AND AUTHORED ONLY:
;; the node/method schemas are the hand-reviewed lint tables, never
;; inferred from golden examples, and there are no live registrations
;; (node support is still negotiated per-connection via `node_types',
;; SPEC-2 §3).  Output is byte-stable — fixed key order, arrays as
;; vectors, UTF-8/LF, one terminal newline — so the reference suite's
;; drift test (`jetpacs-contract-artifact-current') can diff a fresh run
;; against the committed file.  Loading this file only defines functions;
;; it writes nothing until `ebp-contract-write' runs.

(require 'json)
(require 'seq)

(defvar ebp-contract--ebp-root
  (expand-file-name ".." (file-name-directory (or load-file-name buffer-file-name)))
  "This repo's root (SPEC-2.md, contract.json), derived from this file.")

(defvar ebp-contract--reference-root
  (or (getenv "EBP_REFERENCE_ROOT")
      (expand-file-name ".." ebp-contract--ebp-root))
  "Root of the reference-client checkout providing the schema tables.
Defaults to the parent directory — where this repo sits as a submodule.")

(add-to-list 'load-path (expand-file-name "emacs/core" ebp-contract--reference-root))
(require 'jetpacs)
(require 'jetpacs-lint)
(require 'jetpacs-source)

(defconst ebp-contract-format 5
  "Schema version of `contract.json' itself — bump on a contract-shape change.
Format 2 (Spec 1.0-rc freeze, S1) adds `spec_version', `node_schema',
and `kind_schema'.  Format 3 (the ebp extraction) renames `api_version'
to `reference_api_version': the field describes the elisp reference
implementation's Tier-1 surface, not the wire — informational only, so
the contract repo reads as implementation-neutral.  Format 5 (the
JSON-RPC envelope swap, SPEC-2; 4 was claimed by the deferred v1
error_codes amendment) replaces `kind_schema' with `methods' — each
carrying `direction', `type' (request/notification), `params', and for
requests `result' — and lands `error_codes' (codes + `data.kind'
vocabulary).  Drafted by the slop line; reshape freely (SPEC-2 §8.5).")

(defun ebp-contract--spec-version ()
  "The spec version declared in SPEC-2.md's status block (\"2.0-draft\").
SPEC-2.md is the single source of truth for this number; the ERT test
`jetpacs-spec-header-version-coherent' keeps the header machine-readable."
  (with-temp-buffer
    (insert-file-contents (expand-file-name "SPEC-2.md" ebp-contract--ebp-root))
    (goto-char (point-min))
    (unless (re-search-forward
             "^Spec: \\*\\*\\([0-9]+\\.[0-9]+\\(?:-rc\\|-draft\\)?\\)\\*\\*" nil t)
      (error "SPEC-2.md header carries no parseable Spec: version"))
    (match-string 1)))

(defun ebp-contract--node-schema ()
  "The authored per-node key schema as contract objects.
The \"*\" row is the keys legal on any node (post-construction riders)."
  (cons
   (cons "*" (list (cons "required" [])
                   (cons "optional"
                         (ebp-contract--names jetpacs-lint-node-common-keys))))
   (mapcar (lambda (row)
             (cons (nth 0 row)
                   (list (cons "required" (ebp-contract--names (nth 1 row)))
                         (cons "optional" (ebp-contract--names (nth 2 row))))))
           jetpacs-lint-node-schema)))

(defun ebp-contract--methods ()
  "The JSON-RPC method table as contract objects (format 5).
`direction' is the sender (client = Emacs, companion, or both);
`type' is the SPEC-2 §4 classification (request / notification).
Params of a §9 node tree carry `params: \"node\"' instead of key lists;
a request also carries its `result' schema from
`jetpacs-lint-result-schema'."
  (mapcar
   (lambda (row)
     (let* ((method (nth 0 row))
            (request-p (eq (nth 2 row) 'request))
            (result (and request-p (assoc method jetpacs-lint-result-schema))))
       (cons method
             (append
              (list (cons "direction" (symbol-name (nth 1 row)))
                    (cons "type" (if request-p "request" "notification"))
                    (cons "params"
                          (if (eq (nth 3 row) 'node) "node"
                            (list (cons "required" (ebp-contract--names (nth 3 row)))
                                  (cons "optional" (ebp-contract--names (nth 4 row)))))))
              (when result
                (list (cons "result"
                            (list (cons "required" (ebp-contract--names (nth 1 result)))
                                  (cons "optional" (ebp-contract--names (nth 2 result)))))))))))
   jetpacs-lint-kind-schema))

(defun ebp-contract--error-codes ()
  "The error-code vocabulary as contract objects (SPEC-2 §2.4)."
  (mapcar (lambda (row)
            (cons (number-to-string (nth 0 row))
                  (list (cons "kind" (nth 1 row))
                        (cons "context" (nth 2 row)))))
          jetpacs-lint-error-codes))

(defun ebp-contract--names (syms)
  "SYMS as a JSON array (vector) of their names."
  (vconcat (mapcar #'symbol-name syms)))

(defun ebp-contract--action-schema ()
  "The discriminated action schema, derived from the lint defconsts.
`remote' is the named-action shape; each remaining key is a companion-local
builtin mapped to its required payload."
  (let ((optional (ebp-contract--names
                   (seq-difference jetpacs-lint-action-fields '(action builtin)))))
    (cons
     (cons "remote" (list (cons "required" ["action"])
                          (cons "optional" optional)))
     (mapcar
      (lambda (entry)
        (cons (car entry)
              (list (cons "required"
                          (vconcat (cons "builtin"
                                         (mapcar #'symbol-name (nth 1 entry)))))
                    (cons "optional" (ebp-contract--names (nth 2 entry))))))
      jetpacs-lint-action-builtins))))

(defun ebp-contract ()
  "The contract as an ordered alist (objects) with vectors for arrays."
  (list
   (cons "contract_format"  ebp-contract-format)
   ;; Informational: the reference elisp client's Tier-1 API version at
   ;; generation time.  Not a wire number — pin `protocol_version' /
   ;; `spec_version' instead.
   (cons "reference_api_version" jetpacs-api-version)
   (cons "protocol_version" jetpacs-protocol-version)
   (cons "spec_version"     (ebp-contract--spec-version))
   (cons "node_types"       (vconcat jetpacs-lint-node-types))
   (cons "node_schema"      (ebp-contract--node-schema))
   (cons "methods"          (ebp-contract--methods))
   (cons "error_codes"      (ebp-contract--error-codes))
   (cons "action_hook_keys" (ebp-contract--names jetpacs-lint--action-keys))
   (cons "action_fields"    (ebp-contract--names jetpacs-lint-action-fields))
   (cons "offline_policies" (vconcat jetpacs-lint--when-offline-values))
   (cons "offline_default"  "queue")
   (cons "action_schema"    (ebp-contract--action-schema))
   (cons "toolbar"
         (list (cons "ops"        (ebp-contract--names jetpacs-lint--toolbar-ops))
               (cons "placements" (vconcat jetpacs-lint--toolbar-placements))
               (cons "line_ops"   (vconcat jetpacs-lint--toolbar-line-ops))))
   (cons "binding"
         (list (cons "layouts"            (vconcat jetpacs-lint-spec-layouts))
               (cons "transforms"         (vconcat jetpacs-lint-spec-transforms))
               (cons "spec_keys"          (vconcat (mapcar (lambda (k) (substring (symbol-name k) 1))
                                                           jetpacs-lint-spec-keys)))
               (cons "chrome_kinds"       (vconcat jetpacs-lint-spec-chrome-kinds))
               (cons "source_field_types" (vconcat jetpacs-source-field-types))))))

(defun ebp-contract-string ()
  "The canonical JSON text of the contract, with one terminal newline."
  (let ((json-encoding-pretty-print t)
        (json-encoding-default-indentation "  ")
        (json-encoding-object-sort-predicate nil))
    (concat (json-encode (ebp-contract)) "\n")))

(defun ebp-contract-file ()
  "Committed location of `contract.json' (this repo's root)."
  (expand-file-name "contract.json" ebp-contract--ebp-root))

(defun ebp-contract-write ()
  "Write the contract to `contract.json' (UTF-8, LF)."
  (let ((coding-system-for-write 'utf-8-unix))
    (write-region (ebp-contract-string) nil (ebp-contract-file)))
  (message "Wrote %s" (ebp-contract-file)))

(provide 'build-contract)
;;; build-contract.el ends here
