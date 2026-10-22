# Published prediction history and feedback

Both dashboards now keep a persistent first-publication ledger. Gold runs about once an hour (after each completed sync/training); IDX retains its six-hour polling interval and records one signal per ticker/session.

## Sequence

- N+0: save the prediction, issue time, data timestamp, target window, starting price, neutral price band, probabilities, model version and feature snapshot.
- N+1: if the exact target candle is available, append its price/direction, return and correctness. Save the next prediction separately.
- N+2: evaluate that next prediction in the same way. Repeated polls of an existing candle cannot overwrite the first prediction.

Records survive restarts and deployments. History begins at deployment of this feature. Old backtest CSV rows are not imported as if they were live predictions. The model report's historical test accuracy remains separate from the accuracy of published predictions.

## Gold

Windows are 1, 4, 8 and 24 elapsed hours from the data timestamp. Gold is bullish/bearish when its price change exceeds the frozen neutral band (currently 0.25 times the ATR at prediction time); otherwise it is neutral. This matches training labels. A missing target candle is `waiting_data`, not substituted with another candle. A forecast issued after its target is `expired` and is not scored. Outcomes are resolved only from the matching source and symbol, and the first observed outcome is retained even if a provider later revises prices.

Each publication records the probability vectors of both candidate models, including the candidate not selected for the displayed forecast. After at least **30 resolved predictions per horizon**, up to the **latest 200 eligible outcomes** are compared by mean log loss. The candidate with lower loss is selected for the next live forecast. Only outcomes resolved before the training cutoff are eligible. Before the sample threshold, chronological validation selects the model.

Offline test scores continue to use the candidate selected by chronological validation; `test_model` identifies it. Feedback may select a different model for the live forecast. This prevents reuse of live outcomes from turning the historical test into an independent performance claim.

Candle archives are kept separately per source/feed. Training reads the latest 10,000 candles, while older archived candles and ledger records remain on disk. Models are retrained on the current dataset; this feature does not guarantee increasing accuracy or provide online gradient updates to the model weights.

## IDX

Signals are compared with the first subsequent available completed trading session, including weekends/holidays. The reference is the saved close and the outcome is next-session close-to-close return. `BUY_CANDIDATE` is evaluated as bullish and `RISK_OFF` as bearish; `WATCH` abstains and is excluded from directional accuracy. Price changes within +/-1% are neutral. Only signals issued before the evaluated session opens are scored. These are diagnostic conventions, separate from the next-open paper-trade accounting.

IDX currently uses fixed technical rules. The ledger supports analysis and future rule/model changes; it does not automatically modify those rules.

## Storage and access

- Gold: `results/gold/history.sqlite`, plus per-feed `candles_*.csv` archives.
- IDX: `data/idx_history.sqlite`.
- Both existing dashboards show recent predictions vs actual outcomes and live accuracy.
- `/api/gold` and `/api/status` include a `history` field.
- `/api/history?kind=gold&limit=100&offset=0` and `kind=idx` provide paginated history (maximum 1,000 records/page), source/feed/window statistics, snapshots and model versions.

SQLite uses rollback journaling so the web service can query it through its read-only volume mounts. Original records are inserted once; only outcome fields are updated. Back up both `data` and `results`; do not delete the ledger as part of container cleanup. Use SQLite's backup facility for a consistent backup while writers are active. There is currently no automatic history deletion policy.
