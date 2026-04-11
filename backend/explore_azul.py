"""
Azul Board Game DOM Explorer
=============================
Explores https://buddyboardgames.com/azul to map out DOM selectors
for automation. Takes screenshots and dumps HTML structure.

FINDINGS REPORT (completed 2026-04-05)
=========================================

ARCHITECTURE:
  - NOT a React/Vue/Next.js app. Plain server-rendered HTML + jQuery/Bootstrap.
  - Uses Socket.IO v4 (EIO=4) over WebSocket (wss://buddyboardgames.com/socket.io/)
  - Game JS loaded from: /js/azul.js?v=81
  - Styles from: /stylesheets/azul.less?v=81
  - Global `window.io` is available (Socket.IO client).
  - No React fiber, no SPA root (#root, #app, #__next).

LOBBY / PRE-GAME SELECTORS:
  - Player name input:    #player  (input.form-control, placeholder="Your name", maxlength=16)
  - Room name input:      #room    (input.form-control, placeholder="Room name (ex: fun-1)", maxlength=20)
  - "Play Azul" button:   #start-game  (creates or joins room -- triggers joinRoom then createRoom via WS)
  - Start game (lobby):   #start-game-lobby  (visible once in lobby, hidden with d-none initially)
  - Invite buddy button:  #invite-buddy-lobby
  - Play with Buddy:      #play-with-buddy-button  (premium feature)
  - Start demo:           #start-game-demo  (hidden, for demo mode)
  - Room name display:    #azul-room-name-text  (shows current room name after joining)
  - Sharing link:         #sharing-link-field  (hidden input with base64-encoded room URL)
  - Lobby ribbon row:     #sharing-link-row  (.lobby-ribbon-row, visible when in lobby)

LOBBY vs IN-GAME STATE:
  - Lobby: #new-game-modal has class "modal show" (visible). After join: class becomes "modal" (hidden).
  - Lobby: #sharing-link-row visible (has .lobby-ribbon-row). In-game: gets .d-none added.
  - Lobby: #start-game-lobby visible. In-game: gets .d-none and disabled attribute.
  - In-game: factories, pattern lines, wall, floor are populated with tile elements.
  - The main game container is #game-container.

GAME ACTION BUTTONS (in-game):
  - Restart:       #restart-button
  - Leave:         #quit-button         (display:none when host)
  - End Game:      #end-game-button
  - Remove Player: #remove-player-button (premium, display:none)
  - Spectate:      #spectate-button      (premium)
  - Change Theme:  #change-theme-button  (premium)
  - Rematch:       button.rematch-button (after game over)
  - Confirm Remove: #confirm-remove-player
  - Yes/No:        #yes-btn, #no-btn     (confirmation dialogs)

GAME BOARD LAYOUT (inside #game-container):
  - Room info:       #room-info-row > #game-info-col > #room-name
  - Other players:   #other-players-row  (opponent boards shown here)
  - Factories:       #factories-row > .col > #factory-grid-container
  - Center pool:     #center-row
  - My pattern+wall: #me-pattern-and-wall > #me-pattern-lines + #me-wall
  - My floor:        #me-floor-and-bonuses > #floor-grid-container
  - My info/score:   #me-info  (class: .current-turn when it's your turn)
  - Score display:   #player-0-score (my score), #player-1-score, etc. (inside <span>)
  - Player name:     #me-info-name (my name in bold)
  - Bonus badges:    .bonus-badges-row with tooltips for H(orizontal), V(ertical), C(olor) bonuses

FACTORY SELECTORS:
  - Container:       #factory-grid-container
  - Factory row:     .factory-row  (class varies: .three-items for 1p, .five-items for 2p, etc.)
  - Individual factory: #factory-{N}  (N=0,1,2,... has attribute factoryid="{N}", class="factory")
  - Factory tiles:   #factory-{N}-tile-{M}  (class="tile {color} scale-in-center text-center", attr tilecolor="{color}")
  - For 1 player: 3 factories (factory-0 through factory-2)
  - For 2 players: 5 factories (factory-0 through factory-4)

CENTER POOL:
  - Row container:   #center-row
  - First player tile has class "firstPlayer" and tilecolor="firstPlayer"

TILE COLOR SYSTEM:
  - Colors represented as CSS classes AND a `tilecolor` attribute on each tile div.
  - 5 tile colors: blue, yellow, red, black, white
  - Special: "firstPlayer" (first-player marker), "dummy" (empty floor slot)
  - CSS class on .tile element: "tile {color} scale-in-center text-center"
  - tilecolor attribute: tilecolor="red", tilecolor="blue", etc.
  - Computed background colors:
      red    -> rgb(240, 128, 128) (light coral)
      blue   -> rgb(103, 192, 221) (sky blue)
      white  -> rgb(255, 255, 255)
      yellow -> rgb(255, 255, 89)
      black  -> rgb(144, 238, 144) (actually light green!)
      firstPlayer -> rgb(127, 255, 212) (aquamarine)

PATTERN LINES:
  - Container:       #pattern-lines-grid-container (my board)
  - Other player:    .other-player-pattern-lines-grid-container
  - Empty spacer:    .pattern-lines-null-grid-item
  - Tile slot:       .pattern-lines-tile-item  (+ color class when filled, + "selected" when has a tile)
  - Individual tile: #player-{P}-pattern-line-row-{R}-col-{C}  (attr row="{R}")
  - Row 0 = 1 slot, Row 1 = 2 slots, ... Row 4 = 5 slots
  - Filled tile has class: "pattern-lines-tile-item selected {color}"
  - Empty tile has class:  "pattern-lines-tile-item "

WALL GRID:
  - Container (my):  #me-wall > .wall-grid-container (implicit, tiles directly inside)
  - Other player:    .other-player-wall-grid-container
  - Individual tile: #player-{P}-wall-row-{R}-color-{color}
  - Wall tile class: "wall-tile-item {selected|unselected} {color}"
  - "selected" = tile placed on wall, "unselected" = empty slot
  - 5x5 grid, each row has: blue, yellow, red, black, white (shifted per row per Azul rules)

FLOOR LINE:
  - Container:       #floor-grid-container
  - Floor slot:      #player-{P}-floor-container-{N}  (.floor-grid-item)
  - Penalty display: .floor-grid-item-penalty  (text: -1, -1, -2, -2, -2, -3, -3)
  - Tile block:      .floor-grid-item-block
  - Floor tile:      #player-{P}-floor-tile-{N}  (class="tile {color} text-center", tilecolor="{color}")
  - Empty floor tile has tilecolor="dummy"
  - 7 floor slots (0-6)

PLAYER INFO:
  - My info:         #me-info  (.current-turn .align-middle)
  - My avatar:       #avatar-player-0  (.buddy-avatar .{animal} .edit)
  - My score:        #player-0-score
  - My name:         #me-info-name
  - Other player:    .other-player > .other-player-info > .other-player-info-text
  - Other score:     #player-{N}-score
  - Other avatar:    #avatar-player-{N}  (.buddy-avatar .{animal})

SOCKET.IO EVENT PROTOCOL:
  Socket.IO v4, message format: 42["eventName", {payload}]

  Room lifecycle:
    -> 42["joinRoom",     {"room":"X", "player":"Y", "gameName":"azul", "buddy":"raccoon"}]
    <- 42["joinRoomResponse", {"player":"Y", "success":bool, "message":"..."}]
       (If room doesn't exist, success=false, then client sends createRoom)
    -> 42["createRoom",   {"room":"X", "player":"Y", "gameName":"azul", "buddy":"lion"}]
    <- 42["createRoomResponse", {"success":true, "roomHost":"Y", "isPremium":false,
                                  "minPlayers":1, "maxPlayers":4, "muteAllSound":false}]

  Game lifecycle:
    -> 42["startGame",    {"room":"X", "player":"Y"}]
    <- 42["startGameResponse", {"success":true, "players":[...playerObjects...]}]
       (playerObject has: name, score, connected, buddy, isPremium, muteAllSound,
        patternLines{lines:[[{selected,color},...],...]}, wall{grid:[[{selected,color},...],...],
        bonuses:{horizontal:N,vertical:N,color:N}}, floorLine:[{color},...])

  Turn actions:
    -> 42["takeTurn",     {"room":"X", "player":"Y", "gameName":"azul", "turnType":"dealTiles"}]
    <- 42["takeTurnResponse", {"success":true, "game":{...fullGameState...}}]
       (game object has: _id, createdAt, room, players{}, factories[[]], center[],
        factorySize, numFactories, tilePool{}, currentPlayer, round, gameOver, etc.)

    Turn types observed: "dealTiles" (deal tiles to factories at round start)
    Expected turn types for gameplay: pick tiles from factory/center, place on pattern line

  Emotes:
    -> 42["emote",        {"room":"X", "player":"Y", "gameName":"azul", "emote":"greetings", "emoteIndex":1}]
    <- 42["emoteResponse",{"success":true, "player":"Y", "emote":"greetings", "emoteIndex":1}]

SCREENSHOTS SAVED:
  - azul_01_initial_load.png     (initial page with modal)
  - azul_02_filled_inputs.png    (name+room filled in)
  - azul_03_after_join.png       (lobby state after creating room)
  - azul_04_after_start.png      (game started, tiles dealt)
  - azul_05_game_board_full.png  (full page game board)

HTML DUMPS SAVED:
  - azul_01_initial.html
  - azul_03_after_join.html
  - azul_04_after_start.html

JSON FINDINGS:
  - azul_findings.json
"""

