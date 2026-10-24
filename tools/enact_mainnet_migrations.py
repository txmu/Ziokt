#!/usr/bin/env python3
"""Retired historical rewrite entrypoint; deliberately performs no mutations.

A valid signature cannot manufacture missing historical governance. Production
activation requires a signed recovery declaration, chain identity, prospective
policy activation and deterministic replay using the native recovery workflow.
"""

def enact():
    raise RuntimeError('Historical consensus rewriting is disabled. Use the native signed recovery declaration and replay workflow; preserve original history.')

if __name__ == '__main__':
    enact()
