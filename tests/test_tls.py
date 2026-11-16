import os
import unittest

from helpers import TLS_DIR, TOKEN, PanelTestCase, reply

from commypanel import Client, TransportError


def ca():
    with open(os.path.join(TLS_DIR, "ca.pem")) as handle:
        return handle.read()


@unittest.skipUnless(os.path.exists(os.path.join(TLS_DIR, "ca.pem")), "the test-only certificates are not in this copy")
class TLSTests(PanelTestCase):
    def test_a_private_ca_works_when_it_is_given(self):
        panel = self.panel(reply(200, '{"data":[]}'), tls=True)

        self.assertEqual(Client(panel.url, TOKEN, ca_cert_pem=ca()).list_apps(), [])
        # Bytes are accepted too.
        self.assertEqual(Client(panel.url, TOKEN, ca_cert_pem=ca().encode()).list_apps(), [])

    def test_a_certificate_nobody_trusts_is_refused_and_no_request_is_made(self):
        panel = self.panel(reply(200, '{"data":[]}'), tls=True)

        with self.assertRaises(TransportError) as caught:
            Client(panel.url, TOKEN, retries=0).list_apps()

        self.assertIn("CERTIFICATE_VERIFY_FAILED", str(caught.exception))
        self.assertNotIn("secretsecret", str(caught.exception))
        self.assertEqual(panel.requests, [], "the token must not be sent over an unverified connection")

    def test_the_host_name_is_checked_too(self):
        # Signed by the trusted CA, but for another name than the address used: refused all the same.
        panel = self.panel(reply(200, '{"data":[]}'), tls=True, cert="wrongname")

        with self.assertRaises(TransportError) as caught:
            Client(panel.url, TOKEN, ca_cert_pem=ca(), retries=0).list_apps()

        self.assertIn("mismatch", str(caught.exception).lower())
        self.assertEqual(panel.requests, [])

    def test_there_is_no_way_to_skip_verification(self):
        with self.assertRaises(TypeError):
            Client("https://panel.example.com", TOKEN, verify=False)

        with self.assertRaises(TypeError):
            Client("https://panel.example.com", TOKEN, insecure=True)


if __name__ == "__main__":
    unittest.main()