import asyncio
import json
import os
import time
from datetime import datetime
from playwright.async_api import async_playwright

SCREENSHOTS_DIR = "/Users/bravozheng/06_Coding/05_Claude/04_TILES/backend"
BASE_URL = "https://buddyboardgames.com/azul"
PLAYER_NAME = "Explorer1"
ROOM_NAME = "test-explore-1"


async def safe_screenshot(page, name, full_page=True):
    """Take a screenshot, handling errors gracefully."""
    path = os.path.join(SCREENSHOTS_DIR, f"azul_{name}.png")
    try:
        await page.screenshot(path=path, full_page=full_page)
        print(f"  [screenshot] Saved: {path}")
    except Exception as e:
        print(f"  [screenshot] Failed {name}: {e}")
    return path


async def dump_element_info(page, selector, label):
    """Dump info about elements matching a selector."""
    try:
        elements = await page.query_selector_all(selector)
        count = len(elements)
        print(f"\n  [{label}] Found {count} elements for selector: {selector}")
        for i, el in enumerate(elements[:10]):  # limit to first 10
            tag = await el.evaluate("el => el.tagName")
            classes = await el.evaluate("el => el.className")
            inner_text = await el.evaluate("el => el.innerText?.substring(0, 100) || ''")
            outer_html = await el.evaluate("el => el.outerHTML?.substring(0, 300) || ''")
            attrs = await el.evaluate("""el => {
                let result = {};
                for (let attr of el.attributes) {
                    result[attr.name] = attr.value;
                }
                return result;
            }""")
            print(f"    [{i}] <{tag}> class='{classes}' text='{inner_text[:60]}'")
            print(f"         attrs={json.dumps(attrs, indent=2)[:200]}")
            print(f"         html={outer_html[:250]}")
        return count
    except Exception as e:
        print(f"  [{label}] Error: {e}")
        return 0


