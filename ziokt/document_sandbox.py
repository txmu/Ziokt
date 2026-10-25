"""Linux document parser process: bounded input/output, rlimits and seccomp.

All dependencies load before the syscall filter. The parser cannot open files,
start processes or create network sockets. Unavailable isolation fails closed.
"""
import json
import os
import selectors
import time
from types import SimpleNamespace
from pathlib import Path
import subprocess
import sys
import threading
from contextlib import contextmanager
import tempfile

MAX_INPUT=16*1024*1024
MAX_OUTPUT=256*1024
PARSERS=threading.BoundedSemaphore(2)


@contextmanager
def parser_program():
    program=Path(__file__).resolve()
    if program.is_file():
        yield program
        return
    # A zipapp has no executable host path for its source members. Materialize
    # only the two trusted public parser modules; document bytes still use pipes.
    from importlib.resources import files
    with tempfile.TemporaryDirectory(prefix='ziokt-parser-code-') as directory:
        for name in ('document_sandbox.py','library_formats.py','raster_reader.py'):
            (Path(directory)/name).write_bytes(files('ziokt').joinpath(name).read_bytes())
        yield Path(directory)/'document_sandbox.py'


def bounded_process(command,data):
    """Bound both child pipes while streaming input; never spool private pages to disk."""
    if sys.platform!='linux':raise ValueError('document sandbox unavailable: Linux required')
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             close_fds=True,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
    output=bytearray();errors=bytearray();position=0;deadline=time.monotonic()+8
    try:
        with selectors.DefaultSelector() as events:
            for stream,event in ((process.stdin,selectors.EVENT_WRITE),(process.stdout,selectors.EVENT_READ),(process.stderr,selectors.EVENT_READ)):
                os.set_blocking(stream.fileno(),False);events.register(stream,event)
            while events.get_map():
                remaining=deadline-time.monotonic()
                if remaining<=0:raise subprocess.TimeoutExpired(command,8)
                for key,_ in events.select(min(.2,remaining)):
                    stream=key.fileobj
                    if stream is process.stdin:
                        try:position+=os.write(stream.fileno(),data[position:position+8192])
                        except BrokenPipeError:position=len(data)
                        if position==len(data):events.unregister(stream);stream.close()
                    else:
                        chunk=os.read(stream.fileno(),8192)
                        if not chunk:events.unregister(stream);stream.close();continue
                        destination=output if stream is process.stdout else errors;destination.extend(chunk)
                        if len(destination)>(MAX_OUTPUT if stream is process.stdout else 16384):raise ValueError('reader pipe output limit')
            process.wait(timeout=max(.01,deadline-time.monotonic()))
        return SimpleNamespace(returncode=process.returncode,stdout=bytes(output),stderr=bytes(errors))
    finally:
        if process.poll() is None:process.kill()
        process.wait()
        for stream in (process.stdin,process.stdout,process.stderr):stream.close()


def parse_document(source,mime,mode='preview',**arguments):
    if type(source) is not bytes or len(source)>MAX_INPUT:raise ValueError('reader source limit')
    request=json.dumps({'mime':mime,'mode':mode,'arguments':arguments},ensure_ascii=True).encode()
    if len(request)>2048:raise ValueError('reader request limit')
    if not PARSERS.acquire(blocking=False):raise ValueError('document parser concurrency budget exceeded')
    try:
        try:
            with parser_program() as program:
                interpreter=os.environ.get('ZIOKT_DOCUMENT_PYTHON',sys.executable)
                if not Path(interpreter).is_absolute():raise ValueError('absolute reader interpreter required')
                result=bounded_process([interpreter,'-I',str(program)],request+b'\n'+source)
        except subprocess.TimeoutExpired:
            raise ValueError('reader process deadline exceeded') from None
    finally:PARSERS.release()
    if len(result.stdout)>MAX_OUTPUT:raise ValueError('reader response limit')
    if result.returncode:
        raise ValueError('document sandbox unavailable or resource limit exceeded')
    value=json.loads(result.stdout)
    if value.get('ok') is not True:raise ValueError(value.get('error','document rejected'))
    return value['result']


