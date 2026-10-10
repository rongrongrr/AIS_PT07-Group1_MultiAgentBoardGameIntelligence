# Azul — The Rulebook {#title}

A self-contained English write-up of the official rules of Azul
(Plan B Games, 2017, designed by Michael Kiesling). This document is the
*natural-language source* for the TILES rule-ingestion pipeline: it is
chunked, indexed, and mined into structured, machine-readable rules
that are then verified against the deterministic rules engine.

## 1. Overview {#overview}

Azul is a competitive tile-drafting game for 2 to 4 players. Players
take turns drafting colored tiles from shared factory displays (or from
the center of the table) onto the pattern lines of their personal
player board. At the end of each round, completed pattern lines move
one tile each onto the player's wall, scoring points for adjacency.
Wasted tiles fall to the floor line and cost points. The game ends when
a player completes a horizontal row of their wall, and the player with
the most points wins.

## 2. Components {#components}

The game contains exactly 100 resin tiles. The bag starts with
100 tiles: 20 tiles of each of the 5 colors. The colors are blue,
yellow, red, black and white. There are exactly 5 colors of tiles in
the game; no other color ever appears. In addition there is 1 white
first player token (which is a marker, not a tile), a cloth bag, the
factory displays, and one player board plus score marker per player.

## 3. Setup {#setup}

Give each player a player board and set their score marker to 0 on the
score track. Place the factory displays in a circle in the middle of
the table. The number of factory displays depends on the number of
players. In a 2 player game: 5 factory displays. In a 3 player game:
7 factory displays. In a 4 player game: 9 factory displays. You may
only ever draft from a factory display that is in play for your player
count.

Put all 100 tiles into the bag. To start each round, fill each factory
display with exactly 4 tiles drawn from the bag at random. Place the
first player token in the center of the table. The most recent visitor
to Portugal takes the starting player marker for the first round.

## 4. Round Structure {#round-structure}

Each round consists of two phases played in order. Phase A is Factory
Offer: players take turns drafting tiles until every factory display
and the center of the table are empty. Phase B is Wall-tiling: all
players simultaneously move tiles from their completed pattern lines
onto their wall and score them. Then, if the game has not ended, the
next round is prepared.

## 5. Drafting Tiles {#drafting}

On your turn during the Factory Offer phase you must draft tiles in one
of two ways.

Either: pick one factory display, choose one color available on it, and
take all tiles of that color from that display. You must take all tiles
of that color; you may not take fewer. All remaining tiles on that
display (the tiles of the other colors) are moved into the center of
the table.

Or: choose one color available in the center of the table and take all
tiles of that color from the center. Again, you must take all tiles of
that color.

You can never draft a color that is not actually present on the chosen
factory display or in the center. A drafting move always names a source
that actually holds at least one tile of the chosen color.

After drafting, you must immediately place the drafted tiles onto your
player board as described in the Pattern Line Placement section. Play
then continues clockwise with the next player. Once the game has
ended, no further tiles may be drafted and no further turns are taken.

## 6. The First Player Token {#first-player-token}

The first player token starts each round in the center of the table.
The first player who drafts tiles from the center in a round must also
take the first player token. That player places the first player token
onto the leftmost free space of their floor line (where it counts as a
normal floor penalty tile), and they will take the first turn in the
next round. The first player token is never drawn from the bag and is
not a colored tile; at the end of the round it returns to the center
supply rather than the box lid.

## 7. Pattern Line Placement {#pattern-lines}

Your board has exactly 5 pattern lines. The topmost pattern line holds
1 tile, the second holds 2 tiles, the third holds 3, the fourth holds
4, and the bottom pattern line holds 5 tiles. When you draft tiles you
choose exactly one pattern line and add the drafted tiles to it from
right to left. You may also choose to place the drafted tiles directly
onto your floor line instead of any pattern line.

Placement is constrained by three hard rules:

1. A pattern line may only ever hold tiles of one single color. If a
   pattern line already contains tiles, you may only add tiles of that
   same color to it.
2. You may never place a tile of a color into a pattern line whose
   corresponding wall row already holds that color. Each wall row can
   hold each color only once.
3. If a pattern line is already full, you may not add tiles to it.

If you draft more tiles than the chosen pattern line can hold, every
excess tile falls to your floor line. If your floor line is also full,
excess tiles go straight to the box lid.

## 8. Wall Tiling {#wall-tiling}

During the Wall-tiling phase, every player checks each of their
5 pattern lines from top to bottom. For every pattern line that is
complete (completely filled with tiles of one color), move the
rightmost tile of that line onto the matching color space of the
corresponding wall row, and score it immediately. All the other tiles
of that completed pattern line go into the box lid. Pattern lines that
are not complete keep their tiles for the next round.

The wall is a 5 by 5 grid. Each row of the wall contains each of the
5 colors exactly once, with the color pattern shifting one space to the
right on each successive row.

## 9. Wall Tiling Scoring {#placement-scoring}

Each tile placed on the wall is scored immediately, based on adjacency.
Check whether the new tile is directly adjacent (horizontally or
vertically) to tiles already on the wall. If it is linked horizontally,
count all the tiles in the unbroken horizontal chain including the new
tile, and gain that many points. If it is also linked vertically, count
all the tiles in the unbroken vertical chain including the new tile,
and gain that many points as well. A tile that is part of both a
horizontal and a vertical chain scores for both chains. If the new tile
is not adjacent to any tiles at all, it scores exactly 1 point.

## 10. The Floor Line {#floor-line}

Tiles on your floor line represent wasted tiles and score negative
points during the Wall-tiling phase. The floor line has 7 spaces. From
left to right, the seven floor line spaces score -1, -1, -2, -2, -2,
-3 and -3 points. The first player token occupies a floor line space
and counts toward these penalties like any other floor tile. After
scoring, all tiles on the floor line go to the box lid (the first
player token instead returns for the next round). Your score can never
drop below 0; if the floor penalty would take you below zero, your
score marker stops at 0.

## 11. Preparing the Next Round {#next-round}

If the game has not ended, prepare the next round: the player holding
the first player token takes the new first turn, the first player token
returns to the center of the table, and each factory display is
refilled with exactly 4 tiles drawn from the bag. If the bag is empty
before all displays are refilled, refill the bag with all the tiles
from the box lid, then continue drawing. If both the bag and the box
lid are empty, start the round with whatever tiles could be drawn.

## 12. Game End {#game-end}

The game ends after the round in which at least one player has
completed at least one full horizontal row of 5 consecutive tiles on
their wall. That round is always played to completion, including the
full Wall-tiling phase, before the game ends.

## 13. Final Scoring Bonuses {#final-bonuses}

After the final Wall-tiling phase, each player gains end-of-game
bonuses for their wall. You score 2 points for each complete horizontal
row on your wall. You score 7 points for each complete vertical column
on your wall. You score 10 points for each color of which you have
placed all five tiles on your wall.

## 14. Determining the Winner {#winner}

The player with the most points on their score track wins the game. In
the case of a tie, the tied player with the most complete horizontal
rows wins the game. If the tie persists, the tied players share the
victory.
