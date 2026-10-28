"""Validate ALFS phase boundaries and checkpoint identity without native builds."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location('alfs_'+name,ROOT/'ci/openci/alfs'/f'{name}.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class AlfsCheckpointTests(unittest.TestCase):
    def test_only_reached_package_breakpoints_are_partial_success(self):
        module=load('run_jhalfs')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);active=root/'jhalfs';active.mkdir()
            with self.assertRaises(RuntimeError):module.check_exit('base',2,root)
            (active/'829-gawk').touch();self.assertEqual(module.check_exit('base',2,root),'checkpointed')
            with self.assertRaises(RuntimeError):module.check_exit('base',0,root)
            (active/'830-gcc').touch()
            with self.assertRaises(RuntimeError):module.check_exit('base',2,root)
            self.assertEqual(module.check_exit('gcc',2,root),'checkpointed')
            with self.assertRaises(RuntimeError):module.check_exit('finish',2,root)
            self.assertEqual(module.check_exit('finish',0,root),'completed')
    def test_resume_runs_upstream_make_and_clears_previous_breakpoint(self):
        module=load('run_jhalfs')
        _,_,env=module.command('/tmp/source','base','/tmp/build');self.assertEqual(env['MAKEFLAGS'],'BREAKPOINT=829-gawk')
        args,cwd,_=module.command('/tmp/source','gcc','/tmp/build');self.assertEqual(args,['make','-j1','BREAKPOINT=830-gcc']);self.assertEqual(cwd,Path('/tmp/build/jhalfs'))
        args,_,env=module.command('/tmp/source','finish','/tmp/build');self.assertEqual(args,['make','-j1']);self.assertNotIn('MAKEFLAGS',env)
    def test_checkpoint_is_exact_revision_run_and_content_bound(self):
        module=load('checkpoint')
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);files={}
            for name in ('root.tar.zst','kernel.config','jhalfs-configuration'):
                (folder/name).write_bytes(name.encode());files[name]=hashlib.sha256(name.encode()).hexdigest()
            receipt={'schema':'openci.alfs-checkpoint.v1','phase':'base','source_revision':'a'*40,'run_id':'123','full_build_complete':False,'files':files}
            (folder/'checkpoint.json').write_text(json.dumps(receipt))
            module.validate_receipt(folder,'base','a'*40,'123')
            for phase,revision,run in [('gcc','a'*40,'123'),('base','b'*40,'123'),('base','a'*40,'124')]:
                with self.assertRaises(ValueError):module.validate_receipt(folder,phase,revision,run)
            (folder/'kernel.config').write_bytes(b'tampered')
            with self.assertRaises(ValueError):module.validate_receipt(folder,'base','a'*40,'123')
    def test_checkpoint_cannot_write_outside_root_or_create_devices(self):
        module=load('checkpoint');valid=tarfile.TarInfo('openci-lfs/usr/bin/compiler');valid.size=1;module.validate_members([valid])
        for name in ('/etc/passwd','openci-lfs/../../etc/passwd','other/root'):
            with self.assertRaises(ValueError):module.validate_members([tarfile.TarInfo(name)])
        device=tarfile.TarInfo('openci-lfs/dev/device');device.type=tarfile.CHRTYPE
        with self.assertRaises(ValueError):module.validate_members([device])
    def test_parallel_gcc_check_preserves_the_complete_book_test_command(self):
        module=load('configure')
        original='su tester -c "PATH=$PATH make -k check"'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'book/chapter08/gcc.xml';source.parent.mkdir(parents=True);(root/'evidence').mkdir()
            source.write_text('<userinput>'+original+'</userinput>')
            module.prepare_gcc_tests(root,2)
            self.assertIn('su tester -c "PATH=$PATH make -j2 -k check"',source.read_text())
            self.assertFalse(json.loads((root/'evidence/gcc-test-adaptation.json').read_text())['tests_removed'])
            with self.assertRaises(ValueError):module.prepare_gcc_tests(root,2)
