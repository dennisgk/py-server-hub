from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import uuid
import zipfile
from collections import deque
from pathlib import Path

import py7zr
from fastapi import HTTPException

from .config import LOGS_DIR, SERVICES_DIR, UPLOAD_COMMAND_TIMEOUT_SECONDS
from .db import get_db, utcnow_iso


class ServiceManager:
    def __init__(self) -> None:
        self._processes: dict[int, subprocess.Popen] = {}
        self._stdout_files: dict[int, object] = {}
        self._stderr_files: dict[int, object] = {}
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._upload_jobs: dict[str, dict] = {}
        self._upload_jobs_lock = threading.Lock()

    def service_dir(self, folder_name: str) -> Path:
        return SERVICES_DIR / folder_name

    def stdout_log_path(self, service_id: int) -> Path:
        return LOGS_DIR / f"service_{service_id}.stdout.log"

    def stderr_log_path(self, service_id: int) -> Path:
        return LOGS_DIR / f"service_{service_id}.stderr.log"

    def _resolve_venv_python(self, service_path: Path) -> Path:
        if sys.platform.startswith("win"):
            return service_path / ".venv" / "Scripts" / "python.exe"
        return service_path / ".venv" / "bin" / "python"

    def _assert_service_layout(self, service_path: Path) -> None:
        if not (service_path / "main.py").exists() or not (service_path / "requirements.txt").exists():
            entries = [entry.name for entry in service_path.iterdir()]
            raise HTTPException(
                status_code=400,
                detail=f"Service package must contain requirements.txt and main.py at root. Found: {entries}",
            )

    def _normalize_single_nested_root(self, destination: Path, logs: list[str]) -> None:
        if (destination / "main.py").exists() and (destination / "requirements.txt").exists():
            return

        children = [child for child in destination.iterdir() if child.name != "__MACOSX"]
        if len(children) != 1 or not children[0].is_dir():
            return

        nested_root = children[0]
        if not (nested_root / "main.py").exists() or not (nested_root / "requirements.txt").exists():
            return

        logs.append(f"Detected single nested root '{nested_root.name}', flattening into service root.")
        for item in nested_root.iterdir():
            target = destination / item.name
            if target.exists():
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot flatten nested root because '{item.name}' already exists at root",
                )
            shutil.move(str(item), str(target))
        nested_root.rmdir()

    def extract_archive(self, archive_path: Path, destination: Path) -> list[str]:
        logs: list[str] = []
        logs.append(f"Extracting archive: {archive_path.name}")
        destination.mkdir(parents=True, exist_ok=False)
        suffix = archive_path.suffix.lower()
        if suffix == ".zip":
            with zipfile.ZipFile(archive_path, "r") as archive:
                archive.extractall(destination)
        elif suffix == ".7z":
            with py7zr.SevenZipFile(archive_path, "r") as archive:
                archive.extractall(path=destination)
        else:
            raise HTTPException(status_code=400, detail="Only .zip and .7z files are supported")
        self._normalize_single_nested_root(destination, logs)
        self._assert_service_layout(destination)
        logs.append(f"Extracted to: {destination}")
        logs.append("Validated service root files: main.py and requirements.txt")
        return logs

    def _run_logged(self, command: list[str], cwd: Path, logs: list[str]) -> None:
        command_display = " ".join(command)
        logs.append(f"$ {command_display}")
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                text=True,
                capture_output=True,
                timeout=UPLOAD_COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            logs.append(
                f"Command timed out after {UPLOAD_COMMAND_TIMEOUT_SECONDS}s: {command_display}",
            )
            if exc.stdout:
                logs.append(str(exc.stdout).strip())
            if exc.stderr:
                logs.append(str(exc.stderr).strip())
            raise RuntimeError(
                f"Command timed out after {UPLOAD_COMMAND_TIMEOUT_SECONDS}s: {command_display}",
            ) from exc

        if completed.stdout:
            logs.append("----- stdout -----")
            logs.extend(line for line in completed.stdout.splitlines() if line.strip() != "")
        if completed.stderr:
            logs.append("----- stderr -----")
            logs.extend(line for line in completed.stderr.splitlines() if line.strip() != "")
        if completed.returncode != 0:
            raise RuntimeError(f"Command failed ({completed.returncode}): {command_display}")

    def create_venv_and_install(self, service_path: Path) -> list[str]:
        logs: list[str] = []
        venv_path = service_path / ".venv"
        python_in_venv = self._resolve_venv_python(service_path)

        if not python_in_venv.exists():
            logs.append("Creating service virtual environment...")
            self._run_logged([sys.executable, "-m", "venv", str(venv_path)], service_path, logs)
        else:
            logs.append("Virtual environment already exists; reusing.")

        logs.append("Upgrading pip in service virtual environment...")
        self._run_logged(
            [
                str(python_in_venv),
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--progress-bar",
                "off",
                "-v",
                "pip",
            ],
            service_path,
            logs,
        )
        logs.append("Installing requirements.txt...")
        self._run_logged(
            [
                str(python_in_venv),
                "-m",
                "pip",
                "install",
                "--progress-bar",
                "off",
                "-v",
                "-r",
                "requirements.txt",
            ],
            service_path,
            logs,
        )
        logs.append("Service setup complete.")
        return logs

    def _stream_reader(self, stream, file_obj) -> None:
        try:
            for line in iter(stream.readline, ""):
                file_obj.write(line)
                file_obj.flush()
        finally:
            stream.close()

    def start(self, service: dict) -> dict:
        service_id = service["id"]
        folder_name = service["folder_name"]
        service_path = self.service_dir(folder_name)
        python_in_venv = self._resolve_venv_python(service_path)
        main_path = service_path / "main.py"

        if not python_in_venv.exists():
            raise HTTPException(status_code=400, detail="Service virtualenv does not exist")
        if not main_path.exists():
            raise HTTPException(status_code=400, detail="main.py not found for service")

        with self._lock:
            process = self._processes.get(service_id)
            if process and process.poll() is None:
                raise HTTPException(status_code=400, detail="Service is already running")

            stdout_file = self.stdout_log_path(service_id).open("a", encoding="utf-8")
            stderr_file = self.stderr_log_path(service_id).open("a", encoding="utf-8")
            process = subprocess.Popen(
                [str(python_in_venv), str(main_path)],
                cwd=service_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._processes[service_id] = process
            self._stdout_files[service_id] = stdout_file
            self._stderr_files[service_id] = stderr_file

        stdout_thread = threading.Thread(
            target=self._stream_reader,
            args=(process.stdout, stdout_file),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._stream_reader,
            args=(process.stderr, stderr_file),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        self._threads.extend([stdout_thread, stderr_thread])

        with get_db() as conn:
            conn.execute(
                """
                UPDATE services
                SET status = ?, pid = ?, updated_at = ?
                WHERE id = ?
                """,
                ("running", process.pid, utcnow_iso(), service_id),
            )
            row = conn.execute("SELECT * FROM services WHERE id = ?", (service_id,)).fetchone()
        return dict(row)

    def stop(self, service_id: int) -> None:
        with self._lock:
            process = self._processes.get(service_id)
            stdout_file = self._stdout_files.get(service_id)
            stderr_file = self._stderr_files.get(service_id)

        if process:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            with self._lock:
                self._processes.pop(service_id, None)

        if stdout_file:
            stdout_file.close()
            with self._lock:
                self._stdout_files.pop(service_id, None)
        if stderr_file:
            stderr_file.close()
            with self._lock:
                self._stderr_files.pop(service_id, None)

        with get_db() as conn:
            conn.execute(
                "UPDATE services SET status = ?, pid = NULL, updated_at = ? WHERE id = ?",
                ("stopped", utcnow_iso(), service_id),
            )

    def remove_service_dir(self, folder_name: str) -> None:
        service_path = self.service_dir(folder_name)
        if service_path.exists():
            shutil.rmtree(service_path)

    def tail_log(self, path: Path, max_lines: int) -> list[str]:
        if not path.exists():
            return []
        queue: deque[str] = deque(maxlen=max_lines)
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                queue.append(line.rstrip("\n"))
        return list(queue)

    def mark_all_stopped(self) -> None:
        with get_db() as conn:
            conn.execute(
                "UPDATE services SET status = ?, pid = NULL, updated_at = ?",
                ("stopped", utcnow_iso()),
            )

    def sync_process_states(self) -> None:
        updates: list[tuple[str, int | None, str, int]] = []
        with self._lock:
            for service_id, process in list(self._processes.items()):
                if process.poll() is not None:
                    updates.append(("stopped", None, utcnow_iso(), service_id))
                    self._processes.pop(service_id, None)
                    stdout_file = self._stdout_files.pop(service_id, None)
                    stderr_file = self._stderr_files.pop(service_id, None)
                    if stdout_file:
                        stdout_file.close()
                    if stderr_file:
                        stderr_file.close()
        if not updates:
            return
        with get_db() as conn:
            conn.executemany(
                "UPDATE services SET status = ?, pid = ?, updated_at = ? WHERE id = ?",
                updates,
            )

    def _append_job_log(self, job: dict, line: str) -> None:
        condition: threading.Condition = job["condition"]
        with condition:
            job["setup_logs"].append(line)
            job["updated_at"] = utcnow_iso()
            condition.notify_all()

    def _set_job_terminal(self, job: dict, status: str, error_message: str | None = None, service: dict | None = None) -> None:
        condition: threading.Condition = job["condition"]
        with condition:
            job["status"] = status
            job["error_message"] = error_message
            job["service"] = service
            job["updated_at"] = utcnow_iso()
            condition.notify_all()

    def _run_upload_job(self, job_id: str, service_name: str, folder_slug: str, filename: str, tmp_file_path: Path) -> None:
        with self._upload_jobs_lock:
            job = self._upload_jobs[job_id]

        self._append_job_log(job, f"Receiving upload: {filename}")
        self._append_job_log(job, f"Saved temporary file: {tmp_file_path}")
        job["status"] = "running"
        destination = SERVICES_DIR / folder_slug

        try:
            for line in self.extract_archive(tmp_file_path, destination):
                self._append_job_log(job, line)
            for line in self.create_venv_and_install(destination):
                self._append_job_log(job, line)

            now = utcnow_iso()
            with get_db() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO services (name, folder_name, archive_name, status, pid, created_at, updated_at)
                    VALUES (?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (service_name, folder_slug, filename, "stopped", now, now),
                )
                row = conn.execute("SELECT * FROM services WHERE id = ?", (cursor.lastrowid,)).fetchone()
            service = dict(row)
            self._set_job_terminal(job, "completed", service=service)
        except Exception as exc:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            self._append_job_log(job, f"ERROR: {exc}")
            self._set_job_terminal(job, "failed", error_message=f"Upload failed: {exc}")
        finally:
            tmp_file_path.unlink(missing_ok=True)

    def create_upload_job(self, user_id: int, service_name: str, folder_slug: str, filename: str, tmp_file_path: Path) -> str:
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "user_id": user_id,
            "status": "queued",
            "setup_logs": [],
            "error_message": None,
            "service": None,
            "created_at": utcnow_iso(),
            "updated_at": utcnow_iso(),
            "condition": threading.Condition(),
        }
        with self._upload_jobs_lock:
            self._upload_jobs[job_id] = job

        thread = threading.Thread(
            target=self._run_upload_job,
            args=(job_id, service_name, folder_slug, filename, tmp_file_path),
            daemon=True,
        )
        thread.start()
        self._threads.append(thread)
        return job_id

    def get_upload_job(self, job_id: str, user_id: int) -> dict:
        with self._upload_jobs_lock:
            job = self._upload_jobs.get(job_id)
        if not job or job["user_id"] != user_id:
            raise HTTPException(status_code=404, detail="Upload job not found")
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "setup_logs": list(job["setup_logs"]),
            "error_message": job["error_message"],
            "service": job["service"],
        }

    def wait_upload_job_update(self, job_id: str, user_id: int, last_index: int, timeout_seconds: int = 20) -> dict:
        with self._upload_jobs_lock:
            job = self._upload_jobs.get(job_id)
        if not job or job["user_id"] != user_id:
            raise HTTPException(status_code=404, detail="Upload job not found")

        condition: threading.Condition = job["condition"]
        with condition:
            if len(job["setup_logs"]) <= last_index and job["status"] not in {"completed", "failed"}:
                condition.wait(timeout=timeout_seconds)

            lines = job["setup_logs"][last_index:]
            next_index = len(job["setup_logs"])
            done = job["status"] in {"completed", "failed"}
            return {
                "lines": lines,
                "next_index": next_index,
                "done": done,
                "status": job["status"],
                "error_message": job["error_message"],
                "service": job["service"],
            }
