# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "create_ssl_certs.sh"


def _run_ssl_script(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        env=merged_env,
        capture_output=True,
        text=True,
        check=False,
    )


def _cert_text(cert_path: Path) -> str:
    result = subprocess.run(
        ["openssl", "x509", "-in", str(cert_path), "-noout", "-text"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_openssl_fallback_generates_root_ca_and_multi_san_cert(tmp_path: Path):
    cert_path = tmp_path / "server.crt"
    key_path = tmp_path / "server.key"

    res = _run_ssl_script(
        [
            "--no-auto",
            "--backend",
            "openssl",
            "--cert",
            str(cert_path),
            "--key",
            str(key_path),
            "192.168.1.50",
            "orin.local",
        ],
        env={"NOVA_SSL_HOSTS": "100.64.0.10,orin.tailnet.ts.net"},
    )
    assert res.returncode == 0, res.stderr

    ca_pem = tmp_path / "rootCA.pem"
    ca_crt = tmp_path / "rootCA.crt"
    ca_key = tmp_path / "rootCA-key.pem"
    assert cert_path.is_file()
    assert key_path.is_file()
    assert ca_pem.is_file()
    assert ca_crt.is_file()
    assert ca_key.is_file()
    assert ca_pem.read_bytes() == ca_crt.read_bytes()
    assert not list(tmp_path.glob("*.srl"))

    verify = subprocess.run(
        ["openssl", "verify", "-CAfile", str(ca_pem), str(cert_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify.returncode == 0, verify.stderr + verify.stdout

    ca_text = _cert_text(ca_pem)
    assert "CA:TRUE" in ca_text

    leaf_text = _cert_text(cert_path)
    assert "CA:FALSE" in leaf_text
    assert "TLS Web Server Authentication" in leaf_text
    for expected_san in (
        "DNS:localhost",
        "IP Address:127.0.0.1",
        "IP Address:192.168.1.50",
        "DNS:orin.local",
        "IP Address:100.64.0.10",
        "DNS:orin.tailnet.ts.net",
    ):
        assert expected_san in leaf_text


def _write_fake_bin(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def test_auto_detects_lan_mdns_and_tailscale_self_only(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_bin(
        fake_bin,
        "hostname",
        'if [[ "${1:-}" == "-s" ]]; then echo "jetson-orin"; else echo "jetson-orin"; fi',
    )
    _write_fake_bin(
        fake_bin,
        "ip",
        """cat <<'EOF'
2: eth0    inet 192.168.10.42/24 brd 192.168.10.255 scope global eth0
3: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0
4: br-abc123    inet 172.18.0.1/16 brd 172.18.255.255 scope global br-abc123
EOF""",
    )
    _write_fake_bin(
        fake_bin,
        "tailscale",
        """if [[ "${1:-}" == "ip" ]]; then
  echo "100.101.102.103"
elif [[ "${1:-}" == "status" ]]; then
  cat <<'EOF'
{
  "Peer": {
    "nodekey:123": { "DNSName": "laptop.tailnet-abc.ts.net." }
  },
  "Self": {
    "DNSName": "jetson-orin.tailnet-abc.ts.net."
  }
}
EOF
fi""",
    )

    cert_path = tmp_path / "out" / "localhost.crt"
    key_path = tmp_path / "out" / "localhost.key"
    res = _run_ssl_script(
        ["--backend", "openssl", "--cert", str(cert_path), "--key", str(key_path)],
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )
    assert res.returncode == 0, res.stderr

    leaf_text = _cert_text(cert_path)
    for expected in (
        "DNS:localhost",
        "IP Address:127.0.0.1",
        "DNS:jetson-orin.local",
        "IP Address:192.168.10.42",
        "IP Address:100.101.102.103",
        "DNS:jetson-orin.tailnet-abc.ts.net",
    ):
        assert expected in leaf_text

    assert "172.17.0.1" not in leaf_text
    assert "172.18.0.1" not in leaf_text
    assert "laptop.tailnet-abc.ts.net" not in leaf_text


def test_reuses_existing_root_ca_by_default_and_rotates_with_force_ca(tmp_path: Path):
    cert_path = tmp_path / "localhost.crt"
    key_path = tmp_path / "localhost.key"
    ca_pem = tmp_path / "rootCA.pem"

    first = _run_ssl_script(
        ["--no-auto", "--backend", "openssl", "--cert", str(cert_path), "--key", str(key_path)]
    )
    assert first.returncode == 0, first.stderr
    first_ca_bytes = ca_pem.read_bytes()

    second = _run_ssl_script(
        [
            "--no-auto",
            "--backend",
            "openssl",
            "--cert",
            str(cert_path),
            "--key",
            str(key_path),
            "192.168.1.99",
        ]
    )
    assert second.returncode == 0, second.stderr
    assert ca_pem.read_bytes() == first_ca_bytes
    assert "IP Address:192.168.1.99" in _cert_text(cert_path)

    rotated = _run_ssl_script(
        [
            "--no-auto",
            "--force-ca",
            "--backend",
            "openssl",
            "--cert",
            str(cert_path),
            "--key",
            str(key_path),
        ]
    )
    assert rotated.returncode == 0, rotated.stderr
    assert ca_pem.read_bytes() != first_ca_bytes


def test_prefers_mkcert_when_available_and_exports_root_ca(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    caroot = tmp_path / "mkcert-caroot"
    caroot.mkdir()
    (caroot / "rootCA.pem").write_text("FAKE-MKCERT-ROOT-CA", encoding="utf-8")
    invocations = tmp_path / "mkcert.log"

    _write_fake_bin(
        fake_bin,
        "mkcert",
        f"""echo "$*" >> "{invocations}"
if [[ "${{1:-}}" == "-CAROOT" ]]; then
  echo "{caroot}"
  exit 0
fi
if [[ "${{1:-}}" == "-install" ]]; then
  exit 0
fi
cert=""
key=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -cert-file) cert="$2"; shift 2 ;;
    -key-file) key="$2"; shift 2 ;;
    *) shift ;;
  esac
done
echo "CERT" > "$cert"
echo "KEY" > "$key"
""",
    )

    cert_path = tmp_path / "certs" / "server.crt"
    key_path = tmp_path / "certs" / "server.key"
    res = _run_ssl_script(
        ["--no-auto", "--cert", str(cert_path), "--key", str(key_path), "192.168.1.88"],
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )
    assert res.returncode == 0, res.stderr
    assert cert_path.read_text(encoding="utf-8").strip() == "CERT"
    assert key_path.read_text(encoding="utf-8").strip() == "KEY"
    assert (tmp_path / "certs" / "rootCA.pem").read_text(encoding="utf-8") == "FAKE-MKCERT-ROOT-CA"
    assert (tmp_path / "certs" / "rootCA.crt").read_text(encoding="utf-8") == "FAKE-MKCERT-ROOT-CA"
    log_text = invocations.read_text(encoding="utf-8")
    assert "-cert-file" in log_text
    assert "192.168.1.88" in log_text


def test_gitignore_excludes_generated_ssl_and_ca_artifacts():
    sample_paths = [
        "ssl_certs/localhost.crt",
        "ssl_certs/localhost.key",
        "ssl_certs/server.crt",
        "ssl_certs/server.key",
        "ssl_certs/rootCA.pem",
        "ssl_certs/rootCA.crt",
        "ssl_certs/rootCA-key.pem",
        "ssl_certs/rootCA.cer",
        "ssl_certs/rootCA.der",
        "ssl_certs/rootCA.p12",
        "ssl_certs/rootCA.srl",
    ]
    res = subprocess.run(
        ["git", "check-ignore", "--no-index", *sample_paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    ignored = set(res.stdout.splitlines())
    missing = [path for path in sample_paths if path not in ignored]
    assert not missing, f"Paths not ignored by .gitignore: {missing}"

    tracked = subprocess.run(
        ["git", "ls-files", "ssl_certs/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_files = tracked.stdout.splitlines()
    assert tracked_files == ["ssl_certs/put ssl_certs here.txt"]


def test_device_trust_doc_covers_windows_macos_ios_and_android():
    doc = ROOT / "docs" / "https-device-trust.md"
    assert doc.is_file(), "Missing docs/https-device-trust.md"
    text = doc.read_text(encoding="utf-8")
    for required in (
        "SPDX-License-Identifier: Apache-2.0",
        "rootCA.pem",
        "rootCA.crt",
        "Windows",
        "macOS",
        "iOS",
        "描述檔",
        "憑證信任設定",
        "Android",
    ):
        assert required in text, f"docs/https-device-trust.md missing {required!r}"
