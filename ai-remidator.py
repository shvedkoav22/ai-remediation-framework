import json
import os
import subprocess
import requests
import sys
import time
from openai import OpenAI

def log(message):
    print(message)
    sys.stdout.flush()

# ================= НАСТРОЙКИ =================
API_KEY = os.environ.get("OPENROUTER_API_KEY")
BASE_URL = "https://openrouter.ai/api/v1"
MODEL_NAME = "meta-llama/llama-3.1-70b-instruct" 

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

def download_sonar_report():
    log("[*] Запрос отчета у SonarCloud API...")
    project_key = os.environ.get("SONAR_PROJECT_KEY")
    token = os.environ.get("SONAR_TOKEN")
    
    url = f"https://sonarcloud.io/api/issues/search?componentKeys={project_key}&resolved=false&types=VULNERABILITY"
    
    try:
        response = requests.get(url, auth=(token, ''))
        if response.status_code == 200:
            data = response.json()
            log(f"[+] Отчет получен. Всего уязвимостей в проекте: {data.get('total', 0)}")
            return data.get("issues", [])
        log(f"[-] Ошибка API Sonar: {response.status_code}")
        return None
    except Exception as e:
        log(f"[-] Исключение при связи с SonarCloud: {e}")
        return None

def fix_file_content(file_path, issues):
    if not os.path.exists(file_path):
        return False

    with open(file_path, "r", encoding="utf-8") as f:
        original_lines = f.readlines()
        original_code = "".join(original_lines)
     
    if len(original_lines) > 500:
        log(f"[!] Файл {file_path} слишком велик ({len(original_lines)} строк).")
        log("[-] Пропуск: превышен лимит строк для надежной ремедиации.")
        return False
    
    issues_text = ""
    for i, iss in enumerate(issues, 1):
        issues_text += f"Ошибка №{i}: строка {iss['line']} - {iss['message']}\n"

    log(f"[*] Отправка файла {file_path} в ИИ. Исправляем {len(issues)} ошибок...")
    
    prompt = (
        f"Ты DevSecOps эксперт. Твоя задача исправить ВСЕ уязвимости безопасности в файле: {file_path}\n\n"
        f"СПИСОК НАЙДЕННЫХ УЯЗВИМОСТЕЙ В ЭТОМ ФАЙЛЕ:\n{issues_text}\n"
        f"ИСХОДНЫЙ КОД ФАЙЛА:\n```python\n{original_code}\n```\n\n"
        "СТРОГИЕ ТРЕБОВАНИЯ:\n"
        "1. Исправь все перечисленные ошибки, используя безопасные аналоги функций.\n"
        "2. НЕ УДАЛЯЙ полезную логику, классы или импорты. Программа должна работать как прежде.\n"
        "3. Твой ответ должен содержать ПОЛНЫЙ текст файла от первой до последней строки.\n"
        "4. Верни ТОЛЬКО ЧИСТЫЙ КОД без комментариев и Markdown-разметки."
    )
    

    max_retries = 3
    for attempt in range(max_retries):
        try:
            log(f"[*] Отправка {file_path} в ИИ (Попытка {attempt+1}/{max_retries})...")
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            
            fixed_code = response.choices[0].message.content
            fixed_code = fixed_code.replace("```python", "").replace("```", "").strip()

            if len(fixed_code.split('\n')) < (len(original_lines) * 0.7):
                log(f"[-] ИИ удалил код в {file_path}. Отмена.")
                return False

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(fixed_code)
            
            return True

        except Exception as e:
            if "429" in str(e):
                wait_time = 35 # Ждем чуть больше, чем просит провайдер
                log(f"[!] Лимит запросов (429). Ждем {wait_time} секунд...")
                time.sleep(wait_time)
            else:
                log(f"[-] Ошибка ИИ: {e}")
                break # Если ошибка не 429, не пробуем снова
    return False

def finalize_remediation(fixed_count):
    """
    Создает одну ветку и один Merge Request для всех исправленных файлов.
    """
    try:
        ts = int(time.time())
        branch_name = f"ai-remediation-{ts}"
        
        log(f"[*] Финализация: Создание ветки {branch_name} и пуш изменений...")
        
        # Настройка Git (если не настроен в раннере)
        subprocess.run(["git", "config", "--global", "user.email", "ai-bot@gitlab.com"], check=True)
        subprocess.run(["git", "config", "--global", "user.name", "AI Auto-Remediator"], check=True)
        
        # Git операции
        subprocess.run(["git", "checkout", "-b", branch_name], check=True)
        subprocess.run(["rm", "ai-remidator.py", "sonar-report.json"], capture_output=True)
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", f"AI Security Patch: Fixed {fixed_count} files"], check=True)
        
        # Формируем URL для пуша
        token = os.environ.get('GITLAB_AI_TOKEN')
        host = os.environ.get('CI_SERVER_HOST')
        path = os.environ.get('CI_PROJECT_PATH')
        auth_url = f"https://oauth2:{token}@{host}/{path}.git"
        
        subprocess.run(["git", "remote", "remove", "origin"], capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", auth_url], check=True)
        subprocess.run(["git", "push", "origin", branch_name], check=True)
        
        # GitLab API для создания MR
        project_id = os.environ.get('CI_PROJECT_ID')
        api_url = os.environ.get('CI_API_V4_URL')
        url = f"{api_url}/projects/{project_id}/merge_requests"
        
        mr_data = {
            "source_branch": branch_name,
            "target_branch": os.environ.get('CI_DEFAULT_BRANCH', 'main'),
            "title": f"AI Auto-Remediation (Fixed {fixed_count} files)",
            "description": "Пакетное исправление уязвимостей, сгенерированное ИИ на базе отчета SonarCloud.",
            "remove_source_branch": True
        }
        
        resp = requests.post(url, headers={"PRIVATE-TOKEN": token}, json=mr_data)
        if resp.status_code == 201:
            log(f"[+++] Merge Request создан: {resp.json().get('web_url')}")
        else:
            log(f"[-] Не удалось создать MR: {resp.text}")
            
    except Exception as e:
        log(f"[-] Ошибка в процессе финализации: {e}")

if __name__ == "__main__":
    log("AI Remediation Engine (Isolated Context Mode) started...")
    
    raw_issues = download_sonar_report()
    
    if raw_issues:
        files_to_process = {}
        for iss in raw_issues:
            comp = iss.get("component", "")
            f_path = comp.split(":")[-1] if ":" in comp else comp
            
            if f_path not in files_to_process:
                files_to_process[f_path] = []
            
            files_to_process[f_path].append({
                "line": iss.get("line", 1),
                "message": iss.get("message", "Security issue")
            })
        
        log(f"[*] Сгруппировано: {len(files_to_process)} уникальных файлов.")

        processed_files_count = 0
        for file_path, issues in list(files_to_process.items())[:5]:
            if fix_file_content(file_path, issues):
                processed_files_count += 1
            time.sleep(5) 
        if processed_files_count > 0:
            finalize_remediation(processed_files_count)
        else:
            log("[!] Ни один файл не был исправлен корректно.")
    else:
        log("[+] Список уязвимостей пуст или отчет недоступен.")

    log("Finished.")