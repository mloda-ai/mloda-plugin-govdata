"""GenesisClient over respx: auth paths, wire shape, no retry on auth failure, the process lock, host scoping, redaction."""

import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from filelock import FileLock

from mloda_plugin_govdata.feature_groups.destatis.core.api import GenesisClient, _process_lock
from mloda_plugin_govdata.feature_groups.destatis.core.auth import DestatisCredentials
from mloda_plugin_govdata.feature_groups.destatis.core.envelope import GenesisEnvelope, LoginCheckReply
from mloda_plugin_govdata.feature_groups.destatis.core.errors import (
    GenesisAuthError,
    GenesisBackendError,
    GenesisUnknownEnvelope,
    MissingCredentialsError,
    WrongHostCredentialsError,
)
from mloda_plugin_govdata.feature_groups.destatis.core.hosts import GENESIS_ONLINE, REGIONALSTATISTIK

TOKEN = "t0kenAbCdEf0123456789abcdef012345"
USER = "someone@example.org"
PASSWORD = "p4ss w0rd?&="
BASE = GENESIS_ONLINE.base_url
OK_LOGIN = {"Status": "Sie wurden erfolgreich an- und abgemeldet!", "Username": "IHRE_KENNUNG"}
GAST_LOGIN = {"Status": "Sie wurden erfolgreich an- und abgemeldet!", "Username": "GAST"}
NOT_AUTHORIZED = {
    "Code": 15,
    "Content": "Sie sind nicht berechtigt ... Zugangsdaten nicht erkannt werden.",
    "Type": "ERROR",
}
QUALITYSIGNS = {
    "Ident": {"Service": "catalogue", "Method": "qualitysigns"},
    "Status": {"Code": 0, "Content": "erfolgreich", "Type": "Information"},
    "Parameter": {"language": "de", "username": "***", "password": "***"},
    "List": [{"Code": "-", "Content": "nichts vorhanden"}],
    "Copyright": "x",
}


@pytest.fixture(autouse=True)
def _instant_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mloda_plugin_govdata.feature_groups.govdata.core.client._BASE_WAIT", lambda _state: 0.0)


def _client(tmp_path: Path, credentials: DestatisCredentials | None = None, **kwargs: object) -> GenesisClient:
    return GenesisClient(GENESIS_ONLINE, credentials, lock_dir=tmp_path, **kwargs)  # type: ignore[arg-type]


