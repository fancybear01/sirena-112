# Media Gateway

Go-сервис для локального телефонно-аудиоконтура.

Интеграции:

- Asterisk: ARI по HTTP/WebSocket и аудио по RTP;
- Kotlin Core: REST-команды и WebSocket-события;
- Python AI: двунаправленный бинарный WebSocket для PCM-аудио и JSON-метаданных.

При `call.start` Core передаёт `sessionId` и заранее созданный `aiSessionId`.
Media открывает голосовой поток в AI, преобразует RTP в PCM и обратно, а
полученные от AI транскрипты публикует в Core как `transcript.*`.

Сервис не передаёт Python SIP/ARI-управление, не обращается к PostgreSQL и не
вычисляет учебную оценку. Контракт потока: `contracts/media-ai.md`.