def confine():
    import ctypes
    import errno
    import resource
    if sys.platform!='linux':raise RuntimeError('Linux seccomp required')
    resource.setrlimit(resource.RLIMIT_CPU,(3,3))
    resource.setrlimit(resource.RLIMIT_AS,(192*1024*1024,192*1024*1024))
    resource.setrlimit(resource.RLIMIT_FSIZE,(0,0))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_NOFILE,(16,16))
    library=ctypes.CDLL('libseccomp.so.2',use_errno=True)
    library.seccomp_init.argtypes=[ctypes.c_uint32];library.seccomp_init.restype=ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];library.seccomp_syscall_resolve_name.restype=ctypes.c_int
    library.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint]
    library.seccomp_load.argtypes=[ctypes.c_void_p]
    library.seccomp_release.argtypes=[ctypes.c_void_p]
    context=library.seccomp_init(0x00050000|errno.EPERM)  # default: deny unknown syscalls
    if not context:raise RuntimeError('seccomp initialization failed')
    try:
        allowed=('read','write','close','fstat','newfstatat','lseek','brk','mmap','mprotect',
                 'mremap','munmap','madvise','futex','clock_gettime','gettimeofday','getrandom',
                 'rt_sigaction','rt_sigprocmask','rt_sigreturn','sigaltstack','getpid','gettid',
                 'getuid','geteuid','getgid','getegid','getrusage','exit','exit_group')
        for name in allowed:
            number=library.seccomp_syscall_resolve_name(name.encode())
            if number>=0 and library.seccomp_rule_add(context,0x7fff0000,number,0)!=0:raise RuntimeError('seccomp rule failed')
        if library.seccomp_load(context)!=0:raise RuntimeError('seccomp load failed')
    finally:library.seccomp_release(context)


def worker():
    import importlib.util
    import encodings.cp437
    spec=importlib.util.spec_from_file_location('bounded_library_formats',Path(__file__).with_name('library_formats.py'))
    formats=importlib.util.module_from_spec(spec);spec.loader.exec_module(formats)
    # Load all code and input before filesystem/network/process syscalls are denied.
    line=sys.stdin.buffer.readline(2049)
    if len(line)>2048 or not line.endswith(b'\n'):raise ValueError('reader request limit')
    request=json.loads(line);source=sys.stdin.buffer.read(MAX_INPUT+1)
    if len(source)>MAX_INPUT:raise ValueError('reader source limit')
    mime=formats.sniff_format(source,request.get('mime'))
    request['mime']=mime
    raster=None
    if request['mode']=='cover' or mime in {'application/pdf','application/vnd.comicbook+zip','application/x-cbz','application/zip','application/x-zip-compressed'}:
        raster_spec=importlib.util.spec_from_file_location('raster_reader',Path(__file__).with_name('raster_reader.py'))
        raster=importlib.util.module_from_spec(raster_spec);raster_spec.loader.exec_module(raster)
    confine()
    try:
        if request['mode']=='cover':
            if mime=='application/epub+zip':
                image=formats.epub_cover(source);result=raster.cover_image(image) if image else {'image':None}
            elif mime in {'image/png','image/jpeg','image/webp','image/gif'}:result=raster.cover_image(source)
            elif mime in raster.MIMES:
                result=raster.read(source,mime,'chapter',chapter=0,limit=1)
                result={key:result[key] for key in ('image','rendered_in_sandbox','external_resources_loaded') if key in result}
            else:result={'image':None}
        elif raster is not None and mime in raster.MIMES and (mime=='application/pdf' or mime in {'application/vnd.comicbook+zip','application/x-cbz'}):
            result=raster.read(source,mime,request['mode'],**request['arguments'])
        else:
            result=formats.extract(source,mime) if request['mode']=='preview' else formats.reader(source,mime,request['mode'],**request['arguments'])
        value={'ok':True,'result':result}
    except (ValueError,KeyError,TypeError,formats.zipfile.BadZipFile,formats.ET.ParseError,RuntimeError,OSError):
        value={'ok':False,'error':'document rejected by bounded parser'}
    output=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
    if len(output)>MAX_OUTPUT:output=b'{"ok":false,"error":"reader response limit"}'
    sys.stdout.buffer.write(output)


if __name__=='__main__':worker()
