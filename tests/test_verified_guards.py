"""Exercise the exact generated production predicates at domain boundaries."""
from itertools import product
from pathlib import Path
import subprocess
import sys
import unittest
from ziokt import _verified_guards as guards


class VerifiedGuardTests(unittest.TestCase):
    def test_generated_python_and_lean_have_not_drifted(self):
        subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'formal/generate_guards.py'),'--check'],check=True,capture_output=True)

    def test_unbounded_integer_budget_and_revision_boundaries(self):
        values=[0,1,2,31,64,65536,2**64,2**256]
        for budget,used,amount in product(values,repeat=3):
            self.assertEqual(guards.within_budget(budget,used,amount),used+amount<=budget)
        for previous,incoming in product(values,repeat=2):
            self.assertEqual(guards.fresh_revision(previous,incoming),incoming>previous)
            self.assertEqual(guards.before_deadline(previous,incoming),previous<incoming)

    def test_values_outside_the_proved_natural_domain_fail_closed(self):
        for invalid in (-1,True,False,1.0,float('inf'),'1',None):
            for position in range(3):
                values=[64,1,1];values[position]=invalid
                with self.subTest(invalid=invalid,position=position),self.assertRaises(ValueError):guards.within_budget(*values)

    def test_cache_and_privacy_decisions_are_exact(self):
        for mode,restore,save in [('read-write',True,True),('read-only',True,False),('write-only',False,True),('',False,False)]:
            self.assertEqual(guards.cache_restores(mode),restore);self.assertEqual(guards.cache_saves(mode),save)
        self.assertFalse(guards.direct_carrier_permitted(True))
        self.assertFalse(guards.public_publication_permitted(False))
        with self.assertRaises(ValueError):guards.direct_carrier_permitted(1)
