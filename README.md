# EBP — the Emacs Bridge Protocol

Emacs Bridge
Protocol, a JSON-RPC envelope inspired by Language Server Protocol that can be
transported to any companion that can hold a socket and draw
pixels to a canvas. Not just Jetpacs, eg Electron, Tauri, etc.

This branch is the hand-written rebuild.

The other jetpacs reference implementations pin the prior SPEC 2.0 protocol on
the `slop-fork/main` branch. This is the north star the rebuild writes toward.


- Emacs owns application state and policy.  
- Companions provide native presentation and platform integration.  
- EBP carries declarative data and semantic actions, never executable application code.  
- Implementations are language- and toolkit-independent.  
- Capabilities beyond the mandatory core are explicitly negotiated.

Jetpacs is one Companion; EBP is the contract that makes Jetpacs replaceable.