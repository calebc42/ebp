# EBP — the Emacs Bridge Protocol

Emacs Bridge
Protocol, a JSON-RPC envelope inspired by Language Server Protocol that can be
transported to any companion that can hold a socket and draw
pixels to a canvas. Not just Jetpacs, eg Electron, Tauri, etc.

This branch is the hand-written rebuild.

The other jetpacs reference implementations pin the prior SPEC 2.0 protocol on
the `slop-fork/main` branch. This is the north star the rebuild writes toward.