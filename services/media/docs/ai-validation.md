# Локальная проверка, 24 сентября 2026

Все команды ниже выполнялись локально. PR, коммит и push не создавались
по указанию владельца. Записей человеческого голоса не делали.

## Go и актуальный Python AI

```bash
cd services/media
MEDIA_AI_PYTHON=/tmp/sirena-ai-test-env/bin/python go test -race -v ./...
go vet ./...
go build -o /tmp/sirena-media ./cmd/media
```

Python окружение подготовлено с FastAPI/uvicorn; тест запускает текущий
`services/ai/app/main.py` через `scripts/ai-test-server.py` с существующими
ScriptedRecognizer + SilenceSynthesizer.

Фрагмент успешного прогона рабочего моста:

```text
call=1 turn=1 inputFrames=3 outputRTP=120 elapsed=2.378250708s simulated=true
call=1 turn=2 inputFrames=3 outputRTP=99 elapsed=1.959155917s simulated=true
call=2 turn=1 inputFrames=3 outputRTP=120 elapsed=2.38030875s simulated=true
call=2 turn=2 inputFrames=3 outputRTP=99 elapsed=1.959152583s simulated=true
PASS TestActualAIProtocol
```

По каждому звонку: 6 входных RTP-пакетов, 219 выходных; содержимое ответного
μ-law — тишина (`ff`), как требует scripted/silence. Проверены заголовки,
размеры, длительность воспроизведения, `simulated:true`, отсутствие ошибок
на JSON перед PCM и освобождение соединения между звонками.

`TestAICallCleanupAndRestartWithoutProcessRestart`: рабочие Go call service,
ARI-адаптер и AI/RTP-сессия, подставные ARI HTTP и AI WS. Три звонка на одном
RTP-порту: hangup → AI disconnect → hangup. После каждого удалены канал,
externalMedia, bridge и резерв порта. Ровно три `call.ended`, одна `media.error`.
Настоящий Asterisk этот тест не запускает.

Дополнительно проверены FIR-фильтрация и непрерывность, очередь записи,
переполнение playback, отмена устаревшего ответа, повторная HTTP-доставка
с неизменным eventId/envelope и обработка поздних событий.

## Core ingest и терминальные состояния

```bash
cd services/core
./gradlew test --tests '*VoiceTrainingIntegrationTest' \
  --tests '*SessionEventReplayTest' --no-daemon
```

Результат: `BUILD SUCCESSFUL`. Это существующие тесты текущего Core;
совместный запуск настоящего Core + Asterisk + softphone не проводился.
Отдельный Go publisher test проверяет endpoint `/internal/v1/media/events`,
корреляцию, порядок и неизменность повторяемого события.

## Что ещё требует ручной среды

Docker daemon на этой машине не запущен. Поэтому Docker image build,
живой SIP/softphone smoke и аудио с настоящими моделями не подтверждены.
`docker compose config --quiet` проходит. Сценарий проверки softphone и
команды для реальных Vosk/Piper находятся в [AI bridge](ai-websocket.md).
Это оставшаяся часть приёмки, а не результат автоматического теста.
