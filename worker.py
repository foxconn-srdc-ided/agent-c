"""OpenCode role task runner. Runs only trusted repository_dispatch payloads."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

ORG = "foxconn-srdc-ided"
CENTRE = f"{ORG}/agent-collaboration"
ROLE = os.environ["ROLE"]
REPO = {"A": "agent-a", "B": "agent-b", "C": "agent-c"}[ROLE]
AUTOMATION_LOGIN = "ycliu-dev"
ROOT = Path.cwd()
FILES = {"A": {"SPEC.md"}, "B": {"csv_stats.py", "test_csv_stats.py", "README.md"},
         "C": {"REPORT.md", "test_acceptance.py"}}


class SelfCheckError(RuntimeError):
    pass


class UpstreamDefect(RuntimeError):
    pass


def safe_error(value: object) -> str:
    message = json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else str(value)
    for name in ("MODEL_STUDIO_API_KEY", "GH_TOKEN", "GITHUB_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN"):
        secret = os.environ.get(name)
        if secret:
            message = message.replace(secret, "[redacted]")
    return message[:500]


def command(*args: str, cwd: Path | None = None, env: dict | None = None, data: str | None = None,
            timeout: int = 1200) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, input=data, text=True,
                            capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{' '.join(args[:3])}: {result.stderr[-1000:]}")
    return result.stdout.strip()


def model(prompt: str, required: tuple[str, ...]) -> dict:
    env = os.environ.copy()
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN", "CROSS_REPO_TOKEN"):
        env.pop(name, None)
    if not env.get("MODEL_STUDIO_API_KEY") or not env.get("MODEL_STUDIO_BASE_URL"):
        raise RuntimeError("Model Studio endpoint or key missing")
    raw = command("opencode", "run", "--pure", "--format", "json", "--model",
                  "model-studio/qwen3-coder-flash-2025-07-28", prompt, cwd=ROOT, env=env)
    messages = {}
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "error":
            raise RuntimeError(f"OpenCode error: {safe_error(event.get('error'))}")
        if event.get("type") == "text" and isinstance(event.get("part", {}).get("text"), str):
            part = event["part"]
            messages.setdefault(part.get("messageID", "unknown"), []).append(part["text"])
    decoder = json.JSONDecoder()
    candidates = []
    for message_index, parts in enumerate(messages.values()):
        text = "".join(parts)
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                value, end = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                candidates.append((message_index, end, end - index, value))
    if not candidates:
        raise RuntimeError("Model returned no JSON")
    matching = [item for item in candidates if all(key in item[3] for key in required)]
    if not matching:
        errors = [item[3] for item in candidates if "error" in item[3] or item[3].get("type") == "error"]
        if errors:
            raise RuntimeError(f"Model error: {safe_error(errors[-1])}")
        keys = sorted({key for item in candidates for key in item[3]})
        raise RuntimeError(f"Model response missing {required}; available keys: {keys[:20]}")
    return max(matching, key=lambda item: item[:3])[3]


def clone_at(repo: str, sha: str, run_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("Missing fixed source SHA")
    target = Path(tempfile.mkdtemp(prefix="agent-prior-"))
    command("git", "-c", "credential.helper=!gh auth git-credential", "clone", "--quiet",
            "--branch", f"runs/{run_id}", f"https://github.com/{ORG}/{repo}.git", str(target))
    command("git", "checkout", "--detach", sha, cwd=target)
    return target


def send(payload: dict, report: dict) -> None:
    fields = {"run_id": payload["run_id"], "stage": payload["stage"], "version": payload["version"],
              "attempt": payload["attempt"], "action": payload["action"], "role": ROLE, "repo": REPO,
              "report_id": str(uuid.uuid4()), **report}
    body = json.dumps({"event_type": "agent-report", "client_payload": {"report": fields}}, ensure_ascii=False)
    command("gh", "api", f"repos/{CENTRE}/dispatches", "-X", "POST", "--input", "-", data=body)


def context(payload: dict) -> str:
    if payload.get("action") == "review":
        source = clone_at(payload["source_repo"], payload["sha"], payload["run_id"])
    elif payload.get("previous_sha"):
        source = clone_at(payload["previous_repo"], payload["previous_sha"], payload["run_id"])
    else:
        return ""
    files = source / "deliverables" / payload["run_id"]
    pieces = []
    for item in sorted(files.glob("*")):
        if item.is_file() and item.stat().st_size < 100_000:
            pieces.append(f"### {item.name}\n{item.read_text(errors='replace')}")
    if payload.get("prior_b_sha"):
        prior_b = clone_at("agent-b", payload["prior_b_sha"], payload["run_id"])
        for item in sorted((prior_b / "deliverables" / payload["run_id"]).glob("*")):
            if item.is_file() and item.stat().st_size < 100_000:
                pieces.append(f"### prior B {item.name}\n{item.read_text(errors='replace')}")
    return "\n\n".join(pieces)


def produce(payload: dict, source: str) -> dict:
    prompt = (f"你是 Agent {ROLE}。本輪 {payload['stage']}，協議 v{payload['version']}。"
              f"任務：{payload['task']}\n協議：{payload['agreement']}\n上游固定版本內容：\n{source}\n"
              f"原已准收協議（不得削弱）：{payload.get('original_agreement', '')}\n"
              f"退件原因：{payload.get('feedback', '')}\n"
              f"只輸出 JSON，格式 {{\"files\": {{filename: content}}, \"self_check\": string}}。"
              f"files 必須剛好包含 {sorted(FILES[ROLE])}。內容使用繁體中文說明；程式使用 Python 標準函式庫。"
              "若為 C，test_acceptance.py 必須獨立檢查六個指定案例，從環境變數 B_RESULT_DIR 取得 B 成果目錄，"
              "以 subprocess 執行 csv_stats.py，且測試需可由 python3 -m unittest -v test_acceptance 執行。"
              "不得假稱未執行的測試通過。")
    value = model(prompt, ("files", "self_check"))
    if set(value.get("files", {})) != FILES[ROLE] or not value.get("self_check", "").strip():
        raise RuntimeError("Model omitted required files or self-check")
    branch = f"runs/{payload['run_id']}"
    command("git", "fetch", "origin", "main", cwd=ROOT)
    existing = subprocess.run(["git", "ls-remote", "--exit-code", "--heads", "origin", branch],
                              cwd=ROOT, capture_output=True, text=True)
    if existing.returncode == 0:
        command("git", "fetch", "origin", branch, cwd=ROOT)
        command("git", "checkout", "-B", branch, "FETCH_HEAD", cwd=ROOT)
    else:
        command("git", "checkout", "-B", branch, "origin/main", cwd=ROOT)
    target = ROOT / "deliverables" / payload["run_id"]
    target.mkdir(parents=True, exist_ok=True)
    for name, content in value["files"].items():
        if not isinstance(content, str) or not content.strip() or len(content) > 100_000:
            raise RuntimeError("Invalid deliverable content")
        (target / name).write_text(content.rstrip() + "\n")
    evidence = value["self_check"]
    if ROLE == "B":
        result = subprocess.run(["python3", "-m", "unittest", "-v", "test_csv_stats"],
                                cwd=target, capture_output=True, text=True, timeout=120)
        evidence += f"\nFixed test command exit={result.returncode}:\n{result.stderr[-3000:]}"
        if result.returncode:
            raise SelfCheckError("B fixed tests failed: " + result.stderr[-600:])
    if ROLE == "C":
        prior = clone_at(payload["previous_repo"], payload["previous_sha"], payload["run_id"])
        folder = prior / "deliverables" / payload["run_id"]
        result = subprocess.run(["python3", "-m", "unittest", "-v", "test_csv_stats"],
                                cwd=folder, capture_output=True, text=True, timeout=120)
        evidence += f"\nB tests rerun exit={result.returncode}:\n{result.stderr[-3000:]}"
        if result.returncode:
            raise UpstreamDefect("C rerun of B tests failed: " + result.stderr[-600:])
        if len(re.findall(r"\bdef\s+test_", (target / "test_acceptance.py").read_text())) < 6:
            raise SelfCheckError("C independent suite needs six separate scenario tests")
        env = os.environ.copy()
        env["B_RESULT_DIR"] = str(folder)
        own = subprocess.run(["python3", "-m", "unittest", "-v", "test_acceptance"],
                             cwd=target, env=env, capture_output=True, text=True, timeout=120)
        evidence += f"\nC independent tests exit={own.returncode}:\n{own.stderr[-3000:]}"
        if own.returncode:
            diagnosis = model("你是 Agent C。獨立測試失敗，判斷缺陷屬於 B 實作或 C 測試本身。"
                              "只回 JSON：{\"owner\": \"B 或 C\", \"reason\": \"具體理由\"}。\n"
                              f"B 程式：\n{(folder / 'csv_stats.py').read_text()[:20000]}\n"
                              f"C 測試：\n{(target / 'test_acceptance.py').read_text()[:20000]}\n"
                              f"失敗輸出：\n{own.stderr[-3000:]}", ("owner", "reason"))
            reason = f"{diagnosis.get('reason', '')}\n{own.stderr[-600:]}"
            if diagnosis.get("owner") == "B":
                raise UpstreamDefect(reason)
            if diagnosis.get("owner") == "C":
                raise SelfCheckError(reason)
            raise RuntimeError("Unable to classify independent test failure")
    command("git", "add", "deliverables", cwd=ROOT)
    command("git", "-c", "user.name=agent-flow[bot]", "-c", "user.email=agent-flow@users.noreply.github.com",
            "commit", "-m", f"{ROLE} deliverable {payload['run_id']} attempt {payload['attempt']}", cwd=ROOT)
    sha = command("git", "rev-parse", "HEAD", cwd=ROOT)
    command("git", "-c", "credential.helper=!gh auth git-credential", "push", "origin", branch, cwd=ROOT)
    return {"sha": sha, "text": evidence}


def main() -> None:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    if event.get("action") != "agent-task" or event.get("sender", {}).get("login") != AUTOMATION_LOGIN:
        raise RuntimeError("Untrusted dispatch")
    p = event["client_payload"]["task"]
    if p["stage"] not in {"A_B", "B_C", "C_HUMAN"} and not re.fullmatch(r"B_C_FIX_[1-9][0-9]*", p["stage"]):
        raise RuntimeError("Unknown stage")
    source = context(p)
    if p["action"] in {"propose", "amend"}:
        value = model(f"你是 Agent {ROLE}，提出可核對交接協議。任務：{p['task']}。"
                      f"上游成果：{source}\n前版協議：{p['agreement']}\n回饋：{p.get('feedback', '')}\n"
                      f"原已准收協議（修正卡不得削弱）：{p.get('original_agreement', '')}\n"
                      "只回 JSON：{\"text\": \"交付範圍、驗收條件、依據資料\"}。", ("text",))
        report = {"text": value["text"]}
    elif p["action"] == "agree":
        value = model(f"你是接收方或交付方 Agent {ROLE}。檢視協議 v{p['version']}：{p['agreement']}。"
                      f"任務：{p['task']}。上游成果：{source}\n"
                      "只回 JSON：{\"agree\": boolean, \"text\": \"理由或具體修改建議\"}。", ("agree", "text"))
        report = {"agree": value["agree"], "text": value["text"]}
    elif p["action"] == "produce":
        report = produce(p, source)
    elif p["action"] == "review":
        value = model(f"你是接收方 Agent {ROLE}。逐項檢查協議 v{p['version']}，固定 SHA {p['sha']}。"
                      f"任務：{p['task']}\n協議：{p['agreement']}\n成果：{source}\n"
                      "只回 JSON：{\"passed\": boolean, \"text\": \"逐項結果與證據\"}。", ("passed", "text"))
        if ROLE == "C":
            prior = clone_at(p["source_repo"], p["sha"], p["run_id"])
            folder = prior / "deliverables" / p["run_id"]
            test = subprocess.run(["python3", "-m", "unittest", "-v", "test_csv_stats"],
                                  cwd=folder, capture_output=True, text=True, timeout=120)
            value["text"] += f"\n固定測試 exit={test.returncode}:\n{test.stderr[-3000:]}"
            value["passed"] = bool(value["passed"] and test.returncode == 0)
        report = {"sha": p["sha"], "passed": value["passed"], "text": value["text"]}
    else:
        raise RuntimeError("Unknown action")
    send(p, report)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        try:
            event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
            payload = event.get("client_payload", {}).get("task", {})
            if payload.get("run_id") and event.get("action") == "agent-task" and event.get("sender", {}).get("login") == AUTOMATION_LOGIN:
                action = ("upstream_defect" if isinstance(exc, UpstreamDefect) else
                          "selfcheck_failed" if isinstance(exc, SelfCheckError) else "failed")
                send(payload, {"action": action, "failed_action": payload.get("action", ""),
                               "text": str(exc)[-700:]})
        except Exception:
            pass
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
