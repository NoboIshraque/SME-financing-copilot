# China: NBS 10-day market prices of important production materials (WP-09)

- **Source:** National Bureau of Statistics of China (国家统计局), "流通领域重要生产资料市场价格变动情况",
  published every 10 days: https://www.stats.gov.cn/sj/zxfb/ (one page per release).
- **Files:** the release pages saved unmodified on 2026-10-20: `t20260903_1965182.html` (Aug 下旬),
  `t20260914_1965293.html` (Sep 上旬), `t20260923_1965403.html` (Sep 中旬),
  `t20261008_1965465.html` (Sep 下旬). URL: `https://www.stats.gov.cn/sj/zxfb/<yyyymm>/<file>`.
- **What it holds:** national average wholesale/sales prices in yuan for 50 production materials
  (steel, metals, chemicals, fuel, coal, cement, glass, farm products for processing, fertiliser,
  forest products), with the change against the previous 10 days.
- **How the app uses them** (`backend/app/engines/market/nbs.py`): rebar, cement, float glass,
  rice (japonica), wheat, corn, soybean, white sugar, peanut, urea and diesel, per tonne. Each
  release adds a point for its period (dated the 10th, 20th or last day of the month) and, from
  the change column, one for the period before.
- **Terms:** official statistics published by a government body; cited with source and date
  wherever shown. National averages: one "China (national)" location, not a city.
