# CS2 Demo Bridge

StratWeb can prepare a retained completed demo for manual playback in the local CS2 client.
The bridge does not launch CS2, type into its console, inject code, read memory or interact with
an active match.

## Verified command contract

The command names and syntax were checked against the locally installed current CS2
`engine2.dll` command registry before implementation:

- `playdemo <demoname>` — play a recorded `.dem` file;
- `demo_gototick <tick>` — seek demo playback to a tick;
- `demo_pause` — pause demo playback.

`playdemo "match.dem" 45230` is not emitted because the installed command contract does not
define a tick argument for `playdemo`. StratWeb copies two lines instead:

```text
playdemo "StratWeb/stratweb_<match-id>.dem"
demo_gototick <tick>; demo_pause
```

Paste the first line into the CS2 developer console, wait until the demo is loaded, then paste
the second line. Player/first-person selection remains manual because the canonical player UUID
does not prove a current CS2 spectator entity index or slot.

## File safety

The source must be a retained, successfully imported upload. Its internal filename is validated
as a direct `.dem` child of the StratWeb upload directory. Before export, StratWeb recalculates
SHA-256 and compares it with the immutable match source hash.

The destination is a dedicated `game/csgo/StratWeb` directory configured through
`STRATWEB_CS2_DEMO_DIR`. The exported name contains only the internal match UUID. A hard link is
used when possible; otherwise an atomic verified copy is created. Existing verified exports are
reused.

Preparation is a localhost-only POST operation. The browser copies commands to the clipboard;
the user remains responsible for opening CS2 and executing them.
