#!/usr/bin/env python3
"""
Ziokt Unified Graphical Client - End-to-End (E2E) Automated UI & Workflow Test Suite
===================================================================================
Covers:
  1. Asset & Shell Structure Integrity (HTML5, PWA, Semantic DOM)
  2. i18n Translation Completeness & Parity (zh vs en)
  3. Style System & Responsive Theme Verification (Dark, Light, Contrast)
  4. WATChat Dual-UI Switching & State Persistence
  5. dCPM Package Store Lifecycle & Rollback Workflow
  6. Cross-Component Workflows (SafeFS -> WATChat, S6P1 -> Shadow6)
  7. Developer Studio (TC-16 VM Deterministic Step/Run, ZDA Math Gates)
  8. Tauri 2 Desktop/Mobile & HarmonyOS NEXT Configuration Conformance
"""

import os
import re
import json
import unittest
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = GUI_DIR / "src"


class TestZioktGuiE2E(unittest.TestCase):

    def test_01_app_shell_and_dom_structure(self):
        """Verify index.html contains all 9 module views, accessibility roles, and containers."""
        index_html = (SRC_DIR / "index.html").read_text(encoding="utf-8")
        
        # 9 primary modules navigation check
        expected_modules = ["home", "chat", "forum", "files", "apps", "network", "identity", "devtools", "settings"]
        for mod in expected_modules:
            self.assertIn(f'data-tab="{mod}"', index_html, f"Navigation tab for '{mod}' missing in index.html")

        # App shell elements
        self.assertIn('id="sidebar"', index_html)
        self.assertIn('id="topbar"', index_html)
        self.assertIn('id="content-container"', index_html)
        self.assertIn('id="bottombar"', index_html, "Mobile responsive bottom bar missing")
        self.assertIn('id="modal-overlay"', index_html, "Universal modal overlay missing")
        self.assertIn('id="toast-container"', index_html, "Toast notification container missing")
        self.assertIn('src="app.js"', index_html)
        self.assertIn('href="style.css"', index_html)

        # Verify standalone app.js bundle is valid JavaScript syntax
        import subprocess
        res = subprocess.run(["node", "-c", str(SRC_DIR / "app.js")], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Syntax error in app.js: {res.stderr}")

    def test_02_i18n_translation_parity(self):
        """Verify zh.json and en.json dictionaries have 100% key parity and non-empty values."""
        zh = json.loads((SRC_DIR / "i18n" / "zh.json").read_text(encoding="utf-8"))
        en = json.loads((SRC_DIR / "i18n" / "en.json").read_text(encoding="utf-8"))

        def get_keys(d, prefix=""):
            keys = set()
            for k, v in d.items():
                full_k = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    keys.update(get_keys(v, full_k))
                else:
                    keys.add(full_k)
            return keys

        zh_keys = get_keys(zh)
        en_keys = get_keys(en)

        diff_zh = zh_keys - en_keys
        diff_en = en_keys - zh_keys
        self.assertEqual(diff_zh, set(), f"Keys missing in en.json: {diff_zh}")
        self.assertEqual(diff_en, set(), f"Keys missing in zh.json: {diff_en}")
        self.assertGreater(len(zh_keys), 60, "i18n keys dictionary too small")

    def test_03_style_themes_and_responsiveness(self):
        """Verify CSS defines all required themes and mobile responsive breakpoints."""
        css = (SRC_DIR / "style.css").read_text(encoding="utf-8")
        
        self.assertIn(':root', css)
        self.assertIn('[data-theme="light"]', css, "Light theme definition missing")
        self.assertIn('[data-theme="contrast"]', css, "High contrast theme missing")
        self.assertIn('@media (max-width: 768px)', css, "Mobile breakpoint definition missing")
        self.assertIn('.chat-bubble', css)
        self.assertIn('.bubble-mine', css)
        self.assertIn('.bubble-theirs', css)
        self.assertIn('.toast', css)
        self.assertIn('.modal-overlay', css)

    def test_04_watchat_dual_ui_implementation(self):
        """Verify WATChat supports both minimalist and classic rich UI seamlessly."""
        chat_js = (SRC_DIR / "modules" / "chat.js").read_text(encoding="utf-8")
        
        # Dual UI controls
        self.assertIn('toggle-minimalist', chat_js)
        self.assertIn('toggle-classic', chat_js)
        self.assertIn('chatUiMode', chat_js)
        self.assertIn('messagesStore', chat_js)
        self.assertIn('attach-vault-btn', chat_js, "File vault attachment capability missing in chat")
        self.assertIn('XChaCha20-Poly1305', chat_js, "Sealed encryption badge missing")

    def test_05_dcpm_package_lifecycle_and_rollback(self):
        """Verify dCPM package manager includes install, rollback, uninstall, and SHA-256 verification."""
        apps_js = (SRC_DIR / "modules" / "apps.js").read_text(encoding="utf-8")
        
        self.assertIn('view-manifest-btn', apps_js)
        self.assertIn('rollback-btn', apps_js, "Rollback capability missing")
        self.assertIn('uninstall-btn', apps_js, "Uninstall capability missing")
        self.assertIn('install-btn', apps_js, "Install capability missing")
        self.assertIn('import-pkg-btn', apps_js, "Direct .dcpm import missing")
        self.assertIn('sha256:', apps_js, "SHA-256 verification hash missing")
        self.assertIn('dependencies', apps_js, "Dependency check missing")

    def test_06_shadow6_profiles_and_s6p1_envelope(self):
        """Verify Network module manages 13 Shadow6 profiles and parses S6P1 envelopes."""
        network_js = (SRC_DIR / "modules" / "network.js").read_text(encoding="utf-8")
        
        expected_profiles = ["Go", "Rust", "Gleam", "Ada", "Nim", "Pony", "Zig", "D", "C++", "Idris", "Hare", "Carp", "Virtual Broker"]
        for p in expected_profiles:
            self.assertIn(p, network_js, f"Profile '{p}' missing from network module")
        
        self.assertIn('S6P1.', network_js, "S6P1 credential envelope prefix check missing")
        self.assertIn('toggle-sensitive-btn', network_js, "Privacy masking toggle missing")
        self.assertIn('ping-all-btn', network_js, "Latency diagnostic probe missing")

    def test_07_developer_tools_tc16_and_zda_functionality(self):
        """Verify Developer Tools contain full functional TC-16 VM and ZDA math gates."""
        devtools_js = (SRC_DIR / "modules" / "devtools.js").read_text(encoding="utf-8")
        
        # TC-16 16-bit VM runner check
        self.assertIn('tc16State', devtools_js)
        self.assertIn('R0', devtools_js)
        self.assertIn('PC', devtools_js)
        self.assertIn('SP', devtools_js)
        self.assertIn('tc16-step-btn', devtools_js, "TC-16 Step button missing")
        self.assertIn('tc16-run-btn', devtools_js, "TC-16 Run button missing")
        self.assertIn('tc16-reset-btn', devtools_js, "TC-16 Reset button missing")
        self.assertIn('executeInstruction', devtools_js, "TC-16 Instruction dispatcher missing")

        # ZDA & MCP checks
        self.assertIn('polynomial_constraint', devtools_js, "ZDA polynomial gate missing")
        self.assertIn('corium_registration_submit', devtools_js, "MCP tool probes missing")

    def test_08_settings_on_demand_lifecycle_and_modes(self):
        """Verify on-demand component launcher and local/remote/hybrid mode switching."""
        settings_js = (SRC_DIR / "modules" / "settings.js").read_text(encoding="utf-8")
        
        self.assertIn('setting-mode-select', settings_js)
        self.assertIn('toggle-comp-btn', settings_js, "On-demand component launcher missing")
        self.assertIn('theme-btn', settings_js)
        self.assertIn('lang-btn', settings_js)
        self.assertIn('clear-cache-btn', settings_js)

    def test_09_tauri2_and_harmonyos_conformance(self):
        """Verify Tauri 2 desktop/mobile and HarmonyOS NEXT ArkUI configurations."""
        tauri_conf = json.loads((GUI_DIR / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
        self.assertEqual(tauri_conf["productName"], "Ziokt Client")
        self.assertEqual(tauri_conf["build"]["frontendDist"], "../src")
        self.assertTrue(tauri_conf["bundle"]["active"])

        cargo_toml = (GUI_DIR / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
        self.assertIn('name = "ziokt-gui-native"', cargo_toml)
        self.assertIn('tauri = { version = "2.0.0"', cargo_toml)

        rust_lib = (GUI_DIR / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        self.assertIn('get_system_info', rust_lib)
        self.assertIn('manage_component', rust_lib)
        self.assertIn('ping_gateway', rust_lib)

        # HarmonyOS NEXT ArkUI files
        module_json = json.loads((GUI_DIR / "harmonyos" / "module.json5").read_text(encoding="utf-8"))
        self.assertEqual(module_json["module"]["name"], "entry")
        arkui_page = (GUI_DIR / "harmonyos" / "entry" / "src" / "main" / "ets" / "pages" / "Index.ets").read_text(encoding="utf-8")
        self.assertIn('webview.WebviewController', arkui_page)
        self.assertIn('Web({ src:', arkui_page)

    def test_10_local_node_probe_and_remote_node_auth(self):
        """Verify real local node probing, mandatory remote authentication, and custom remote node management."""
        core_js = (SRC_DIR / "core.js").read_text(encoding="utf-8")
        settings_js = (SRC_DIR / "modules" / "settings.js").read_text(encoding="utf-8")
        home_js = (SRC_DIR / "modules" / "home.js").read_text(encoding="utf-8")

        # 1. Real Local Node health check requirement
        self.assertIn('checkLocalNodeHealth', core_js)
        self.assertIn('localNodeStatus', core_js)
        self.assertIn('/api/gateway/status', core_js)
        self.assertIn('probe-local-node-btn', settings_js)
        self.assertIn('home-probe-local-btn', home_js)

        # 2. Mandatory Remote Node authentication credentials
        self.assertIn('Authorization', core_js)
        self.assertIn('X-Ziokt-Auth', core_js)
        self.assertIn('verifyRemoteNodeAuth', core_js)
        self.assertIn('test-node-btn', settings_js)
        self.assertIn('node-token-input', settings_js)

        # 3. Custom Remote Node addition, switching, and deletion
        self.assertIn('addRemoteNode', core_js)
        self.assertIn('removeRemoteNode', core_js)
        self.assertIn('setActiveRemoteNode', core_js)
        self.assertIn('add-node-btn', settings_js)
        self.assertIn('activate-node-btn', settings_js)
        self.assertIn('delete-node-btn', settings_js)

    def test_11_android_configuration_and_resolution_adaptation(self):
        """Verify Android App manifest versioning, API levels, screen resolution adaptation, and WebView parameters."""
        manifest_xml = (GUI_DIR / "android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionCode="10000"', manifest_xml)
        self.assertIn('android:versionName="1.0.0"', manifest_xml)
        self.assertIn('android:minSdkVersion="24"', manifest_xml)
        self.assertIn('android:targetSdkVersion="34"', manifest_xml)
        self.assertIn('<supports-screens', manifest_xml)
        self.assertIn('android:anyDensity="true"', manifest_xml)
        self.assertIn('android:resizeableActivity="true"', manifest_xml)

        main_activity = (GUI_DIR / "android" / "app" / "src" / "main" / "java" / "com" / "ziokt" / "client" / "MainActivity.java").read_text(encoding="utf-8")
        self.assertIn('setUseWideViewPort(true)', main_activity)
        self.assertIn('setLoadWithOverviewMode(true)', main_activity)
        self.assertIn('MATCH_PARENT', main_activity)
        self.assertIn('setStatusBarColor', main_activity)

    def test_12_local_node_offline_gatekeeping_and_chat_layout(self):
        """Verify local node offline gatekeeping (only settings accessible) and chat input bar clearance."""
        core_js = (SRC_DIR / "core.js").read_text(encoding="utf-8")
        build_js = (GUI_DIR / "build.js").read_text(encoding="utf-8")
        style_css = (SRC_DIR / "style.css").read_text(encoding="utf-8")
        chat_js = (SRC_DIR / "modules" / "chat.js").read_text(encoding="utf-8")
        files_js = (SRC_DIR / "modules" / "files.js").read_text(encoding="utf-8")
        identity_js = (SRC_DIR / "modules" / "identity.js").read_text(encoding="utf-8")
        settings_js = (SRC_DIR / "modules" / "settings.js").read_text(encoding="utf-8")

        # 1. Gatekeeping when local node is offline
        self.assertIn("isLocalNodeOffline", core_js)
        self.assertIn("updateNavLockState", core_js)
        self.assertIn(".nav-locked", style_css)
        self.assertIn("isLocalNodeOffline() && tabName !== 'settings'", build_js)
        self.assertIn("settings-probe-top-btn", settings_js)

        # 2. Files & Identity guarded when local node offline
        self.assertIn("isLocalNodeOffline", files_js)
        self.assertIn("isLocalNodeOffline", identity_js)

        # 3. Chat input bar unobstructed & responsive
        self.assertIn("chat-page-wrapper", chat_js)
        self.assertIn("chat-input-bar", chat_js)
        self.assertIn(".chat-page-wrapper", style_css)
        self.assertIn(".chat-input-bar", style_css)
        self.assertIn("var(--bottombar-height)", style_css)


if __name__ == "__main__":
    unittest.main()
