"""Public incident scope must not expose private recovery material."""
import json
from pathlib import Path
import tempfile
import unittest

from ziokt.assurance import public_hold, snapshot


class AssuranceTests(unittest.TestCase):
    def test_hold_is_exposed_without_private_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'hold.json'
            value={'schema':'ziokt.consensus-safety-hold.v1','active':True,
                   'reason_code':'WORK_GOVERNANCE_NOT_COMMITTED','first_unverified_height':64,
                   'history_rewritten':False,'backup':'private-backup-must-not-be-public'}
            path.write_text(json.dumps(value));path.chmod(0o600)
            hold=public_hold({'consensus_safety_hold':str(path)})
            self.assertNotIn('backup',hold)
            state=snapshot(hold)
            self.assertEqual(state['consensus']['operational_state'],'safety_hold')
            self.assertNotIn('private-backup',json.dumps(state))
            self.assertFalse(state['privacy']['independently_audited'])

    def test_missing_or_malformed_hold_cannot_claim_healthy(self):
        self.assertEqual(snapshot()['consensus']['operational_state'],'not_assessed')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'hold.json';path.write_text('{"active":"false"}');path.chmod(0o600)
            with self.assertRaises(ValueError):public_hold({'consensus_safety_hold':str(path)})
