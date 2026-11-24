"""capture_genesis_fixtures.py: argument parsing, redaction, and the live-host call, mocked."""

import hashlib
import io
import json
import zipfile
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
import respx

from mloda_plugin_govdata.feature_groups.destatis.core.api import GenesisClient
from mloda_plugin_govdata.feature_groups.destatis.core.auth import ENV_SUFFIXES
from mloda_plugin_govdata.feature_groups.destatis.core.hosts import GENESIS_ONLINE, KNOWN_HOSTS
from mloda_plugin_govdata.feature_groups.destatis.core.redact import REDACTED
from scripts.capture_genesis_fixtures import _leaks, _parse_pairs, _write, capture, main

_CREDENTIAL_ENV_VARS = tuple(host.env_var(suffix) for host in KNOWN_HOSTS.values() for suffix in ENV_SUFFIXES)


@pytest.fixture(autouse=True)
def _instant_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mloda_plugin_govdata.feature_groups.govdata.core.client._BASE_WAIT", lambda _state: 0.0)


def _client(tmp_path: Path) -> GenesisClient:
    return GenesisClient(GENESIS_ONLINE, None, lock_dir=tmp_path)


def _zip(member: str = "data.csv", text: str = "", comment: bytes = b"", encoding: str = "utf-8") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.comment = comment
        rows = "Statistik_Code;Zeit;Wert\n" * 50 + text + "12411;2022;84358845\n" * 50
        archive.writestr(member, rows.encode(encoding))
    return buffer.getvalue()


# --- argument parsing --------------------------------------------------------------------------


def test_parse_pairs_builds_a_dict() -> None:
    assert _parse_pairs(["name=12411-0015", "format=ffcsv"]) == {"name": "12411-0015", "format": "ffcsv"}


@pytest.mark.parametrize("pair", ["badpair", "=ffcsv"])
def test_parse_pairs_rejects_a_malformed_pair(pair: str) -> None:
    with pytest.raises(SystemExit, match="--tablefile expects key=value"):
        _parse_pairs([pair])


def test_unknown_host_choice_is_rejected_by_argparse(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--host", "not-a-host", "--out", str(tmp_path)])
    assert excinfo.value.code == 2


def test_missing_out_is_rejected_by_argparse() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


@respx.mock
def test_no_credentials_and_not_guest_exits_with_a_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # respx with no routes registered: any accidental request past this early return raises
    # instead of silently reaching the network.
    for var in _CREDENTIAL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    assert main(["--out", str(tmp_path)]) == 2
    assert "no credentials for genesis" in capsys.readouterr().err


# --- _write: the redaction safety net ----------------------------------------------------------


@pytest.mark.parametrize("data", [b'{"ok": true}', _zip()], ids=["json", "deflated-zip"])
def test_write_returns_the_sha256_when_no_secret_survives(tmp_path: Path, data: bytes) -> None:
    sha = _write(tmp_path, "fixture.bin", data, ["sub-token"])
    assert sha == hashlib.sha256(data).hexdigest()
    assert (tmp_path / "fixture.bin").read_bytes() == data


@pytest.mark.parametrize("data", [b"anything at all, even a fake secret-looking string", b"PK\x03\x04 not a zip"])
def test_write_with_no_secrets_never_flags_anything(tmp_path: Path, data: bytes) -> None:
    # --guest mode: secrets is empty, so the safety net is vacuously off, even for an unreadable zip.
    sha = _write(tmp_path, "fixture.txt", data, [])
    assert sha == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    ("data", "match"),
    [
        ("leaked: p ss+w/rdö".encode(), "redaction failed"),  # the plain secret, as sent
        # fully URL-encoded (%20/%2B/%2F), as it can appear on the wire
        (f"leaked: {quote('p ss+w/rdö', safe='')}".encode(), "redaction failed"),
        (b"PK\x03\x04 truncated archive", "cannot inspect zip"),  # unreadable zip: fail closed
        (_zip(text="p ss+w/rdö;2022;1\n", encoding="latin-1"), "redaction failed"),  # non-ASCII, latin-1
    ],
    ids=["plain", "url-encoded", "bad-zip", "latin-1-member"],
)
def test_write_fails_loudly_and_writes_nothing_if_a_secret_variant_survives(
    tmp_path: Path, data: bytes, match: str
) -> None:
    with pytest.raises(SystemExit, match=match):
        _write(tmp_path, "fixture.txt", data, ["p ss+w/rdö"])
    assert not (tmp_path / "fixture.txt").exists()


# --- capture: body branches, over a mocked host -----------------------------------------------


@respx.mock
def test_capture_redacts_a_json_body_before_writing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    respx.get(GENESIS_ONLINE.base_url + "helloworld/whoami").mock(
        return_value=httpx.Response(200, json={"User-Agent": "sub-token"})
    )
    with _client(tmp_path) as client:
        capture(client, "helloworld/whoami", {}, tmp_path, "whoami", ["sub-token"])
    assert json.loads((tmp_path / "whoami.json").read_text(encoding="utf-8")) == {"User-Agent": REDACTED}
    assert "whoami.json: HTTP 200, json" in capsys.readouterr().out


@respx.mock
def test_capture_redacts_a_text_body_before_writing(tmp_path: Path) -> None:
    respx.get(GENESIS_ONLINE.base_url + "helloworld/whoami").mock(
        return_value=httpx.Response(
            200, content=b"plain text with sub-token inside", headers={"content-type": "text/plain"}
        )
    )
    with _client(tmp_path) as client:
        capture(client, "helloworld/whoami", {}, tmp_path, "whoami", ["sub-token"])
    written = (tmp_path / "whoami.txt").read_text(encoding="utf-8")
    assert written == f"plain text with {REDACTED} inside"


@pytest.mark.parametrize(
    "body",
    [
        b"PK\x03\x04" + b"leaked sub-token inside the archive bytes",
        _zip(text="leaked sub-token;2022;1\n"),
        _zip(member="sub-token.csv"),
        _zip(comment=b"sub-token"),
    ],
    ids=["raw", "deflated-member", "member-name", "zip-comment"],
)
@respx.mock
def test_capture_fails_loudly_when_a_secret_survives_in_the_unredacted_zip_body(tmp_path: Path, body: bytes) -> None:
    # The zip branch skips redact_json/redact_text; _write scans the raw bytes and every unpacked member.
    respx.get(GENESIS_ONLINE.base_url + "helloworld/whoami").mock(
        return_value=httpx.Response(200, content=body, headers={"content-type": "application/octet-stream"})
    )
    with _client(tmp_path) as client, pytest.raises(SystemExit, match="redaction failed"):
        capture(client, "helloworld/whoami", {}, tmp_path, "whoami", ["sub-token"])
    assert not (tmp_path / "whoami.zip").exists()
    assert not (tmp_path / "NOTICE").exists()


def test_deflated_member_hides_the_secret_from_a_raw_scan() -> None:
    # Guards the deflated-member case above: it must exercise unpacking, not the raw scan.
    assert not _leaks(_zip(text="leaked sub-token;2022;1\n"), ["sub-token"])


@respx.mock
def test_capture_does_not_write_on_a_redirect(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Credentials are not sent across redirects (a stale base URL); nothing is captured either.
    respx.get(GENESIS_ONLINE.base_url + "helloworld/whoami").mock(
        return_value=httpx.Response(307, headers={"location": "https://example.org/"})
    )
    with _client(tmp_path) as client:
        capture(client, "helloworld/whoami", {}, tmp_path, "whoami", ["sub-token"])
    assert not any(path.suffix != ".lock" for path in tmp_path.iterdir())
    assert "not captured" in capsys.readouterr().out
