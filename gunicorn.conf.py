# Gunicorn 설정 — Render 배포용
# 프록시(유튜브 자막) + GPT API 호출이 30초 이상 걸릴 수 있음

# 워커 타임아웃: 기본 30초 → 180초 (3분)
timeout = 180

# 무료 플랜(512MB RAM)에서는 워커 1개면 충분
workers = 1

# 로그 레벨
loglevel = "info"
