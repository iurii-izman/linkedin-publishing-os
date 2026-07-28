# LinkedIn Publishing OS

Связанный пакет проектной документации для разработки приложения публикации контента в личный профиль LinkedIn с помощью Codex/ChatGPT.

**Версия спецификации:** 1.0  
**Дата актуализации внешних API:** 23 июля 2026  
**Рабочее название репозитория:** `linkedin-publishing-os`

## Решение в одном абзаце

Система строится как гибрид:

- **FastAPI-сервис** владеет доменной моделью, PostgreSQL, OAuth, токенами, state machine и единственной интеграционной границей с LinkedIn;
- **n8n** собирает источники, запускает генерацию, связывает Telegram, планирует операции и вызывает API сервиса;
- **Telegram** используется как human-in-the-loop интерфейс согласования;
- **PostgreSQL** является единственным источником состояния;
- публикация выполняется только через официальный LinkedIn API, без Playwright, Selenium, scraping и имитации действий в браузере.

Сначала выполняется короткий **Stage 0 API Feasibility Spike**. Stage 1 начинается
только после реального owner-operated подтверждения OAuth, `w_member_social` и
текстовой публикации. Недоступность изображения должна быть записана как ограничение
и может привести к `GO_WITH_LIMITATIONS`; она не может быть скрыта.

## Что входит в пакет

| Файл | Назначение |
|---|---|
| [`MASTER_SPEC.md`](MASTER_SPEC.md) | Консолидированный источник требований и архитектуры |
| [`AGENTS.md`](AGENTS.md) | Постоянные правила для Codex |
| [`TASKS.md`](TASKS.md) | Эпики, задачи, зависимости и критерии готовности |
| [`docs/01_PRD.md`](docs/01_PRD.md) | Product Requirements Document |
| [`docs/02_ARCHITECTURE.md`](docs/02_ARCHITECTURE.md) | Архитектура и границы компонентов |
| [`docs/03_DOMAIN_MODEL.md`](docs/03_DOMAIN_MODEL.md) | Состояния, сущности, инварианты и данные |
| [`docs/04_LINKEDIN_INTEGRATION.md`](docs/04_LINKEDIN_INTEGRATION.md) | OAuth, Posts/Images/Documents API и ошибки |
| [`docs/05_N8N_WORKFLOWS.md`](docs/05_N8N_WORKFLOWS.md) | Контракты и логика workflow |
| [`docs/06_CONTENT_ENGINE.md`](docs/06_CONTENT_ENGINE.md) | Evidence, генерация, QA и контентная политика |
| [`docs/07_SECURITY.md`](docs/07_SECURITY.md) | Threat model, секреты, приватность и hardening |
| [`docs/08_TEST_STRATEGY.md`](docs/08_TEST_STRATEGY.md) | Полная тестовая стратегия |
| [`docs/09_OPERATIONS.md`](docs/09_OPERATIONS.md) | Развёртывание, наблюдаемость, backup и runbooks |
| [`docs/10_IMPLEMENTATION_PLAN.md`](docs/10_IMPLEMENTATION_PLAN.md) | Последовательность реализации и stage gates |
| [`docs/11_CODEX_RUNBOOK.md`](docs/11_CODEX_RUNBOOK.md) | Как вести разработку с Codex |
| [`docs/12_RISKS_AND_SOURCES.md`](docs/12_RISKS_AND_SOURCES.md) | Риски, допущения и официальный source registry |
| [`docs/13_ACCEPTANCE_CHECKLISTS.md`](docs/13_ACCEPTANCE_CHECKLISTS.md) | Приёмочные чек-листы |
| [`docs/00_SPEC_AUDIT_REPORT.md`](docs/00_SPEC_AUDIT_REPORT.md) | Фактический аудит пакета и исправления |
| [`docs/STAGE0_MANUAL_ACTIONS.md`](docs/STAGE0_MANUAL_ACTIONS.md) | Ручные действия владельца для безопасного spike |
| [`docs/STAGE1_VERTICAL_MVP.md`](docs/STAGE1_VERTICAL_MVP.md) | Локальный запуск, exact approval, idempotency, recovery и controlled live checkpoint |
| [`docs/feasibility_report.md`](docs/feasibility_report.md) | Шаблон фактических результатов Stage 0 |
| [`specs/openapi.yaml`](specs/openapi.yaml) | Целевой внутренний HTTP API |
| [`specs/schema.sql`](specs/schema.sql) | Референсная PostgreSQL-схема |
| [`data/candidate_evidence_seed.yaml`](data/candidate_evidence_seed.yaml) | Начальная доказательная база для постов |
| [`data/content_policy.yaml`](data/content_policy.yaml) | Контентные правила и пропорции |
| [`prompts/`](prompts/) | Готовые промпты для этапов и LLM-узлов |

## Иерархия источников истины

При противоречии использовать следующий порядок:

1. `AGENTS.md` — ограничения разработки и безопасности.
2. `MASTER_SPEC.md` — продуктовые и архитектурные решения.
3. ADR в `docs/adr/`.
4. `specs/openapi.yaml` и `specs/schema.sql` — машинные контракты.
5. Подробные документы в `docs/`.
6. `TASKS.md` — план, но не замена требованиям.
7. n8n workflow JSON и код — реализация, которая обязана соответствовать документам.

## Как начать разработку

1. Создать приватный репозиторий `linkedin-publishing-os`.
2. Распаковать этот пакет в корень.
3. Открыть репозиторий в Codex.
4. Скопировать `.env.example` в локальный `.env`, не добавляемый в Git.
5. Выполнить `uv sync --frozen --dev`.
6. Следовать [`docs/STAGE0_MANUAL_ACTIONS.md`](docs/STAGE0_MANUAL_ACTIONS.md).
7. Зафиксировать фактические возможности LinkedIn в `docs/feasibility_report.md`.
8. Только владелец может разрешить Stage 1 после `GO` или
   `GO_WITH_LIMITATIONS`.

Локальные проверки:

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest -q
uv run python scripts/validate_repository.py
```

Stage 1 запускается только после явной миграции PostgreSQL. Полная инструкция,
безопасные CLI-команды и offline E2E описаны в
[`docs/STAGE1_VERTICAL_MVP.md`](docs/STAGE1_VERTICAL_MVP.md). Реальная публикация
по умолчанию заблокирована.

## Жёсткие ограничения

- Никакой браузерной автоматизации LinkedIn.
- Никакого автоматического networking, лайков, комментариев или сообщений.
- Никакой публикации без неизменённого одобренного текста и вложения.
- Никаких неподтверждённых профессиональных claims.
- Никаких секретов, токенов, персональных данных клиентов или реальных CRM payload в Git.
- Никакого автоматического retry после неоднозначного результата финального `POST /rest/posts`.
- Портфолио-проекты не называются коммерческими production-внедрениями.
