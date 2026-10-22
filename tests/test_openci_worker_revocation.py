"""Actual authenticated HTTP revocation, not a simulated request dispatcher."""
import unittest
import test_openci_http as fixture
from openci.state import Error


class WorkerRevocationTests(unittest.TestCase):
    setUp=fixture.HTTPTests.setUp
    def test_only_admin_can_disable_and_disabled_worker_cannot_claim(self):
        self.owner.request('POST','/v1/workers/approve',{'worker':'node1','arch':'x86_64','pool':'community','cpu':1,'memory_mb':128,'slots':1,'projects':['demo']})
        for client in (self.other,self.worker):
            with self.assertRaises(Error) as caught:client.request('POST','/v1/workers/disable',{'worker':'node1'})
            self.assertEqual(caught.exception.status,403)
        for body in ({'worker':'node1','enabled':True},{'worker':True},{}):
            with self.assertRaises(Error):self.owner.request('POST','/v1/workers/disable',body)
        result=self.owner.request('POST','/v1/workers/disable',{'worker':'node1'})
        self.assertEqual(result['state'],'disabled')
        self.assertEqual(self.owner.request('POST','/v1/workers/disable',{'worker':'node1'}),result)
        with self.assertRaises(Error):self.worker.request('POST','/v1/claim',{})
        with self.assertRaises(Error) as caught:self.owner.request('POST','/v1/workers/disable',{'worker':'unknown'})
        self.assertEqual(caught.exception.status,404)

if __name__=='__main__':unittest.main()
