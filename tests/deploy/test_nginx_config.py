"""The edge nginx templates render and pass `nginx -t` in the stock image."""

import re
import shutil
import subprocess
from pathlib import Path

from tests.deploy.helpers import MATERIALS_DIR, requires_compose

import pytest

pytestmark = requires_compose

NGINX_IMAGE = "nginx:1.28.3-alpine"
HOST_ENV = {
    "HOST_ID": "id.ihsu.test",
    "HOST_MY": "my.ihsu.test",
    "HOST_APP": "app.ihsu.test",
    "HOST_STAFF": "staff.ihsu.test",
    "HOST_ADMIN": "admin.ihsu.test",
    "HOST_LMS": "lms.ihsu.test",
    "HOST_LIBRARY": "lib.ihsu.test",
    "HOST_S": "s.ihsu.test",
    "HOST_API": "api.ihsu.test",
    "HOST_MCP": "mcp.ihsu.test",
    "HOST_APEX": "ihsu.test",
    "HOST_STORAGE": "storage.ihsu.test",
    "HOST_PORT_SUFFIX": "",
    "CERT_NAME": "ihsu.test",
    "NGINX_ENVSUBST_FILTER": "^(HOST|CERT)_",
}


def _image_available() -> bool:
    inspect = subprocess.run(
        ["docker", "image", "inspect", NGINX_IMAGE], capture_output=True, check=False
    )
    if inspect.returncode == 0:
        return True
    pull = subprocess.run(
        ["docker", "pull", NGINX_IMAGE], capture_output=True, check=False
    )
    return pull.returncode == 0


def _self_signed(directory: Path) -> None:
    live = directory / "live" / "ihsu.test"
    live.mkdir(parents=True)
    subprocess.run(
        ["openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048", "-days", "1"]
        + ["-subj", "/CN=ihsu.test", "-keyout", str(live / "privkey.pem")]
        + ["-out", str(live / "fullchain.pem")],
        capture_output=True,
        check=True,
    )
    for pem in live.glob("*.pem"):
        pem.chmod(0o644)


def _nginx(
    mode: str, extra_mounts: list[str], *args: str
) -> subprocess.CompletedProcess[str]:
    command = ["docker", "run", "--rm"]
    for name, value in HOST_ENV.items():
        command += ["-e", f"{name}={value}"]
    command += ["-v", f"{MATERIALS_DIR / 'nginx' / mode}:/etc/nginx/templates:ro"]
    command += ["-v", f"{MATERIALS_DIR / 'nginx' / 'common'}:/etc/nginx/ihsp:ro"]
    for mount in extra_mounts:
        command += ["-v", mount]
    command += [NGINX_IMAGE, "nginx", *args]
    return subprocess.run(command, capture_output=True, text=True, check=False)


@pytest.fixture(scope="module", autouse=True)
def _nginx_image() -> None:
    if not _image_available():
        pytest.skip(f"{NGINX_IMAGE} is not available")


def test_local_templates_pass_nginx_t() -> None:
    result = _nginx("local", [], "-t")
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is not installed")
def test_prod_templates_pass_nginx_t(tmp_path: Path) -> None:
    _self_signed(tmp_path)
    result = _nginx("prod", [f"{tmp_path}:/etc/letsencrypt:ro"], "-t")
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is not installed")
def test_prod_config_routes_the_documented_hosts(tmp_path: Path) -> None:
    _self_signed(tmp_path)
    dump = _nginx("prod", [f"{tmp_path}:/etc/letsencrypt:ro"], "-T").stdout
    for host in HOST_ENV.values():
        if host.endswith("ihsu.test"):
            assert f"server_name {host};" in dump
    assert "listen 443 ssl;" in dump
    assert "ssl_reject_handshake on;" in dump
    assert "proxy_pass $up_hydra;" in dump
    assert "/.well-known/acme-challenge/" in dump
    assert "return 404;" in dump  # /internal/ is never reachable from outside


def test_the_api_routes_send_identity_paths_to_identity() -> None:
    route = (MATERIALS_DIR / "nginx" / "common" / "route-api.inc").read_text()
    assert "^/v1/(id|oauth)/" in route
    assert "^/v1/admin/(users|teachers|audit)(/|$)" in route
    assert route.index("teachers/[^/]+/profile") < route.index("(users|teachers|audit)")
    assert "location ^~ /telegram/" in route
    assert "location ^~ /internal/" in route


def test_the_library_route_sends_public_pages_to_the_api_and_the_rest_to_web() -> None:
    route = (MATERIALS_DIR / "nginx" / "common" / "route-library.inc").read_text()
    for location in (
        "location ^~ /b/ {",
        "location = /sitemap.xml {",
        "location = /robots.txt {",
        "location ^~ /opds/ {",
    ):
        body = route.split(location, 1)[1].split("}", 1)[0]
        assert "proxy_pass $up_api;" in body, location
        # the Host header reaches the api unchanged, as for the room pages
        assert "/etc/nginx/ihsp/proxy.inc;" in body, location
    # everything else is the static app; student projects (/p/) are not routed yet
    assert (
        "location / {\n    include /etc/nginx/ihsp/proxy.inc;\n    proxy_pass $up_web;"
        in route
    )
    assert "location ^~ /p/" not in route
    assert route.count("proxy_pass $up_api;") == 4


