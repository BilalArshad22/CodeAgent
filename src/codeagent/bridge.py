"""Backend bridge for Electron UI via JSON-lines on stdin/stdout."""

from __future__ import annotations

import json
import logging
import sys
import threading
from dataclasses import asdict
from pathlib import Path

from .agent import Event
from .config import Settings, load_settings, save_settings
from .runner import run_pipeline

# Re-route all root logging to stderr to keep stdout clean for JSON
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger("codeagent.bridge")

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not reconfigure streams to UTF-8: {e}")

class Bridge:
    def __init__(self):
        self.lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self._running = True

    def _send(self, data: dict):
        with self.lock:
            try:
                sys.stdout.write(json.dumps(data) + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                self._running = False
            except Exception as e:
                logger.error(f"Error writing to stdout: {e}")

    def send_response(self, req_id, result=None, error=None):
        resp = {"id": req_id}
        if error is not None:
            resp["error"] = error
        else:
            resp["result"] = result
        self._send(resp)

    def send_event(self, event: Event):
        # We forward the Event as exactly described.
        self._send({
            "event": event.kind,
            "message": event.message,
            "data": event.data,
        })

    def handle_request(self, req: dict):
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if not method:
            self.send_response(req_id, error="Missing method")
            return

        handler = getattr(self, f"handle_{method}", None)
        if not handler:
            self.send_response(req_id, error=f"Unknown method: {method}")
            return

        try:
            handler(req_id, params)
        except Exception as e:
            logger.exception(f"Error in {method}")
            self.send_response(req_id, error=str(e))

    def handle_get_settings(self, req_id, params):
        settings = load_settings()
        self.send_response(req_id, result=asdict(settings))

    def handle_save_settings(self, req_id, params):
        try:
            settings = Settings(**params)
            save_settings(settings)
            self.send_response(req_id, result="ok")
        except TypeError as e:
            self.send_response(req_id, error=f"Invalid settings: {e}")

    def handle_list_samples(self, req_id, params):
        samples_dir = Path(__file__).resolve().parent / "samples"
        samples = [str(p) for p in sorted(samples_dir.glob("*.md"))]
        self.send_response(req_id, result=samples)

    def handle_test_connection(self, req_id, params):
        from .llm import DeepSeekClient
        settings = Settings(**params.get("settings", {}))
        
        def work():
            try:
                client = DeepSeekClient(
                    settings.effective_api_key(), 
                    model=settings.model, 
                    base_url=settings.base_url, 
                    max_retries=1,
                    timeout=30, 
                    provider=settings.provider
                )
                models = client.list_models()
                self.send_response(req_id, result={"ok": True, "message": "✓ Connected"})
            except Exception as exc:
                self.send_response(req_id, result={"ok": False, "message": f"✗ {type(exc).__name__}: {exc}"})
                
        threading.Thread(target=work, daemon=True).start()

    def handle_check_output_dir(self, req_id, params):
        path_str = params.get("path")
        if not path_str:
            self.send_response(req_id, error="Missing path")
            return
            
        out = Path(path_str)
        if not out.exists():
            self.send_response(req_id, result={"exists": False, "empty": True})
            return
            
        from .tools import META_DIR
        if out.is_dir():
            has_files = any(p.name != META_DIR for p in out.iterdir())
            self.send_response(req_id, result={"exists": True, "empty": not has_files})
        else:
            self.send_response(req_id, result={"exists": True, "empty": False, "is_file": True})

    def handle_start_run(self, req_id, params):
        if self.worker_thread and self.worker_thread.is_alive():
            self.send_response(req_id, error="Already running")
            return
            
        settings = Settings(**params.get("settings", {}))
        # Optional LLM can be passed in for testing, but in bridge it's not passed via JSON.
        # We will allow a test-injectable LLM on the Bridge instance if needed.
        llm = getattr(self, "test_llm", None)
            
        self.cancel_event.clear()
        
        def work():
            try:
                # CodeAgent.run() emits the "done" event itself; sending another would duplicate it.
                run_pipeline(settings, on_event=self.send_event, cancel_event=self.cancel_event, llm=llm)
            except Exception as exc:
                logger.exception("Pipeline crashed")
                self.send_event(Event("error", f"{type(exc).__name__}: {exc}"))
                self.send_event(Event("done", "Failed", data={"success": False, "stop_reason": "error"}))
        
        self.worker_thread = threading.Thread(target=work, daemon=True)
        self.worker_thread.start()
        
        self.send_response(req_id, result="started")

    def handle_stop_run(self, req_id, params):
        if self.worker_thread and self.worker_thread.is_alive():
            self.cancel_event.set()
        self.send_response(req_id, result="stopping")

    def serve(self, in_stream=sys.stdin):
        while self._running:
            line = in_stream.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            
            try:
                req = json.loads(line)
                self.handle_request(req)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON: {e} - Line: {line}")
                
def main():
    bridge = Bridge()
    bridge.serve()

if __name__ == "__main__":
    main()
