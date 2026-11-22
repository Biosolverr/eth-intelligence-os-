## Overview

ETH Intelligence OS теперь включает **Social Intelligence Layer** — дополнительный уровень понимания рынка, основанный на социальных данных, нарративах и потоках внимания.

Рынок криптовалют реагирует на информацию **до того**, как она отражается в ценовых данных.  Нарративы формируются за часы или дни до движения цены.  Social Intelligence Layer позволяет системе читать эти сигналы на уровне формирования, а не на уровне реакции.

---

## Архитектура

### До (Market Intelligence OS)

```
Price / Flows / Derivatives / Macro
              ↓
        Feature Engine
              ↓
  Macro · Flow · Manip · Quant · Risk
              ↓
        Consensus Engine
              ↓
      Final Market Assessment
```

### После (Market + Social Intelligence OS)

```
Price / Flows / Derivatives / Macro
                Social Data
                    ↓
          Unified Feature Engine
                    ↓
  Macro · Flow · Manip · Quant · Risk
     (каждый агент читает социальные фичи)
                    ↓
             Consensus Engine
                    ↓
         Final Market Assessment
```

Социальные данные становятся **first-class intelligence source** — они инжектируются в feature dict до того, как агенты запускаются, а не добавляются как отдельный голос в консенсус.

---

## Структура модуля

```
data/social/
├── __init__.py
├── schemas.py          # Pydantic-модели: RawSocialPost, SocialFeatures, Narrative, SocialSnapshot
├── collector.py        # Параллельный сбор из всех провайдеров
├── processor.py        # Трансформация постов → фичи + нарративы
└── providers/
    ├── __init__.py
    ├── base.py         # Абстрактный базовый класс SocialProvider
    ├── openklav.py     # OpenKlav (crypto-native аналитика)
    ├── hermes.py       # Hermes (narrative-level бандлы)
    └── rss.py          # RSS/News (CoinDesk, Cointelegraph, etc.)
```

---

## Pipeline шаг за шагом

### Шаг 1 — Сбор (SocialCollector)

`SocialCollector` запускает все провайдеры параллельно через `asyncio.gather`.  Каждый провайдер возвращает `List[RawSocialPost]`.  Посты дедуплицируются по `id`.

```python
async with SocialCollector() as collector:
    posts, coverage = await collector.collect_with_coverage(asset="ETH")
```

Провайдер падает → возвращает `[]`, pipeline не прерывается.

### Шаг 2 — Обработка (SocialProcessor)

Из сырых постов вычисляются нормализованные метрики:

```python
processor = SocialProcessor(previous_features=prev_snapshot.features)
features, narratives = processor.process(posts)
features = SocialProcessor.enrich_features_with_narratives(features, narratives)
```

**Сентимент** = 80% провайдерский + 20% эвристический (keyword lexicon).

**Engagement weight** = `log(1 + likes + shares×2 + comments + views/100)` — логарифмическое сжатие, чтобы вирусные посты не доминировали.

**Velocity** = `attention_score[now] - attention_score[prev]` — скорость роста внимания.

**Acceleration** = `velocity[now] - velocity[prev]` — является ли рост ускоряющимся.

### Шаг 3 — Детекция нарративов

Keyword-based clustering по таксономии из 10 нарративных категорий:

| Нарратив | Ключевые слова |
|---|---|
| ETH ETF accumulation | etf, institutional, blackrock, fidelity |
| Base ecosystem growth | base, base l2, base ecosystem |
| L2 expansion | l2, rollup, arbitrum, optimism, zk |
| Staking yield | staking, stake, yield, lido, eigenlayer |
| DeFi resurgence | defi, tvl, liquidity, amm |
| Regulatory clarity | regulation, sec, approved, legal |
| Macro risk-off | recession, inflation, rate, fed |
| Whale activity | whale, large wallet, dormant |
| Technical breakout | breakout, resistance, support, rsi |
| Stablecoin demand | stablecoin, usdc, dai |

Каждый нарратив получает `strength` (доля дискурса) и `velocity` (скорость распространения).

### Шаг 4 — Инжекция в Feature Engine

`inject_social_features(base_dict, social_features)` мерджит `SocialFeatures` в общий feature dict.  Существующие агенты игнорируют незнакомые ключи — **нет breaking changes**.

```python
SocialFeatures fields injected:
  sentiment_score, bullish_ratio, bearish_ratio
  engagement_velocity, attention_score, attention_acceleration
  narrative_strength, narrative_concentration
  trend_momentum, influencer_alignment
  bot_probability, engagement_anomaly
  panic_score, euphoria_score
  post_count, unique_sources, data_quality
```

---

## Как социальные сигналы потребляются агентами

### QuantAgent
Читает: `sentiment_score`, `attention_acceleration`, `trend_momentum`

- Сильный бычий сентимент + trend momentum → +10 очков к tech_score
- Ускоряющееся внимание (attention_acceleration > 0.2) → +0.05 confidence
- Затухающее внимание → -0.05 confidence