def _form(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(request.content.decode("utf-8"), keep_blank_values=True)


@respx.mock
def test_logincheck_sends_token_in_headers_and_language_in_body(tmp_path: Path) -> None:
    route = respx.post(BASE + "helloworld/logincheck").mock(return_value=httpx.Response(200, json=OK_LOGIN))
    with _client(tmp_path, DestatisCredentials(token=TOKEN)) as client:
        reply = client.logincheck()
    assert isinstance(reply, LoginCheckReply) and reply.is_success
    request = route.calls.last.request
    assert request.headers["username"] == TOKEN and request.headers["password"] == ""
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert _form(request) == {"language": ["de"]}
    assert TOKEN not in str(request.url)


@respx.mock
def test_password_path_sends_user_and_password_headers(tmp_path: Path) -> None:
    route = respx.post(BASE + "helloworld/logincheck").mock(return_value=httpx.Response(200, json=OK_LOGIN))
    with _client(tmp_path, DestatisCredentials(user=USER, password=PASSWORD), language="en") as client:
        client.logincheck()
    request = route.calls.last.request
    assert request.headers["username"] == USER and request.headers["password"] == PASSWORD
    assert _form(request) == {"language": ["en"]}


@respx.mock
def test_guest_reply_is_an_auth_error_and_never_retried(tmp_path: Path) -> None:
    route = respx.post(BASE + "helloworld/logincheck").mock(return_value=httpx.Response(200, json=GAST_LOGIN))
    with _client(tmp_path, DestatisCredentials(token=TOKEN)) as client, pytest.raises(GenesisAuthError, match="GAST"):
        client.logincheck()
    assert route.call_count == 1


@respx.mock
def test_http_401_is_an_auth_error_never_retried(tmp_path: Path) -> None:
    route = respx.post(BASE + "metadata/table").mock(return_value=httpx.Response(401, json=NOT_AUTHORIZED))
    with _client(tmp_path, DestatisCredentials(token=TOKEN)) as client, pytest.raises(GenesisAuthError) as info:
        client.metadata_table("12411-0015")
    assert route.call_count == 1
    assert info.value.http_status == 401 and info.value.endpoint == "metadata/table"


@respx.mock
def test_transient_5xx_is_retried_then_a_backend_error(tmp_path: Path) -> None:
    route = respx.post(BASE + "helloworld/logincheck").mock(return_value=httpx.Response(503))
    with _client(tmp_path, DestatisCredentials(token=TOKEN)) as client, pytest.raises(GenesisBackendError, match="503"):
        client.logincheck()
    assert route.call_count == 5


@respx.mock
def test_whoami_and_qualitysigns_send_no_credentials(tmp_path: Path) -> None:
    whoami = respx.get(BASE + "helloworld/whoami").mock(return_value=httpx.Response(200, json={"User-Agent": "ua"}))
    signs = respx.get(BASE + "catalogue/qualitysigns").mock(return_value=httpx.Response(200, json=QUALITYSIGNS))
    with _client(tmp_path, DestatisCredentials(token=TOKEN)) as client:
        assert client.whoami().user_agent == "ua"
        legend = client.qualitysigns()
    assert isinstance(legend, GenesisEnvelope) and legend.parameter == {"language": "de"}
    for route in (whoami, signs):
        headers = route.calls.last.request.headers
        assert "username" not in headers and "password" not in headers
    assert dict(whoami.calls.last.request.url.params) == {}
    assert signs.calls.last.request.url.params["language"] == "de"


@respx.mock
def test_metadata_table_sends_name_and_language_only(tmp_path: Path) -> None:
    route = respx.post(BASE + "metadata/table").mock(return_value=httpx.Response(200, json=QUALITYSIGNS))
    with _client(tmp_path, DestatisCredentials(token=TOKEN)) as client:
        client.metadata_table("12411-0015")
    assert _form(route.calls.last.request) == {"name": ["12411-0015"], "language": ["de"]}


def test_unknown_operation_and_field_are_refused_before_the_wire(tmp_path: Path) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.post(BASE + "data/tablefile").mock(return_value=httpx.Response(200, content=b"PK\x03\x04"))
        with _client(tmp_path, DestatisCredentials(token=TOKEN)) as client:
            with pytest.raises(ValueError, match="Unknown GENESIS operation"):
                client.request("data/table", {})
            with pytest.raises(ValueError, match="regionalkeycode"):
                client.request("data/tablefile", {"name": "12411-0015", "regionalkeycode": "x"})
            zipped = client.call("data/tablefile", {"name": "12411-0015", "format": "ffcsv"})
        assert zipped.kind == "zip" and route.call_count == 1
        assert _form(route.calls.last.request) == {"name": ["12411-0015"], "format": ["ffcsv"], "language": ["de"]}


def test_missing_credentials_raise_before_any_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENESIS_TOKEN", TOKEN)  # the client never reads the environment
    with respx.mock(assert_all_called=False) as router:
        route = router.post(BASE + "helloworld/logincheck").mock(return_value=httpx.Response(200, json=OK_LOGIN))
        with _client(tmp_path) as client, pytest.raises(MissingCredentialsError, match="handle 'genesis'"):
            client.logincheck()
        assert route.call_count == 0


def test_credentials_of_one_host_never_reach_the_other(tmp_path: Path) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.post(REGIONALSTATISTIK.base_url + "helloworld/logincheck").mock(
            return_value=httpx.Response(200, json=OK_LOGIN)
        )
        with (
            GenesisClient(
                REGIONALSTATISTIK, DestatisCredentials(host="genesis", token=TOKEN), lock_dir=tmp_path
            ) as client,
            pytest.raises(WrongHostCredentialsError),
        ):
            client.logincheck()
        assert route.call_count == 0
        # By name works too.
        regional = DestatisCredentials(host="regionalstatistik", token=TOKEN)
        with GenesisClient("regionalstatistik", regional, lock_dir=tmp_path) as client:
            client.logincheck()
        assert route.calls.last.request.headers["username"] == TOKEN


@respx.mock
def test_raised_text_never_contains_credentials(tmp_path: Path) -> None:
    echo = {"Status": f"Neuer Text mit {TOKEN.upper()}", "Username": TOKEN}
    respx.post(BASE + "helloworld/logincheck").mock(return_value=httpx.Response(200, json=echo))
    with _client(tmp_path, DestatisCredentials(token=TOKEN)) as client, pytest.raises(GenesisUnknownEnvelope) as info:
        client.logincheck()
    for text in (str(info.value), repr(info.value), repr(info.value.status_block)):
        assert TOKEN.lower() not in text.lower()


def test_redirects_are_not_followed_with_credentials(tmp_path: Path) -> None:
    with respx.mock(assert_all_called=False) as router:
        stale = router.post(BASE + "helloworld/logincheck").mock(
            return_value=httpx.Response(307, headers={"location": "https://elsewhere.example.org/x"})
        )
        elsewhere = router.post("https://elsewhere.example.org/x").mock(return_value=httpx.Response(200, json=OK_LOGIN))
        with (
            _client(tmp_path, DestatisCredentials(token=TOKEN)) as client,
            pytest.raises(GenesisUnknownEnvelope, match="stale"),
        ):
            client.logincheck()
        assert stale.call_count == 1 and elsewhere.call_count == 0


def test_injected_client_cannot_re_enable_redirects(tmp_path: Path) -> None:
    with respx.mock(assert_all_called=False) as router:
        stale = router.post(BASE + "helloworld/logincheck").mock(
            return_value=httpx.Response(307, headers={"location": "https://elsewhere.example.org/x"})
        )
        elsewhere = router.post("https://elsewhere.example.org/x").mock(return_value=httpx.Response(200, json=OK_LOGIN))
        with httpx.Client(follow_redirects=True) as injected:
            client = GenesisClient(GENESIS_ONLINE, DestatisCredentials(token=TOKEN), client=injected, lock_dir=tmp_path)
            with pytest.raises(GenesisUnknownEnvelope, match="stale"):
                client.logincheck()
        assert stale.call_count == 1 and elsewhere.call_count == 0


@respx.mock
def test_guest_mode_sends_no_headers_only_when_allowed(tmp_path: Path) -> None:
    route = respx.post(BASE + "helloworld/logincheck").mock(return_value=httpx.Response(200, json=GAST_LOGIN))
    with _client(tmp_path, allow_guest=True) as client, pytest.raises(GenesisAuthError):
        client.logincheck()
    assert "username" not in route.calls.last.request.headers
    # Explicit credentials are sent even when guest mode is allowed.
    with (
        _client(tmp_path, DestatisCredentials(token=TOKEN), allow_guest=True) as client,
        pytest.raises(GenesisAuthError),
    ):
        client.logincheck()
    assert route.calls.last.request.headers["username"] == TOKEN


@respx.mock
def test_warning_log_is_redacted(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    warned = dict(QUALITYSIGNS, Status={"Code": 22, "Content": f"erfolgreich (angepasst: {TOKEN})", "Type": "Warnung"})
    respx.post(BASE + "metadata/table").mock(return_value=httpx.Response(200, json=warned))
    with _client(tmp_path, DestatisCredentials(token=TOKEN)) as client, caplog.at_level("WARNING"):
        client.metadata_table("12411-0015")
    assert "angepasst" in caplog.text and TOKEN not in caplog.text


def test_non_string_values_are_refused(tmp_path: Path) -> None:
    with _client(tmp_path, DestatisCredentials(token=TOKEN)) as client, pytest.raises(TypeError, match="'job'"):
        client.request("data/tablefile", {"name": "12411-0015", "job": False})  # type: ignore[dict-item]


@respx.mock
def test_language_is_in_every_request(tmp_path: Path) -> None:
    respx.get(BASE + "catalogue/qualitysigns").mock(return_value=httpx.Response(200, json=QUALITYSIGNS))
    respx.post(BASE + "helloworld/logincheck").mock(return_value=httpx.Response(200, json=OK_LOGIN))
    respx.post(BASE + "metadata/table").mock(return_value=httpx.Response(200, json=QUALITYSIGNS))
    with _client(tmp_path, DestatisCredentials(token=TOKEN)) as client:
        client.qualitysigns()
        client.logincheck()
        client.metadata_table("12411-0015")
    for call in respx.calls:
        request = call.request
        sent = request.url.params.get("language") if request.method == "GET" else _form(request)["language"][0]
        assert sent == "de"


@respx.mock
def test_two_threads_serialize_under_the_process_lock(tmp_path: Path) -> None:
    windows: list[tuple[float, float]] = []
    held: list[bool] = []

    def slow(request: httpx.Request) -> httpx.Response:
        held.append(_process_lock(GENESIS_ONLINE).locked())
        start = time.monotonic()
        time.sleep(0.15)
        windows.append((start, time.monotonic()))
        return httpx.Response(200, json=OK_LOGIN)

    respx.post(BASE + "helloworld/logincheck").mock(side_effect=slow)
    with _client(tmp_path, DestatisCredentials(token=TOKEN)) as client:
        threads = [threading.Thread(target=client.logincheck) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert len(windows) == 2 and held == [True, True]
    (_, first_end), (second_start, _) = sorted(windows)
    assert first_end <= second_start, "requests overlapped"


@respx.mock
def test_lock_is_released_between_retry_attempts(tmp_path: Path) -> None:
    respx.post(BASE + "helloworld/logincheck").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=OK_LOGIN)]
    )
    client = _client(tmp_path, DestatisCredentials(token=TOKEN))
    seen: list[bool] = []
    original = client._serialized

    def observed() -> Any:
        seen.append(_process_lock(GENESIS_ONLINE).locked())
        return original()

    client._serialized = observed  # type: ignore[method-assign]
    client.logincheck()
    assert seen == [False, False], "the lock was still held when the next attempt started"


