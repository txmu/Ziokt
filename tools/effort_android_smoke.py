#!/usr/bin/env python3
"""CI-only real emulator checks; no local Android compilation or mocked network state."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET


def adb(*args,check=True):
    return subprocess.run(['adb',*args],capture_output=True,text=True,check=check,timeout=45).stdout


def main():
    p=argparse.ArgumentParser();p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();out=args.output;out.mkdir(parents=True,exist_ok=True)
    package='com.ziokt.effort';checks=[]
    def nodes():
        adb('shell','uiautomator','dump','/sdcard/effort-ui.xml');raw=adb('shell','cat','/sdcard/effort-ui.xml')
        if len(raw)>1024*1024 or '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():raise ValueError('bounded entity-free UI XML required')
        (out/'last-ui.xml').write_text(raw);return list(ET.fromstring(raw).iter('node'))
    def tap(text):
        # Settings can scroll on smaller/large-font devices; start/stop stay pinned.
        width,height=map(int,re.findall(r'(\d+)x(\d+)',adb('shell','wm','size'))[-1])
        for direction in (1,-1):
            for attempt in range(7):
                for node in nodes():
                    if text in node.get('text',''):
                        a,b,c,d=map(int,re.findall(r'\d+',node.get('bounds','')))
                        if c>a and d>b:
                            adb('shell','input','tap',str((a+c)//2),str((b+d)//2));return
                start,end=(.6,.25) if direction==1 else (.25,.6)
                adb('shell','input','swipe',str(width//2),str(int(height*start)),str(width//2),str(int(height*end)),'250')
        raise AssertionError('UI control missing after bounded scrolling: '+text)
    def wait_text(*values,seconds=45):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            body=' '.join(n.get('text','') for n in nodes())
            if any(v in body for v in values):return body
            time.sleep(1)
        raise AssertionError('Actual Android UI did not show: '+repr(values))
    def open_app():adb('shell','am','start','-W','-n',package+'/.MainActivity')
    try:
        adb('install','-r',str(args.artifacts/'ziokt-effort-android-universal.apk'));adb('install','-r',str(args.artifacts/'native-tests.apk'))
        api=int(adb('shell','getprop','ro.build.version.sdk').strip());abis=adb('shell','getprop','ro.product.cpu.abilist').strip()
        if api>=33:adb('shell','pm','grant',package,'android.permission.POST_NOTIFICATIONS')
        native=adb('shell','am','instrument','-w','-r',package+'.test/com.ziokt.effort.Smoke');(out/'native-checks.txt').write_text(native);assert 'native_checks=passed' in native and 'INSTRUMENTATION_CODE: -1' in native,native;checks.append('actual_runtime_sha256_cancel_and_origin')
        open_app();wait_text('尚未启动');tap('一键启用');wait_text('直连已启用');checks.append('real_selected_node_task_queue')
        adb('shell','input','keyevent','KEYCODE_HOME');time.sleep(2)
        services=adb('shell','dumpsys','activity','services',package);(out/'services-background.txt').write_text(services);assert 'isForeground=true' in services;checks.append('foreground_service_survives_home')
        memory=adb('shell','dumpsys','meminfo',package);(out/'memory.txt').write_text(memory)
        matched=re.search(r'TOTAL PSS:\s*(\d+)',memory) or re.search(r'^\s*TOTAL\s+(\d+)',memory,re.M);assert matched,'actual PSS missing';pss=int(matched[1]);assert pss<128*1024,('PSS exceeds 128 MiB budget',pss);checks.append('measured_pss_under_128_mib')
        adb('shell','svc','wifi','disable');adb('shell','svc','data','disable');open_app();wait_text('网络已断开，已暂停');checks.append('real_system_network_loss_pauses')
        adb('shell','svc','wifi','enable');adb('shell','svc','data','enable');wait_text('直连已启用',seconds=60);checks.append('real_system_network_recovery_resumes')
        adb('shell','svc','wifi','disable');adb('shell','svc','data','disable');wait_text('网络已断开，已暂停');tap('停止助力');wait_text('已停止；不会自动恢复')
        adb('shell','svc','wifi','enable');adb('shell','svc','data','enable');time.sleep(4);wait_text('已停止；不会自动恢复');checks.append('manual_stop_cancels_recovery')
        tap('轻量网络协作（主网直连，非匿名）');tap('计算协作（单线程）');tap('一键启用');wait_text('计算协作运行中','等待真实计算任务','证明已提交',seconds=60);tap('停止助力');wait_text('已停止；不会自动恢复');checks.append('native_compute_path_and_stop')
        adb('shell','screencap','-p','/sdcard/effort-screen.png');adb('pull','/sdcard/effort-screen.png',str(out/'effort-screen.png'))
        result={'success':True, 'checks':checks, 'api':api, 'emulator_abis':abis, 'emulator_cores':2, 'emulator_ram_mb':2048, 'measured_pss_kib':pss, 'source_commit':json.loads((args.artifacts/'build-source.json').read_text())['source_commit']}
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:
        (out/'logcat.txt').write_text(adb('logcat','-d','-t','1000',check=False));adb('shell','svc','wifi','enable',check=False);adb('shell','svc','data','enable',check=False);adb('shell','am','force-stop',package,check=False)

if __name__=='__main__':main()
