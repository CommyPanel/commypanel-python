import json
import pickle
import socket
import traceback
import unittest
from concurrent.futures import ThreadPoolExecutor

from helpers import TOKEN, PanelTestCase, dep_json, reply

from commypanel import (
    ApiError,
    Client,
    CommyPanelError,
    InsecureURLError,
    InvalidInputError,
    InvalidTokenError,
    InvalidURLError,
    RedirectError,
    ResponseTooLargeError,
    TransportError,
    WaitTimeoutError,
    is_conflict,
    is_forbidden,
    is_not_found,
    is_rate_limited,
    is_unauthorized,
)
from commypanel import _client

APP = (
    '{"slug":"shop","name":"Shop","status":"running","stack":"go","deploy_strategy":"rolling",'
    '"domains":["shop.example.com"],"live_deployment":3,"latest_deployment":null,"created_at":"2026-11-16T10:00:00+00:00"}'
)
TOKEN_JSON = '{"data":{"name":"ci","abilities":["apps:read"],"apps":null,"expires_at":null,"last_used_at":null,"owner":"Sam"}}'


class AddressTests(unittest.TestCase):
    def test_good_addresses(self):
        for url in ("https://panel.example.com", "https://panel.example.com/", "https://panel.example.com:8443", "https://panel.example.com/api/v1"):
            Client(url, TOKEN)

        for url in ("http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000"):
            Client(url, TOKEN, allow_http_loopback=True)

    def test_insecure_addresses_are_refused(self):
        for url, allow in (
            ("http://panel.example.com", False),
            ("http://localhost:8000", False),  # loopback http needs the option
            ("http://panel.example.com", True),  # and only loopback
            ("http://192.168.1.10", True),
            ("ftp://panel.example.com", False),
        ):
            with self.assertRaises(InsecureURLError, msg=url):
                Client(url, TOKEN, allow_http_loopback=allow)

    def test_invalid_addresses(self):
        for url in (
            "", "panel.example.com", "https://", "https://user:pw@panel.example.com", "https://panel.example.com/admin",
            "https://panel.example.com?x=1", "https://panel.example.com#top", "https://panel.example.com/api/v2",
            "https://panel.example.com:notaport", None,
        ):
            with self.assertRaises(InvalidURLError, msg=repr(url)):
                Client(url, TOKEN)

    def test_tokens(self):
        for token in ("", " ", "has space", "new\nline", "tab\t", "ctl\x01", "a" * 513, None, 5):
            with self.assertRaises(InvalidTokenError, msg=repr(token)):
                Client("https://panel.example.com", token)

    def test_bad_options(self):
        for options in ({"timeout": 0}, {"timeout": -1}, {"retries": -1}, {"retries": 6}, {"max_response_bytes": 0}, {"ca_cert_pem": "not pem"}):
            with self.assertRaises(ValueError, msg=repr(options)):
                Client("https://panel.example.com", TOKEN, **options)


