# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The backend serves only the built frontend, same-origin with its API."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from src.server import server
from src.server.server import FrontendNotBuilt, create_app, require_frontend
from src.utils.paths import PROJECT_ROOT
from tests.access_helpers import LAN_ADDRESS, access_client, built_frontend


def test_default_frontend_is_the_absolute_vite_build_directory():
    assert server.FRONTEND_DIST == PROJECT_ROOT / "web" / "dist"
    assert server.FRONTEND_DIST.is_absolute()


def test_missing_build_fails_instead_of_serving_the_web_source_tree(tmp_path):
    with pytest.raises(FrontendNotBuilt, match="npm run build"):
        require_frontend(tmp_path / "dist")
    with pytest.raises(FrontendNotBuilt):
        create_app(admin_env_path=tmp_path / "admin.env", frontend_dir=tmp_path / "dist")


def test_lan_visitor_gets_the_console_page_and_nothing_outside_the_build():
    async def run():
        async with access_client(admin=False, remote=LAN_ADDRESS) as client:
            index = await client.get("/")
            assert index.status == 200
            assert "nova-console" in await index.text()
            stage = await client.get("/stage.html")
            assert stage.status == 200
            assert "nova-stage" in await stage.text()
            for path in ("/logs/frontend.log", "/vite.config.js", "/package.json", "/src/main.js"):
                response = await client.get(path)
                assert response.status == 404, (path, response.status)
    asyncio.run(run())


def test_built_frontend_helper_emits_both_entry_pages():
    root = built_frontend()
    assert (root / "index.html").is_file()
    assert (root / "stage.html").is_file()


def test_vite_build_emits_the_stage_page():
    config = (PROJECT_ROOT / "web" / "vite.config.js").read_text(encoding="utf-8")
    assert 'stage: path.resolve(__dirname, "stage.html")' in config


def test_vite_dev_server_binds_loopback_by_default():
    config = (PROJECT_ROOT / "web" / "vite.config.js").read_text(encoding="utf-8")
    assert "let webHost = '127.0.0.1'" in config
    assert "'0.0.0.0'" not in config
    for name in Path(PROJECT_ROOT / "config").glob("config*.yaml"):
        text = name.read_text(encoding="utf-8")
        assert "host: 0.0.0.0" not in text.split("web:", 1)[-1].split("\n\n", 1)[0], name


def test_web_logs_are_ignored_by_git():
    result = subprocess.run(
        ["git", "check-ignore", "-q", "web/logs/frontend.log"],
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert result.returncode == 0
