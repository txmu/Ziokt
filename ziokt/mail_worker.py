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
    if args.once:accounts.sync_once();return
    done=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:done.set())
    accounts.start()
    try:done.wait()
    finally:accounts.close()
if __name__=='__main__':main()