@pytest.mark.parametrize("mode", ["local", "prod"])
def test_the_library_host_has_its_own_route(mode: str, tmp_path: Path) -> None:
    mounts: list[str] = []
    if mode == "prod":
        if shutil.which("openssl") is None:
            pytest.skip("openssl is not installed")
        _self_signed(tmp_path)
        mounts = [f"{tmp_path}:/etc/letsencrypt:ro"]
    dump = _nginx(mode, mounts, "-T").stdout
    servers = dump.split("\nserver {")
    library = next(s for s in servers if "server_name lib.ihsu.test;" in s)
    assert "include /etc/nginx/ihsp/route-library.inc;" in library
    # nginx -T appends the included files: the library route is in the tested config
    assert "location ^~ /opds/ {" in dump
    # the other static hosts keep the plain static route
    lms = next(s for s in servers if "server_name lms.ihsu.test;" in s)
    assert "include /etc/nginx/ihsp/route-lms.inc;" in lms


def _route(name: str) -> str:
    return (MATERIALS_DIR / "nginx" / "common" / name).read_text(encoding="utf-8")


def _locations(text: str) -> list[str]:
    """The bodies of the location blocks of a route file."""
    bodies: list[str] = []
    for match in re.finditer(r"^\s*location\s+[^{]+\{", text, flags=re.M):
        bodies.append(text[match.end() :].split("}", 1)[0])
    return bodies


def test_every_api_and_mcp_location_adds_the_json_response_headers() -> None:
    for name in ("route-api.inc", "route-mcp.inc"):
        for body in _locations(_route(name)):
            if "proxy_pass" in body:
                assert "headers-api.inc" in body, (name, body)
    headers = _route("headers-api.inc")
    assert 'X-Content-Type-Options "nosniff"' in headers
    assert 'Referrer-Policy "no-referrer"' in headers
    assert "default-src 'none'; frame-ancestors 'none'" in headers
    assert "Strict-Transport-Security" in headers


def test_server_rendered_pages_get_the_html_headers() -> None:
    for name, prefix in (
        ("route-s.inc", "location / "),
        ("route-apex.inc", "location ^~ /r/ "),
        ("route-library.inc", "location ^~ /b/ "),
    ):
        body = _route(name).split(prefix, 1)[1].split("}", 1)[0]
        assert "headers-html.inc" in body, name
    html = _route("headers-html.inc")
    assert "form-action 'self'" in html and "frame-ancestors 'none'" in html


def test_login_oauth_registration_and_webhook_are_rate_limited() -> None:
    api = _route("route-api.inc")
    login = api.split("^/v1/(id|oauth)/", 1)[1].split("}", 1)[0]
    assert "limit_req zone=ihsp_auth" in login
    telegram = api.split("location ^~ /telegram/", 1)[1].split("}", 1)[0]
    assert "limit_req zone=ihsp_auth" in telegram and "access_log off" in telegram
    ident = _route("route-id.inc")
    register = ident.split("location = /oauth2/register", 1)[1].split("}", 1)[0]
    assert "limit_req zone=ihsp_register" in register
    assert "limit_conn ihsp_mcp" in _route("route-mcp.inc")
    for mode in ("prod", "local"):
        template = (MATERIALS_DIR / "nginx" / mode / "default.conf.template").read_text(
            encoding="utf-8"
        )
        assert "zone=ihsp_auth:10m rate=10r/s" in template
        assert "zone=ihsp_register:10m rate=1r/m" in template
        assert "limit_conn_zone $binary_remote_addr zone=ihsp_mcp" in template
        assert "log_format ihsp" in template and '"$request"' not in template


def test_port_80_redirects_known_hosts_only() -> None:
    template = (MATERIALS_DIR / "nginx" / "prod" / "default.conf.template").read_text()
    default, named = template.split("listen 80;", 1)
    assert "return 404;" in default.split("listen 80 default_server;", 1)[1]
    assert "server_name ${HOST_ID} ${HOST_MY}" in named
    assert "return 301 https://$host$request_uri;" in named


def test_the_lms_route_sends_h5p_files_to_the_api_and_the_rest_to_web() -> None:
    route = _route("route-lms.inc")
    body = route.split("location ^~ /v1/lms/h5p/ {", 1)[1].split("}", 1)[0]
    assert "proxy_pass $up_api;" in body
    assert "/etc/nginx/ihsp/proxy.inc;" in body
    assert "include /etc/nginx/ihsp/route-static.inc;" in route


def test_static_routes_never_leak_the_internal_port_in_redirects() -> None:
    route = (MATERIALS_DIR / "nginx" / "common" / "route-static.inc").read_text()
    assert "proxy_redirect ~^http://[^/]+:8080/(.*)$ https://$host/$1;" in route


def test_upload_routes_allow_the_h5p_and_cartridge_caps_only_there() -> None:
    api = _route("route-api.inc")
    h5p = api.split("location ~ ^/v1/lms/courses/[^/]+/h5p$ {", 1)[1].split("}", 1)[0]
    imscc = api.split("location = /v1/lms/courses/import {", 1)[1].split("}", 1)[0]
    assert "client_max_body_size 101m;" in h5p  # H5P cap is 100 MiB
    assert "client_max_body_size 201m;" in imscc  # .imscc cap is 200 MiB
    for body in (h5p, imscc):
        assert "proxy.inc" in body and "headers-api.inc" in body
        assert "proxy_pass $up_api;" in body
    assert api.count("client_max_body_size") == 2
    for mode in ("local", "prod"):
        template = MATERIALS_DIR / "nginx" / mode / "default.conf.template"
        assert "client_max_body_size 25m;" in template.read_text()
