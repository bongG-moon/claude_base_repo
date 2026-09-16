"""Standalone entry: intentionally does not initialize or modify User State."""
import sys

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8')

from company_agent.routing_diagnostics import main

if __name__ == '__main__':
    raise SystemExit(main())
