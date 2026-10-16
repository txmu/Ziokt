import copy
from fractions import Fraction
import unittest
from ziokt.ano import ZDANumber,AnoNumber,AnoVector,Signal,calculate
from ziokt.protocol import ProtocolError

class ExactAlgebraDocuments(unittest.TestCase):
    def test_existing_exact_complex_and_special_operations_roundtrip(self):
        a=ZDANumber(Fraction(1,3),Fraction(2,5));b=ZDANumber(3)
        result=calculate('zda','mul',a.document(),b.document())
        self.assertEqual(ZDANumber.from_document(result['result']),ZDANumber(1,Fraction(6,5)))
        self.assertFalse(result['cryptographic_proof'])
        for left,right,state in [(ZDANumber(1),ZDANumber(),'infinity'),(ZDANumber(),ZDANumber(),'bottom'),(ZDANumber.infinity(),ZDANumber.infinity(),'bottom')]:
            self.assertEqual(calculate('zda','div',left.document(),right.document())['result']['state'],state)
        for value in [a,ZDANumber.infinity(),ZDANumber.bottom()]:self.assertEqual(ZDANumber.from_document(value.document()),value)

    def test_ano_number_and_vector_operations_keep_explicit_logic_profile(self):
        a=AnoNumber(Fraction(1,3),ano_part=Signal.POSITIVE);b=AnoNumber(Fraction(2,3),ano_part=Signal.NEGATIVE)
        value=calculate('ano','add',a.document(),b.document())['result']
        self.assertEqual(AnoNumber.from_document(value),AnoNumber(1,ano_part=Signal.POSITIVE))
        vector=AnoVector(a,b,AnoNumber())
        self.assertEqual(AnoVector.from_document(vector.document()),vector)
        result=calculate('vector','dot',vector.document(),vector.document())['result']
        self.assertEqual(AnoNumber.from_document(result),vector.dot(vector))

    def test_malformed_noncanonical_and_excessive_numbers_fail_closed(self):
        valid=ZDANumber(1).document()
        bad=[]
        for ratio in [{'numerator':'2','denominator':'2'},{'numerator':'1','denominator':'0'},{'numerator':True,'denominator':'1'},{'numerator':'1'*1300,'denominator':'1'},{'numerator':'-0','denominator':'1'}]:
            value=copy.deepcopy(valid);value['real']=ratio;bad.append(value)
        malformed=copy.deepcopy(valid);malformed['state']=[];bad.append(malformed)
        for value in bad:
            with self.subTest(value=str(value)[:80]),self.assertRaises(ProtocolError):ZDANumber.from_document(value)
        with self.assertRaises(ProtocolError):calculate('zda','mul',ZDANumber(2**4095).document(),ZDANumber(2).document())
        with self.assertRaises(ProtocolError):calculate('zda','execute',valid,valid)
