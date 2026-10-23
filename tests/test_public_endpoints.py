"""Endpoint configuration has no fixed server address and never publishes credentials."""
import unittest
from ziokt.gateway import public_endpoints
class PublicEndpointTests(unittest.TestCase):
    def test_arbitrary_hosts_ipv6_ports_and_paths_are_preserved(self):
        values={'gateway':'https://gateway.example.net:9443/','content':'https://[2001:db8::1]:9444/read/','openci':'https://build.example.org/','nntp':'nntps://news.example.net:563/'}
        self.assertEqual(public_endpoints(values),values)
        self.assertEqual(public_endpoints({}),{})
    def test_credentials_script_urls_and_undocumented_fields_fail(self):
        for value in ({'private':'https://example.org/'},{'mcp':'https://user:secret@example.org/'},{'mcp':'javascript:alert(1)'},{'mcp':'https://example.org/?token=secret'},{'mcp':'https://example.org/#secret'},{'mcp':'https://example.org:bad/'},{'mcp':None}):
            with self.subTest(value=value),self.assertRaises(ValueError):public_endpoints(value)
if __name__=='__main__':unittest.main()

class OriginConfigurationTests(unittest.TestCase):
    def test_ipv6_and_arbitrary_tls_origins_work_without_disabling_host_checks(self):
        from ziokt.endpoint_config import https_origin,local_listener
        for value in ('https://[::1]:9443','https://gateway.example.net:9444','https://203.0.113.1'):self.assertEqual(https_origin(value),value)
        self.assertEqual(local_listener('::1'),'::1')
        for value in ('http://example.net','https://user:secret@example.net','https://example.net/path'):
            with self.assertRaises(ValueError):https_origin(value)
        for value in ('0.0.0.0','::','203.0.113.1'):
            with self.assertRaises(ValueError):local_listener(value)
