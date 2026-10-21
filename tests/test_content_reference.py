"""Real signed versions/native bytes; references cannot grant access or follow edits."""
from test_content_fabric import FabricTests
from ziokt.content_reference import create,resolve,verify_reference
from ziokt.protocol import ProtocolError

class ReferenceTests(FabricTests):
    def test_signed_reference_verifies_native_bytes_and_pins_edition(self):
        obj=self.upload();book=self.book(obj,'public')
        linked=create(self.fabric,'alice',book['id'],verify_bytes=True)
        self.assertTrue(linked['content_bytes_verified']);self.assertFalse(linked['permission_granted_by_reference'])
        self.assertEqual(verify_reference(linked['reference'],linked['source_event']),linked['reference'])
        self.assertEqual(resolve(self.fabric,'bob',linked['reference'])['state'],'available')
        edited=dict(self.fabric._get('alice',book['id']));edited['id']=book['id'];edited.pop('file');edited.pop('updated_at');edited['edition_id']='revised';edited['visibility']='public'
        self.fabric.create_book('alice',edited)
        with self.assertRaises(ProtocolError) as changed:resolve(self.fabric,'bob',linked['reference'])
        self.assertEqual(changed.exception.code,'CONTENT_VERSION_CHANGED')
        forged={**linked['reference'],'origin':'f'*64}
        with self.assertRaises(ProtocolError):verify_reference(forged,linked['source_event'])

    def test_private_or_locally_stopped_reference_does_not_publish_or_authorize(self):
        obj=self.upload();self.book(obj)
        with self.assertRaises(PermissionError):create(self.fabric,'alice','book')
        with self.assertRaises(PermissionError):create(self.fabric,'bob','book')
        self.assertFalse(self.fabric.export()['events'])

        self.book(obj,'public',bid='public-book')
        from ziokt.content_rights import Governance
        Governance(self.fabric).policy('operator','public-book','stop_distribution','local policy',allow=True)
        with self.assertRaises(PermissionError):create(self.fabric,'alice','public-book')

    def test_shared_api_returns_signed_reference_and_denies_implicit_rights(self):
        from ziokt.content_api import invoke
        obj=self.upload();book=self.book(obj,'public')
        linked=invoke(self.fabric,'alice','content.reference.create',{'id':book['id'],'verify_bytes':True})
        result=invoke(self.fabric,'bob','content.reference.resolve',{'reference':linked['reference'],'verify_bytes':True})
        self.assertEqual(result['state'],'available')
        self.assertFalse(result['permission_granted_by_reference'])
        self.fabric.withdraw('alice',book['id'])
        with self.assertRaises((PermissionError,KeyError,ProtocolError,ValueError)):
            invoke(self.fabric,'bob','content.reference.resolve',{'reference':linked['reference'],'verify_bytes':False})
