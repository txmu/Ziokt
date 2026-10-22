"""Actual HTTP requests cannot escape the public GUI subtree via prefix siblings."""
from pathlib import Path
import unittest
import ziokt.gateway as module
import test_gateway_native as fixture


class AssetBoundaryTests(unittest.TestCase):
    request=fixture.GatewayTests.request
    def setUp(self):
        fixture.GatewayTests.setUp(self);self.addCleanup(self.gateway.close)
        self.assets=self.root/'assets';gui=self.assets/'gui';gui.mkdir(parents=True)
        self.sibling=self.assets/'gui-private';self.sibling.mkdir();(self.sibling/'secret.txt').write_bytes(b'PRIVATE-UNIT-FIXTURE')
        (gui/'style.css').write_bytes(b'body { color: black; }');(gui/'escape.txt').symlink_to(self.sibling/'secret.txt')
        previous=module.ASSETS;module.ASSETS=self.assets
        self.addCleanup(setattr,module,'ASSETS',previous)
    def test_absolute_prefix_sibling_is_not_a_gui_asset(self):
        status,_,body=self.request('GET','/gateway-assets/gui/'+str(self.sibling/'secret.txt'))
        self.assertEqual(status,404);self.assertNotIn(b'PRIVATE-UNIT-FIXTURE',body)
    def test_symlink_prefix_sibling_is_not_a_gui_asset(self):
        status,_,body=self.request('GET','/gateway-assets/gui/escape.txt')
        self.assertEqual(status,404);self.assertNotIn(b'PRIVATE-UNIT-FIXTURE',body)
    def test_normal_asset_stays_readable(self):
        status,headers,body=self.request('GET','/gateway-assets/gui/style.css')
        self.assertEqual(status,200);self.assertEqual(body,b'body { color: black; }');self.assertEqual(headers['Content-Type'],'text/css; charset=utf-8')

if __name__=='__main__':unittest.main()
