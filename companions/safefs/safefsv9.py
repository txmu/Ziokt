"""Compatibility command for the modern bounded, non-root SafeFS vault."""
from ziokt.safefs import Vault,sandbox_plan
if __name__=='__main__':
    from ziokt.companion_cli import main
    raise SystemExit(main(['safefs',*__import__('sys').argv[1:]]))
