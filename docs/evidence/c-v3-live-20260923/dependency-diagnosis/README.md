# Search/default AI dependency diagnosis (2026-09-23)

Tested production: `a6c939351579076ce65b0fec6573bf72cb3cfcd9`.
Scope: read-only network probes. No production code, algorithms, provider selection, credentials, or database contents changed by these probes.

## Reproduced blockers

- Catalog synchronization fails (502/50001); the isolated live database therefore cannot search (503/50006). The original database has only one basic-stock row and cannot serve as a complete catalog.
- Default AI context fails first at `get_stock_info`, before the LLM call. News for 600519 independently returned two items. Real custom-backtest DeepSeek interpretation already passed; see the parent evidence directory.
- Both basic-info and catalog-page endpoints on the delayed Eastmoney host returned HTTP 502 through system proxy and through direct requests. Merely toggling the proxy is not a verified fix.

## Candidate-source feasibility, NOT an applied repair

- The existing Tencent qfq endpoint returned matching six-digit codes and real names for 600519, 000001 and 300750 in `data[symbol].qt[symbol]`.
- This observed response declares UTF-8 but contains GBK Chinese bytes. Direct `response.json()` corrupts the names; the probe strictly decodes GBK. A production adapter needs an explicit encoding policy and identity checks, including fixtures for encoding, missing fields and wrong codes. The probe is not a production adapter.
- No industry or market-cap fields were inferred. The existing schema allows null for those fields.
- AKShare exchange catalog probes: SSE main board 1702 rows and STAR 618 rows succeeded; SZSE failed with TLS EOF; BSE exceeded the 25-second subprocess limit and was terminated. **This is an incomplete catalog and must not be imported or marked complete merely because the row count exceeds 1000.**

## Coordinated next change

Request: https://github.com/27ye/ai-quant-platform/issues/20#issuecomment-5780110490

B/D must confirm source choice and implementation owner before changing teammate production code, per the user's coordination requirement. Proposed narrow scope: stock-info fallback with real identity and null optional fields; a independently verified complete stock catalog with provenance. No quant changes; no swallowing news failures or fake successful synchronization.

After an approved implementation: test source failure/identity/encoding/partial catalog handling, then real sync -> search by code/name -> default AI -> fresh-connection MySQL history, while preserving the already passing numeric consistency checks. Current status remains **not repaired**.
