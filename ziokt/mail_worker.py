"""Run reliable account-local synchronization independently of the interactive client."""
import argparse
import signal
import threading
from .protocol import secure_read,strict_json
from .mail_accounts import InternetAccounts

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--once',action='store_true');args=parser.parse_args()
    config=strict_json(secure_read(args.config,131072),131072)
    internet=config['internet']
    if 'accounts' not in internet:internet={'accounts':[internet]}
    accounts=InternetAccounts(internet,config.get('internet_state',str(config['state'])+'/internet'))
    run(accounts,once=args.once)


def run(channel, *, once=False):
    if once:
        if hasattr(channel,'sync_once'):channel.sync_once()
        else:
            if channel.config.get('smtp'):channel.flush(5)
            if channel.config.get('imap'):channel.poll(5)
        return channel.status()
    done=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:done.set())
    channel.start()
    try:done.wait()
    finally:channel.close()
    return channel.status()

if __name__=='__main__':main()
