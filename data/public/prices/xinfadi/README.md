# Beijing Xinfadi wholesale market daily prices (WP-09)

- **Source:** 北京新发地农产品批发市场 (Beijing Xinfadi, the city's largest wholesale market for
  fresh produce), public price list on its website: http://www.xinfadi.com.cn/priceDetail.html
  (data endpoint `POST http://www.xinfadi.com.cn/getPriceData.html`, the one its own page calls).
- **Files:** one JSON per item, the endpoint's answer saved unmodified on 2026-10-20 for dates
  2026-09-01 to 2026-10-20 (`limit=500`): `potato.json` (prodName=土豆), `garlic.json` (大蒜),
  `egg.json` (鸡蛋), `chinese_cabbage.json` (大白菜), `cabbage.json` (圆白菜), `carrot.json` (胡萝卜).
- **What it holds:** per day and per variety/origin: lowest, highest and average wholesale price in
  yuan, per 斤 (jin, 500 g) unless the unit says otherwise.
- **How the app uses them** (`backend/app/engines/market/xinfadi.py`): potato (土豆, plain),
  dry garlic (大蒜, 干), loose eggs (散鸡蛋), Chinese cabbage (大白菜), cabbage (圆白菜) and washed
  carrot (胡萝卜, 洗), per jin. When a day has several rows for an item (origins), the price is
  the median of their averages and the range their lowest low to highest high.
- **Terms:** public price information on the market's own website; no open-data licence stated.
  We keep the answers unmodified and cite the market and date wherever a price is shown.
