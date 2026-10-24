import hashlib,json,re,tempfile,unittest,zipfile
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
 def test_release_manifest_and_checksums_cover_exact_installers(self):
  with tempfile.TemporaryDirectory() as temp:
   output=Path(temp);records=package(output)
   manifest=json.loads((output/'build-source.json').read_text())
   self.assertRegex(manifest['source_commit'],r'^[0-9a-f]{40}$')
   self.assertFalse(manifest['store_signed'])
   self.assertEqual({r['file'] for r in manifest['packages']},{Path(r['path']).name for r in records})
   lines=(output/'SHA256SUMS').read_text().splitlines()
   self.assertEqual(len(lines),4)
   for line in lines:
    digest,name=line.split('  ')
    self.assertEqual(hashlib.sha256((output/name).read_bytes()).hexdigest(),digest)

if __name__=='__main__':unittest.main()

class SiteNavigationTests(unittest.TestCase):
 def test_shared_url_builder_rejects_ambient_authority_and_traversal(self):
  import subprocess
  script="""const assert=require('node:assert/strict'),url=require('./gateway/gui/site-url.js');
assert.equal(url('https://node.example','blog.team.example.corix','posts/a b/'),'https://node.example/gateway/corix/blog.team.example/posts/a%20b/');
for(const args of [['https://user:secret@node.example','example.corix',''],['http://remote.example','example.corix',''],['https://node.example','example.com',''],['https://node.example','example.corix','../key'],['https://node.example','example.corix','%2fadmin'],['https://node.example','a..example.corix','']])assert.throws(()=>url(...args));"""
  subprocess.run(['node','-e',script],cwd=ROOT,check=True,capture_output=True)
  with tempfile.TemporaryDirectory() as temp:
   for item in package(Path(temp)):
    with zipfile.ZipFile(item['path']) as archive:self.assertEqual(archive.read('site-url.js'),(ROOT/'gateway/gui/site-url.js').read_bytes())