def test_file_lock_blocks_another_process(tmp_path: Path) -> None:
    client = _client(tmp_path, DestatisCredentials(token=TOKEN))
    probe = (
        "import sys; from filelock import FileLock, Timeout\n"
        "try:\n"
        "    with FileLock(sys.argv[1], timeout=0.3): print('acquired')\n"
        "except Timeout: print('blocked')\n"
    )
    with client._serialized():
        held = subprocess.run(
            [sys.executable, "-c", probe, str(client.lock_path)], capture_output=True, text=True, check=True
        )
    free = subprocess.run(
        [sys.executable, "-c", probe, str(client.lock_path)], capture_output=True, text=True, check=True
    )
    assert held.stdout.strip() == "blocked"
    assert free.stdout.strip() == "acquired"


def test_stuck_lock_holder_fails_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mloda_plugin_govdata.feature_groups.destatis.core.api.LOCK_TIMEOUT_SECONDS", 0.2)
    client = _client(tmp_path, DestatisCredentials(token=TOKEN))
    client.lock_path.parent.mkdir(parents=True, exist_ok=True)
    holder = FileLock(str(client.lock_path))
    holder.acquire()
    try:
        with pytest.raises(GenesisBackendError, match="held the GENESIS lock"), client._serialized():
            pass
    finally:
        holder.release()
