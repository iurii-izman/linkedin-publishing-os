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

Сначала выполняется короткий **Stage 0 API Feasibility Spike**. Полная разработка начинается только после реального подтверждения OAuth, `w_member_social`, текстовой публикации и загрузки одного изображения.

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
4. Передать Codex файл [`prompts/00_REPOSITORY_KICKOFF.md`](prompts/00_REPOSITORY_KICKOFF.md).
5. Выполнить только **Stage 0**.
6. Зафиксировать фактические возможности LinkedIn в `docs/feasibility_report.md`.
7. После успешного gate перейти к Stage 1.

## Жёсткие ограничения

- Никакой браузерной автоматизации LinkedIn.
- Никакого автоматического networking, лайков, комментариев или сообщений.
- Никакой публикации без неизменённого одобренного текста и вложения.
- Никаких неподтверждённых профессиональных claims.
- Никаких секретов, токенов, персональных данных клиентов или реальных CRM payload в Git.
- Никакого автоматического retry после неоднозначного результата финального `POST /rest/posts`.
- Портфолио-проекты не называются коммерческими production-внедрениями.
