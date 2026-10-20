"""A rendered catalog must not manufacture native runtime observations."""
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class ObservationTests(unittest.TestCase):
    def render(self,app,context=None,api_override=None,query=None):
        class API:
            def get_node_context(self):return context or {}
        source=(ROOT/'gateway/default_dapp/entrypoint.py').read_text().replace('MESSAGES = {}','MESSAGES = '+repr(json.loads((ROOT/'gateway/i18n.json').read_text())))
        namespace={'api':api_override or API(),'request':{'app_id':app,'locale':'en-US','query':query or {}}}
        exec(compile(source,'gateway/default_dapp/entrypoint.py','exec'),namespace)
        return namespace['response']

    def test_absent_observations_keep_catalog_and_authorized_controls(self):
        for app in ('ufsdcpm','shadow6','watchat','blockchain','overview'):
            with self.subTest(app=app):
                page=self.render(app)
                self.assertIn('runtime-evidence-note',page)
                self.assertIn('mcp-console',page)
                for unsupported in ('>VERIFIED</span>','>RUNNING</span>','>LISTENING<','HEALTHY / 100%','ONLINE &bull; ETP-v2','ACTIVE / MOUNTED'):
                    self.assertNotIn(unsupported,page)
        self.assertIn('go-kcp',self.render('shadow6'))
        self.assertIn('Example digest only',self.render('ufsdcpm'))

    def test_actual_context_values_are_escaped_and_unknown_is_not_zero(self):
        page=self.render('overview',{'blockchain':{'height':42,'tx_count':7},'dht':{'nodes_count':3,'chunks_count':9}})
        self.assertIn('#42',page)
        literal=self.render('overview',{'blockchain':{'height':'NOT OBSERVED'}});self.assertIn('#NOT OBSERVED',literal)
        absent=self.render('overview');self.assertIn('#Not observed',absent)
        forged=self.render('overview',{'blockchain':{'height':'<script>fixture</script>'}})
        self.assertNotIn('<script>fixture</script>',forged)

    def test_public_board_is_not_claimed_e2ee_and_failed_write_is_not_sent(self):
        class FailedVault:
            def get_node_context(self):return {}
            def read_from_vault(self,path):return {'status':'success','data':json.dumps([{'user':'<img src=x onerror=alert(1)>','msg':'<script>vault</script>'}])}
            def write_to_vault(self,*args):return {'status':'error'}
        # Use an empty vault for the write-failure case; timestamp formatting in
        # the existing reader is exercised with a valid legacy record below.
        class Empty(FailedVault):
            def read_from_vault(self,path):return {'status':'error'}
        page=self.render('watchat',api_override=Empty(),query={'msg':['UNSTORED-TEST-MESSAGE']})
        self.assertIn('Public plaintext board',page)
        self.assertNotIn('ENCRYPTED P2P CHANNEL',page)
        self.assertIn('The board entry was not stored',page)
        self.assertNotIn('UNSTORED-TEST-MESSAGE',page)
        page=self.render('watchat',api_override=FailedVault())
        self.assertNotIn('<script>vault</script>',page)
        self.assertNotIn('<img src=x onerror=alert(1)>',page)

    def test_no_invented_public_services_or_encoded_old_ip(self):
        for app in ('shadow6', 'ufsdcpm', 'watchat'):
            page = self.render(app)
            for forbidden in ('https://chat.ziokt.com', 'https://ufs.ziokt.com',
                              'https://shadow6.ziokt.com', 'sslip.io', '43.207.75.185', 'IjQzLjIwNy43NS4xODUi'):
                self.assertNotIn(forbidden, page)
        page = self.render('shadow6')
        self.assertIn('/api/gateway/public-address', page)
        self.assertIn('not signature or connectivity verification', page)
        self.assertIn('envelopeText(r.host', page)

    def test_shadow6_failed_vault_write_is_not_claimed_saved(self):
        class FailedVault:
            def get_node_context(self): return {}
            def read_from_vault(self, path): return {'status': 'error'}
            def write_to_vault(self, *args): return {'status': 'error'}
        page = self.render('shadow6', api_override=FailedVault(),
                           query={'s6p1': ['S6P1.rejected'], 'action': ['save']})
        self.assertIn('Vault did not confirm persistence', page)
        self.assertNotIn('已安全存入', page)
