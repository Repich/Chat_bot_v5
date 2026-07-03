# Raw Manifest — Wiki Язык 1С

## Storage Policy

- Полные raw-исходники официальной документации и книг хранятся вне Nextcloud.
- В этом проекте хранится только metadata: путь, URL, размер, checksum и timestamp.
- Cookies, session state, логины и пароли не сохраняются.

## Runtime Root

- Runtime raw root: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/`
- Current source root: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-v8327doc/developer-guide/`
- Runtime manifest: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-v8327doc/developer-guide/manifest.json`

## Captures

### its-1c-v8327doc-dev-intro

- Title: `Введение`
- Platform version: `8.3.27`
- Page URL: `https://its.1c.ru/db/v8327doc/content/45/1`
- Captured at UTC: `2026-04-25T13:54:15+00:00`
- HTML: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-v8327doc/developer-guide/developer-guide-introduction.html`
- HTML bytes: `86512`
- HTML sha256: `71a3e5dda326a725f0b8387a1540a0d0120656d9086ba547f396acd61d7015a9`
- Text: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-v8327doc/developer-guide/developer-guide-introduction.txt`
- Text bytes: `38775`
- Text chars: `21891`
- Text sha256: `23b65e346ea0123551391f5524f3129dc95e57fe486c3b37a6718e56c86be9b7`

### its-1c-v8327doc-dev-chapter-1

- Title: `Глава 1. Концепция системы`
- Platform version: `8.3.27`
- Page URL: `https://its.1c.ru/db/v8327doc/content/46/1`
- Captured at UTC: `2026-04-25T13:54:15+00:00`
- HTML: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-v8327doc/developer-guide/developer-guide-chapter-1-concept-system.html`
- HTML bytes: `163863`
- HTML sha256: `2ca001ecc4c75e16d342c128827cad00d5987fcae047af7c5c3ba834893b8fee`
- Text: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-v8327doc/developer-guide/developer-guide-chapter-1-concept-system.txt`
- Text bytes: `115435`
- Text chars: `62684`
- Text sha256: `35a49490db1bee4a50f0da614d6f85b5b7e4b727eed8ab74958f5257696dd22d`

## Batch Capture: Developer Guide Chapters 2-11

