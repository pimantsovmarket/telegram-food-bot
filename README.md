# СУТЬ Control Center

Technical ID: `sut_control_center`.

Это чистый foundation системы управления Ozon-бизнесом. Текущий этап содержит только единую конфигурацию, безопасное логирование, базовый Ozon Seller API client, Telegram bootstrap и healthcheck.

Мониторинг цен, browser scraping, Playwright, AI, actions и бизнес-модули в foundation не входят.

## Запуск

1. Создайте virtual environment.
2. Установите проект: `pip install -e .`
3. Скопируйте `.env.example` в `.env` и заполните его локально.
4. Запустите `sut-control-center`.

Тесты запускаются обычной командой `pytest`.
