"""Real archive handling tests; no container execution is simulated as success."""
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from openci.runner import unpack_source, canonical_outputs
from openci.state import Error


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def archive(self, members):
        path=self.root/'input.tar'
        with tarfile.open(path,'w') as archive:
            for name,kind in members:
                info=tarfile.TarInfo(name);info.mtime=123;info.uid=567;info.gid=8
                if kind=='file':info.size=4;archive.addfile(info,io.BytesIO(b'data'))
                else:info.type=tarfile.SYMTYPE;info.linkname='/etc/passwd';archive.addfile(info)
        return path

    def test_source_readonly_and_roundtrip_canonical_output(self):
        source=self.archive([('dir/file','file')]);destination=self.root/'snapshot'
        unpack_source(source,destination)
        self.assertEqual((destination/'dir/file').read_bytes(),b'data')
        self.assertEqual((destination/'dir/file').stat().st_mode&0o222,0)
        output=self.root/'canonical.tar';canonical_outputs(source,output)
        with tarfile.open(output) as archive:
            member=archive.getmembers()[0];self.assertEqual((member.uid,member.gid,member.mtime),(0,0,0))

    def test_parent_absolute_symlink_and_duplicate_rejected(self):
        for members in ([('../escape','file')],[('/absolute','file')],[('link','link')],[('same','file'),('same','file')]):
            with self.subTest(members=members):
                source=self.archive(members)
                with self.assertRaises(Error):unpack_source(source,self.root/('dest'+str(len(list(self.root.iterdir())))))
                with self.assertRaises(Error):canonical_outputs(source,self.root/'out.tar')

    def test_missing_declared_output_is_not_a_valid_artifact(self):
        source=self.archive([('other.txt','file')])
        with self.assertRaises(Error) as missing:
            canonical_outputs(source,self.root/'missing.tar',['result.json'])
        self.assertEqual(missing.exception.code,'OUTPUT_MISSING')


if __name__=='__main__':unittest.main()
