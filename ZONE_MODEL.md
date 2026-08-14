# Zone Model 1.0.0

Нормативная семантика Stage 8.2 Map Zone Engine (`src/stratweb/zones/`).
Schema `1.0.0`, resolution rule `point_in_polygon_v1`, validation rule
`simple_polygon_v1`.

## Принципы

- Зона — это **доказанная** именованная область карты. Координата вне любого
  полигона даёт `unknown`; «ближайшая предполагаемая зона» запрещена.
- Полигоны авторизуются в **мировых координатах Source 2**, а не в пикселях:
  мировые координаты — физическое свидетельство матча, поэтому смена map
  revision или ассета никогда не переинтерпретирует уже вычисленный результат.
- Каждый `ZoneSetDefinition` привязан к `map_name` + `map_revision` и имеет
  детерминированный SHA-256 fingerprint (`canonical_json`), который обязан
  закрепляться в любом run, использующем зоны.
- Движок чистый и детерминированный: без парсера, БД, сети, времени и LLM.

## Контракты

- `ZonePolygon` — простой полигон (≥3 вершин, конечные координаты), опционально
  ограниченный по высоте `min_z`/`max_z` (этажи Nuke).
- `ZoneDefinition` — `zone_id` (slug), имя, `kind`
  (`bombsite|spawn|pathway|chokepoint|area`), уровень (`MapLevel`), `priority`,
  полигоны, статус верификации (`proposed|overlay_verified|demo_validated`) и
  `source` (происхождение границ).
- `ZoneResolution` — `resolved` с данными зоны либо `unknown`; всегда несёт
  `rule_version` и warnings.

## Правила resolution (`point_in_polygon_v1`)

1. Нефинитные координаты → `unknown` + `nonfinite_world_coordinate`.
2. Точка на ребре или вершине полигона считается **внутри** — правило тотально
   и не зависит от направления обхода при floating point на общей границе.
3. Полигон с `min_z`/`max_z` совпадает только при доказанном `z` в границах.
   Если `z` отсутствует, зона **не** совпадает и добавляется warning
   `zone_z_unproven:<zone_id>` — высотное попадание не доказано.
4. При нескольких совпадениях выбирается зона с большим `priority`, затем с
   меньшей суммарной площадью (shoelace), затем с меньшим `zone_id`; добавляется
   warning `overlapping_zones_resolved_by_priority`.

## Валидация и диагностика

- `validate_zone_set` (`simple_polygon_v1`) возвращает детерминированные коды:
  дубликаты `zone_id`, нулевую площадь, повторные вершины, рёбра нулевой
  длины, самопересечения не-соседних рёбер, инвертированные z-границы и
  несовпадение map/revision между зоной и набором. Редактор отклоняет такой
  proposal до записи на диск; явную closing-вершину повторять нельзя, потому
  что замыкающее ребро хранится неявно.
- `sampled_coverage` — доля детерминированной мировой сетки (по калиброванному
  прямоугольнику картинки), резолвящейся в любую зону. Это диагностика
  прогресса авторинга, а не утверждение о проходимости пространства.

## Статус авторинга

Полигоны карт добавляются поэтапно: сначала `proposed` (по overview-ассету и
Valve-якорям), затем `overlay_verified` через ручной developer overlay
(`/ui/dev/zones/{map}` при `STRATWEB_MAP_DEVELOPER_MODE=true`), затем
`demo_validated` по реальным демкам.

Авторские наборы (`src/stratweb/zones/definitions/`):

- `de_mirage` @ `cs2-1.41.7.1-d263aa1118fb` — **33 зоны, OVERLAY_VERIFIED**.
  Все границы расставлены пользователем вручную в overlay-редакторе
  (сохранено 2026-07-26T23:20:49Z, ~40 минут ручной разметки). Evidence:
  freeze-end центроиды сторон матча `e0f188cf` и Valve-якоря bombA/bombB
  резолвятся в свои зоны (`tests/test_zones.py`). Принятая разметка
  заархивирована в `zone_proposals/de_mirage.accepted-2026-07-27.json`.
- `de_anubis` @ `cs2-1.41.7.1-d263aa1118fb` — **34 зоны, OVERLAY_VERIFIED**.
  Ручная схема сохранена 2026-08-01T19:06:34.608089+00:00 и закреплена в
  `src/stratweb/zones/definitions/anubis.py`. Технические суффиксы `_2`,
  созданные редактором после перерисовки зон, удалены из постоянных `zone_id`.
  Технические closing-точки и локальные петли редактора удалены по
  `simple_polygon_v1`; остальные ручные границы сохранены. Fingerprint:
  `229855ed871084178b2c95351816450818387496268ac615ec6bf26d1338b0eb`.
- `de_cache` @ `cs2-1.41.7.1-d263aa1118fb` — **36 зон, OVERLAY_VERIFIED**.
  Ручная схема сохранена 2026-08-01T19:34:07.329855+00:00 и закреплена в
  `src/stratweb/zones/definitions/cache.py`. Valve-якоря обоих спавнов и
  bombsite A/B и закреплённые точки Mid/Garage/A Main/B Main/Heaven резолвятся
  в ожидаемые зоны. Технические closing-точки и локальные петли редактора
  удалены по `simple_polygon_v1`. Fingerprint:
  `73aa9b028c38975284425041f544c1d65164d212628926b4d8e3362d3b7bc30c`.

На baseline 2026-08-02 все восемь зарегистрированных authored zone sets
проходят `simple_polygon_v1`. Эта структурная проверка не заменяет
`DEMO_VALIDATED`: Anubis и Cache остаются `OVERLAY_VERIFIED`, пока их map
revision и зоны не подтверждены реальными демками.

## Persisted Zone Assignment Run 1.0.0

Stage 8.2B материализует результат `point_in_polygon_v1` для каждого
`SpatialSnapshot`. Это отдельный immutable слой, а не изменение исторического
Spatial run:

```text
Canonical match
  → exact Temporal run
  → exact Spatial run
  → exact Zone Assignment run
       → one assignment per Spatial snapshot
```

Run закрепляет:

- `spatial_run_id`, Spatial fingerprint/schema/rule и dataset fingerprint;
- canonical map name, selected map revision, map-definition fingerprint и
  `proven|unproven|unsupported`;
- zone-set SHA-256, zone schema `1.0.0`, resolution/validation rule versions;
- assignment schema `1.0.0`, rule `snapshot_point_to_zone_v1` и config SHA-256.

Результаты:

- `resolved` — координата доказанно внутри конкретного полигона;
- `unknown` — координаты доступны, но ни один полигон не совпал;
- `unavailable` — нет позиции, точной map semantics/zone set либо политика
  запретила unproven map revision.

`proposed` polygons исключаются из persisted evidence. Если весь набор ещё
`proposed`, run получает `zone_geometry_unverified`, все assignments становятся
`unavailable`, и названия этих зон в playback не показываются. Геометрия должна
быть минимум `overlay_verified`.

Каждый assignment хранит `match_id`, `round_id`, `round_number`, `tick`,
`participant_id`, `spatial_snapshot_id`, точный run и warnings. Имена/вид зон
копируются в строку результата, поэтому изменение авторского набора не меняет
смысл старого run. Coverage считается только как `resolved / position_available`;
неизвестный denominator не подменяется числом.

DuckDB migration 017 создаёт `zone_assignment_runs` и `zone_assignments`.
API и playback всегда выбирают zone run для того же exact `spatial_run_id` и
никогда не смешивают два runs на одной странице.