class RequestTests(PanelTestCase):
    def test_the_token_is_only_in_the_header(self):
        panel = self.panel(reply(200, TOKEN_JSON))
        token = self.client(panel, user_agent="mytool/1.0").token()
        request = panel.last()

        self.assertEqual(request["headers"]["Authorization"], "Bearer " + TOKEN)
        self.assertEqual(request["headers"]["Accept"], "application/json")
        self.assertTrue(request["headers"]["User-Agent"].startswith("mytool/1.0 commypanel-python/"))
        self.assertNotIn("secretsecret", request["path"] + request["query"] + request["body"])
        self.assertEqual((token.name, token.owner, token.apps, token.abilities), ("ci", "Sam", None, ["apps:read"]))

    def test_every_call_uses_the_right_method_path_query_and_body(self):
        deployment = '{"data":' + dep_json() + "}"
        app = '{"data":' + APP + "}"
        cases = [
            ("list apps", '{"data":[]}', lambda c: c.list_apps(), "GET", "/api/v1/apps", "", ""),
            ("get app", app, lambda c: c.get_app("shop"), "GET", "/api/v1/apps/shop", "", ""),
            ("list deployments", '{"data":[]}', lambda c: c.list_deployments("shop", 5), "GET", "/api/v1/apps/shop/deployments", "limit=5", ""),
            ("list deployments default", '{"data":[]}', lambda c: c.list_deployments("shop"), "GET", "/api/v1/apps/shop/deployments", "", ""),
            ("get deployment with log", deployment, lambda c: c.get_deployment("shop", 4, True), "GET", "/api/v1/apps/shop/deployments/4", "log=1", ""),
            ("start deployment", deployment, lambda c: c.start_deployment("shop"), "POST", "/api/v1/apps/shop/deployments", "", ""),
            ("apply", deployment, lambda c: c.apply_changes("shop"), "POST", "/api/v1/apps/shop/apply", "", ""),
            ("start app", app, lambda c: c.start_app("shop"), "POST", "/api/v1/apps/shop/start", "", ""),
            ("stop app", app, lambda c: c.stop_app("shop"), "POST", "/api/v1/apps/shop/stop", "", ""),
            ("restart app", app, lambda c: c.restart_app("shop"), "POST", "/api/v1/apps/shop/restart", "", ""),
            ("logs", '{"data":{"live":true,"lines":50,"logs":"hi"}}', lambda c: c.logs("shop", 50), "GET", "/api/v1/apps/shop/logs", "tail=50", ""),
            ("list env", '{"data":{"keys":["A"],"pending_changes":false}}', lambda c: c.list_env("shop"), "GET", "/api/v1/apps/shop/env", "", ""),
            ("set env", '{"data":{"key":"A_B","pending_changes":true}}', lambda c: c.set_env("shop", "A_B", 'va"lue'), "PUT", "/api/v1/apps/shop/env/A_B", "", '{"value":"va\\"lue"}'),
            ("unset env", '{"data":{"key":"A_B","pending_changes":true}}', lambda c: c.unset_env("shop", "A_B"), "DELETE", "/api/v1/apps/shop/env/A_B", "", ""),
        ]

        for name, reply_body, call, method, path, query, body in cases:
            with self.subTest(name):
                panel = self.panel(reply(200, reply_body))
                call(self.client(panel))
                request = panel.last()
                self.assertEqual((request["method"], request["path"], request["query"], request["body"]), (method, path, query, body))

    def test_decodes_the_objects(self):
        body = (
            '{"data":{"slug":"shop","name":"Shop","status":"running","stack":"go","deploy_strategy":"stop_first",'
            '"domains":["a.example.com"],"live_deployment":3,"latest_deployment":{"number":3,"status":"active","stage":"done",'
            '"finished":true,"succeeded":true,"commit":"abc123","commit_message":"Fix","strategy":"stop_first","is_rollback":false,'
            '"error":null,"created_at":"2026-11-16T10:00:00+00:00","finished_at":"2026-11-16T10:01:00+00:00","url":"https://x"},'
            '"created_at":"2026-11-16T09:00:00Z"}}'
        )
        app = self.client(self.panel(reply(200, body))).get_app("shop")

        self.assertEqual((app.deploy_strategy, app.stack, app.live_deployment, app.domains), ("stop_first", "go", 3, ["a.example.com"]))
        latest = app.latest_deployment
        self.assertTrue(latest.finished and latest.succeeded)
        self.assertEqual((latest.commit, latest.strategy), ("abc123", "stop_first"))
        self.assertEqual((latest.finished_at - latest.created_at).total_seconds(), 60)
        self.assertEqual(app.created_at.year, 2026)

    def test_set_env_tells_new_from_replaced(self):
        for status, created in ((201, True), (200, False)):
            panel = self.panel(reply(status, '{"data":{"key":"A","pending_changes":true}}'))
            change, was_created = self.client(panel).set_env("shop", "A", "v")
            self.assertEqual((change.key, change.pending_changes, was_created), ("A", True, created))

    def test_a_value_that_is_not_text_is_refused_before_any_request(self):
        panel = self.panel()

        with self.assertRaises(InvalidInputError):
            self.client(panel).set_env("shop", "A", 5)

        self.assertEqual(panel.requests, [])


