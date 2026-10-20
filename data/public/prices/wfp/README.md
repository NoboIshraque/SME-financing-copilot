# WFP Bangladesh market prices (WP-09)

- **Source:** World Food Programme market monitoring, via the Humanitarian Data Exchange:
  https://data.humdata.org/dataset/wfp-food-prices-for-bangladesh
- **Licence:** Creative Commons Attribution for Intergovernmental Organisations (CC BY-IGO).
- **Files:** `wfp_food_prices_bgd.csv` (prices) and `wfp_markets_bgd.csv` (markets with division,
  district and coordinates), downloaded unmodified on 2026-10-20 (HDX resources last updated 11
  and 18 Oct 2026). Latest prices are dated 15 Aug 2026 (some markets 15 Jul).
- **What it holds:** monthly retail and wholesale prices in taka for about 100 markets in all eight
  divisions.
- **How the app uses them** (`backend/app/engines/market/wfp.py`): retail rows flagged `actual`
  (observed in that market, not a division average) for 12 staples; each market is a location
  the owner can pick. Monthly data: the baseline is the previous month, and the screen says so.
