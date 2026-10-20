import hashlib,tempfile,unittest
from ziokt.content_fabric import Fabric
from ziokt.optimization import finite_metrics

class OptimizationTests(unittest.TestCase):
 def test_reversible_account_profiles_preserve_baseline_and_permissions(self):
  with tempfile.TemporaryDirectory() as temp:
   fabric=Fabric(temp)
   try:
    data=b'An original sample';fabric.begin('alice','sample',len(data),'sha256:'+hashlib.sha256(data).hexdigest(),'text/plain');fabric.put('alice','sample',0,data);obj=fabric.finish('alice','sample');fabric.create_book('alice',{'id':'book','file_id':obj['id'],'title':'Astronomy','work_id':'work','edition_id':'edition','license':'CC0-1.0'})
    self.assertFalse(fabric.optimizations.get('alice')['effective']['enabled'])
    self.assertEqual(fabric.search('alice','Astronmy')['items'],[])
    fabric.optimizations.set('alice',{'enabled':True,'search_fuzzy':True,'search_group_works':True},0)
    result=fabric.search('alice','Astronmy');self.assertEqual(len(result['items']),1);self.assertTrue(result['fuzzy_fallback']);self.assertEqual(result['works'][0]['work_id'],'work')
    self.assertEqual(fabric.search('bob','Astronmy')['items'],[])
    with self.assertRaises(ValueError):fabric.optimizations.set('alice',{'enabled':False},0)
    fabric.optimizations.set('alice',{'enabled':False},1);self.assertEqual(fabric.search('alice','Astronmy')['items'],[])
    with self.assertRaises(ValueError):fabric.optimizations.set('alice',{'disable_signatures':True},2)
   finally:fabric.close()
 def test_information_and_risk_have_separate_units(self):
  joint=[{'x':'0','y':'0','z':'','p':.45},{'x':'0','y':'1','z':'','p':.05},{'x':'1','y':'0','z':'','p':.05},{'x':'1','y':'1','z':'','p':.45}]
  result=finite_metrics(joint,[{'y':'0','z':'','decision':'1'},{'y':'1','z':'','decision':'1'}])
  self.assertAlmostEqual(result['information_retained_bits'],.5310044064)
  self.assertAlmostEqual(result['optimal_zero_one_risk'],.1);self.assertAlmostEqual(result['actual_zero_one_risk'],.5);self.assertAlmostEqual(result['interpretation_extra_zero_one_risk'],.4)
  self.assertFalse(result['independence_inferred']);self.assertFalse(result['human_intent_inferred'])
 def test_unmeasured_actual_risk_is_unknown(self):
  result=finite_metrics([{'x':'0','y':'same','z':'','p':.5},{'x':'1','y':'same','z':'','p':.5}]);self.assertEqual(result['information_retained_bits'],0);self.assertIsNone(result['actual_zero_one_risk'])

if __name__=='__main__':unittest.main()
