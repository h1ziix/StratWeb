# Local map asset pack

StratWeb does not hotlink map images and does not redistribute Valve radar files. The
runtime pack used for Stage 7.3 was extracted from the user's installed CS2 copy and is
ignored by Git. Its license status is **Valve proprietary; local use only; redistribution
not granted**.

## Provenance

- CS2 VPK: `game/csgo/pak01_dir.vpk`
- VPK SHA-256: `d263aa1118fb692baf83d44a7e20526eb6d6917fab26296ed410455f506d6aec`
- game patch: `1.41.7.1`, client/server build `2000876`, Source revision `10830129`
- local `steam.inf` version date: `Jul 16 2026` (recorded provenance, not a demo selector)
- extractor: Source2Viewer CLI `19.2.6339+c72208352f5bf62f1482447ed166c548f303f8fa`
- extractor archive SHA-256:
  `53e7e8dac1ddd876078346de709c8dbe613a967e94cd0c969aa34c61ec07680d`

Source2Viewer is MIT-licensed; this does not change the license of the Valve assets it
extracts. The configured map revision is `cs2-1.41.7.1-d263aa1118fb`, asset version
`cs2-1.41.7.1-vpk-d263aa1118fb`.

## Manifest

All PNGs are 1024×1024. Metadata checksums refer to the matching Valve
`resource/overviews/<map>.txt` file.

| Map | Upper PNG SHA-256 | Lower PNG SHA-256 | Metadata SHA-256 |
|---|---|---|---|
| de_ancient | `cb6adca45e32ecff0b131f742c129324ba5e2dd695247f61d2d21d85ef2c581c` | — | `f6b420a983e2702c3c0d903a901483b6bc61fcf5eef2b6fb62da485ba93eb3c1` |
| de_anubis | `b8f07c36edb13e34dbfaabf9a74e057961ac4fb29545d98d16ff9b7c4e6d1206` | — | `f83755ed8a85365923ac565d3fbd2ab1391e75d8b89cfd759da9214bf80e9fff` |
| de_cache | `94c058b3deaa5cc24be81006322da3af1ef0bbded116160a3fcdea6d87227967` | — | `4344e0364bc9ec31f9f3fc04fe24aacb465e5252f8c173e661cebec586b54c0d` |
| de_dust2 | `0828297130ce26db25a299806ff743df9104de634a3e64b52b358f6f4399354d` | — | `97947e99bc7930fc06dc15af3dcf942dbca5ca1c6f36119a089615fd4b383620` |
| de_inferno | `53e1d660d5e61a9b876cc56725c2e891c56efcb788657520fa9c10fec321dce3` | — | `ff93b0ff1f6705ccfb4daf3b038dd88ccdf3ca776823667c19782650e94d2c54` |
| de_mirage | `c8032f6c83ffca63c0a20ebdcc598a0e1aa618efd746e381e2db26f33a4a964f` | — | `f201fd608d6ea0bd091920620a4f74e97197d26caf36f133875b58d5ba1d77fe` |
| de_nuke | `21167d05292e80eebe7b068f0bba36a2e3f9116d154d96952a8366cdcc72e6b1` | `b8c4e659491ba79be60b7d3f9bc78bdaeb808afc2bae14bf3b25b1801220ebe0` | `877a8df76cee8e5abc4756df162790ed25c5f5dd994ed9d895a7bc3a9c3ac585` |
| de_overpass | `2a59b62668e80037b5a88e980f56af360269f5ea581d52eb0669d78a981f0d96` | — | `23b44305d79a15dc9feea71528a7015d6f3612044a8367f29b20c65aec2e7897` |

The full machine-readable record is generated at
`data/map_overviews/vpk-d263aa1118fb/manifest.json` and includes byte sizes, original VPK
paths, build metadata, extractor version, and license status.

## Local installation

Run the verified extractor once per map from the project root:

```powershell
python .\scripts\install_map_overview.py de_mirage `
  --cs2-root "C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive" `
  --vrf-cli "C:\path\to\Source2Viewer-CLI.exe" `
  --output .\data\map_overviews\vpk-d263aa1118fb
```

Repeat with the other canonical names. The installer validates the exact extractor
version, PNG signature/dimensions, metadata presence, and writes the manifest atomically.
Nuke's metadata triggers extraction of the lower image automatically.

At runtime set `STRATWEB_MAP_OVERVIEW_DIR=.\data\map_overviews`. Assets are resolved by
revision plus checksum, not by a mutable filename alone. Missing, wrong-size, or
checksum-mismatched assets produce a placeholder and warning; no other map is substituted.

