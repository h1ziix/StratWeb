# Stage 9.7.2 — Градации надёжности выборки

Этот документ — каноническая product-readiness policy StratWeb. Старые пороги в
`FINDING_READINESS.md`, `COUNTER_STRATEGY_MODEL.md`, README и плане реализации считаются
deprecated, если противоречат этой странице и `finding_readiness_v2`.

## Уровни продуктовой правды

| Уровень | Что подтверждает | Условие |
|---|---|---|
| Data imported | демка сохранена | матч существует в canonical storage |
| Structurally valid | структура пригодна для чтения | нет fatal validation errors |
| Analytics available | рассчитаны обязательные слои | Analytics, Temporal и Spatial не `unavailable` |
| Evidence sufficient | finding можно интерпретировать | readiness не `blocked`; все ограничения явны |
| Recommendation eligible | правило может создать гипотезу | finding имеет `ready` или `limited`; blocker отсутствует |
| Real-data corpus accepted | корпус принят аналитиком | Golden Corpus status `ready`, включая реальные подтверждённые матчи и labels |

`ready` означает отсутствие blocker и limitation. `limited` означает, что результат можно
использовать только с показанными ограничениями; он не должен называться полностью готовым или
доказанной привычкой. `blocked` запрещает рекомендацию. Технически валидный manifest не равен
принятому real-data corpus.

## Проблема

Прежняя проверка блокировала все рекомендации, пока в корпусе не было 20 матчей. Для
тир-2/3, FACEIT, ESEA, студенческих лиг и пракков такой корпус часто недостижим, хотя
несколько свежих демо уже дают полезные проверяемые сигналы.

## Новая политика

- 15 и больше матчей — **«Высокая статистическая надёжность»**.
- 8–14 матчей — **«Устойчивый тактический тренд»**.
- 3–7 матчей — **«Тактический тренд»**; вывод используется как гипотеза.
- 1–2 матча — **«Факты конкретной игры»**; это не доказанная привычка соперника.
- 0 матчей — данных для вывода нет.

Диапазон 8–14 закрыт отдельной подписью, чтобы классификация была полной и не имела
неопределённого промежутка.

## Поведение движка

Малый корпус и small-sample finding теперь записываются как ограничения. Они не являются
автоматическим запретом для детерминированного правила контрстратегии. Настоящие проблемы
целостности, недоступные обязательные данные и строгие source-quality проверки продолжают
блокировать публикацию.

Каждая опубликованная рекомендация сохраняет исходную статистику и evidence, получает
машиночитаемую limitation `corpus_reliability:<tier>` и показывает уровень надёжности в UI.
Размер корпуса ниже 15 отображается в validation как warning, а не blocker.

Golden Corpus использует отдельный строгий acceptance gate. Текущий repository manifest
структурно валиден, но остаётся `blocked`: подтверждённых матчей и analyst labels нет.

## Версии правил

- readiness: `finding_readiness_v2`;
- counter strategy: `counter_strategy_rules_v2`;
- strategy validation: `counter_strategy_validation_v2`;
- report presentation: `scouting_report_view_v2`, `coach_report_projection_v3`;
- stable export: schema `1.1.0`, rule `evidence_report_export_v2`.