async def explore_page_structure(page, stage_name):
    """Broadly explore the page DOM structure."""
    print(f"\n{'='*60}")
    print(f"EXPLORING STAGE: {stage_name}")
    print(f"{'='*60}")
    print(f"  URL: {page.url}")
    print(f"  Title: {await page.title()}")

    # Dump all top-level structure
    structure = await page.evaluate("""() => {
        function describeNode(el, depth) {
            if (depth > 4) return null;
            let result = {
                tag: el.tagName,
                id: el.id || undefined,
                class: el.className || undefined,
                childCount: el.children.length,
                text: el.children.length === 0 ? (el.innerText || '').substring(0, 80) : undefined
            };
            if (el.children.length > 0 && el.children.length < 30) {
                result.children = Array.from(el.children).map(c => describeNode(c, depth + 1)).filter(Boolean);
            }
            return result;
        }
        return describeNode(document.body, 0);
    }""")
    print(f"\n  DOM TREE (depth 4):")
    print(json.dumps(structure, indent=2, default=str)[:5000])

    # Look for common game-related selectors
    selectors_to_try = [
        # Inputs and buttons
        ("input[type='text']", "text inputs"),
        ("input[type='password']", "password inputs"),
        ("input", "all inputs"),
        ("button", "buttons"),
        ("a.btn, button.btn, .btn", "bootstrap-style buttons"),
        # Game elements
        (".factory, [class*='factory']", "factory elements"),
        (".tile, [class*='tile']", "tile elements"),
        (".board, [class*='board']", "board elements"),
        (".wall, [class*='wall']", "wall elements"),
        (".floor, [class*='floor']", "floor elements"),
        (".pattern, [class*='pattern']", "pattern line elements"),
        (".center, [class*='center']", "center pool elements"),
        (".score, [class*='score']", "score elements"),
        (".player, [class*='player']", "player elements"),
        (".lobby, [class*='lobby']", "lobby elements"),
        (".game, [class*='game']", "game elements"),
        (".room, [class*='room']", "room elements"),
        # React / framework hints
        ("[data-reactroot]", "React root"),
        ("#root, #app, #__next", "SPA roots"),
        ("[class*='MuiButton'], [class*='MuiInput']", "Material UI"),
        # Socket.IO
        ("[class*='socket']", "socket elements"),
    ]

    for selector, label in selectors_to_try:
        await dump_element_info(page, selector, label)


