# TEST-ONLY certificates

These files exist only so the tests can prove the `ca_cert_pem` option works and that an untrusted
certificate is refused. They are **throwaway**: a private CA (its key was deleted right after signing) and a
server certificate for `localhost`, `127.0.0.1` and `::1`, valid for 100 years. `server.key` protects
nothing: it is only used by the tests' local server. Never trust `ca.pem` anywhere.

They were made once with:

```
openssl req -x509 -newkey rsa:2048 -nodes -keyout ca.key -out ca.pem -days 36500 -config openssl.cnf -extensions v3_ca -subj "/CN=commypanel-test-only-ca"
openssl req -newkey rsa:2048 -nodes -keyout server.key -out server.csr -subj "/CN=localhost"
# wrongname.pem is made the same way with -extensions v3_wrongname
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial -out server.pem -days 36500 -extfile openssl.cnf -extensions v3_server
```
