"""Portable website materials, escaped user content, naming and cold recovery."""
import io
from pathlib import Path
import secrets
import tempfile
import unittest
import zipfile

from ziokt.community import Community, RIGHTS, create_policy
from ziokt.community_site import build_site, publish_site
from ziokt.security import sign


class SiteTests(unittest.TestCase):
    def test_named_website_is_reproducible_safe_and_survives_original_node_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); private, key = secrets.token_bytes(32), secrets.token_bytes(32)
            public = sign({}, private, 'test')['public_key']
            policy = create_policy(private, 'village', {public: sorted(RIGHTS)}, privacy='private')
            with Community(root/'source', policy, public, key) as source:
                source.publish(private, 'wiki', 'home', {'title': '<script>title</script>', 'text': '<script>alert(1)</script>'})
                source.publish(private, 'forum', 'welcome', {'title': 'Welcome', 'text': 'Discussion', 'reply_to': ''})
                first, manifest = build_site(source, 'Village')
                self.assertEqual(first, build_site(source, 'Village')[0])
                with zipfile.ZipFile(io.BytesIO(first)) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertIn('index.html', archive.namelist())
                    pages = b''.join(archive.read(name) for name in archive.namelist() if name.endswith('.html'))
                    self.assertNotIn(b'<script>', pages); self.assertIn(b'&lt;script&gt;', pages)
                    self.assertTrue(all('/' not in name for name in archive.namelist()))
                published = publish_site(source, private, 'community', 'Village')
                checkpoint = source.checkpoint(private)
            with Community(root/'survivor', policy, public, key) as survivor:
                survivor.restore(checkpoint, public)
                self.assertEqual(survivor.get_file(published['materials']), first)
                self.assertEqual(survivor.view('names')['events'][0]['body']['target'], published['reference'])
                self.assertFalse(published['runtime_ready'])


if __name__ == '__main__': unittest.main()