### ManipAgent
Читает: `bot_probability`, `engagement_velocity`, `influencer_alignment`, `engagement_anomaly`

- Bot probability > 30% → +20 очков к risk score
- Engagement anomaly > 0.5 (аномальный перекос influencer/обычные) → +15
- Influencer bullish + цена падает → детектируется narrative pump (+15)

### RiskAgent
Читает: `panic_score`, `euphoria_score`

- Panic score > 0.5 → +15 к cascade risk (толпа бежит → ликвидации)
- Euphoria score > 0.6 → +10 (переполненные лонги = потенциальный flash crash)

### FlowAgent
Читает: `narrative_strength`, `attention_score`

- Narrative strength > 0.6 + attention > 0.4 + bullish flow → +0.08 confidence
- Высокое внимание без нарратива (спекулятивный spike) → -0.08 confidence

---

## Нарративы vs. Сентимент — ключевое различие

**Сентимент** — это *тон* разговора.  «Рынок настроен медвежьи» — это сентимент.

**Нарратив** — это *сюжет*, который движет рынком.  «Эфир станет settlement layer для всех L2, поэтому ETH accumulation неизбежен» — это нарратив.

Нарративы:
- Предсказывают движение за дни до исполнения
- Имеют `velocity` — можно видеть их рождение и смерть
- Влияют на capital flows (деньги текут в ETH → Base выстреливает)
- Создают самосбывающиеся пророчества (FOMO-driven pumps)

Система детектирует нарративы через кластеризацию топиков и отслеживает `velocity` как производную `strength` во времени.

---

## Добавление нового провайдера

1. Создать файл в `data/social/providers/myprovider.py`
2. Наследовать `SocialProvider`
3. Имплементировать `collect(asset: str) -> List[RawSocialPost]`
4. Зарегистрировать в `data/social/providers/__init__.py`
5. Добавить в `_default_providers()` в `data/social/collector.py`

```python
# Минимальный пример
class TwitterProvider(SocialProvider):
    name = "Twitter/X"
    source_tag = "twitter"

    async def collect(self, asset: str = "ETH") -> List[RawSocialPost]:
        # fetch tweets via Twitter API v2
        tweets = await self._fetch_tweets(f"#{asset} OR $ETH")
        return [self._parse_tweet(t) for t in tweets]
```

Провайдер автоматически получает:
- Safe collection wrapper (исключения не ломают pipeline)
- Influencer classification (по `author_followers`)
- Base bot heuristic (переопределить `_is_bot()` для platform-specific логики)

---

## Использование

### Только market data (существующее поведение)
```bash
python -m core --input input.json
```

### С социальным слоем
```bash
python -m core --input input.json --social
```

### Программный API
```python
import asyncio
from core import run_pipeline_async

result = asyncio.run(run_pipeline_async(raw_data, collect_social=True))

# Social summary
print(result["social"])          # метрики сбора
print(result["narratives"])      # детектированные нарративы

# Social-скорректированные базовые метрики
print(result["base_scores"]["wdi_final"])          # WDI + social adj
print(result["base_scores"]["social_wdi_adj"])     # величина корректировки
print(result["base_scores"]["confidence_final"])   # conf + social adj
```

### Standalone social pipeline
```python
import asyncio
from data.social.collector import SocialCollector
from data.social.processor import SocialProcessor

async def get_social_snapshot(asset="ETH"):
    async with SocialCollector() as collector:
        posts, coverage = await collector.collect_with_coverage(asset=asset)
    
    processor = SocialProcessor()
    features, narratives = processor.process(posts)
    features = SocialProcessor.enrich_features_with_narratives(features, narratives)
    
    return features, narratives

features, narratives = asyncio.run(get_social_snapshot())
print(f"Sentiment: {features.sentiment_score:+.2f}")
print(f"Top narrative: {narratives[0].narrative} (strength={narratives[0].strength:.2f})")
```

---

## Конфигурация API ключей

```bash
# .env или environment variables
OPENKLAV_API_KEY=ok_live_...
HERMES_API_KEY=hm_live_...
```

Без ключей провайдеры возвращают реалистичный stub-data — pipeline работает полностью в development mode.

---

## Запланированные провайдеры

| Провайдер | Источник | Статус |
|---|---|---|
| OpenKlav | Twitter/X, Telegram, Reddit агрегация | ✅ Реализован |
| Hermes | Narrative bundles | ✅ Реализован |
| RSS/News | CoinDesk, Cointelegraph, The Block | ✅ Реализован |
| Twitter/X | Прямой API v2 | 🔜 Planned |
| Reddit | r/ethereum, r/ethfinance | 🔜 Planned |
| Telegram | Public channels через MTProto | 🔜 Planned |
| AI Research | GPT-4 summaries of research feeds | 🔜 Planned |
ading SOCIAL_INTELLIGENCE.md…]()
