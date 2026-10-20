# TCB daily retail prices, Dhaka (WP-09, FEATURES N3)

- **Source:** Trading Corporation of Bangladesh (TCB), Ministry of Commerce, "ঢাকা মহানগরীর নিত্য
  প্রয়োজনীয় পণ্যের দৈনিক খুচরা বাজার দর" (daily retail market prices of essentials in Dhaka city).
- **Listing page:** https://tcb.gov.bd/pages/daily-rmps (one entry per day, each with an XLSX file).
- **Files here:** `<publication date>.xlsx`, saved unmodified on 2026-10-20 from the URLs in
  `sources.csv` (TCB's file store on the government cloud). Ten lists: 10 to 19 October 2026.
- **What each list holds:** for about 70 items, the lowest and highest retail price today, one
  week before and one month before (TCB's own columns), plus one year before. Prices are in taka,
  collected by TCB from Mirpur-6, Mohammadpur Town Hall, Malibagh, Rampura, Mohakhali, Hatirpool
  and West Agargaon markets.
- **Licence / terms:** public information published by a government body on its official website.
  No open-data licence is stated on the page; we keep the files unmodified, cite TCB with the URL
  and publication date wherever a price is shown, and use them for a non-commercial demonstration.
- **How the app uses them:** `backend/app/engines/market/tcb.py` reads 13 inputs a small shop buys
  (rice coarse and fine, atta, loose soybean oil, masur lentil, chickpea, sugar, onion, potato, farm eggs,
  garlic, iodised salt, 60-grade MS rod). The price is the midpoint of TCB's low-high range. Each
  list adds a point for its own date and, from its week-before and month-before columns, for those
  dates (the list published on a date wins when two lists give the same date). The screen says
  "published on <date> by TCB", never "live".
- **Refreshing:** download the newest XLSX files from the listing page into this folder as
  `<YYYY-MM-DD>.xlsx` and add their URLs to `sources.csv`. Note: tcb.gov.bd serves an incomplete
  certificate chain; verify it with Sectigo's public intermediate
  (http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt), never by turning
  verification off.
