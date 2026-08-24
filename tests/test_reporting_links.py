from stratweb.reporting.links import prefer_smooth_playback


def test_evidence_link_keeps_exact_tick_and_prefers_smooth_playback() -> None:
    href = "/ui/spatial/match/rounds/7?tick=12345&run_id=spatial-run&mode=exact#evidence"

    result = prefer_smooth_playback(href)

    assert result == (
        "/ui/spatial/match/rounds/7?tick=12345&run_id=spatial-run&mode=smooth#evidence"
    )


def test_evidence_link_adds_mode_without_dropping_filters() -> None:
    result = prefer_smooth_playback("/ui/spatial/match/rounds/7?tick=12345&player=player-id")

    assert result == ("/ui/spatial/match/rounds/7?tick=12345&player=player-id&mode=smooth")
