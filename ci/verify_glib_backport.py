"""Verify the vendored upstream backport used by Linux desktop builds."""
import hashlib,json,tomllib
from pathlib import Path
root=Path(__file__).resolve().parents[1];crate=root/'gui/src-tauri/vendor/glib'
metadata=json.loads((crate/'ZIOKT-BACKPORT.json').read_text())
assert metadata['upstream_crate_sha256']=='233daaf6e83ae6a12a52055f568f9d7cf4671dabb78ff9560ab6da230ce00ee5'
source=crate/metadata['patched_file'];assert hashlib.sha256(source.read_bytes()).hexdigest()==metadata['patched_file_sha256']
part=source.read_text().split('fn impl_get(&self, i: usize)',1)[1].split("impl<'a> Iterator for VariantStrIter",1)[0]
assert 'let mut p: *mut libc::c_char' in part and '&mut p,' in part and '\n                &p,' not in part
manifest=tomllib.loads((root/'gui/src-tauri/Cargo.toml').read_text());assert manifest['patch']['crates-io']['glib']['path']=='vendor/glib'
lock=tomllib.loads((root/'gui/src-tauri/Cargo.lock').read_text());package=next(p for p in lock['package'] if p['name']=='glib' and p['version']=='0.18.5');assert 'source' not in package and 'checksum' not in package
print('Pinned upstream GLib ABI-compatible security backport is selected')
