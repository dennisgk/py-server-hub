from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import zipfile
from collections import deque
from pathlib import Path

import py7zr
from fastapi import HTTPException

from .config import LOGS_DIR, SERVICES_DIR
from .db import get_db, utcnow_iso


class ServiceManager:
    def __init__(self) -> None:
        self._processes: dict[int, subprocess.Popen] = {}
        self._stdout_files: dict[int, object] = {}
        self._stderr_files: dict[int, object] = {}
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

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
            raise HTTPException(
                status_code=400,
                detail="Service package must contain requirements.txt and main.py at root",
            )

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
        self._assert_service_layout(destination)
        logs.append(f"Extracted to: {destination}")
        logs.append("Validated service root files: main.py and requirements.txt")
        return logs

    def _run_logged(self, command: list[str], cwd: Path, logs: list[str]) -> None:
        command_display = " ".join(command)
        logs.append(f"$ {command_display}")
        completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
        if completed.stdout.strip():
            logs.append(completed.stdout.strip())
        if completed.stderr.strip():
            logs.append(completed.stderr.strip())
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
            [str(python_in_venv), "-m", "pip", "install", "--upgrade", "pip"],
            service_path,
            logs,
        )
        logs.append("Installing requirements.txt...")
        self._run_logged(
            [str(python_in_venv), "-m", "pip", "install", "-r", "requirements.txt"],
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
