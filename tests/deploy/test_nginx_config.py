"""The edge nginx templates render and pass `nginx -t` in the stock image."""

import shutil
import subprocess
from pathlib import Path

from tests.deploy.helpers import MATERIALS_DIR, requires_compose

import pytest

pytestmark = requires_compose

NGINX_IMAGE = "nginx:1.27-alpine"
HOST_ENV = {
    "HOST_ID": "id.ihsu.test",
    "HOST_SP": "my.ihsu.test",
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
    assert "include /etc/nginx/ihsp/route-static.inc;" in lms