- Captured at UTC: `2026-04-25T14:13:41+00:00`
- Runtime source root: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-v8327doc/developer-guide/`
- Path convention: `<source-root>/<slug>.html`, `<source-root>/<slug>.txt`, `<source-root>/<slug>.json`
- Request pacing: one authenticated browser session, sequential chapter capture, `10-18` second pauses between chapter requests.

| Source id | Title | Slug | Page URL | Text chars | HTML bytes | Text bytes | HTML sha256 | Text sha256 |
|---|---|---|---|---:|---:|---:|---|---|
| `its-1c-v8327doc-dev-chapter-2` | `Глава 2. Работа с конфигурацией` | `developer-guide-chapter-2-configuration-work` | `https://its.1c.ru/db/v8327doc/content/47/1` | `103741` | `297426` | `188053` | `1716767f2ac659fee28c57db4081b861440cdf08a92ab6f64aee2ac9b643e45a` | `52bdc8db49990aa8abd76b5d4ca7096916f486076614323b01fa58488d1e3d46` |
| `its-1c-v8327doc-dev-chapter-3` | `Глава 3. Интерфейс приложения` | `developer-guide-chapter-3-application-interface` | `https://its.1c.ru/db/v8327doc/content/48/1` | `73040` | `208221` | `133680` | `43f544fcbb26cc4130a4e3a9281c70795d91e60bce0c4328036b37dee3810100` | `c51a1d6666fe7d3f4361d61a3934e6a1bde8d19aae095377dd6736c5e96b9f02` |
| `its-1c-v8327doc-dev-chapter-4` | `Глава 4. Встроенный язык` | `developer-guide-chapter-4-built-in-language` | `https://its.1c.ru/db/v8327doc/content/49/1` | `165910` | `493226` | `300066` | `ffd7b8c6b8339c1a3e5737f1ecd4660b12a4e7c4f05b0a99378b00083d1a8879` | `aabfcb4c9cf5cb770b97fd8a088d9dcef25c1dcbc8afbf50c1c9c993187a7c9b` |
| `its-1c-v8327doc-dev-chapter-5` | `Глава 5. Объекты конфигурации` | `developer-guide-chapter-5-configuration-objects` | `https://its.1c.ru/db/v8327doc/content/50/1` | `571671` | `1426961` | `1047586` | `b656216bbce8022544314fdc4bc989e5ecc2db2ffc9d9f2ecf2155c19133cde4` | `e64f6943edc328e6acb76229ac559268d38f77e26334b86c133c207e8bb84af0` |
| `its-1c-v8327doc-dev-chapter-6` | `Глава 6. Командный интерфейс` | `developer-guide-chapter-6-command-interface` | `https://its.1c.ru/db/v8327doc/content/51/1` | `83913` | `237761` | `153946` | `682dc8754afdbffd8f3acf9f0ae00da5423840ef2ed13c9d59a33efd2ef03d78` | `f2d97f055b8badf474fae1ae29b87c8e86be5fbb7e081b153526fd789ed996cd` |
| `its-1c-v8327doc-dev-chapter-7` | `Глава 7. Формы` | `developer-guide-chapter-7-forms` | `https://its.1c.ru/db/v8327doc/content/52/1` | `494370` | `1320602` | `906887` | `2351e6a9f9422a9064ec0a92387da3e928d63d48ed901b49dca0492295a3e03d` | `c57d095ef8dd2bd47ad4d6698389a4b8c7886f8ba378d904960c2ad1e147a677` |
| `its-1c-v8327doc-dev-chapter-8` | `Глава 8. Работа с запросами` | `developer-guide-chapter-8-queries` | `https://its.1c.ru/db/v8327doc/content/53/1` | `148198` | `484350` | `266960` | `7568a2eafc37051b5243976a48f92e5a181e100bfc1bc941d19d1924c251339d` | `8812323c93b81a0bc0211fe369a148e7c52b2256cd08009358c234a46b3741a2` |
| `its-1c-v8327doc-dev-chapter-9` | `Глава 9. Работа с данными` | `developer-guide-chapter-9-data-work` | `https://its.1c.ru/db/v8327doc/content/54/1` | `75074` | `221923` | `137027` | `37d17832f21612be8b5549684e280578ed49c6fc183adf31102ca335c7124769` | `a7c77e76dac2742858c1ee12275f5a7053f27df52e0c82f3bb01eb6a87818a93` |
| `its-1c-v8327doc-dev-chapter-10` | `Глава 10. Система компоновки данных` | `developer-guide-chapter-10-data-composition-system` | `https://its.1c.ru/db/v8327doc/content/55/1` | `219874` | `648833` | `399208` | `5a58ceadbfb00135e3bd373210a4815456766381a27c1401551879f999a98d27` | `cef5b6d1c66164a086858eef83b3f948d1a01da0587df09ccdc50544bd8b2fc7` |
| `its-1c-v8327doc-dev-chapter-11` | `Глава 11. Бухгалтерский учет` | `developer-guide-chapter-11-accounting` | `https://its.1c.ru/db/v8327doc/content/56/1` | `26683` | `85126` | `49256` | `161ef34f7ee6663398c4a23a6b8c124ba6a5599ece0831c502bfdf644f349520` | `4f0e4ba36cc943ae4281b1c04fc141b7e7743ac22a5b8eebd6a84362f0fbf558` |

## Batch Capture: Developer Guide Chapters 12-39

