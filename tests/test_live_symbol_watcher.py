from synthetic_trader.live.live_symbol_watcher import (
    LiveSymbolWatcherStore,
    PreparedSymbolState,
)


def test_prepared_symbol_state_tracks_freshness_and_levels() -> None:
    store = LiveSymbolWatcherStore()
    prepared = PreparedSymbolState(
        symbol="R_75",
        call="sell_candidate",
        state="actionable",
        confidence=0.62,
        regime="range",
        market_thesis="sellers still control the upper rejection zone",
        entry_area="around 53074.2",
        entry=53074.2,
        stop_area="above 53173.2",
        stop_loss=53173.2,
        target_area="toward 52886.2",
        take_profit=52886.2,
        reward_risk=1.9,
        invalidates_if="price closes back above the rejection shelf",
        next_trigger="a fresh bearish continuation close",
        current_close=53074.2,
        call_age_seconds=3,
        generated_at="2026-07-11T20:32:54.127Z",
    )

    store.update(prepared)
    loaded = store.get("R_75")

    assert loaded is not None
    assert loaded.state == "actionable"
    assert loaded.call_age_seconds == 3
    assert loaded.entry == 53074.2


def test_store_returns_unavailable_snapshot_when_symbol_has_no_prepared_state() -> None:
    store = LiveSymbolWatcherStore()

    loaded = store.get("R_100")

    assert loaded is None
