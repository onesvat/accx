import json
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ACCX = runpy.run_path(Path(__file__).parents[1] / 'accx')


class OpenCodeTests(unittest.TestCase):
    def test_import_switch_preserves_other_keys_and_hides_secrets(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ACCX_HOME': tmp + '/vault', 'XDG_DATA_HOME': tmp + '/data'}):
            provider = ACCX['Provider']('opencode')
            live = {'opencode-go': {'type': 'api', 'key': 'old-secret'}, 'nvidia': {'type': 'api', 'key': 'other-secret'}}
            ACCX['write_json'](provider.live_credential_path(), live)
            ACCX['save_opencode_key']('original')
            self.assertEqual(ACCX['detect_active_profile'](provider), 'original')
            stored = json.loads(provider.stored_credential_path('original').read_text())
            self.assertEqual(stored, live['opencode-go'])
            ACCX['save_opencode_key']('second', 'new-secret')
            ACCX['perform_switch_profile'](provider, 'second')
            changed = json.loads(provider.live_credential_path().read_text())
            self.assertEqual(changed['nvidia'], live['nvidia'])
            self.assertEqual(changed['opencode-go']['key'], 'new-secret')
            self.assertEqual(ACCX['detect_active_profile'](provider), 'second')
            public = json.dumps(ACCX['dashboard_data']())
            for secret in ('old-secret', 'new-secret', 'other-secret'):
                self.assertNotIn(secret, public)
            with self.assertRaises(ValueError):
                ACCX['save_opencode_key']('second', 'overwrite')

    def test_three_usage_windows(self):
        raw = {'usage': {name: {'percent': value, 'resetsAt': '2030-01-01T00:00:00Z'} for name, value in [('rolling', 12), ('weekly', 34), ('monthly', 56)]}}
        provider = ACCX['Provider']('opencode')
        snapshot = ACCX['usage_snapshot'](provider, raw)
        self.assertEqual(snapshot['five_hour'], 12)
        self.assertEqual(snapshot['seven_day'], 34)
        self.assertEqual(snapshot['windows'][2]['used_percent'], 56)
        self.assertEqual(snapshot['windows'][2]['label'], 'Aylık')

    def test_usage_uses_go_api_key(self):
        from unittest.mock import Mock
        fetch = ACCX['fetch_usage']
        request = Mock(return_value={'usage': {}})
        with patch.dict(fetch.__globals__, {'http_get_json': request}):
            fetch(ACCX['Provider']('opencode'), {'type': 'api', 'key': 'test-key'})
        self.assertEqual(request.call_args.args[0], 'https://opencode.ai/zen/go/v1/usage')
        self.assertEqual(request.call_args.args[1]['Authorization'], 'Bearer test-key')


class OpenCodeIdentityTests(unittest.TestCase):
    def test_single_member_email_is_saved_without_key(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"ACCX_HOME": tmp}):
            provider = ACCX["Provider"]("opencode")
            function = ACCX["refresh_opencode_identity"]
            response = {"items": [{"email": "user@example.com", "userId": "account-1"}], "pageInfo": {"total": 1}}
            with patch.dict(function.__globals__, {"http_get_json": lambda *args: response}):
                function(provider, "test", {"key": "secret-key"})
            meta = json.loads(provider.stored_meta_path("test").read_text())
            self.assertEqual(meta["identity"]["email"], "user@example.com")
            self.assertNotIn("secret-key", json.dumps(meta))

    def test_shared_workspace_and_permission_denial_do_not_guess_identity(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"ACCX_HOME": tmp}):
            provider = ACCX["Provider"]("opencode")
            function = ACCX["refresh_opencode_identity"]
            for response in (None, {"items": [{"email": "wrong@example.com"}], "pageInfo": {"total": 2}}):
                with patch.dict(function.__globals__, {"http_get_json": lambda *args: response}):
                    function(provider, "test", {"key": "secret-key"})
                self.assertFalse(provider.stored_meta_path("test").exists())