- Captured at UTC: `2026-04-26T05:49:36Z` - `2026-04-26T05:56:06Z`
- Runtime source root: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-v8327doc/developer-guide/`
- Path convention: `<source-root>/<slug>.html`, `<source-root>/<slug>.txt`, `<source-root>/<slug>.json`
- Request pacing: one authenticated browser session, sequential chapter capture, `10-18` second pauses between chapter requests.

| Source id | Title | Slug | Page URL | Text chars | HTML bytes | Text bytes | HTML sha256 | Text sha256 |
|---|---|---|---|---:|---:|---:|---|---|
| `its-1c-v8327doc-dev-chapter-12` | `Глава 12. Периодические расчеты` | `developer-guide-chapter-12-periodic-calculations` | `https://its.1c.ru/db/v8327doc/content/57/1` | `18350` | `44996` | `33318` | `b828a4c7d0f630aed9de2fdbe4850a9b7bad60e058aa9565c47dc0138951a588` | `879df5c4313684614f33826882a7fdeb1836cb59017b8c99187e70e1c17fbb21` |
| `its-1c-v8327doc-dev-chapter-13` | `Глава 13. Бизнес-процессы и задачи` | `developer-guide-chapter-13-business-processes-and-tasks` | `https://its.1c.ru/db/v8327doc/content/58/1` | `40415` | `116184` | `73814` | `3a330fccbc74b7c220f56107da84291aab87d81d3ed15e23c464f7d9b13b0d66` | `60352cd2f1e271539348268fe85f2e2bd557ca92681cb1293f0b730b28a96747` |
| `its-1c-v8327doc-dev-chapter-14` | `Глава 14. Анализ данных и прогнозирование` | `developer-guide-chapter-14-data-analysis-and-forecasting` | `https://its.1c.ru/db/v8327doc/content/59/1` | `48256` | `151672` | `87144` | `443b9ba09affae83a15790d425cd9f613ba0f3a57210185899d9c48fcaec4fce` | `42d23ad15d87b698f03dfc0c19f15a8adbb615df5a31759aa9cac6d99e1ebe62` |
| `its-1c-v8327doc-dev-chapter-15` | `Глава 15. Механизмы обмена данными` | `developer-guide-chapter-15-data-exchange-mechanisms` | `https://its.1c.ru/db/v8327doc/content/60/1` | `120706` | `304082` | `213517` | `538b28509dc350d2234b10aa3367b21649d0ed82f8b89abde939554365c0bdd2` | `5f867573c7fc0b707c4281061a4233d33715f4c367f4c151ee3e4d71c843a5b6` |
| `its-1c-v8327doc-dev-chapter-16` | `Глава 16. Работа с различными форматами данных` | `developer-guide-chapter-16-data-formats` | `https://its.1c.ru/db/v8327doc/content/61/1` | `251671` | `707740` | `444006` | `04c4ecb3252af69ca785fd42d7a20f9bc8472ad1a3d680fe6d8aa0f2b611f57c` | `696e5ee1551f80853fde058f27f0c42886af704b13f27188bc6a599fcfa2ecc1` |
| `its-1c-v8327doc-dev-chapter-17` | `Глава 17. Интеграция с внешними системами` | `developer-guide-chapter-17-external-systems-integration` | `https://its.1c.ru/db/v8327doc/content/62/1` | `297012` | `779889` | `518250` | `3571c58b91e3207712c62822bf01e4efb8d2eac37e46beca0db4d20e9f2ba16e` | `fd0a37b72e3b9dca326222f35ed86eb85ae4ccf1200e1fcc3c7a8d0e24d0965f` |
| `its-1c-v8327doc-dev-chapter-18` | `Глава 18. Дополнительные возможности веб-клиента` | `developer-guide-chapter-18-web-client-extra-features` | `https://its.1c.ru/db/v8327doc/content/63/1` | `22913` | `62388` | `39961` | `c4ca64c30d275041c1050a4e894a1497fbf6e486e13444e0c9eb53f2abe27cad` | `345582b81c8f8a6780ea9ca91b4575894d1358439eb11ead1d405e7ef34d9f11` |
| `its-1c-v8327doc-dev-chapter-19` | `Глава 19. Механизм заданий` | `developer-guide-chapter-19-jobs-mechanism` | `https://its.1c.ru/db/v8327doc/content/64/1` | `30285` | `75904` | `55289` | `5807ca46bcb98047e167fb7ac94e01ebf9e9ed67a4fcfe29f8a5d6aac0cff417` | `38c61a24a9b0f87eed4ae7a66b8772218a882eaaa11a3081230e28ef84bf1490` |
| `its-1c-v8327doc-dev-chapter-20` | `Глава 20. Механизм полнотекстового поиска в данных` | `developer-guide-chapter-20-full-text-search` | `https://its.1c.ru/db/v8327doc/content/65/1` | `28061` | `65957` | `51081` | `72f24bfafbc2c106fd761fe14bcbf7c1ac1b53e302038a0812add8dc52f9cab2` | `21218eef60f744c1b4317f8a30d6603cba105154e44ad88f321d14c95e5b4320` |
| `its-1c-v8327doc-dev-chapter-21` | `Глава 21. Механизм временного хранилища, работа с файлами и картинками` | `developer-guide-chapter-21-temporary-storage-files-and-pictures` | `https://its.1c.ru/db/v8327doc/content/66/1` | `41515` | `107874` | `75799` | `476d6aebac10b28f4576beb9f156891dd2eceabd8bb47383bd9dd316c5f366b5` | `ce64a24037c5c5e285ac7f20be77a52d0c403738a1ea56bea9dafe7005864146` |
| `its-1c-v8327doc-dev-chapter-22` | `Глава 22. Журнал регистрации` | `developer-guide-chapter-22-event-log` | `https://its.1c.ru/db/v8327doc/content/67/1` | `35258` | `97371` | `63813` | `0bb661a9fd71b264a00c9f3aba3ccf908c77e07498dfab64d41581cf9c7606fc` | `137663ff4d3759fd1e0c99f45668abaa7190c7775ac70e4eef13b7b836ca437e` |
| `its-1c-v8327doc-dev-chapter-23` | `Глава 23. Механизм криптографии` | `developer-guide-chapter-23-cryptography` | `https://its.1c.ru/db/v8327doc/content/68/1` | `38960` | `117385` | `70564` | `ffa588843b2190e750c390d18b49c0da8051be04b10dde327f4a5f8614aa32df` | `3892f0f18ba397a9b3ae8bfe07e3ed3ff1c4c78d9a75c2c943f838fbbf212de4` |
| `its-1c-v8327doc-dev-chapter-24` | `Глава 24. Механизм разделения данных` | `developer-guide-chapter-24-data-separation` | `https://its.1c.ru/db/v8327doc/content/69/1` | `48349` | `132499` | `87765` | `f9054f3ff1ea1e5368d980908a92df001be18ff7170517628721edb20a21e4d1` | `838d40888fd72f9df316282aa8adbd8e9a663ce8a5edcc56110aa6002b5e9315` |
| `its-1c-v8327doc-dev-chapter-25` | `Глава 25. История данных` | `developer-guide-chapter-25-data-history` | `https://its.1c.ru/db/v8327doc/content/70/1` | `40998` | `101986` | `75075` | `4b9871ff83bd29f00c627c563527ef64a204f1e070b9966f53c9b78b3dbbdeb9` | `9c9b4f6abbcc126f380d52b957fdea8372098a183e52266a0628597904482dd9` |
| `its-1c-v8327doc-dev-chapter-26` | `Глава 26. Механизм копий базы данных` | `developer-guide-chapter-26-database-copies` | `https://its.1c.ru/db/v8327doc/content/71/1` | `45485` | `107464` | `82802` | `de402db139084f157c20e2870ccda0984b1491367ed162abf7b073cf32e5e5d5` | `3b782483556ec79678248337a6e17369f096a6e3dd62b60bc36fd7a697ca5701` |
| `its-1c-v8327doc-dev-chapter-27` | `Глава 27. Глобальный поиск` | `developer-guide-chapter-27-global-search` | `https://its.1c.ru/db/v8327doc/content/72/1` | `31719` | `85398` | `57845` | `6b2b3027370119d8f7f09c3664ca05b8e9ca758f68d154a33018a351357ff4e0` | `8bc810af22c614e2253b9b68b0b87331e6822695e7e1f5864503ad8e1fd4d4c3` |
| `its-1c-v8327doc-dev-chapter-28` | `Глава 28. Разработка для мобильных устройств` | `developer-guide-chapter-28-mobile-development` | `https://its.1c.ru/db/v8327doc/content/73/1` | `581173` | `1419723` | `1041765` | `542f046a10225a9134259967b2d6c70e086892901eebc08efa3f43b1ef2c143f` | `cca468ba8f2688c08ea1b766fade664c3b9d2fa7f117bff7cf3ed0936bb1799d` |
| `its-1c-v8327doc-dev-chapter-29` | `Глава 29. Система взаимодействия` | `developer-guide-chapter-29-collaboration-system` | `https://its.1c.ru/db/v8327doc/content/74/1` | `208287` | `494388` | `377718` | `65b0d804c329bee6d3ee82e49e823f115e265bfe995e6039f2d3921011d25f05` | `3e5de722ee0f79699b0164c727bc7a85ebc956b795a10001ab8b049dd203796c` |
| `its-1c-v8327doc-dev-chapter-30` | `Глава 30. Расширение конфигурации` | `developer-guide-chapter-30-configuration-extensions` | `https://its.1c.ru/db/v8327doc/content/75/1` | `128576` | `309236` | `235295` | `a682dd4000cb4d02beeedf4f1dabe5722fe1810ebed5dbb91d938d87dc5ee6e4` | `f1b64dcb7fc1743caaa5b644c3711ce663a02efbdea14ceb7871850600145123` |
| `its-1c-v8327doc-dev-chapter-31` | `Глава 31. Отладка и тестирование прикладных решений` | `developer-guide-chapter-31-debugging-and-testing` | `https://its.1c.ru/db/v8327doc/content/76/1` | `186308` | `456030` | `335164` | `7b4c4000b20e302a6ae4bd148ff47a80ce0710e4c916f1370b37f3b79d6f9319` | `d4440998e4d07e996da92c9677209a352b770ababa88d2a5a1cf4077d887f96a` |
| `its-1c-v8327doc-dev-chapter-32` | `Глава 32. Внешние компоненты` | `developer-guide-chapter-32-external-components` | `https://its.1c.ru/db/v8327doc/content/77/1` | `25566` | `69786` | `45594` | `a464213449b18424f193681129cfe840d66c19946e58b16ee18590370f31d683` | `cb07f0e41f155a7b67602740ab6751e2c68c8de2fb542e130c7d9224f6e4b337` |
| `its-1c-v8327doc-dev-chapter-33` | `Глава 33. Особенности разработки кроссплатформенных прикладных решений` | `developer-guide-chapter-33-cross-platform-development` | `https://its.1c.ru/db/v8327doc/content/78/1` | `7096` | `18284` | `12427` | `35deb525c819a7fd5f9aa7d5a3d250f129dd38e8578a8a36a34a3281cd161c43` | `6b43d5eca7509c23b56cbc51f7094fc16669906403f56cb4230691a3dafe035d` |
| `its-1c-v8327doc-dev-chapter-34` | `Глава 34. Прочие механизмы` | `developer-guide-chapter-34-other-mechanisms` | `https://its.1c.ru/db/v8327doc/content/79/1` | `101381` | `267392` | `185188` | `a9c0e83e1950fb8cfecac6f89fd805a93d9ab439067f2f72692292d1868d9cdb` | `2a0d57f9942d09a36054df4f5602f3023a279f6c86e20c27e2c44fd490ed2249` |
| `its-1c-v8327doc-dev-chapter-35` | `Глава 35. Инструменты разработки` | `developer-guide-chapter-35-development-tools` | `https://its.1c.ru/db/v8327doc/content/80/1` | `203849` | `538868` | `369104` | `e538a11ca2d9fd4f641421a40ff98d4f1f8eb9482c15d550b3a50daaabc586bf` | `76cc0925401920a930f0be6dec28275bc8136c418cad0faeaecf8f0df194de19` |
| `its-1c-v8327doc-dev-chapter-36` | `Глава 36. Механизм сравнения и объединения конфигураций` | `developer-guide-chapter-36-configuration-compare-and-merge` | `https://its.1c.ru/db/v8327doc/content/81/1` | `46432` | `117600` | `84954` | `28a75313a5fae7bdaa6fd5205b08900e21e0ed8aa10038102be4ba3edcac1ba5` | `0d77c2289dcb39e1168362ddf5972765f800c143ac2b422e913d04961a5d30df` |
| `its-1c-v8327doc-dev-chapter-37` | `Глава 37. Групповая разработка конфигурации` | `developer-guide-chapter-37-group-development` | `https://its.1c.ru/db/v8327doc/content/82/1` | `63850` | `168950` | `114517` | `18795655921fb85e61eae595772179a6ed013c3dc220887a6de729455ba0faeb` | `f6f098cbda1f3f3f7366b71767936e4b174fa745cbb7934421d40c680820814e` |
| `its-1c-v8327doc-dev-chapter-38` | `Глава 38. Поставка и поддержка конфигурации` | `developer-guide-chapter-38-delivery-and-support` | `https://its.1c.ru/db/v8327doc/content/83/1` | `40912` | `104082` | `74634` | `9ba47b5b47b274cd41424a3292a6a24ac612dad9c3442e88c92c1f935175c404` | `c7e6dab6eabcc048698f0cffc588a7bbd1f1473ea9963abceb89bf83c20a84ba` |
| `its-1c-v8327doc-dev-chapter-39` | `Глава 39. Сервисные возможности` | `developer-guide-chapter-39-service-features` | `https://its.1c.ru/db/v8327doc/content/84/1` | `92873` | `243781` | `167369` | `85d86969543c8f93d2b30121499d119425db600e6914fe0d1f2d8ca5b137135b` | `03bc709e93c598834eeb5ec94a15e3ba3b3f345fc9e684c66c5cc057e0e72dad` |

## Batch Capture: metod8dev Developers Branch

- Source: `its-1c-metod8dev`.
- Scope: `Методическая поддержка для разработчиков и администраторов 1С:Предприятия 8` -> `Разработчикам`.
- Start URL: `https://its.1c.ru/db/metod8dev#browse:13:-1:3199`
- Captured at UTC: completed `2026-04-26T06:41:50Z`.
- Runtime source root: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-metod8dev/developers/`
- Runtime manifest: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-metod8dev/developers/manifest.json`
- Captured folders: `73`.
- Captured documents: `601`.
- Failed documents: `0`.
- Text chars total: `7392171`.
- Runtime size: about `39M`.
- Path convention: `<source-root>/doc-<doc_id>.html`, `<source-root>/doc-<doc_id>.txt`, `<source-root>/doc-<doc_id>.json`.
- Project Markdown stores only this summary and links to runtime metadata; full raw texts remain outside Nextcloud.