async def capture_network_info(page):
    """Set up network interception to capture Socket.IO events."""
    ws_messages = []
    xhr_requests = []

    def on_websocket(ws):
        print(f"\n  [WebSocket] Connected: {ws.url}")

        def on_frame_sent(payload):
            msg = str(payload)[:300]
            ws_messages.append({"direction": "sent", "data": msg})
            print(f"  [WS SENT] {msg[:150]}")

        def on_frame_received(payload):
            msg = str(payload)[:300]
            ws_messages.append({"direction": "received", "data": msg})
            print(f"  [WS RECV] {msg[:150]}")

        ws.on("framesent", on_frame_sent)
        ws.on("framereceived", on_frame_received)

    def on_request(request):
        url = request.url
        if "socket.io" in url or "azul" in url.lower():
            xhr_requests.append({"method": request.method, "url": url[:200]})
            print(f"  [HTTP] {request.method} {url[:150]}")

    page.on("websocket", on_websocket)
    page.on("request", on_request)

    return ws_messages, xhr_requests


async def try_find_and_fill(page, selectors, value, label):
    """Try multiple selectors to find and fill an input."""
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                is_visible = await el.is_visible()
                if is_visible:
                    await el.fill(value)
                    print(f"  [FILLED] {label} using selector: {sel} with value: {value}")
                    return sel
        except Exception as e:
            pass
    print(f"  [NOT FOUND] Could not find {label} with any selector")
    return None


async def try_find_and_click(page, selectors, label):
    """Try multiple selectors to find and click a button."""
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                is_visible = await el.is_visible()
                if is_visible:
                    await el.click()
                    print(f"  [CLICKED] {label} using selector: {sel}")
                    return sel
        except Exception as e:
            pass
    print(f"  [NOT FOUND] Could not click {label} with any selector")
    return None


async def dump_all_html(page, filename):
    """Dump the full page HTML to a file."""
    html = await page.content()
    path = os.path.join(SCREENSHOTS_DIR, filename)
    with open(path, "w") as f:
        f.write(html)
    print(f"  [HTML] Saved full page HTML to: {path}")
    return path


