# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **BREAKING**: The state of `sensor.frank_current_price` changes from Frank's complete consumer all-in price to Frank's dynamic **"marktprijs+"** basis, computed as `market_price + market_price_tax + sourcing_markup_price` from the actual per-quarter values in the price block — the dynamic component Frank bills as "het dynamische deel", which is the all-in price minus the energy tax. All three components are required because their VAT bases differ: `market_price` excludes VAT (its 21% arrives separately as `market_price_tax`) while `sourcing_markup_price` already includes it. The formula was verified against Frank's own `marketPricePlus` field on the public API and reproduced it exactly on all 288 quarter-hour blocks checked across three days; no VAT rate, markup or tax amount is hard-coded. The entity id, unique id, friendly name, unit `EUR/kWh`, device class `monetary`, state class and attribute key set are all unchanged; only the numeric state value changes (e.g. `0.26440` → `0.15355` at 2026-09-09 10:00 local). The energy tax is no longer included in this sensor, so it is no longer a complete consumer price. Existing history is not back-filled, so the Energy Dashboard cost curve will show a visible step at the upgrade. The previous all-in value stays reachable on the same entity via the `full_block.total_price_eur_kwh` attribute, and the cheapest/most-expensive, daily-array, price-zone and optimal-period sensors keep the all-in basis. Automations comparing `sensor.frank_current_price` against an absolute threshold must be re-tuned.

## [0.1.7] - 2026-08-15

### Fixed

- Het `prices`-attribuut van `sensor.frank_prices_today` en `sensor.frank_prices_tomorrow` wordt niet langer in de Recorder-database opgeslagen. De volledige dagreeks is ongeveer 25 kB en overschreed daarmee de limiet van 16384 bytes, waarna Home Assistant bij elke statuswijziging de waarschuwing *"State attributes for sensor.frank_prices_today exceed maximum size of 16384 bytes. This can cause database performance issues; Attributes will not be stored"* logde en vervolgens **alle** attributen van die status oversloeg — ook de kleine samenvattingsattributen ernaast. Er wordt uitsluitend `prices` uitgesloten, via Home Assistant's eigen `_unrecorded_attributes`-mechanisme (beschikbaar sinds HA 2023.8, ruim onder de minimumversie 2025.1.0 van deze integratie).
- Het attribuut zelf blijft **volledig ongewijzigd** als live status-attribuut: `state_attr('sensor.frank_prices_today', 'prices')` geeft nog steeds de complete blokkenreeks terug, met exact hetzelfde schema. Dashboards, templates, automatiseringen, Alpha EMS Manager en andere EMS-consumenten merken er niets van. Alleen de historische opslag van dat ene attribuut vervalt — precies de historie die de Recorder toch al weigerde te bewaren. De overige attributen worden nu wél weer bewaard.
- De ApexCharts-voorbeelden — zowel de bestanden in `examples/` als de ingesloten voorbeelden in beide README's — zetten de y-as niet langer vast met `min: 0`. Frank-prijzen kunnen legitiem negatief worden en de integratie laat die ongewijzigd staan, maar een op nul vastgezette as duwde precies die staven buiten beeld. De as schaalt nu mee met de data, zodat een negatief kwartier onder de nullijn zichtbaar blijft. Verder ongewijzigd: elk prijsblok wordt nog steeds afzonderlijk getekend en er wordt nooit geaggregeerd.
- De ApexCharts-voorbeelden verwezen voor de optionele kleurdrempels naar `sensor.frank_green_threshold` en `sensor.frank_red_threshold`. Een helper die je via **Instellingen → Apparaten & diensten → Helpers** aanmaakt komt echter in het `input_number`-domein terecht en niet in `sensor`, dus die verwijzing kon nooit iets vinden en de drempels vielen stilzwijgend terug op de ingebouwde standaarden. De voorbeelden gebruiken nu `input_number.frank_green_threshold` en `input_number.frank_red_threshold`, zowel in de toelichting als in de `variables:`-blokken. De terugval op 0,12 en 0,25 EUR/kWh blijft bestaan, dus de kaart blijft gewoon werken wanneer je de helpers niet hebt aangemaakt.
- Het voorbeeldbestand voor de grafiek van morgen noemde nog ~15:00 CET als publicatiemoment. Dat is in lijn gebracht met de README's: de prijzen voor morgen verschijnen doorgaans tussen 13:00 en 14:00 markttijd.