class ErrorTests(PanelTestCase):
    def test_errors_carry_the_panels_sentence(self):
        cases = [
            (404, '{"error":"Not Found","message":"Not Found"}', is_not_found),
            (401, '{"error":"Unauthenticated."}', is_unauthorized),
            (403, '{"error":"Invalid ability provided."}', is_forbidden),
            (409, '{"error":"A deployment is already in progress."}', is_conflict),
            (429, '{"error":"Too Many Attempts."}', is_rate_limited),
        ]

        for status, body, check in cases:
            with self.subTest(status):
                client = self.client(self.panel(reply(status, body)), retries=0)

                with self.assertRaises(ApiError) as caught:
                    client.get_app("shop")

                self.assertTrue(check(caught.exception))
                self.assertEqual(caught.exception.status, status)
                self.assertTrue(caught.exception.message)
                self.assertFalse(check(ValueError("x")))

    def test_the_message_key_is_used_when_there_is_no_error_key(self):
        with self.assertRaises(ApiError) as caught:
            self.client(self.panel(reply(500, '{"message":"Server Error"}'))).get_app("shop")

        self.assertEqual(caught.exception.message, "Server Error")

    def test_a_conflict_names_the_running_deployment_and_a_422_the_fields(self):
        body = '{"error":"A deployment is already in progress.","deployment":' + dep_json(7, "building") + "}"

        with self.assertRaises(ApiError) as caught:
            self.client(self.panel(reply(409, body))).start_deployment("shop")

        self.assertEqual(caught.exception.deployment.number, 7)

        invalid = '{"error":"PORT is set by CommyPanel.","errors":{"key":["PORT is set by CommyPanel."]}}'

        with self.assertRaises(ApiError) as caught:
            self.client(self.panel(reply(422, invalid))).set_env("shop", "PORT", "1")

        self.assertEqual(caught.exception.fields, {"key": ["PORT is set by CommyPanel."]})
        self.assertIn("key: PORT is set by CommyPanel.", str(caught.exception))

    def test_a_server_that_echoes_the_token_cannot_put_it_in_an_error(self):
        echo = {
            "error": "Bad credentials: " + TOKEN,
            "errors": {"key " + TOKEN: ["the value " + TOKEN + " is wrong", "second " + TOKEN]},
            "deployment": json.loads(dep_json(7, "building", error="failed for " + TOKEN)) | {"commit_message": "msg " + TOKEN, "url": "https://x/" + TOKEN},
        }
        client = self.client(self.panel(reply(422, json.dumps(echo))), retries=0)

        with self.assertRaises(ApiError) as caught:
            client.set_env("shop", "KEY", "v")

        err = caught.exception
        shown = [str(err), repr(err), err.message, repr(err.fields), repr(err.deployment), repr(err.args)]

        for text in shown:
            self.assertNotIn("secretsecret", text)

        self.assertIn("[redacted]", err.message)
        self.assertIn("[redacted]", "".join(err.fields) + "".join("".join(v) for v in err.fields.values()))
        self.assertEqual(err.deployment.error, "failed for [redacted]")
        self.assertEqual(err.deployment.commit_message, "msg [redacted]")
        self.assertEqual(err.deployment.number, 7)

    def test_an_answer_that_is_not_the_apis_is_said_plainly_without_echoing_it(self):
        for status in (200, 502):
            with self.subTest(status):
                panel = self.panel(reply(status, "<html>nginx says hi</html>"))

                with self.assertRaises(CommyPanelError) as caught:
                    self.client(panel, retries=0).list_apps()

                self.assertNotIn("nginx says hi", str(caught.exception))

    def test_a_connection_that_fails_does_not_show_the_token(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        client = Client("http://127.0.0.1:%d" % port, TOKEN, allow_http_loopback=True, retries=0, timeout=2)

        with self.assertRaises(TransportError) as caught:
            client.list_apps()

        shown = "".join(traceback.format_exception(type(caught.exception), caught.exception, caught.exception.__traceback__))
        self.assertNotIn("secretsecret", shown)

    def test_a_timeout_is_a_transport_error(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        self.addCleanup(server.close)
        client = Client("http://127.0.0.1:%d" % server.getsockname()[1], TOKEN, allow_http_loopback=True, retries=0, timeout=0.3)

        with self.assertRaises(TransportError) as caught:
            client.list_apps()

        self.assertIn("timed out", str(caught.exception))


class RedirectTests(PanelTestCase):
    def test_redirects_are_never_followed_so_the_token_stays_home(self):
        elsewhere = self.panel(reply(200, '{"data":[]}'))
        panel = self.panel(lambda request, n: (302, "", {"Location": elsewhere.url + "/api/v1/apps"}))

        with self.assertRaises(RedirectError):
            self.client(panel).list_apps()

        self.assertEqual(elsewhere.requests, [], "the other address must never receive the token")


class RetryTests(PanelTestCase):
    def test_a_read_is_retried_after_a_gateway_error(self):
        panel = self.panel(lambda request, n: (503, '{"error":"down"}', None) if n < 3 else (200, '{"data":[]}', None))
        client = self.client(panel)

        self.assertEqual(client.list_apps(), [])
        self.assertEqual(len(panel.requests), 3)
        self.assertEqual(client.waits, [0.5, 1.0])

    def test_a_write_is_not_retried_after_a_gateway_error(self):
        panel = self.panel(reply(503, '{"error":"down"}'))

        with self.assertRaises(ApiError):
            self.client(panel).start_deployment("shop")

        self.assertEqual(len(panel.requests), 1)

    def test_a_429_is_retried_for_writes_too_after_the_wait_it_asks_for(self):
        def handler(request, n):
            if n == 1:
                return 429, '{"error":"slow down"}', {"Retry-After": "7"}

            return 202, '{"data":' + dep_json(1) + "}", None

        panel = self.panel(handler)
        client = self.client(panel)
        client.start_deployment("shop")

        self.assertEqual(client.waits, [7.0])

    def test_an_enormous_retry_after_is_capped(self):
        panel = self.panel(reply(429, '{"error":"slow down"}', {"Retry-After": "86400"}))
        client = self.client(panel, retries=1)

        with self.assertRaises(ApiError) as caught:
            client.list_apps()

        self.assertTrue(is_rate_limited(caught.exception))
        self.assertEqual(client.waits, [30.0])
        self.assertEqual(caught.exception.retry_after_seconds, 86400)

    def test_retries_stop_at_the_limit(self):
        panel = self.panel(reply(503, '{"error":"down"}'))

        with self.assertRaises(ApiError):
            self.client(panel, retries=1).list_apps()

        self.assertEqual(len(panel.requests), 2)

    def test_other_errors_are_not_retried(self):
        panel = self.panel(reply(404, '{"error":"Not Found"}'))

        with self.assertRaises(ApiError):
            self.client(panel).get_app("shop")

        self.assertEqual(len(panel.requests), 1)


class LimitTests(PanelTestCase):
    def test_an_answer_that_is_too_large_is_refused(self):
        panel = self.panel(reply(200, '{"data":{"live":true,"lines":10,"logs":"' + "x" * 5000 + '"}}'))

        with self.assertRaises(ResponseTooLargeError):
            self.client(panel, max_response_bytes=1000).logs("shop", 10)

    def test_an_error_body_is_limited_to_a_megabyte(self):
        panel = self.panel(reply(500, "x" * ((1 << 20) + 10)))

        with self.assertRaises(ResponseTooLargeError):
            self.client(panel, retries=0).list_apps()


class SecretTests(PanelTestCase):
    def test_the_token_never_shows_up(self):
        client = self.client(self.panel())

        for shown in (repr(client), str(client), "%s" % client, "%r" % client, "{}".format(client), "%s" % (client,), f"{client}", f"{client!r}"):
            self.assertNotIn("secretsecret", shown)

        self.assertIn("redacted", repr(client))

    def test_the_client_cannot_be_pickled(self):
        with self.assertRaises(TypeError):
            pickle.dumps(self.client(self.panel()))

    def test_scrub_removes_the_token_from_anything_quoted(self):
        self.assertNotIn("secretsecret", _client._scrub("failed with " + TOKEN, TOKEN))


class NameTests(PanelTestCase):
    def test_names_that_cannot_be_right_never_become_requests(self):
        panel = self.panel(reply(200, '{"data":{}}'))
        client = self.client(panel)
        slugs = ["", "../etc", "a/b", "A", "a b", "-x", "a?x=1", "a#b", "a%2Fb", "a" * 64, "ok\n", None, 5]
        keys = ["", "1BAD", "A-B", "A B", "A/B", "A?", "A" * 129, "OK\n", None]

        for slug in slugs:
            with self.assertRaises(InvalidInputError, msg=repr(slug)):
                client.get_app(slug)

        for key in keys:
            with self.assertRaises(InvalidInputError, msg=repr(key)):
                client.set_env("shop", key, "v")

            with self.assertRaises(InvalidInputError, msg=repr(key)):
                client.unset_env("shop", key)

        for number in (0, -1, "4", None, True):
            with self.assertRaises(InvalidInputError, msg=repr(number)):
                client.get_deployment("shop", number)

        self.assertEqual(panel.requests, [], "no request may be made for an invalid name")

    def test_the_longest_valid_names_are_accepted(self):
        panel = self.panel(reply(200, '{"data":{"key":"K","pending_changes":false}}'))
        client = self.client(panel)

        client.unset_env("a" + "b" * 62, "A" * 128)
        self.assertEqual(len(panel.requests), 1)


class WaitTests(PanelTestCase):
    def test_polls_until_it_is_over(self):
        def handler(request, n):
            done = n >= 3

            return 200, '{"data":' + dep_json(4, "active" if done else "building", None, done, done) + "}", None

        client = self.client(self.panel(handler))
        looks = []
        deployment = client.wait_for_deployment("shop", 4, 1, looks.append)

        self.assertTrue(deployment.finished and deployment.succeeded)
        self.assertEqual(len(looks), 3)
        self.assertEqual(client.waits, [1.0, 1.0])

    def test_a_poll_under_a_second_means_three(self):
        calls = []
        panel = self.panel(lambda request, n: (200, '{"data":' + dep_json(4, "active", None, n > 1, n > 1) + "}", None))
        client = self.client(panel)
        client.wait_for_deployment("shop", 4, 0.1)

        self.assertEqual(client.waits, [3.0])

    def test_a_timeout_stops_the_waiting(self):
        panel = self.panel(reply(200, '{"data":' + dep_json(4, "building") + "}"))
        client = self.client(panel)

        with self.assertRaises(WaitTimeoutError):
            client.wait_for_deployment("shop", 4, 1, None, timeout=0.2)


class ConcurrencyTests(PanelTestCase):
    def test_a_client_can_be_shared_between_threads(self):
        panel = self.panel(reply(200, '{"data":[]}'))
        client = self.client(panel)

        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(lambda _: client.list_apps(), range(24)))

        self.assertEqual(results, [[]] * 24)
        self.assertEqual(len(panel.requests), 24)


if __name__ == "__main__":
    unittest.main()
