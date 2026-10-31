import pathlib,tempfile,threading,unittest
from unittest.mock import patch
from ziokt.mcp import Service

class NativeListenerLifecycleTests(unittest.TestCase):
    def test_start_without_http_visitor_retry_failure_and_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            config={'schema':'ziokt.mcp.v1','issuer':'https://gateway.test','state':str(pathlib.Path(tmp)/'state'),'bridges':{},'clients':{},'etp':{'replica':{'binary':'owner-binary','digest':'pinned','config':'owner-config'}},'etp_autostart':True}
            service=Service(config);self.addCleanup(service.close);ready=threading.Event();calls=[]
            class Backend:
                def call(self,method,params):
                    calls.append(method)
                    if len(calls)==1:raise RuntimeError('native process died')
                    ready.set()
            with patch.object(service,'etp_backend',return_value=Backend()):
                service.start_native_etp();thread=service.etp_thread;service.start_native_etp();self.assertIs(service.etp_thread,thread)
                self.assertTrue(ready.wait(8),'native listener did not restart autonomously')
                service.close();self.assertFalse(thread.is_alive());self.assertEqual(calls,['etp.stats','etp.stats'])
