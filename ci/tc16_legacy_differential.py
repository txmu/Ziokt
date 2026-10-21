"""CI-native compiler -> same package on Python and Rust; no sample app claim."""
import base64,json,subprocess,sys
from ziokt.tc16_spec import execute_package,unpack

def main():
    cases=['int main(){return 0;}','int main(){return 65535+2;}','int main(){return 0-1;}','int main(){return 17-3+9;}','void helper(){return 1;} int main(){return 42;}']
    rejected=['int main(){int x=5;return x;}','int main(){return 2*3;}','int main(){contract_store(1,2);return 0;}','int main(){return 65536;}','int main(){return 1;']
    with subprocess.Popen([sys.argv[1]],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True) as compiler,subprocess.Popen([sys.argv[2]],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True) as rust:
        for source in cases+rejected:
            compiler.stdin.write(json.dumps({'source':source})+'\n');compiler.stdin.flush();frame=json.loads(compiler.stdout.readline())
            if source in rejected:
                assert frame['ok'] is False,frame
                continue
            assert frame['ok'] is True,frame
            result=frame['result'];blob=base64.b64decode(result['package']);metadata,code=unpack(blob,{'tc16-unified-v1'})
            python=execute_package(blob,10000)
            rust.stdin.write(json.dumps({'package':result['package'],'cycles':10000})+'\n');rust.stdin.flush();native=json.loads(rust.stdout.readline())
            assert python==native,{'source':source,'python':python,'rust':native}
            assert python['exception'] is None and python['halted'],python
            assert python['registers'][0]==result['legacy_result'],{'source':source,'expected':result['legacy_result'],'actual':python}
            assert result['debug']['functions']['main']>=4
        compiler.stdin.close();rust.stdin.close();assert compiler.wait(timeout=5)==0;assert rust.wait(timeout=5)==0
    print(json.dumps({'schema':'etp.legacy-differential.v1','native_compiler':True,'real_executors':3,'accepted':len(cases),'explicitly_rejected':len(rejected),'real_legacy_application_samples':'not_found_skipped','all_legacy_features':False}))

if __name__=='__main__':main()
