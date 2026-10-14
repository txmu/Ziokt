"""Read-only Warden capabilities; never changes host cgroups/eBPF/interfaces."""
from ziokt.safefs import sandbox_plan
if __name__=='__main__':
    import json
    print(json.dumps(sandbox_plan(),sort_keys=True))
