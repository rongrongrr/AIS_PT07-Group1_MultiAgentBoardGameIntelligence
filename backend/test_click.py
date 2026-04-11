#!/usr/bin/env python3
"""Quick test: verify Socket.IO emit works for chooseTiles + placeTiles."""
import asyncio, sys, time
sys.path.insert(0, ".")
from playwright.async_api import async_playwright
from base64 import b64encode
from app.engine.state_parser import parse_socketio_message, parse_game_state_from_event

INIT = """(function(){let _io;try{Object.defineProperty(window,'io',{configurable:true,get(){return _io;},set(v){_io=v;if(v&&typeof v.connect==='function'){const o=v.connect.bind(v);v.connect=function(){const s=o.apply(v,arguments);window.__tiles_socket=s;return s;};}}});}catch(e){}})();"""

async def main():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(viewport={"width":1280,"height":900})
    page = await ctx.new_page()

    ws_frames = []
    def on_ws(ws):
        ws.on("framereceived", lambda d: ws_frames.append(d))
    page.on("websocket", on_ws)
    await page.add_init_script(INIT)

    room = "emit-test-1"
    name = "EmitBot"

    # Join
    await page.goto(f"https://buddyboardgames.com/azul?name={b64encode(name.encode()).decode()}")
    await page.wait_for_timeout(2000)
    await page.fill("#room", room)
    await page.click("#start-game")
    await page.wait_for_timeout(3000)
    btn = await page.query_selector("#start-game-lobby")
    if btn: await btn.click()
    await page.wait_for_timeout(3000)

    # Wait for auto-deal — check if tiles appeared
    tiles = await page.evaluate("""()=>{
        let c=0;
        document.querySelectorAll('.factory .tile[tilecolor]').forEach(t=>{
            if(t.getAttribute('tilecolor')!=='dummy')c++;
        });
        return c;
    }""")
    print(f"Tiles after startGame (no manual deal): {tiles}")

    # Check if dealTiles was already emitted by client JS
    for d in ws_frames:
        p = parse_socketio_message(d)
        if p and "dealTiles" in str(p):
            print(f"  Found dealTiles in WS frames!")

    if tiles == 0:
        # Need to deal manually
        print("No tiles, dealing manually...")
        await page.evaluate(f"""()=>{{
            window.__tiles_socket.emit('takeTurn',{{
                room:'{room}',player:'{name}',gameName:'azul',turnType:'dealTiles'
            }});
        }}""")
        await page.wait_for_timeout(3000)
        tiles = await page.evaluate("""()=>{
            let c=0;
            document.querySelectorAll('.factory .tile[tilecolor]').forEach(t=>{
                if(t.getAttribute('tilecolor')!=='dummy')c++;
            });
            return c;
        }""")
        print(f"Tiles after manual deal: {tiles}")

    # Get the room name and player name as the platform knows them
    room_name = await page.evaluate("()=>document.querySelector('#azul-room-name-text')?.textContent?.trim()||''")
    player_name = await page.evaluate("()=>document.querySelector('#me-info-name')?.textContent?.trim()||''")
    print(f"Room: '{room_name}', Player: '{player_name}'")

    # Read a factory tile color
    first_tile = await page.evaluate("""()=>{
        const t = document.querySelector('#factory-0 .tile[tilecolor]');
        return t ? t.getAttribute('tilecolor') : null;
    }""")
    print(f"\nFirst tile in factory 0: {first_tile}")

    # === Test chooseTiles via socket emit ===
    print(f"\n--- chooseTiles: factory=0, color={first_tile} ---")
    result = await page.evaluate(
        """([factory, tileType]) => {
            const socket = window.__tiles_socket;
            if (!socket) return 'no_socket';
            const room = document.querySelector('#azul-room-name-text')?.textContent?.trim();
            const player = document.querySelector('#me-info-name')?.textContent?.trim();
            socket.emit('takeTurn', {
                room, player, gameName: 'azul',
                turnType: 'chooseTiles', factory: factory, tileType: tileType
            });
            return 'emitted';
        }""",
        [0, first_tile],
    )
    print(f"  Emit result: {result}")
    await page.wait_for_timeout(2000)

    # Check response
    prompt = await page.evaluate("()=>document.body.innerText.includes('Select a row')")
    print(f"  'Select a row' prompt: {prompt}")

    # Check WS response
    for d in ws_frames[-5:]:
        p = parse_socketio_message(d)
        if p:
            evt, payload = p
            if evt == "takeTurnResponse":
                print(f"  WS Response: success={payload.get('success')} msg={payload.get('message','')[:100]}")

    if prompt:
        # === Test placeTiles ===
        print(f"\n--- placeTiles: patternLine=0 ---")
        await page.evaluate(
            """([patternLine]) => {
                const socket = window.__tiles_socket;
                const room = document.querySelector('#azul-room-name-text')?.textContent?.trim();
                const player = document.querySelector('#me-info-name')?.textContent?.trim();
                socket.emit('takeTurn', {
                    room, player, gameName: 'azul',
                    turnType: 'placeTiles', patternLine: patternLine
                });
            }""",
            [0],
        )
        await page.wait_for_timeout(2000)

        tiles_after = await page.evaluate("""()=>{
            let c=0;
            document.querySelectorAll('.factory .tile[tilecolor]').forEach(t=>{
                if(t.getAttribute('tilecolor')!=='dummy')c++;
            });
            return c;
        }""")
        score = await page.evaluate("()=>document.querySelector('#player-0-score')?.textContent||'?'")
        print(f"  Tiles after move: {tiles_after} (was {tiles})")
        print(f"  Score: {score}")
        print("\n  SUCCESS! Full move completed via Socket.IO!")
    else:
        print("\n  chooseTiles not accepted. Checking error...")
        for d in ws_frames[-3:]:
            p = parse_socketio_message(d)
            if p:
                print(f"  WS: {p[0]} -> {str(p[1])[:200]}")

    await browser.close()
    await pw.stop()

asyncio.run(main())
