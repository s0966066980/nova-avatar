# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""An empty stage must not display a sample caption or unavailable board controls."""
import argparse
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base-url', default='http://localhost:3000')
args = parser.parse_args()
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    try:
        page = browser.new_page()
        page.goto(args.base_url, wait_until='domcontentloaded')
        page.get_by_role('button', name='啟動連線', exact=False).wait_for(timeout=10000)
        assert page.locator('.stage-captions-sub:visible').count() == 0, (
            'A new console displays a caption before any reply has played')
        print('PASS: no caption is visible before a reply has played')
        page.goto(args.base_url + '/stage.html', wait_until='domcontentloaded')
        page.locator('#boardReopen').wait_for(state='attached')
        assert not page.locator('#boardReopen').is_visible(), (
            'The board button is visible even though no board items exist')
        print('PASS: an empty stage hides the board button')
    finally:
        browser.close()
