# Metodologija S&P 500 portfelja (PoC)

## Ulazni skup i odabir

- Aktualni sastav indeksa S&P 500 preuzima se iz javne tablice na Wikipediji.
- Simboli se sortiraju abecedno, a zatim se odabire prvih 100 **različitih kompanija**.
- Yahoo Finance simboli dobivaju se zamjenom točke crticom (primjerice `BRK.B` u
  `BRK-B`). Izvorni simbol i naziv kompanije ostaju u izlazu radi sljedivosti.

## Cijene i razdoblje

- Koristi se polje **`Close`**, a ne `Adj Close` (`auto_adjust=False`).
- Promatra se pet kalendarskih godina do dana pokretanja. Yahooov završni datum je
  isključiv, pa se kao završni datum upita šalje dan nakon datuma pokretanja.
- Tržišni benchmark je S&P 500 (`^GSPC`). Ako mrežno okruženje blokira Yahoo,
  skripta jasno prijavljuje rezervni izvor: javni, stvarni `all_stocks_5yr`
  povijesni snapshot. Tada se datum završetka postavlja na zadnji datum snapshota,
  a benchmark je dnevno rebalansirani jednako ponderirani prinos svih kompanija u
  snapshotu. Izvor i vrsta benchmarka zapisani su u svakom retku izlaza.
- Dnevni prinos je postotna promjena uzastopnih dostupnih cijena. Ne popunjavaju se
  nedostajući dani niti cijene.

## Pokazatelji

- Godišnja volatilnost: standardna devijacija dnevnih prinosa uzorka (`ddof=1`),
  pomnožena s `sqrt(252)`.
- Sharpeov omjer: `(annualizirani geometrijski prinos - 0,02) / godišnja
  volatilnost`. Geometrijski prinos izračunava se iz prve i zadnje cijene, s brojem
  godina jednakim broju kalendarskih dana između tih opažanja podijeljenim s
  365,25. Pretpostavljena bezrizična stopa je 2% godišnje.
- Beta: kovarijanca dnevnog prinosa dionice i benchmarka podijeljena varijancom
  dnevnog prinosa benchmarka, nakon unutarnjeg spajanja po datumu (`ddof=1`).
- Simulirani SRI dodjeljuje se samo iz godišnje volatilnosti: 1 (`<5%`), 2
  (`<10%`), 3 (`<15%`), 4 (`<20%`), 5 (`<30%`), 6 (`<50%`) ili 7 (`>=50%`).
  To je ilustrativna, simulirana mjera, a ne regulatorni SRI.

## Potpunost i izlazi

Puna povijest znači da je prvo opažanje najviše sedam kalendarskih dana nakon
traženog početka te da je zadnje opažanje najviše sedam dana prije traženog kraja.
Status i razlog nepotpunosti zapisuju se za svih 100 kompanija. Skripta stvara:

- `output/sp500_portfolio.csv` — pokazatelji i metapodaci svih odabranih kompanija;
- `output/incomplete_history.csv` — samo kompanije bez pune povijesti;
- `output/validation_summary.csv` — kontrole jedinstvenosti, formula i broja redaka;
- `output/selected_companies.csv` — auditni popis odabranih kompanija.
