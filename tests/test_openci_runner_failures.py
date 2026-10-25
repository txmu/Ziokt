"""Failure-path regression only; actual OCI execution belongs to CI."""
import io
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from openci.runner import Runner
from test_openci_state import pipeline


class RunnerFailures(unittest.TestCase):
    def test_container_creation_failure_persists_failed_receipt_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'source.tar'
            with tarfile.open(source,'w') as archive:
                member=tarfile.TarInfo('input');member.size=4
                archive.addfile(member,io.BytesIO(b'data'))
            assignment={'pipeline':'pipeline','project':'demo','task':pipeline()['tasks'][0],
                        'source':pipeline()['source'],'lease':'lease','attempt':1}
            receipts=[];uploaded=[];commands=[]
            class Client:
                def request(self,method,path,body):
                    if path=='/v1/claim':return {'assignment':assignment}
                    if path=='/v1/finish':
                        receipts.append(body)
                        return {'state':'failed'}
                    return {}
                def download(self,project,reference,path,maximum):shutil.copyfile(source,path)
                def upload(self,project,path):
                    uploaded.append(Path(path).read_bytes())
                    return pipeline()['source']
            def command(*args,**kwargs):
                commands.append(args)
                if args[0]=='create':raise subprocess.CalledProcessError(125,['docker','create'])
                return subprocess.CompletedProcess(args,0,stdout='amd64\n')
            runner=Runner(Client(),root/'runner',[assignment['task']['image']])
            with patch.object(runner,'command',side_effect=command):
                self.assertEqual(runner.run_once(),{'state':'failed'})
            self.assertEqual(receipts[0]['exit_code'],125)
            self.assertIsNone(receipts[0]['artifact'])
            self.assertNotIn('cache_artifact',receipts[0])
            self.assertIn(b'CalledProcessError',uploaded[0])
            create=next(args for args in commands if args[0]=='create')
            self.assertFalse(any('dst=/cache' in str(arg) for arg in create))
            self.assertIn('/cache:rw,nosuid,nodev,size=67108864,mode=1777',create)
            self.assertEqual(commands[-1][0:2],('rm','--force'))
            self.assertIsNone(runner.assignment)
            self.assertFalse(list((root/'runner').glob('receipt-*.json')))
