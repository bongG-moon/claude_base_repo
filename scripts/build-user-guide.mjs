// Backward-compatible entrypoint. Do not rebuild a separate, divergent guide.
// Same arguments: --modules <approved node_modules> [--check]
await import('./build-manuals.mjs');