### Added

- Optionele **optimale goedkope periode**: de goedkoopste aaneengesloten periode van precies de ingestelde duur, voor vandaag en voor morgen. Standaard uitgeschakeld.
- Optionele **optimale dure periode**: het spiegelbeeld, de duurste aaneengesloten periode van precies de ingestelde duur. Bruikbaar om verbruik te vermijden of teruglevering te plannen. Standaard uitgeschakeld.
- Per functie een instelbare **duur** in minuten: van 15 tot 720 minuten in stappen van 15, standaard 120. Het maximum van 12 uur is een bewuste halve-dagbegrenzing — daarboven nadert "de goedkoopste aaneengesloten periode" simpelweg de hele dag — en past ook nog op de 23-uursdag rond de zomertijdovergang.
- Een **onbruikbare ingestelde duur wordt geweigerd, niet stilzwijgend vervangen**. Het optieformulier weigert een waarde buiten 15–720 minuten of naast de stap van 15 met een duidelijke foutmelding bij het betreffende veld, zodat zo'n waarde niet opgeslagen kan worden. Staat er door handmatig bewerken van de configuratie tóch een onbruikbare waarde (`0`, `-15`, `17`, `22.5`, tekst), dan blijven de bijbehorende entiteiten onbeschikbaar en wordt dat één keer per afwijkende waarde in het logboek gemeld. Een automatisering draait zo nooit op een duur die de gebruiker nooit heeft ingesteld. Een *ontbrekende* instelling is iets anders en valt gewoon terug op de standaard van 120 minuten.
- Vier nieuwe opties in de Options Flow: **Optimale goedkope periode inschakelen**, **Duur optimale goedkope periode**, **Optimale dure periode inschakelen** en **Duur optimale dure periode**, met Nederlandse en Engelse vertalingen. Het formulier blijft één platte lijst, geordend in drie logische groepen (terugleverprijs, prijszones, optimale periodes).
- Zes nieuwe entiteiten, maar alleen wanneer de betreffende functie is ingeschakeld: `sensor.frank_optimal_cheap_period_today`, `sensor.frank_optimal_cheap_period_tomorrow`, `binary_sensor.frank_optimal_cheap_period` en de drie `expensive`-equivalenten. De status van de sensoren is de starttijd als tijdzonebewuste tijdstempel (`device_class: timestamp`), net als bij de zonegrenzen; de gemiddelde prijs, de eindtijd, de duur en het aantal blokken staan als attributen erbij. De binaire sensoren zijn aan zolang `start <= nu < eind`.
- Het algoritme kiest de kandidaat met het laagste respectievelijk hoogste **naar bloklengte gewogen gemiddelde** van `total_price_eur_kwh`, uit alle aaneengesloten reeksen hele prijsblokken waarvan de werkelijke duur exact gelijk is aan de gevraagde duur. Bij een gelijkspel wint altijd de vroegste periode, voor beide varianten. Negatieve prijzen tellen ongewijzigd mee: niet afgekapt en niet als absolute waarde.
- Prijsblokken worden nooit opgeknipt, samengevoegd of overgeslagen. Past de gevraagde duur niet op de blokken van de dag — bijvoorbeeld 90 minuten op een dag met uurprijzen — dan blijven de entiteiten onbeschikbaar in plaats van een half uur te verzinnen dat nooit is gepubliceerd.
- Anders dan de prijszones leveren de optimale periodes wél een resultaat op een volledig **vlakke** dag: elke kandidaat scoort dan gelijk, dus wint de vroegste. Een prijszone vereist een goedkoop-versus-duur onderscheid dat een vlakke dag niet heeft; een venster van vaste lengte niet.
- Diagnostiek toont nu ook `optimal_cheap_enabled`, `optimal_cheap_duration_minutes`, `optimal_expensive_enabled` en `optimal_expensive_duration_minutes`, zodat een onbeschikbare planner-entiteit direct verklaarbaar is. De volledige dagreeks wordt daarvoor niet gedupliceerd.
- README en README_EN: nieuwe sectie **Optimale periodes** met een expliciete vergelijking tussen prijszones en optimale periodes, de duursemantiek, het gedrag rond uurdata, vandaag/morgen en een automatiseringsvoorbeeld. Ook een korte uitleg over het Recorder-gedrag toegevoegd.

