"""Fail on unreviewed scanner findings; preserve explicit source audit evidence."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def findings(scanner,path):
    document=json.loads(Path(path).read_text());items=[]
    if scanner=='semgrep' and document.get('errors'):raise ValueError('Semgrep parse/scan errors require review')
    for item in document.get('results',[]):
        if scanner=='semgrep':
            file=item['path'];start=item['start']['line'];end=item['end']['line'];rule=item['check_id'];severity=item['extra']['severity']
        else:
            if item['issue_severity']=='LOW' or item['issue_confidence']=='LOW':continue
            file=item['filename'];start=item['line_number'];end=item.get('end_lineno') or max(item.get('line_range') or [start]);rule=item['test_id'];severity=item['issue_severity']
        target=Path(file)
        if target.is_absolute():file=str(target.relative_to(ROOT))
        else:file=str(target)
        source=ROOT/file
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT):raise ValueError('scanner path outside repository')
        code='\n'.join(source.read_text().splitlines()[start-1:end]).strip()
        fingerprint=hashlib.sha256((scanner+'\0'+file+'\0'+rule+'\0'+code).encode()).hexdigest()
        items.append({'scanner':scanner,'path':file,'line':start,'rule':rule,'severity':severity,'fingerprint':fingerprint})
    return items


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--semgrep',required=True);p.add_argument('--bandit',required=True);a=p.parse_args()
    baseline=json.loads((ROOT/'docs/security/STATIC-AUDIT-2026-10-27.json').read_text())
    reviewed={i['fingerprint'] for i in baseline['reviewed_active_findings']}
    current=findings('semgrep',a.semgrep)+findings('bandit',a.bandit)
    unknown=[i for i in current if i['fingerprint'] not in reviewed]
    print(json.dumps({'schema':'ziokt.source-audit-gate.v1','findings':len(current),'unreviewed':unknown,'checked':not unknown},sort_keys=True))
    raise SystemExit(1 if unknown else 0)
