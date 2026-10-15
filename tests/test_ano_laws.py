import itertools
import unittest
from fractions import Fraction
from ziokt.ano import (Signal, PROFILE, LEGACY_PROFILE, AnoNumber, merge, cross,
                       law_report, truth_table, defence)
from ziokt.protocol import ProtocolError

class AnoFormalContracts(unittest.TestCase):
    def test_exhaustive_finite_laws_and_legacy_counterexample(self):
        current=law_report()['laws'];legacy=law_report(LEGACY_PROFILE)['laws']
        for name in ('merge_associative','cross_associative','merge_commutative','cross_commutative','unknown_absorbs_merge','unknown_absorbs_cross'):
            self.assertTrue(current[name]['holds'])
        self.assertFalse(current['cross_distributes_over_merge']['holds'])
        self.assertFalse(legacy['merge_associative']['holds'])
        p,u=Signal.POSITIVE,Signal.UNKNOWN
        self.assertNotEqual(merge(merge(p,p,profile=LEGACY_PROFILE),u,profile=LEGACY_PROFILE),merge(p,merge(p,u,profile=LEGACY_PROFILE),profile=LEGACY_PROFILE))
        for a,b in itertools.product((False,True),repeat=2):
            self.assertEqual(merge(a,b)==Signal.POSITIVE,a^b)
            self.assertEqual(cross(a,b)==Signal.POSITIVE,not(a^b))
        self.assertEqual(len(truth_table(include_unknown=True)['rows']),9)
    def test_exact_numeric_product_laws_do_not_imply_distributivity_or_authorization(self):
        values=[AnoNumber(Fraction(1,3),Fraction(-2,5),s) for s in Signal]
        for a,b,c in itertools.product(values,repeat=3):
            self.assertEqual((a+b)+c,a+(b+c))
            self.assertEqual((a*b)*c,a*(b*c))
        n=AnoNumber(ano_part=Signal.NEGATIVE)
        self.assertNotEqual(n*(n+n),n*n+n*n)
        for profile in (PROFILE,LEGACY_PROFILE):
            self.assertFalse(law_report(profile)['security_policy_proof'])
        self.assertEqual(defence({'integrity':True,'authorized':None},('integrity','authorized'))['decision'],'hold')
        with self.assertRaises(ProtocolError):law_report('unknown')