### Compatibility

- De optimale periodes zijn **volledig onafhankelijk** van de prijszones. Ze gebruiken uitsluitend de werkelijke prijzen en de ingestelde duur, nooit een zonemarge; omgekeerd verandert een andere duur nooit een zonegrens. Beide richtingen zijn expliciet getest.
- Bestaande entity ID's, unique ID's, namen, eenheden, device classes, attributen, het `prices`-schema, de kwartiergrens-synchronisatie uit v0.1.4, het cachegedrag uit v0.1.5 en het prijszone-algoritme uit v0.1.6 zijn ongewijzigd. De handmatige teruglevercorrectie en de btw-optie blijven ongewijzigd behouden.
- Een bestaande installatie krijgt standaard **geen** nieuwe entiteiten: beide functies staan uit tenzij je ze zelf inschakelt. Opnieuw toevoegen of migreren is niet nodig.
- De optionele entiteiten worden **alleen aangemaakt wanneer de betreffende functie wordt ingeschakeld**, dus een bestaande installatie die de functie nooit aanzet krijgt er geen enkele entiteit bij. Wordt een functie daarna weer uitgeschakeld, dan blijft de entiteit in het register staan en wordt hij `unavailable`; hij wordt bewust **niet** verwijderd. Daardoor blijven alle eigen aanpassingen — gewijzigd entity-ID, naam, icoon, gebied, labels, verborgen of uitgeschakeld — behouden, en ziet een automatisering die ernaar verwijst een status waarop hij kan reageren in plaats van een entiteit die zonder melding verdwenen is. Bij opnieuw inschakelen keert exact dezelfde registerregel terug: hetzelfde entity-ID, dezelfde unique ID, dezelfde aanpassingen — geen `_2`-achtervoegsel en geen dubbele entiteiten, hoe vaak er ook wordt gewisseld. Wil je zo'n achtergebleven entiteit definitief kwijt, verwijder hem dan terwijl de functie uit staat; verwijderen terwijl de functie aan staat is zinloos omdat de integratie hem bij de volgende herlaadbeurt opnieuw aanmaakt.
- De optimale periodes worden lokaal afgeleid uit de reeds opgehaalde prijsreeks en kosten aantoonbaar **nul** extra API-aanvragen: geen eigen client, geen tweede coordinator, geen extra timer of kwartiergrens-listener. Elke ingeschakelde periode wordt precies één keer per coordinator-update berekend en door alle bijbehorende entiteiten gedeeld.
- Een optimale periode wordt alleen gepubliceerd voor een **volledige** marktdag, via dezelfde volledigheidscontrole als de prijszones. De 92-, 96- en 100-kwartierdagen rond de zomertijdovergang werken correct; de duur is altijd werkelijk verstreken tijd, nooit een wandklokverschil.

## [0.1.6] - 2026-08-14

### Added

