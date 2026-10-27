# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Verify generated English board content and a live voice change."""
import asyncio
import json
from playwright.async_api import async_playwright
from verify_ui import INIT, BASE, OUT, post, sessions, wait_event

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path='/snap/chromium/current/usr/lib/chromium-browser/chrome',
            headless=True, args=['--no-sandbox', '--autoplay-policy=no-user-gesture-required'])
        try:
            context = await browser.new_context(ignore_https_errors=True, viewport={'width':900,'height':1100})
            await context.add_init_script(INIT)
            page = await context.new_page()
            await page.goto(BASE+'/stage.html', wait_until='domcontentloaded')
            async with page.expect_response(lambda r:r.url.endswith('/offer'), timeout=90000) as pending:
                await page.locator('#entryLanguages [data-locale="en-US"]').click()
            sessionid = (await (await pending.value).json())['sessionid']
            await page.wait_for_function("window.probeEvents.some(e=>e.type==='state'&&e.state==='listening')", timeout=90000)
            changed = await post(page, f'/api/conversations/{sessionid}', {'voice_en_us':'en-US-AriaNeural'})
            assert changed['data']['voice_en_us'] == 'en-US-AriaNeural'
            count = await page.evaluate('window.probeEvents.length')
            await post(page, '/human', {'sessionid':sessionid,'type':'chat','text':'Show a board with three deployment steps for Nova Avatar, with a short explanation for each step.','interrupt':False})
            board = await wait_event(page, 'board_end', after=count)
            commit = await wait_event(page, 'turn_committed', after=count)
            items = await page.locator('#boardList').inner_text()
            assert items.strip(), items
            assert not any('\u4e00' <= c <= '\u9fff' for c in items), items
            assert not any('\u4e00' <= c <= '\u9fff' for c in commit['played_text']), commit
            await page.screenshot(path=str(OUT/'english-board.png'))
            (OUT/'english-board-results.json').write_text(json.dumps({
                'passed':True, 'voice':'en-US-AriaNeural','board':board,'items':items,
                'commit':commit,'session':(await sessions(page))['sessions'],
            }, ensure_ascii=False, indent=2)+'\n')
            print(items, commit['played_text'], flush=True)
            console = await context.new_page()
            await console.goto(BASE, wait_until='domcontentloaded')
            await console.locator(f'.conversation-heading option[value="{sessionid}"]').wait_for(state='attached')
            await console.locator('.conversation-heading select').select_option(str(sessionid))
            await console.locator('.conversation-panel summary').click()
            await console.get_by_role('button', name='清空此場次記憶與看板', exact=True).click()
            await console.locator('.conversation-feedback').filter(has_text='已清空此場次').wait_for()
            current = next(s for s in (await sessions(console))['sessions'] if s['sessionid']==sessionid)
            assert current['memory']['retained_messages'] == 0, current
            await page.wait_for_function("document.querySelector('#boardList').innerText.trim()===''")
            (OUT/'clear-session-results.json').write_text(json.dumps({'passed':True, 'session':current}, ensure_ascii=False, indent=2)+'\n')
            print('targeted clear passed', flush=True)
        finally:
            await browser.close()

asyncio.run(main())