async def explore_game_elements_detailed(page):
    """Deep dive into game element structure once in-game."""
    print(f"\n{'='*60}")
    print("DETAILED GAME ELEMENT ANALYSIS")
    print(f"{'='*60}")

    # Get all unique class names on the page
    all_classes = await page.evaluate("""() => {
        let classes = new Set();
        document.querySelectorAll('*').forEach(el => {
            if (el.className && typeof el.className === 'string') {
                el.className.split(/\\s+/).forEach(c => { if (c) classes.add(c); });
            }
        });
        return Array.from(classes).sort();
    }""")
    print(f"\n  ALL CSS CLASSES ON PAGE ({len(all_classes)}):")
    print(f"  {json.dumps(all_classes, indent=2)[:3000]}")

    # Get all IDs on the page
    all_ids = await page.evaluate("""() => {
        let ids = [];
        document.querySelectorAll('[id]').forEach(el => {
            ids.push({id: el.id, tag: el.tagName, class: el.className?.substring(0, 80)});
        });
        return ids;
    }""")
    print(f"\n  ALL IDs ON PAGE ({len(all_ids)}):")
    print(f"  {json.dumps(all_ids, indent=2)[:2000]}")

    # Get all data attributes
    data_attrs = await page.evaluate("""() => {
        let attrs = new Set();
        document.querySelectorAll('*').forEach(el => {
            for (let attr of el.attributes) {
                if (attr.name.startsWith('data-')) {
                    attrs.add(attr.name + '=' + attr.value.substring(0, 50));
                }
            }
        });
        return Array.from(attrs).sort();
    }""")
    print(f"\n  ALL DATA ATTRIBUTES ({len(data_attrs)}):")
    print(f"  {json.dumps(data_attrs, indent=2)[:2000]}")

    # Analyze tile color representation
    tile_analysis = await page.evaluate("""() => {
        let tiles = document.querySelectorAll('[class*="tile"], [class*="Tile"]');
        let results = [];
        tiles.forEach((t, i) => {
            if (i < 20) {
                results.push({
                    tag: t.tagName,
                    class: t.className,
                    style: t.getAttribute('style') || '',
                    innerHTML: t.innerHTML.substring(0, 200),
                    outerHTML: t.outerHTML.substring(0, 300),
                    dataAttrs: Object.fromEntries(
                        Array.from(t.attributes)
                            .filter(a => a.name.startsWith('data-'))
                            .map(a => [a.name, a.value])
                    )
                });
            }
        });
        return results;
    }""")
    print(f"\n  TILE ANALYSIS ({len(tile_analysis)} tiles):")
    print(f"  {json.dumps(tile_analysis, indent=2)[:3000]}")

    # Analyze SVG elements (games sometimes use SVG)
    svg_count = await page.evaluate("() => document.querySelectorAll('svg').length")
    canvas_count = await page.evaluate("() => document.querySelectorAll('canvas').length")
    print(f"\n  SVG elements: {svg_count}, Canvas elements: {canvas_count}")

    # Look for game state in JavaScript
    game_state = await page.evaluate("""() => {
        // Check for common global state patterns
        let state = {};
        if (window.__NEXT_DATA__) state.__NEXT_DATA__ = 'found';
        if (window.__NUXT__) state.__NUXT__ = 'found';
        if (window.gameState) state.gameState = JSON.stringify(window.gameState).substring(0, 500);
        if (window.game) state.game = typeof window.game;
        if (window.socket) state.socket = typeof window.socket;
        if (window.io) state.io = typeof window.io;

        // Check for React fiber
        let root = document.getElementById('root') || document.getElementById('app') || document.getElementById('__next');
        if (root) {
            let fiberKey = Object.keys(root).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
            if (fiberKey) state.reactFiber = 'found';
        }

        return state;
    }""")
    print(f"\n  JAVASCRIPT GLOBAL STATE:")
    print(f"  {json.dumps(game_state, indent=2)}")


