# Delta Option Desk

A local, single-machine dashboard for Delta Exchange option buying. It binds to `127.0.0.1:8765`; it is not exposed to the LAN. The backend uses Delta's documented REST signing format directly so credentials remain in the local Python process and are never saved to disk or browser storage.

## Start

1. Install Python 3.10 or later.
2. Run `python server.py` from this folder.
3. Open [http://127.0.0.1:8765](http://127.0.0.1:8765).
4. Connect using a Delta API key with read and trade access. Use an exchange testnet environment first.
5. Stop the process with Ctrl+C when finished; its in-memory API key and secret are cleared on shutdown.

No Python package is needed for the local bridge. The user-referenced [Tradehull Delta Exchange package](https://pypi.org/project/Tradehull-Delta-Exchange/) exposes comparable OHLC, quote, option selection, and bracket workflows. This dashboard uses Delta's documented REST endpoints directly for request signing and exchange-native orders; the package is not installed or imported.

## Behavior

- The signal rules are mandatory: BUY CALL requires ADX above 25, bullish Supertrend, and either the selected-timeframe candle close or current underlying price above the configured EMA; bearish SELL signals require ADX above 25, bearish Supertrend, and candle close or current underlying price below the configured EMA. On Arm, the signal table evaluates BTC, ETH, and XAUT immediately using completed candles, then checks once one second after each selected-timeframe candle closes. A bearish SELL signal buys an ATM put option, consistent with this option-buying strategy.
- A qualifying signal selects the nearest eligible expiry with live quotes, then the nearest ATM strike for that option side. Contracts expiring within 60 minutes are excluded; the next available expiry is used. The current best ask is the entry reference for IOC limit buys and percentage brackets; the exchange order cannot fill above its limit price. Stop level is `ask × (1 − stop_percent / 100)`; target level is `ask × (target_percent / 100)`. Defaults are 50% and 200% of ask, respectively (for ask 140: stop 70, target 280). Option ATR remains displayed as an informational metric and does not set the brackets.
- The selected contract's bid, ask, last price, and mark price refresh every five seconds independently of signal scans. Quote refreshes do not evaluate signals or place orders. The last traded price may be stale or absent; the best ask is the buy-side quote used as the entry reference.
- Live orders require a verified Delta connection and an explicit click on Arm live auto execution. While armed, qualifying BTC, ETH, or XAUT signals submit IOC limit buy orders at a freshly verified best ask on the immediate arm check and each timeframe check, without an order review dialog. If the quote changes by more than one tick before submission, the order is skipped; if the ask moves beyond the limit, the IOC order does not chase it. A same-side position still open at a check is skipped; Delta order errors such as insufficient balance are shown as the reason in the signal table. Disarming blocks further order submissions. Use this only with an API key whose permissions and IP allowlist are configured as intended.
- Strategy settings are saved in the current browser tab's session storage so refresh restores the armed strategy parameters; API credentials are not stored there. Refresh reads the armed state from the local server before enabling controls. If the tab has no saved parameter set, controls remain locked and automatic scans pause until the user disarms, sets values, and arms again.
- After an automatic order, an asset-and-side signal lock prevents duplicate entries until Delta reports that the tracked option product has no open position. The other signal direction is tracked independently.
- The Open positions table reads the connected Delta account positions and displays Delta-reported mark-based unrealized P&L. It refreshes every five seconds; Delta notes that the margined-position view may take up to ten seconds to reflect a change.
- Each Exit action submits a reduce-only market order for that product's current position after a confirmation prompt. Exit All disarms auto execution, then calls Delta's account-wide close-all endpoint for portfolio and isolated positions. Delta can skip disrupted products, and this endpoint does not cancel open orders; the confirmation and table footnote explain this before submission.
- Exchange brackets are submitted with the entry order. The displayed row is session-tracked and shows Delta's returned order state; it is not a substitute for reconciling with the exchange account.
- “Stop & close tracked” cancels session-tracked orders and closes only positions for those tracked option product IDs, with reduce-only market orders. It then clears local session state. API errors leave the session rows available for follow-up.
- “Clear session” only clears local display/session state; it does not cancel or close exchange activity.

## Notes

- Delta API credentials must have permission for the selected environment. The app verifies them with a signed wallet-balance request and shows Delta's error response without printing credentials.
- The secret is held in process memory while connected and is discarded at process shutdown or disconnect. Do not run this local app on a shared computer.
- BTC, ETH, and XAUT option availability depends on the selected Delta environment. If Delta does not return a live XAUT option chain, its signals remain visible but automatic order submission is unavailable for that setup.
- Option ATR uses the selected option's historical candles and is informational. Percentage brackets are based on the current best ask; actual market fill may differ from the ask, so realized risk and reward can differ from the displayed calculation.
- This is a live trading tool; market and execution risks remain with the account holder. Arming is authorization for immediate live order submission whenever the strategy qualifies.

## References

- [Tradehull Delta Exchange on PyPI](https://pypi.org/project/Tradehull-Delta-Exchange/)
- [Delta Python REST client README](https://github.com/delta-exchange/python-rest-client/blob/master/README.md)
- [Delta API documentation](https://docs.delta.exchange/)
