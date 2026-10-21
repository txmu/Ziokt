"""MCP native binding lifetime and scope tests; no simulated native evidence."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ziokt.mcp import Service
from ziokt.content_api import required_scopes

class NativeMcpBindingTests(unittest.TestCase):
    def setUp(self):
        self.area=tempfile.TemporaryDirectory();self.addCleanup(self.area.cleanup)
        root=Path(self.area.name);admin=root/'admin';admin.write_text('a'*64);admin.chmod(0o600)
        self.service=Service({'schema':'ziokt.mcp.v1','issuer':'https://gateway.test','origins':['https://gateway.test'],
            'state':str(root/'state'),'admin_token':str(admin),'bridges':{},'clients':{},'writes_enabled':True})
        self.addCleanup(self.service.close)
        self.config={'gateway':{'binary':'/missing/native-etp','digest':'a'*64,'config':'/missing/private-config'},
            'accounts':{'alice':{'aliases':[],'topics':[],'groups':[],'remote_authors':[],
                'fileshare':{'authors':['a'*64],'topics':['books'],'peers':['127.0.0.1:1234']}}}}
    def test_lazy_binding_reused_and_revocation_closes_shared_backend(self):
        settings={'enabled':True,'native_etp':self.config}
        adapter=self.service.native_content_etp(settings)
        self.assertIs(adapter,self.service.native_content_etp(settings))
        self.assertFalse(self.service.etp) # offline status need not launch native node
        with patch('ziokt.etp.EtpGateway') as constructor:
            gateway=constructor.return_value;gateway.call.return_value={'controlled':True}
            adapter.call('etp.stats',{})
            self.assertIs(self.service.etp_backend(self.config['gateway']),gateway)
            adapter.call('etp.stats',{})
            self.assertEqual(constructor.call_count,1)
            self.assertIsNone(self.service.native_content_etp({'enabled':False}))
            gateway.close.assert_called_once()
            self.assertFalse(self.service.etp)
    def test_library_source_writes_require_both_delegations(self):
        for operation in ('begin','step','cancel'):
            self.assertEqual(required_scopes('library.etp.'+operation),{'library:write','content:write'})
        self.assertEqual(required_scopes('library.etp.status'),{'library:read'})
    def test_inflight_library_steps_read_current_revocable_policy(self):
        from ziokt.content_etp_application import EtpApplications
        live=[self.config['accounts']['alice']['fileshare']]
        app=EtpApplications(self.config,file_policy=lambda owner:live[0] if owner=='alice' else None)
        try:
            self.assertEqual(app.file_policy('alice')['topics'],['books'])
            live[0]=None
            self.assertIsNone(app.file_policy('alice'))
        finally:app.close()