- Dagelijkse **prijszones**: de langste aaneengesloten goedkope en dure periode van vandaag, lokaal afgeleid uit de prijsreeks die al is opgehaald.
- Vier nieuwe sensoren met de zonegrenzen: `sensor.frank_cheap_zone_start_today`, `sensor.frank_cheap_zone_end_today`, `sensor.frank_expensive_zone_start_today` en `sensor.frank_expensive_zone_end_today`. Hun status is een tijdzonebewuste tijdstempel (`device_class: timestamp`), direct bruikbaar in een automatiseringstrigger; de vertrouwde `"HH:MM"`-weergave blijft beschikbaar als het attribuut `time`.
- Twee nieuwe binaire sensoren, `binary_sensor.frank_cheap_period` en `binary_sensor.frank_expensive_period`, die aangeven of de huidige lokale tijd binnen de betreffende zone valt (`start <= nu < eind`). Ze zijn onbeschikbaar wanneer er voor vandaag geen zone bepaald kan worden en tonen nooit een zone van gisteren.
- Twee nieuwe instelbare opties in de Options Flow: **Marge goedkope prijszone** en **Marge dure prijszone**, beide standaard 15%, instelbaar van 0 tot 49% in stappen van 1%. Nederlandse en Engelse vertalingen toegevoegd.
- De zonemarge is een percentage van het **prijsverschil van de dag zelf** (duurste kwartier min goedkoopste), niet van de prijs in euro's. Daardoor kunnen de goedkope en de dure zone elkaar per definitie niet overlappen zolang beide marges samen onder de 100% blijven; het maximum van 49% garandeert dat.
- De prijszones worden alleen afgeleid uit een **volledige** marktdag. Zolang de prijsreeks van vandaag onvolledig is, blijven de zes zone-entiteiten onbeschikbaar in plaats van een zone uit een halve dag te tonen. Is de dag volledig vlak (alle kwartieren exact dezelfde prijs), dan is er geen goedkoop-versus-duur onderscheid en blijven de zones eveneens onbeschikbaar.
- De Frank-marktdag wordt nu bepaald in de **tijdzone van de markt** (`Europe/Amsterdam` voor NL, `Europe/Brussels` voor BE) in plaats van in de tijdzone die in Home Assistant is ingesteld. Een Home Assistant op bijvoorbeeld UTC zag een Nederlandse dag daardoor twee uur te kort, waardoor geen enkele dag ooit als volledig werd geaccepteerd, de zone-entiteiten permanent onbeschikbaar bleven en beide dagen bij iedere kwartiertik opnieuw werden opgehaald.
- Diagnostiek toont nu ook het land, de markttijdzone, de Home Assistant-tijdzone, de effectief gebruikte marges en de bron van de terugleverprijsberekening, en werkt ook wanneer de integratie niet geladen is.
- GitHub Actions-workflow `tests.yml` toegevoegd, die de volledige pytest-suite op Ubuntu draait bij elke push naar `main` en elke pull request.
- Het actieve kwartier en de zone-lidmaatschapstoets vergelijken nu op absolute tijdstippen. Python vergelijkt twee tijdzonebewuste datums die dezelfde `tzinfo` delen naïef op de wandklok en negeert daarbij `fold`; op de dag van de overgang naar wintertijd komt 02:00–03:00 twee keer voor, waardoor de actuele prijs een uur lang die van het vorige uur toonde en de periode-sensoren een uur te vroeg konden omschakelen.

### Changed

- README en README_EN: configuratiesectie met alle vier de instellingen toegevoegd, sensoroverzicht bijgewerkt naar 19 entiteiten, prijszones en marktdaggedrag gedocumenteerd, dashboardvoorbeeld herschreven zodat het de nieuwe zonesensoren toont in plaats van de zones zelf in Jinja te berekenen, EMS-voorbeelden met de nieuwe binaire sensoren toegevoegd en een schermafbeelding van de prijszonekaart opgenomen.
- README en README_EN: de lange rekenvoorbeelden voor de terugleverprijs ingekort tot één korte, accurate uitleg, en de sectie met merkmateriaal verwijderd. De merkbestanden zelf blijven ongewijzigd in de repository.

### Compatibility

- Bestaande entity ID's, unique ID's, namen, eenheden, device classes, attributen en de today/tomorrow-datastructuren zijn ongewijzigd. De zes nieuwe entiteiten zijn puur additief.
- De kwartiergrens-synchronisatie uit v0.1.4 en het cachegedrag uit v0.1.5 zijn ongewijzigd. De prijszones worden lokaal afgeleid en kosten aantoonbaar **nul** extra API-aanvragen: geen eigen client, geen tweede coordinator, geen extra timer of kwartiergrens-listener.
- Bestaande installaties zonder de nieuwe opties gebruiken automatisch 15%/15%. Opnieuw toevoegen of migreren is niet nodig; een onbekende sleutel uit een oudere versie in de opgeslagen configuratie wordt genegeerd, en een opgeslagen marge buiten het bereik wordt veilig teruggebracht naar 0 of 49.
- De berekening van `sensor.frank_current_return_price` is **niet** gewijzigd en de handmatige teruglevercorrectie blijft beschikbaar, net als de btw-optie. Zie de toelichting hieronder.

### Notes

- Onderzocht is of `sourcing_markup_price` gebruikt kan worden als automatische teruglevercorrectie, zodat de handmatige instelling zou kunnen vervallen. Verificatie tegen de live Frank Energie API wees uit dat dit veld een vast bedrag is (NL: `0.01815 EUR/kWh` op elk kwartier van elke gecontroleerde dag) dat optelt in de all-in **afname**prijs. Er is geen bewijs gevonden dat het de contractuele teruglevercorrectie is, en de openbare API biedt geen enkel terugleverveld. De automatische afleiding is daarom bewust **niet** geïmplementeerd en de handmatige teruglevercorrectie is behouden.

