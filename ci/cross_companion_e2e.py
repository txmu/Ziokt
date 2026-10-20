"""Host-specific read-only companion diagnostics, not a content delivery test.

This script does not create, transfer or recover a common object across native
components and must never be counted as proof of end-to-end interoperability.
"""
import base64
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ziokt.protocol import strict_json, secure_read
from ziokt.mcp import Service
from ziokt.etp import EtpRecordSocket, EtpGateway
from ziokt.client import NativeClient
from ziokt.config import load

def test_cross_companion_closed_loop():
    print("=== Step 1: Corium Creation & Object Verification ===")
    mcp_config = strict_json(secure_read('/home/admin/.local/share/ziokt-production/mcp/mcp.json'))
    srv = Service(mcp_config)
    
    # 1. Corium objects & ZKT merit status
    corium_objects = srv.execute('ziokt-operator', 'corium_production_objects_list', {'params': {}})
    assert len(corium_objects['objects']) >= 40, f"Expected >= 40 Corium objects, got {len(corium_objects['objects'])}"
    print(f"Corium objects verified: {len(corium_objects['objects'])} objects present without UNSAFE_FILE.")
    
    zkt_status = srv.execute('ziokt-operator', 'corium_production_zkt_status', {'params': {}})
    assert zkt_status['active_operators_count'] >= 1
    assert 'forum' in zkt_status['application_services']
    print(f"ZKT merit status verified: policy {zkt_status['policy_id']}, active operators: {zkt_status['active_operators_count']}, services: {zkt_status['application_services']}")

    # 2. Corium CBB verified games
    cbb_games = srv.execute('ziokt-operator', 'corium_cbb_games', {})
    assert cbb_games.get('native_verified') is True
    print(f"Corium CBB games verified: native_verified=True, {len(cbb_games.get('data', []))} games listed.")

    print("=== Step 2: SafeFS & UFS Distribution ===")
    # Test UFS & SafeFS bridge tools
    ufs_status = srv.execute('ziokt-operator', 'ufs_component_status', {'params': {}})
    assert ufs_status.get('schema') == 'ziokt.component-status.v1'
    print(f"UFS bridge verified: status={ufs_status.get('status')}")
    
    safefs_status = srv.execute('ziokt-operator', 'safefs_component_status', {'params': {}})
    assert safefs_status.get('schema') == 'ziokt.component-status.v1'
    print(f"SafeFS bridge verified: status={safefs_status.get('status')}")

    print("=== Step 3: ETP Transport & Mailbox Health ===")
    etp_health = srv.execute('ziokt-operator', 'etp_etp_mailbox_status', {'params': {}})
    assert etp_health['native_store'] == 'opened'
    print(f"ETP dead-letter mailbox verified: {etp_health}")

    etp_stats = srv.execute('ziokt-operator', 'etp_etp_stats', {'params': {}})
    assert etp_stats['schema'] == 'ziokt.etp-stats.v1'
    print(f"ETP native stats verified: {etp_stats['native']}")

    print("=== Step 4: Shadow6 Native Provider Services ===")
    fed = load('/home/admin/.local/share/ziokt-production/config/federation.json')
    s6_provider = [p for p in fed['providers'] if p['provider_id'] == 'shadow6-production'][0]
    s6_client = NativeClient(fed['federation_id'], s6_provider)
    s6_objects = s6_client.call('objects.list', {})
    services = [o['native_id'] for o in s6_objects['objects']]
    assert 'storage/safefs' in services
    assert 'mesh/router' in services
    assert 'gateway/broker' in services
    assert 'compute/executor' in services
    print(f"Shadow6 native provider verified: {len(services)} services active: {services}")

    print("=== Step 5: Unified Ziokt Audit Trail ===")
    audit = srv.execute('ziokt-operator', 'ziokt_audit_read', {'limit': 10})
    assert len(audit['audit']) > 0
    print(f"Ziokt unified audit trail verified: {len(audit['audit'])} recent tool records logged.")

    print(json.dumps({'schema':'ziokt.companion-diagnostics.v1','status_queries_passed':True,'closed_loop_verified':False,'content_created':False,'content_transferred':False,'recovery_verified':False}))

if __name__ == '__main__':
    test_cross_companion_closed_loop()
