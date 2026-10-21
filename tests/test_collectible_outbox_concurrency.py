"""Real SQLite workers and crash leases; injected errors never claim delivery."""
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from pathlib import Path
import secrets
import tempfile
import threading
import time
import unittest

from cryptography.hazmat.primitives.asymmetric import ec
from ziokt.collectibles import GiftOutbox,gift,receiver
from test_collectibles import snapshot,pem


def crash_after_claim(path,key):
    box=GiftOutbox(path,key)
    def crash(*args):raise SystemExit(97)
    box.cycle(crash,lambda *args:'test-route')


class OutboxConcurrencyTests(unittest.TestCase):
    def setup_queue(self,root):
        key=secrets.token_bytes(32);path=root/'outbox.sqlite'
        owner=ec.generate_private_key(ec.SECP256K1());offer,_=receiver('default')
        transaction=gift(snapshot(owner),1,offer,pem(owner))
        box=GiftOutbox(path,key,privacy_mode='legacy')
        tx=box.enqueue(transaction)
        return path,key,box,tx

    def test_two_independent_connections_only_one_worker_enters_rpc(self):
        with tempfile.TemporaryDirectory() as temp:
            path,key,first,tx=self.setup_queue(Path(temp));self.addCleanup(first.close)
            second=GiftOutbox(path,key);self.addCleanup(second.close)
            entered=threading.Event();release=threading.Event();other=[]
            def failing_rpc(*args):
                entered.set()
                if not release.wait(5):raise AssertionError('test synchronization timed out')
                raise OSError('injected route failure, no native submission')
            with ThreadPoolExecutor(max_workers=1) as pool:
                running=pool.submit(first.cycle,failing_rpc,lambda *args:'route')
                try:
                    self.assertTrue(entered.wait(5))
                    result=second.cycle(lambda *args:other.append(args),lambda *args:'route')
                    self.assertEqual(other,[]);self.assertEqual(result[0]['attempts'],0)
                finally:release.set()
                self.assertEqual(running.result(timeout=5)[0]['attempts'],1)
            self.assertEqual(second.db.execute('SELECT lease_token,lease_until FROM gifts WHERE id=?',(tx,)).fetchone(),(None,0))

    def test_process_crash_keeps_intent_and_expired_lease_recovers(self):
        with tempfile.TemporaryDirectory() as temp:
            path,key,box,tx=self.setup_queue(Path(temp))
            before=box.db.execute('SELECT body,operation_id FROM gifts WHERE id=?',(tx,)).fetchone();box.close()
            process=multiprocessing.get_context('spawn').Process(target=crash_after_claim,args=(path,key))
            process.start();process.join(10)
            if process.is_alive():process.terminate();process.join(5);self.fail('crash worker did not exit')
            self.assertEqual(process.exitcode,97)
            box=GiftOutbox(path,key);self.addCleanup(box.close)
            row=box.db.execute('SELECT body,operation_id,lease_token,lease_until FROM gifts WHERE id=?',(tx,)).fetchone()
            self.assertEqual(row[:2],before);self.assertTrue(row[2]);self.assertGreater(row[3],int(time.time()))
            calls=[];box.cycle(lambda *args:calls.append(args),lambda *args:'route');self.assertEqual(calls,[])
            # Fault injection models an expired durable deadline without waiting 5 minutes.
            with box.db:box.db.execute('UPDATE gifts SET lease_until=? WHERE id=?',(int(time.time())-1,tx))
            def fail(*args):calls.append(args);raise OSError('injected outage')
            self.assertEqual(box.cycle(fail,lambda *args:'route')[0]['attempts'],1)
            self.assertEqual(len(calls),1)
            self.assertEqual(box.db.execute('SELECT body,operation_id FROM gifts WHERE id=?',(tx,)).fetchone(),before)

    def test_stale_worker_cannot_prepare_or_overwrite_new_lease(self):
        with tempfile.TemporaryDirectory() as temp:
            path,key,box,tx=self.setup_queue(Path(temp));self.addCleanup(box.close)
            observer=GiftOutbox(path,key);self.addCleanup(observer.close)
            methods=[];replacement=secrets.token_hex(32)
            def lose_lease(method,args,route):
                methods.append(method)
                with observer.db:
                    observer.db.execute('UPDATE gifts SET lease_token=?,lease_until=?,attempts=7 WHERE id=?',(replacement,int(time.time())+300,tx))
                return {'phase':'absent'}
            box.cycle(lose_lease,lambda *args:'route')
            self.assertEqual(methods,['zkn.fact'])
            self.assertEqual(observer.db.execute('SELECT lease_token,attempts FROM gifts WHERE id=?',(tx,)).fetchone(),(replacement,7))


if __name__=='__main__':unittest.main()
