# 🛡️ AI Auto-Remediation Framework for GitLab CI

**AI Auto-Remediation** — это легковесный DevSecOps-инструмент для автоматического устранения уязвимостей в исходном коде с использованием больших языковых моделей (LLM) и статических анализаторов. 

Модуль интегрируется непосредственно в конвейер GitLab CI/CD, анализирует отчеты SonarCloud, генерирует безопасные патчи с помощью нейросетей (Llama 3 / Gemma 2) и создает верифицированные Merge Requests, прошедшие локальную проверку сканером Semgrep.

---

## ✨ Ключевые особенности (Features)

* **Isolated Context Mode (Гранулярный контекст):** Формирование индивидуальных промптов для каждого уязвимого файла, что кратно снижает риск "галлюцинаций" ИИ.
* **Context Window Guard:** Встроенный предохранитель, отбрасывающий файлы объемом > 500 строк для защиты от деструктивных правок и обрыва генерации.
* **Batch Remediation:** Группировка множественных исправлений в единый транзакционный Merge Request для предотвращения "спама" в репозитории.
* **Differential Validation (Defense in Depth):** Локальная проверка сгенерированных патчей сканером Semgrep. Если ИИ внедряет новую уязвимость или ломает синтаксис — пайплайн блокируется.
* **Fault Tolerance (Отказоустойчивость):** Встроенная логика Exponential Backoff для обхода лимитов провайдеров API (ошибки HTTP 429/402).

---

## ⚙️ Архитектура процесса

1. **Анализ:** `sonar-sast-check` выявляет уязвимости в ветке `main` и роняет пайплайн.
2. **Экстракция:** `ai-remediator.py` скачивает актуальный отчет по REST API SonarCloud.
3. **Генерация:** Скрипт обращается к шлюзу OpenRouter, передавая код и найденные дефекты.
4. **Фиксация:** Инструмент создает новую ветку, делает коммит и пушит код в GitLab.
5. **Верификация:** Создается Merge Request, внутри которого запускается Semgrep. Он анализирует *только измененные файлы*.
6. **Human-in-the-Loop:** Специалист по безопасности проводит финальное ревью зеленого пайплайна и нажимает "Merge".

---

## 🚀 Установка и настройка (Quick Start)

### 1. Переменные окружения (CI/CD Variables)
Для работы модуля необходимо задать следующие переменные в настройках GitLab (`Settings` -> `CI/CD` -> `Variables`):

| Переменная | Описание | Тип |
|---|---|---|
| `SONAR_TOKEN` | Токен для доступа к API SonarCloud | Masked |
| `SONAR_PROJECT_KEY` | Идентификатор вашего проекта в SonarCloud | - |
| `SONAR_ORGANIZATION_KEY` | Идентификатор организации в SonarCloud | - |
| `OPENROUTER_API_KEY` | API-ключ для доступа к LLM шлюзу | Masked |
| `GITLAB_AI_TOKEN` | Project Access Token (права: `api`, `write_repository`) | Masked |

### 2. Подключение к вашему `.gitlab-ci.yml`
Пример интеграции фреймворка в существующий проект (см. файл `example-gitlab-ci.yml`):

```yaml
include:
  # Подключаем шаблон аудита (путь к вашему репозиторию с шаблонами)
  - project: 'your-group/ci-templates'
    file: 'sonar-check.yml'

ai-remediation:
  stage: security
  image: python:3.11-slim
  rules:
    - if: '$CI_COMMIT_REF_NAME == "main" && $CI_PIPELINE_SOURCE == "push"'
      when: on_failure
  before_script:
    - apt-get update && apt-get install -y git curl
    - pip install -r requirements.txt
    - curl -O "https://gitlab.com/your-group/ci-templates/-/raw/main/ai-remediator.py"
  script:
    - python3 -u ai-remediator.py

ai-code-validation:
  stage: test
  image: python:3.11-slim
  rules:
    - if: '$CI_COMMIT_REF_NAME =~ /^ai-/ && $CI_PIPELINE_SOURCE == "push"'
  script:
    - apt-get update && apt-get install -y git
    - pip install semgrep
    - git config --global --add safe.directory $CI_PROJECT_DIR
    - git fetch origin main
    - CHANGED_FILES=$(git diff --name-only origin/main...HEAD | tr '\n' ' ')
    - if [ -n "$CHANGED_FILES" ]; then semgrep scan --config auto --error $CHANGED_FILES; fi
