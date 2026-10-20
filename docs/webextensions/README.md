# Ziokt Companion WebExtensions

Build unsigned, deterministic Chromium ZIP and Firefox/Thunderbird XPI packages:

```sh
python3 tools/package_webextensions.py
```

For Chromium developer installations, load `dist/extensions/chromium` unpacked. For Firefox development, load its manifest using the temporary add-on debugger. These development packages are unsigned; permanent consumer installation and store review have not been verified. No store publication is performed by this build.

Configure a Content service with `--allow-webextensions` and create a separate application credential. The extension requests permission for the selected node origin. Remote nodes require HTTPS. Credentials remain in extension session storage; saved connection names and UI preferences use local storage. Disconnect clears the current identity's session credential. Gateway administrator credentials must not be used.

Implemented screens call actual application APIs for Library search/download, Netnews reading/posting/replying, authorized Community forum access, and capability discovery. Missing node functions remain unavailable. This release does not claim complete ecosystem feature coverage.

## Mobile interaction

The same extension page supports narrow viewports, wrapped navigation, touch targets of at least 44 CSS pixels, safe-area spacing, enlarged form text, dark/light themes, and configurable font sizes. “Open in a full tab” gives long reading and editing tasks a persistent page. English and simplified Chinese are included. Compact mode preserves touch target sizes.

CI checks the actual Chromium extension against a real node, then checks every application tab at 320, 360, 390 and 768 CSS pixels for horizontal overflow and undersized controls. These are desktop viewport checks. Android/iOS extension installation, virtual keyboard behavior, device downloads and mobile browser permission prompts require separate device validation. Firefox runtime testing uses a desktop installation. Thunderbird mobile is not validated. No claim is made that every mobile Chromium browser supports extensions. Where extensions cannot run, use the existing authorized Content web interface; this does not imply offline PWA support.

## Evidence

The Content Fabric workflow records extension package, desktop runtime and responsive layout results separately. Test host permissions are pregranted by the harness; the interactive permission prompt is not covered. Browser-specific unsupported behavior must remain visible rather than reporting a fabricated success.
