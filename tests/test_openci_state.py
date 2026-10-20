"""Controller tests use real SQLite; they do not claim container execution."""
from concurrent.futures import ThreadPoolExecutor
import copy
import tempfile
import unittest
from openci.state import Error, Store, validate_pipeline

REF = {'object':'cf1-'+'1'*64,'digest':'sha256:'+'a'*64}
OTHER = {'object':'cf1-'+'2'*64,'digest':'sha256:'+'b'*64}


def task(name='build', needs=None, pool='community'):
    return {'id': name, 'needs': needs or [], 'image': 'example.invalid/ci@sha256:'+'1'*64,
            'argv': ['make'], 'arch': 'x86_64', 'pool': pool, 'cpu': 1,
            'memory_mb': 128, 'timeout': 30, 'attempts': 2}


def pipeline(tasks=None, project='demo', nonce='one'):
    return {'schema': 'openci.pipeline.v1', 'project': project, 'nonce': nonce,
            'source': REF, 'tasks': tasks or [task()]}


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.now = 1000
        self.store = Store(self.temporary.name, clock=lambda: self.now)
        self.worker('node1')

    def worker(self, name, pool='community', projects=None, cpu=2, slots=2):
        self.store.approve_worker('owner', name, arch='x86_64', pool=pool,
            cpu=cpu, memory_mb=256, slots=slots, projects=projects or ['demo'])

    def submit(self, spec=None):
        return self.store.submit('owner', spec or pipeline())['pipeline']

    def finish(self, claim, code=0):
        return self.store.finish('node1', claim['pipeline'], claim['task']['id'], claim['lease'],
                                 exit_code=code, artifact=REF if code == 0 else None, logs=OTHER)

    def test_idempotency_conflict_and_cycle_no_partial_submission(self):
        pid = self.submit()
        self.assertTrue(self.store.submit('owner', pipeline())['duplicate'])
        changed = pipeline(); changed['tasks'][0]['argv'] = ['other']
        with self.assertRaisesRegex(Error, 'Nonce'): self.submit(changed)
        cyclic = pipeline([task('a', ['b']), task('b', ['a'])], nonce='cycle')
        with self.assertRaisesRegex(Error, 'Cycle'): self.submit(cyclic)
        self.assertEqual(self.store.inspect(pid)['state'], 'submitted')

    def test_schema_rejects_mutable_image_and_invalid_resources(self):
        for change in ({'image':'ubuntu:latest'}, {'memory_mb':True}, {'cpu':0},
                       {'attempts':100}, {'argv':['bad\x00argument']}):
            value = pipeline();value['tasks'][0].update(change)
            with self.subTest(change=change), self.assertRaises(Error): validate_pipeline(value)

    def test_dag_completion_is_not_verification_or_release_or_settlement(self):
        pid = self.submit(pipeline([task('build'), task('test', ['build'])]))
        claim = self.store.claim('node1'); self.assertEqual(claim['task']['id'], 'build')
        self.assertIsNone(self.store.claim('node1'))
        self.assertEqual(self.finish(claim)['verification'], 'pending')
        self.assertTrue(self.finish(claim)['duplicate'])
        self.finish(self.store.claim('node1'))
        result = self.store.inspect(pid)
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['release'], 'unpublished')
        self.assertEqual(result['settlement'], 'not_requested')
        self.assertTrue(all(task['verification'] is None for task in result['tasks']))

    def test_crash_restart_reassigns_and_old_worker_cannot_replay(self):
        pid = self.submit(); first = self.store.claim('node1', 10)
        self.now += 11
        restarted = Store(self.temporary.name, clock=lambda: self.now)
        second = restarted.claim('node1', 10)
        self.assertEqual(second['attempt'], 2)
        self.assertNotEqual(first['lease'], second['lease'])
        with self.assertRaises(Error): self.finish(first)
        self.finish(second)
        self.assertEqual(restarted.inspect(pid)['state'], 'completed')

    def test_expired_leases_hit_attempt_limit_and_block_dependants(self):
        pid = self.submit(pipeline([task('a'), task('b', ['a'])]))
        self.store.claim('node1', 10); self.now += 11
        self.store.claim('node1', 10); self.now += 11
        self.assertIsNone(self.store.claim('node1'))
        result = self.store.inspect(pid)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual([task['state'] for task in result['tasks']], ['failed', 'blocked'])

    def test_project_and_pool_and_capacity_are_operator_caps(self):
        self.submit(pipeline([task(pool='trusted')]))
        self.assertIsNone(self.store.claim('node1'))
        self.worker('release', pool='trusted', projects=['other'])
        self.assertIsNone(self.store.claim('release'))
        self.worker('approved', pool='trusted')
        self.assertIsNotNone(self.store.claim('approved'))
        self.submit(pipeline([task('one'),task('two'),task('three')], nonce='parallel'))
        self.assertIsNotNone(self.store.claim('node1'))
        self.assertIsNotNone(self.store.claim('node1'))
        self.assertIsNone(self.store.claim('node1'))
        with self.assertRaisesRegex(Error, 'Drain'): self.worker('node1', cpu=64)

    def test_unknown_worker_and_disabled_worker_cannot_claim(self):
        self.submit()
        with self.assertRaises(Error): self.store.claim('self-reported-supercomputer')
        self.store.disable_worker('owner', 'node1')
        with self.assertRaises(Error): self.store.claim('node1')

    def test_cancel_revokes_lease_and_heartbeat(self):
        pid = self.submit(); claim = self.store.claim('node1')
        self.store.cancel('owner', pid)
        with self.assertRaises(Error): self.finish(claim)
        with self.assertRaises(Error): self.store.heartbeat('node1', pid, 'build', claim['lease'])
        self.assertEqual(self.store.inspect(pid)['state'], 'cancelled')

    def test_retry_failed_task_and_conflicting_receipt(self):
        pid = self.submit(pipeline([task('a'), task('b', ['a'])]))
        first = self.store.claim('node1'); self.finish(first, 1)
        self.assertEqual(self.store.inspect(pid)['tasks'][1]['state'], 'blocked')
        with self.assertRaises(Error): self.finish(first)
        self.store.retry('owner', pid, 'a')
        self.finish(self.store.claim('node1'))
        self.assertEqual(self.store.claim('node1')['task']['id'], 'b')

    def test_two_controllers_do_not_double_assign(self):
        self.submit()
        other = Store(self.temporary.name, clock=lambda: self.now)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda store: store.claim('node1'), [self.store, other]))
        self.assertEqual(sum(result is not None for result in results), 1)


if __name__ == '__main__': unittest.main()
