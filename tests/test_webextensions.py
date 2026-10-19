import json,re,tempfile,unittest,zipfile
from pathlib import Path
from tools.package_webextensions import package,ROOT

class ExtensionTests(unittest.TestCase):
 def test_target_manifests_locales_and_no_ambient_administration(self):
  source=ROOT/'extensions'/'ziokt';languages=[json.loads((source/'_locales'/name/'messages.json').read_text()) for name in ('en','zh_CN')]
  self.assertEqual(set(languages[0]),set(languages[1]))
  used=set(re.findall(r"\bt\('([A-Za-z0-9_]+)'\)",(source/'popup.js').read_text()))|set(re.findall(r'data-i18n="([A-Za-z0-9_]+)"',(source/'popup.html').read_text()))
  self.assertTrue(used<=set(languages[0]),used-set(languages[0]))
  for target in ('chromium','firefox','thunderbird'):
   manifest=json.loads((source/f'manifest.{target}.json').read_text());self.assertEqual(manifest['permissions'],['storage']);self.assertNotIn('content_scripts',manifest);self.assertNotIn('externally_connectable',manifest);self.assertEqual(manifest['default_locale'],'en')
 def test_deterministic_unsigned_packages_reuse_real_application_client(self):
  with tempfile.TemporaryDirectory() as temp:
   first=package(Path(temp));second=package(Path(temp));self.assertEqual([x['sha256'] for x in first],[x['sha256'] for x in second])
   for record in first:
    self.assertFalse(record['store_signed'])
    with zipfile.ZipFile(record['path']) as archive:self.assertEqual(archive.read('application-client.js'),(ROOT/'ziokt'/'web'/'application-client.js').read_bytes())

if __name__=='__main__':unittest.main()
