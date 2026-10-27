# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Connect two silent microphones without exercising ASR or reply playback."""
import asyncio
from playwright.async_api import async_playwright
from verify_ui import INIT, BASE

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path='/snap/chromium/current/usr/lib/chromium-browser/chrome',
            headless=True, args=['--no-sandbox', '--autoplay-policy=no-user-gesture-required'])
        try:
            for locale in ('zh-TW', 'en-US'):
                context = await browser.new_context(ignore_https_errors=True)
                await context.add_init_script(INIT)
                page = await context.new_page()
                await page.goto(BASE+'/stage.html', wait_until='domcontentloaded')
                await page.locator(f'#entryLanguages [data-locale="{locale}"]').click()
                await page.wait_for_function("window.probePC?.connectionState==='connected'", timeout=90000)
                print('connected', locale, flush=True)
            await asyncio.sleep(20)
            response = await page.request.get(BASE+'/api/conversations')
            print('healthy', response.status, flush=True)
            assert response.ok
        finally:
            await browser.close()

asyncio.run(main())
