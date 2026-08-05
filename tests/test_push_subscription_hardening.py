"""Tests for push subscription registration limits.

/api/push/subscribe is necessarily unauthenticated -- the viewer registers
itself and viewer login is optional by default -- so the protection is on what
may be registered rather than who may register. Without it, any https URL could
be stored and the server would POST to it every time a severe alert fired.
"""

import unittest

from fastapi import HTTPException

from app import main


class PushEndpointAllowlistTests(unittest.TestCase):
    def test_accepts_real_push_services(self):
        for endpoint in [
            "https://fcm.googleapis.com/fcm/send/abc123",
            "https://updates.push.services.mozilla.com/wpush/v2/xyz",
            "https://sub.notify.windows.com/w/?token=x",
            "https://web.push.apple.com/abc",
        ]:
            self.assertTrue(main._is_allowed_push_endpoint(endpoint), endpoint)

    def test_rejects_arbitrary_hosts(self):
        for endpoint in [
            "https://evil.example.com/collect",
            "https://192.168.1.1/admin",
            "https://10.0.0.5:8080/",
        ]:
            self.assertFalse(main._is_allowed_push_endpoint(endpoint), endpoint)

    def test_rejects_suffix_confusion(self):
        """A host merely *containing* an allowed name must not pass."""
        for endpoint in [
            "https://fcm.googleapis.com.evil.test/x",
            "https://notfcm.googleapis.com/x",
            "https://push.apple.com.attacker.net/x",
        ]:
            self.assertFalse(main._is_allowed_push_endpoint(endpoint), endpoint)

    def test_rejects_non_https_and_malformed(self):
        for endpoint in ["http://fcm.googleapis.com/x", "not-a-url", "", "ftp://fcm.googleapis.com/x"]:
            self.assertFalse(main._is_allowed_push_endpoint(endpoint), endpoint)

    def test_sanitize_rejects_bad_endpoint_with_400_not_500(self):
        """This path used to raise a bare ValueError, surfacing as a 500."""
        with self.assertRaises(HTTPException) as ctx:
            main._sanitize_push_subscription(
                {"endpoint": "https://evil.example.com/x", "keys": {"p256dh": "a", "auth": "b"}}
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_sanitize_accepts_a_valid_subscription(self):
        result = main._sanitize_push_subscription(
            {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "a", "auth": "b"}}
        )
        self.assertEqual(result["endpoint"], "https://fcm.googleapis.com/fcm/send/abc")
        self.assertEqual(result["keys"], {"p256dh": "a", "auth": "b"})

    def test_sanitize_still_requires_keys(self):
        with self.assertRaises(HTTPException) as ctx:
            main._sanitize_push_subscription({"endpoint": "https://fcm.googleapis.com/fcm/send/abc"})
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