async def main():
    print(f"Azul DOM Explorer - Starting at {datetime.now()}")
    print(f"Target: {BASE_URL}")
    print(f"Screenshots dir: {SCREENSHOTS_DIR}")

    findings = {
        "selectors": {},
        "ws_messages": [],
        "xhr_requests": [],
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        # Set up network capture
        ws_messages, xhr_requests = await capture_network_info(page)

        # ============================================================
        # STAGE 1: Load the page
        # ============================================================
        print(f"\n{'#'*60}")
        print("STAGE 1: Loading page...")
        print(f"{'#'*60}")

        try:
            await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"  Warning: networkidle timeout, continuing... {e}")
            try:
                await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e2:
                print(f"  Error loading page: {e2}")
                await browser.close()
                return

        await page.wait_for_timeout(2000)
        await safe_screenshot(page, "01_initial_load")
        await dump_all_html(page, "azul_01_initial.html")
        await explore_page_structure(page, "Initial Load / Lobby")

        # ============================================================
        # STAGE 2: Fill in player name and room name
        # ============================================================
        print(f"\n{'#'*60}")
        print("STAGE 2: Filling in player/room info...")
        print(f"{'#'*60}")

        # Try various selectors for inputs
        name_selectors = [
            "input[placeholder*='name' i]",
            "input[placeholder*='player' i]",
            "input[placeholder*='Name' i]",
            "input[name*='name' i]",
            "input[name*='player' i]",
            "#playerName", "#player-name", "#name",
            "input:first-of-type",
            "input[type='text']:first-of-type",
        ]

        room_selectors = [
            "input[placeholder*='room' i]",
            "input[placeholder*='Room' i]",
            "input[name*='room' i]",
            "#roomName", "#room-name", "#room",
            "#roomId", "#room-id",
            "input[placeholder*='code' i]",
            "input:nth-of-type(2)",
            "input[type='text']:nth-of-type(2)",
        ]

        # First, let's enumerate all inputs to understand the form
        all_inputs = await page.query_selector_all("input")
        print(f"\n  Found {len(all_inputs)} input elements total:")
        for i, inp in enumerate(all_inputs):
            attrs = await inp.evaluate("""el => ({
                type: el.type, name: el.name, id: el.id,
                placeholder: el.placeholder, class: el.className,
                value: el.value, visible: el.offsetParent !== null
            })""")
            print(f"    Input[{i}]: {json.dumps(attrs)}")

        # Fill name
        name_sel = await try_find_and_fill(page, name_selectors, PLAYER_NAME, "Player Name")
        if name_sel:
            findings["selectors"]["player_name_input"] = name_sel

        await page.wait_for_timeout(500)

        # Fill room
        room_sel = await try_find_and_fill(page, room_selectors, ROOM_NAME, "Room Name")
        if room_sel:
            findings["selectors"]["room_name_input"] = room_sel

        await page.wait_for_timeout(500)
        await safe_screenshot(page, "02_filled_inputs")

        # ============================================================
        # STAGE 3: Click create/join button
        # ============================================================
        print(f"\n{'#'*60}")
        print("STAGE 3: Creating/joining room...")
        print(f"{'#'*60}")

        # Enumerate all buttons first
        all_buttons = await page.query_selector_all("button, input[type='submit'], a.btn, [role='button']")
        print(f"\n  Found {len(all_buttons)} button-like elements:")
        for i, btn in enumerate(all_buttons):
            info = await btn.evaluate("""el => ({
                tag: el.tagName, text: (el.innerText || el.value || '').substring(0, 50),
                class: el.className, id: el.id, type: el.type,
                visible: el.offsetParent !== null
            })""")
            print(f"    Button[{i}]: {json.dumps(info)}")

        join_selectors = [
            "button:has-text('Create')",
            "button:has-text('Join')",
            "button:has-text('Play')",
            "button:has-text('Start')",
            "button:has-text('Enter')",
            "button:has-text('Go')",
            "button[type='submit']",
            "input[type='submit']",
            "form button",
            ".btn-primary",
            "button.btn",
        ]

        join_sel = await try_find_and_click(page, join_selectors, "Create/Join Button")
        if join_sel:
            findings["selectors"]["create_join_button"] = join_sel

        await page.wait_for_timeout(3000)
        await safe_screenshot(page, "03_after_join")
        await dump_all_html(page, "azul_03_after_join.html")
        await explore_page_structure(page, "After Join/Create")

        # ============================================================
        # STAGE 4: Look for Start Game button (in lobby/waiting room)
        # ============================================================
        print(f"\n{'#'*60}")
        print("STAGE 4: Looking for start game / waiting room...")
        print(f"{'#'*60}")

        # Re-enumerate buttons after joining
        all_buttons = await page.query_selector_all("button, input[type='submit'], a.btn, [role='button']")
        print(f"\n  Found {len(all_buttons)} button-like elements after join:")
        for i, btn in enumerate(all_buttons):
            info = await btn.evaluate("""el => ({
                tag: el.tagName, text: (el.innerText || el.value || '').substring(0, 50),
                class: el.className, id: el.id,
                visible: el.offsetParent !== null
            })""")
            print(f"    Button[{i}]: {json.dumps(info)}")

        start_selectors = [
            "button:has-text('Start')",
            "button:has-text('Start Game')",
            "button:has-text('Begin')",
            "button:has-text('Play')",
            "#startGame", "#start-game",
            ".start-btn", ".start-game",
        ]

        start_sel = await try_find_and_click(page, start_selectors, "Start Game Button")
        if start_sel:
            findings["selectors"]["start_game_button"] = start_sel

        await page.wait_for_timeout(3000)
        await safe_screenshot(page, "04_after_start")
        await dump_all_html(page, "azul_04_after_start.html")

        # ============================================================
        # STAGE 5: Explore game board elements
        # ============================================================
        print(f"\n{'#'*60}")
        print("STAGE 5: Exploring game board elements...")
        print(f"{'#'*60}")

        await explore_page_structure(page, "In-Game Board")
        await explore_game_elements_detailed(page)

        # ============================================================
        # STAGE 6: Take final screenshots of different areas
        # ============================================================
        print(f"\n{'#'*60}")
        print("STAGE 6: Final screenshots and analysis...")
        print(f"{'#'*60}")

        await safe_screenshot(page, "05_game_board_full", full_page=True)

        # Try to get computed styles for tile colors
        color_info = await page.evaluate("""() => {
            let colorMap = {};
            let allEls = document.querySelectorAll('[class*="tile"], [class*="Tile"], [class*="color"], [class*="Color"]');
            allEls.forEach((el, i) => {
                if (i < 30) {
                    let style = getComputedStyle(el);
                    colorMap[el.className] = {
                        bg: style.backgroundColor,
                        color: style.color,
                        border: style.borderColor,
                        fill: style.fill,
                    };
                }
            });
            return colorMap;
        }""")
        print(f"\n  TILE COLOR COMPUTED STYLES:")
        print(f"  {json.dumps(color_info, indent=2)[:3000]}")

        # Store WS and XHR findings
        findings["ws_messages"] = ws_messages[-50:]  # last 50
        findings["xhr_requests"] = xhr_requests[-50:]

        # ============================================================
        # STAGE 7: Dump all collected findings
        # ============================================================
        print(f"\n{'#'*60}")
        print("STAGE 7: Summary of findings")
        print(f"{'#'*60}")

        print(f"\n  SELECTORS FOUND: {json.dumps(findings['selectors'], indent=2)}")
        print(f"\n  WS MESSAGES CAPTURED: {len(ws_messages)}")
        for msg in ws_messages[:20]:
            print(f"    {msg['direction']}: {msg['data'][:200]}")
        print(f"\n  XHR REQUESTS CAPTURED: {len(xhr_requests)}")
        for req in xhr_requests[:20]:
            print(f"    {req['method']} {req['url'][:200]}")

        # Save findings to JSON
        findings_path = os.path.join(SCREENSHOTS_DIR, "azul_findings.json")
        with open(findings_path, "w") as f:
            json.dump(findings, f, indent=2, default=str)
        print(f"\n  Findings saved to: {findings_path}")

        # Keep browser open briefly for visual inspection
        print("\n  Browser will close in 5 seconds...")
        await page.wait_for_timeout(5000)
        await browser.close()

    print(f"\nExploration complete at {datetime.now()}")


if __name__ == "__main__":
    asyncio.run(main())
