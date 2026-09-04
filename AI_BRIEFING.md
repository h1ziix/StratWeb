# Stage 9.11 — локальный AI-пересказ через Ollama

## Назначение

Stage 9.11 добавляет к готовому плану короткий русскоязычный брифинг. Ollama не
парсит demo, не вычисляет статистику и не создаёт новые findings или рекомендации.
Она получает не более шести уже опубликованных детерминированных рекомендаций и
может только сократить их формулировки.

Если Ollama остановлена, модель отсутствует или ответ не прошёл проверку, обычный
отчёт продолжает работать. Неуспешный AI-ответ не сохраняется.

## Поток данных

```text
pinned strategy run
  -> validated recommendations
  -> deterministic source selection (max 6, useful/diverse patterns)
  -> compact untrusted JSON prompt
  -> local Ollama /api/chat (structured output, stream=false, temperature=0)
  -> Pydantic validation
  -> source-id / number / absolute-claim validation
  -> immutable DuckDB artifact
  -> optional coach-report card
```

## Жёсткие границы

- API Ollama принимается только на loopback HTTP (`127.0.0.1`, `localhost`, `::1`).
- В модель не отправляются demo-файлы, координаты, Steam ID и полный corpus.
- Каждый свободный текст ссылается ровно на одну исходную рекомендацию.
- Новое число разрешено только если такое же число присутствовало в соответствующем
  исходном тексте. Слова с абсолютной уверенностью и гарантией блокируются.
- Исходные numerator, denominator, frequency, sample size, limitations и evidence count
  сохраняются рядом, но модель не получает задачу их пересчитывать.
- В UI результат подписан как AI-пересказ/черновик, а не как новый анализ.
- Семантическую эквивалентность свободного текста невозможно доказать одной JSON-схемой.
  Поэтому ссылка на источник обязательна, а AI-текст не заменяет deterministic report.

## Версии и воспроизводимость

- schema: `1.0.0`;
- rule: `source_bound_rephrasing_v1`;
- prompt: `coach_briefing_ru_v3`;
- provider: `ollama`;
- generation: `temperature=0`, `seed=0`, structured non-streaming response;
- сохраняются model name и SHA-256 digest из документированного `/api/tags`.

Source fingerprint зависит от pinned strategy run, выбранных исходных рекомендаций и
версии prompt. Изменение модели, digest или prompt создаёт новый совместимый artifact;
старые результаты не смешиваются.

## Настройка

```env
STRATWEB_AI_BRIEFING_ENABLED=true
STRATWEB_OLLAMA_BASE_URL=http://127.0.0.1:11434
STRATWEB_OLLAMA_MODEL=qwen3:8b
STRATWEB_OLLAMA_TIMEOUT_SECONDS=120
```

После установки Ollama:

```powershell
ollama pull qwen3:8b
ollama list
```

Откройте готовый план соперника и нажмите `Сделать краткую версию плана`. Генерация
является localhost-only POST. Обычный просмотр отчётов остаётся read-only.

## Ручная приёмка

Перед тем как считать AI-текст основным тренерским представлением, нужно проверить
несколько реальных профилей:

1. все пункты подтверждаются открываемым источником;
2. новых чисел, игроков, оружия, зон и причин нет;
3. малая выборка не превращена в уверенный прогноз;
4. текст читается естественно на русском;
5. выключенная Ollama показывает понятную ошибку и не ломает отчёт.
