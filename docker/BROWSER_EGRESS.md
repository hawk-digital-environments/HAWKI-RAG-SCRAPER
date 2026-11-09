# Protected Chromium egress

The browser path is functional only with enforced Linux namespace isolation.
It does not fall back to ordinary Chromium networking.

```text
Crawl4AI/Playwright (parent, local CDP control only)
  -> Chromium in fresh unprivileged user + network + PID namespaces
       -> namespace-local HTTP proxy bridge
       -> private filesystem Unix socket
       -> validating egress broker in parent namespace
       -> approved numeric destination
```

The child verifies that its network/PID namespaces differ from the parent,
that it is PID 1, and that no interface other than loopback is active. Some
kernels create dormant tunnel devices; those must remain DOWN. It verifies
that an external numeric address has no route, locks no-new-privileges and
root capability semantics, and drops all capabilities before starting Chromium.
The new user namespace maps only the runtime's own UID; it does not grant host
root privileges. Chromium uses `--no-sandbox` inside this already isolated user
namespace. Network restrictions are kernel namespace restrictions, not that
Chromium flag or a renderer interception hook.

Chromium receives a fixed HTTP proxy, `<-loopback>` bypass removal, disabled
QUIC/DNS prefetch/background networking, and disabled non-proxied WebRTC UDP.
Only the broker bridge and necessary local CDP endpoints are reachable inside
the namespace. Literal IPs, localhost implicit bypass, HTTP/3, DNS-over-HTTPS,
service workers, and browser background traffic cannot create an external
route. Even a context explicitly configured to bypass the proxy cannot reach
the fixture's public IP in the integration test.

The broker applies the existing HTTP destination policy. All DNS answers must
pass; CONNECT/WebSocket sockets connect to the approved numeric address with
no second hostname lookup. HTTP responses return redirects to Chromium, whose
next connection must traverse the boundary again. CONNECT preserves encrypted
end-to-end TLS, hostname SNI, Host and certificate validation. BrowserConfig's
permissive HTTPS default is explicitly overridden. WebSocket and secure
WebSocket traffic use the same bound upstream sockets.

HTTP proxy uploads require Content-Length and are bounded to 16 MiB. Chunked
request uploads are rejected rather than bypassing the broker. Response bodies
stream through the broker. HTTP/3 and direct UDP transports are unsupported.

The namespace worker owns Chromium and its descendants in a PID namespace.
Closing its stdin terminates that namespace; killing the unshare supervisor
also kills namespace PID 1 through `--kill-child=KILL`. Browser cleanup waits
for process-tree exit, broker/control relays, DNS work, and the Playwright
driver before the existing runtime may issue a sealed receipt. No lifecycle,
generation, writer-fence or HAWKI-RAG ownership protocol is replaced.

## Deployment prerequisite

Linux must support unprivileged user, network and PID namespaces. The runtime
needs `/usr/bin/unshare`, procfs, and installed Playwright Chromium. The images
already contain these; no runtime NET_ADMIN, SYS_ADMIN or privileged container
is required.

Docker's default seccomp policy blocks the namespace creation syscall. Supply
the included profile when creating the crawler container:

```sh
docker run --security-opt seccomp=/absolute/path/docker/browser-seccomp.json ...
```

For Compose, the equivalent service override is:

```yaml
services:
  scraper:
    security_opt:
      - seccomp=/absolute/path/docker/browser-seccomp.json
```

The profile retains Moby's default deny policy and adds one rule permitting
`unshare` only with user/network/PID namespace flags. It does not permit mount
or setns operations or add capabilities. Host LSM/AppArmor policy or a disabled
unprivileged-user-namespace kernel setting can still reject creation; that is
a startup failure, never a reason to disable isolation. Production deployment
configuration is not changed automatically by this repository change.

The upstream profile was retrieved from
[moby/profiles seccomp/default.json](https://github.com/moby/profiles/blob/main/seccomp/default.json),
original SHA-256 `6416b47770785a41ac59073cdc77d9fe98517df2799dc83ef207e622de3053f6`.
It is distributed under the accompanying `browser-seccomp.LICENSE` (Apache 2.0).
The only semantic addition is the final namespace permission rule.

## Disposable browser tests

The test image contains Chromium, iproute2 and NSS tools. Its launcher assigns
a public fixture IP plus private/metadata sink IPs only within a disposable
container. It then drops to www-data before executing any tests. The runtime
destination policy is never relaxed, and no real Internet test site is needed.
NET_ADMIN below is solely for fixture setup, not a deployment requirement.

```sh
docker build --target test -t customcrawler-browser-test .
docker run --rm --cap-add NET_ADMIN \
  --security-opt seccomp="$PWD/docker/browser-seccomp.json" \
  -e REQUIRE_PROTECTED_BROWSER_TESTS=1 \
  --entrypoint /bin/sh customcrawler-browser-test -c '
    ip addr add 93.184.216.34/32 dev lo &&
    ip addr add 10.77.0.2/32 dev lo &&
    ip addr add 169.254.169.254/32 dev lo &&
    exec gosu www-data /tests/.venv/bin/python -m pytest -q -p no:cacheprovider
  '
```

The requirement variable belongs to tests only: missing prerequisites fail
the required run instead of being silently skipped. Ordinary macOS/default
seccomp test runs skip the real browser fixtures. TLS tests import a disposable
CA into isolated test NSS stores; they never disable certificate verification.
