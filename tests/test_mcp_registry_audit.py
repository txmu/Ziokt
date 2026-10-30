import json
from pathlib import Path
import tempfile
import threading
import unittest

from tools.audit_mcp_registry import audit,compare,build_alignment
from ziokt.build_info import registry_digest,snapshot
from ziokt.gateway import Server
from ziokt.mcp import Service,http_handler


class RegistryAuditTests(unittest.TestCase):
    def test_descriptor_equality_cannot_hide_deployment_version_drift(self):
        source={'source_commit':'a'*40,'python_sources_sha256':'b'*64,'native_sources':{'corium':{'revision':'c'*40}},'working_tree_dirty':False}
        deployed={**source,'source_commit':'d'*40}
        result=build_alignment(source,{'serverInfo':{'build':deployed}},{'build':source,'native_entrypoint_digest':'sha256:'+'e'*64})
        self.assertFalse(result['all_build_metadata_matches'])
        self.assertEqual(result['declarations'][0]['status'],'mismatch')
        self.assertNotIn('installed_native_revision_verification',result)
        self.assertTrue(build_alignment(source,{'serverInfo':{'build':source}},{'build':source})['all_build_metadata_matches'])
        self.assertFalse(build_alignment(source,{},None)['all_build_metadata_matches'])
        self.assertFalse(build_alignment({**source,'working_tree_dirty':True},{'serverInfo':{'build':source}},{'build':source})['all_build_metadata_matches'])

    def test_compares_authorization_schema_and_mutation_separately(self):
        tool={'name':'example','scope':'private:read','inputSchema':{'type':'object'},'securitySchemes':[{'scopes':['private:read']}],'annotations':{'readOnlyHint':True}}
        row=compare([tool],[{key:value for key,value in tool.items() if key!='scope'}],[tool])[0]
        self.assertEqual(row['source_live_differences'],[])
        changed={**tool,'securitySchemes':[{'scopes':['private:write']}],'inputSchema':{'type':'array'},'annotations':{'readOnlyHint':False}}
        row=compare([tool],[changed],[tool])[0]
        self.assertEqual(set(row['source_live_differences']),{'authorization_changed','schema_changed','operation_semantics_changed'})
        self.assertNotIn('business_operational',row)

    def test_set_order_does_not_hide_real_schema_or_scope_changes(self):
        original={'name':'example','inputSchema':{'required':['a','b'],'enum':['one','two']},'securitySchemes':[{'scopes':['read','write']}]}
        reordered={'name':'example','inputSchema':{'required':['b','a'],'enum':['two','one']},'securitySchemes':[{'scopes':['write','read']}]}
        row=compare([original],[reordered],[original])[0]
        self.assertEqual(row['source_live_differences'],[])
        self.assertEqual(set(row['representation_only_differences']),{'inputSchema','securitySchemes'})
        self.assertEqual(registry_digest([original]),registry_digest([reordered]))
        reordered['inputSchema']['required'].append('c')
        self.assertEqual(compare([original],[reordered],[original])[0]['source_live_differences'],['schema_changed'])

    def test_missing_extra_and_duplicate_ids(self):
        rows=compare([{'name':'missing'}],[{'name':'extra'}],[{'name':'missing'}])
        self.assertEqual({change for row in rows for change in row['source_live_differences']},{'missing_in_live_registry','live_only_tool'})
        with self.assertRaises(ValueError):compare([{'name':'same'},{'name':'same'}],[],[])
        self.assertEqual(registry_digest([{'name':'b'},{'name':'a','scope':'x'}]),registry_digest([{'name':'a'},{'name':'b'}]))

    def test_actual_http_registry_matches_source_without_credentials_or_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config={'state':str(root/'state'),'issuer':'https://test.invalid','bridges':{},'clients':{},'writes_enabled':False}
            service=Service(config);server=Server(('127.0.0.1',0),http_handler(service))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                config_path=root/'config.json';config_path.write_text(json.dumps(config));config_path.chmod(0o600)
                baseline=root/'baseline.json';baseline.write_text(json.dumps({'tools':list(service.tools.values())}))
                output=root/'audit.json'
                result=audit(config_path,baseline,'http://127.0.0.1:'+str(server.server_port)+'/mcp',output)
                self.assertTrue(result['all_descriptors_match'])
                report=json.loads(output.read_text());self.assertEqual(report['live_discovery']['serverInfo']['build'],snapshot())
                self.assertEqual(report['live_discovery']['registry_sha256'],result['source_registry_sha256'])
                self.assertEqual(len(report['tools']),len(service.tools))
                self.assertTrue(output.with_suffix('.md').is_file())
            finally:server.shutdown();server.server_close();service.close()


if __name__=='__main__':unittest.main()