## [0.1.5] - 2026-08-08

### Fixed

- Scheidt het ophalen van de dagreeksen van het berekenen van het actieve kwartier. De gepubliceerde prijslijsten worden per lokale kalenderdag gecachet en alleen nog opgevraagd wanneer ze ontbreken; elke andere kwartiertik leidt het actieve blok lokaal af uit de cache ([#3](https://github.com/Bennie-JC/ha-frank-quarter-prices/issues/3)).
- Een mislukte aanvraag voor morgen zet niet langer álle prijssensoren op `unavailable`. Zolang er geldige prijsdata voor vandaag bekend is, blijft de integratie bruikbaar en blijft de actuele kwartierprijs kloppen.
- Vraagt de prijzen voor morgen pas vanaf 12:00 lokale tijd op. Frank publiceert ze kort na de SDAC-veiling van 12:00 CET, dus elke aanvraag daarvoor was een gegarandeerde misser.
- De rollover om middernacht kost geen enkele aanvraag meer: de dag die 's middags al als "morgen" is opgehaald, wordt zonder netwerkverkeer de nieuwe "vandaag".
- Beoordeelt de volledigheid van een dag aan de hand van de echte lokale dagrand in plaats van een vast aantal blokken, zodat de 23-uurs- en 25-uursdag rond de zomertijdovergang correct valideren. De vergelijking gebeurt op absolute UTC-momenten, zodat het dubbel voorkomende uur bij de overgang naar wintertijd correct wordt afgehandeld.
- Een onvolledig antwoord wordt niet als volledige dag gecachet en vervangt nooit een reeds bekende volledige dag. Twee onvolledige antwoorden worden per tijdvak samengevoegd in plaats van dat de langste lijst wint, zodat een verse deellijst die het actieve kwartier wél bevat niet verloren gaat.
- De actuele prijs wordt nooit afgeleid uit een ander kwartier dan het kwartier dat op dat moment werkelijk actief is. Ontbreekt het actieve kwartier in de bekende data, dan is de actuele prijs onbekend in plaats van een verouderde of toekomstige waarde.

### Changed

- Het aantal API-aanvragen daalt fors. Onder normale omstandigheden wordt elke kalenderdag ongeveer één keer opgehaald in plaats van bij iedere kwartiertik; bij storingen kan het herhaalgedrag dat aantal legitiem verhogen.
- README: de publicatietijd van de prijzen voor morgen gecorrigeerd naar de vroege middag in plaats van ~15:00 CET.
- README: HACS Default duidelijker als primaire installatie- en updatemethode, en een "Add Integration"-knop van My Home Assistant toegevoegd voor het toevoegen van de integratie na installatie.

### Compatibility

- Bestaande entity ID's, unique ID's, namen, eenheden, device classes, attributen en de today/tomorrow-datastructuren zijn ongewijzigd. De kwartiergrens-synchronisatie uit v0.1.4 blijft intact. Alleen het ophaalgedrag van de coordinator is aangepast.

## [0.1.4] - 2026-08-07

### Fixed

- Synchroniseert prijsupdates nu met de echte kwartiergrenzen (`:00`/`:15`/`:30`/`:45`) in plaats van met een vrijlopend interval dat begon te tellen vanaf het opstarten van de integratie ([#2](https://github.com/Bennie-JC/ha-frank-quarter-prices/issues/2)).
- Voorkomt dat de actuele kwartierprijs tot circa 14 minuten kan achterlopen op de werkelijke kwartiergrens.
- Verbetert de today/tomorrow-rollover rond middernacht: de nieuwe dag wordt vlak na 00:00 opgehaald in plaats van pas tot ~14 minuten later.

### Compatibility

- Bestaande entity ID's, unique ID's, de volledige 15-minutenprijsdata, de today/tomorrow-datastructuren en de EMS-facing attributen zijn ongewijzigd. Alleen het ververstijdstip van de coordinator is aangepast.

## [0.1.3] - 2026-07-22

### Added

- Home Assistant Energy Dashboard support for `sensor.frank_current_price` as the current electricity purchase-price entity.
- New `sensor.frank_current_return_price` entity exposing the estimated current electricity feed-in price.
- Configurable **feed-in adjustment** through the integration options (positive, negative or zero; default `0.0 EUR/kWh`).
- Optionele instelling toegevoegd om 21% btw toe te passen op de berekende terugleverprijs (standaard uitgeschakeld).
- Dutch and English translations for the new options.
- Energy Dashboard setup instructions and a feed-in-price calculation example in the README.

### Changed

- The feed-in-price calculation uses the Frank API's verified raw `market_price` field (the EPEX/spot price, excluding VAT, energy tax and markups) plus the configured adjustment. It does **not** assume VAT (`market_price_tax`), energy tax or purchase-price components apply to electricity returned to the grid. Verified against the live public API: `market_price_tax` is 21% VAT charged on the purchase side, and the public endpoint exposes no explicit feed-in-price field.

## [0.1.2] - 2026-06-21

### Added

- Dutch translation file (`translations/nl.json`) for the config flow.
- GitHub Actions workflows: Hassfest validation, HACS validation, and Ruff lint.
- `country` key in `hacs.json` (`["NL", "BE"]`) for HACS Default inclusion.
- Brands-ready PNG assets documented in the README for the Home Assistant Brands submission.

### Changed

- README fully translated to Dutch and optimized for SEO (Frank Energie, kwartierprijzen, EMS, batterijoptimalisatie).
- Clarified the integration delivers **quarter-hour (15-minute) prices**, never hourly prices (hourly is only a fallback).

### Fixed

- Removed the unsupported `domains` key from `hacs.json` so HACS manifest validation passes.
- Documented the exact fix for the *"icon not available"* entry in the Home Assistant integration list (Home Assistant Brands submission).

## [0.1.1] - 2026-06-14

### Added

- ApexCharts dashboard examples for today and tomorrow price charts (`examples/apexcharts_frank_prices_today.yaml`, `examples/apexcharts_frank_prices_tomorrow.yaml`).
- README instructions for the ApexCharts Card and Config Template Card.
- Integration icon/logo assets (`icons/icon.svg`, `icons/logo.svg`) and Home Assistant Brands guidance.

### Changed

- Integration manufacturer/service info changed to **Jouw Cloud B.V.** (device model is now "Frank Energie Market Prices"; `sw_version` reflects the integration version).
- Documentation improved for EMS usage and quarter-hour price attributes.

### Fixed

- Clarified chart usage with `sensor.frank_prices_today` attributes — each block from `attributes.prices` is rendered individually (96 bars for quarter-hour data, 24 for hourly).

## [0.1.0] - 2026-06-14

Initial release.

### Added

- Config-flow setup for the Frank Energie market price integration (NL default, optional BE via `x-country`).
- Native **quarter-hourly (15-minute, 96 blocks/day)** electricity prices via the public `marketPrices(date:, resolution: PT15M)` GraphQL query, with automatic fallback to hourly data when Frank has not published quarter-hour prices for a day.
- `DataUpdateCoordinator` polling every 15 minutes for today's and tomorrow's prices.
- Current price sensor with the full price breakdown as attributes.
- Today and tomorrow price sensors exposing the full raw price arrays as attributes.
- Cheapest and most-expensive price and start-time sensors for today and tomorrow.
- Binary sensor indicating whether tomorrow's prices are available (typically after ~15:00 CET).
- Diagnostics support with secrets redacted.
- HACS compatibility (`hacs.json`) and documentation.

[0.1.7]: https://github.com/Bennie-JC/ha-frank-quarter-prices/releases/tag/v0.1.7
[0.1.6]: https://github.com/Bennie-JC/ha-frank-quarter-prices/releases/tag/v0.1.6
[0.1.5]: https://github.com/Bennie-JC/ha-frank-quarter-prices/releases/tag/v0.1.5
[0.1.4]: https://github.com/Bennie-JC/ha-frank-quarter-prices/releases/tag/v0.1.4
[0.1.3]: https://github.com/Bennie-JC/ha-frank-quarter-prices/releases/tag/v0.1.3
[0.1.2]: https://github.com/Bennie-JC/ha-frank-quarter-prices/releases/tag/v0.1.2
[0.1.1]: https://github.com/Bennie-JC/ha-frank-quarter-prices/releases/tag/v0.1.1
[0.1.0]: https://github.com/Bennie-JC/ha-frank-quarter-prices/releases/tag/v0.1.0