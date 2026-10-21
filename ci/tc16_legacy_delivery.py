"""CI native Legacy compilation -> signed native dCPM -> install -> real runtimes."""
import base64,hashlib,json,subprocess,sys,tempfile
from pathlib import Path
from ziokt.content_fabric import Fabric
from ziokt.protocol import encoded
from ziokt.tc16_legacy import compile_native
from ziokt.tc16_spec import execute_package
from ziokt.ufsdcpm import reference_package

def main():
    binary=Path(sys.argv[1]).resolve();runtime=Path(sys.argv[2]).resolve()
    stat=binary.stat();print(json.dumps({'native_compiler_bytes':stat.st_size,'links':stat.st_nlink,'mode':oct(stat.st_mode & 0o777)}),flush=True)
    result=compile_native('int main(){return 65535+43;}',{'binary':str(binary),'sha256':'sha256:'+hashlib.sha256(binary.read_bytes()).hexdigest()})
    blob=base64.b64decode(result['package'])
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'companions/ufsdcpm/src'))
    from dcpm_ufs_packages import PackageStore
    with tempfile.TemporaryDirectory(prefix='tc16-native-delivery-') as area:
        root=Path(area);fabric=Fabric(root/'fabric')
        try:
            owner='compiler'
            references={}
            for name,data in [('program.tc16',blob),('source.legacy',b'int main(){return 65535+43;}'),('debug.json',encoded(result['debug']))]:
                upload='upload-'+hashlib.sha256(name.encode()).hexdigest()[:16]
                fabric.begin(owner,upload,len(data),'sha256:'+hashlib.sha256(data).hexdigest(),'application/octet-stream')
                for index,start in enumerate(range(0,len(data),16384)):fabric.put(owner,upload,index,data[start:start+16384])
                obj=fabric.finish(owner,upload);references[name]=fabric.object_info(owner,obj['id'])['reference']
            with fabric.store(owner) as objects:
                native=PackageStore(root/'registry',reference_store=objects)
                try:
                    package=reference_package(objects,'etp-legacy-program','1',references,[],native.private)
                    published=native.admit(package);installer=native.file_installer(root/'installed')
                    installed=installer.install(published['package_id'],published['version_id'],allow=True)
                    installer.activate(published['package_id'],published['version_id'],allow=True)
                    actual=(Path(installed['directory'])/'program.tc16').read_bytes();assert actual==blob
                    python=execute_package(actual,10000)
                    rust=subprocess.run([str(runtime)],input=json.dumps({'package':base64.b64encode(actual).decode(),'cycles':10000})+'\n',stdout=subprocess.PIPE,text=True,timeout=10,check=True)
                    assert json.loads(rust.stdout)==python
                    assert python['registers'][0]==42 and python['exception'] is None
                    assert not installed['execution_authorized']
                    print(json.dumps({'schema':'etp.legacy-delivery.v1','state':'verified','native_compiler':True,'native_signed_reference_package':True,'native_file_installed':True,'explicit_test_execution':True,'python_rust_equal':True,'real_application_sample':'not_found_skipped','general_legacy_migration_complete':False}))
                finally:native.close()
        finally:fabric.close()

if __name__=='__main__':main()
