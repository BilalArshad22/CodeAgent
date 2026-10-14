"""Tkinter desktop GUI: API key, input files, output directory, run/stop, live log."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import APP_NAME, __version__
from .agent import AgentResult, Event
from .config import PROVIDERS, Settings, load_settings, save_settings
from .llm import DeepSeekClient, LLMError
from .runner import run_pipeline
from .tools import META_DIR

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"

# Color Palette (Dark Theme Default)
COLORS = {
    "bg": "#1A1915",
    "surface": "#262522",
    "surface-2": "#30302C",
    "border": "#3D3C37",
    "text": "#ECEAE4",
    "text-dim": "#9B9890",
    "accent": "#D97757",
    "accent-hover": "#E08A6D",
    "success": "#7FB685",
    "warning": "#E5B567",
    "error": "#E5726A",
    "info": "#8AB4F8",
}

# Typography
if os.name == "nt":
    FONT_UI = ("Segoe UI", 10)
    FONT_UI_BOLD = ("Segoe UI", 10, "bold")
    FONT_UI_SMALL = ("Segoe UI", 9)
    FONT_UI_SMALL_BOLD = ("Segoe UI", 9, "bold")
    FONT_HEADER = ("Segoe UI", 12, "semibold")
    FONT_MONO = ("Cascadia Mono", 10) # fallback Consolas handles transparently if Cascadia missing
else:
    FONT_UI = ("SF Pro", 13) # fallback to Helvetica Neue
    FONT_UI_BOLD = ("SF Pro", 13, "bold")
    FONT_UI_SMALL = ("SF Pro", 11)
    FONT_UI_SMALL_BOLD = ("SF Pro", 11, "bold")
    FONT_HEADER = ("SF Pro", 16, "bold")
    FONT_MONO = ("SF Mono", 14)


def _open_path(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: App):
        super().__init__(parent.root)
        self.title("Settings")
        self.configure(bg=COLORS["surface"])
        self.geometry("350x250")
        self.transient(parent.root)
        self.grab_set()
        
        pad = {"padx": 10, "pady": 5}
        
        ttk.Label(self, text="Base URL:", background=COLORS["surface"], foreground=COLORS["text"]).grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(self, textvariable=parent.base_url, width=24).grid(row=0, column=1, sticky="ew", **pad)
        
        ttk.Label(self, text="Max turns:", background=COLORS["surface"], foreground=COLORS["text"]).grid(row=1, column=0, sticky="w", **pad)
        ttk.Spinbox(self, from_=10, to=400, textvariable=parent.max_turns, width=10).grid(row=1, column=1, sticky="w", **pad)
        
        tk.Checkbutton(self, text="Show model reasoning", variable=parent.show_thinking, 
                       bg=COLORS["surface"], fg=COLORS["text"], selectcolor=COLORS["bg"], activebackground=COLORS["surface"], activeforeground=COLORS["text"]).grid(row=2, column=0, columnspan=2, sticky="w", **pad)
        tk.Checkbutton(self, text="Remember API key", variable=parent.remember_key, 
                       bg=COLORS["surface"], fg=COLORS["text"], selectcolor=COLORS["bg"], activebackground=COLORS["surface"], activeforeground=COLORS["text"]).grid(row=3, column=0, columnspan=2, sticky="w", **pad)
        
        ttk.Button(self, text="Close", command=self.destroy).grid(row=4, column=0, columnspan=2, pady=15)
        
        self.bind("<Escape>", lambda e: self.destroy())

class App:
    POLL_MS = 100

    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = load_settings()
        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.started_at = 0.0

        root.title(f"{APP_NAME} {__version__}")
        root.geometry("1180x780")
        root.minsize(900, 600)
        root.configure(bg=COLORS["bg"])
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.provider_key = self.settings.provider if self.settings.provider in PROVIDERS else "deepseek"
        self._keys = {"deepseek": self.settings.api_key, "gemini": self.settings.gemini_api_key}
        
        self.provider_label = tk.StringVar(value=PROVIDERS[self.provider_key]["label"])
        self.api_key = tk.StringVar(value=self._keys[self.provider_key])
        self.show_key = tk.BooleanVar(value=False)
        self.remember_key = tk.BooleanVar(value=self.settings.remember_key)
        self.model = tk.StringVar(value=self.settings.model)
        self.base_url = tk.StringVar(value=self.settings.base_url)
        self.thinking = tk.BooleanVar(value=self.settings.thinking)
        self.max_turns = tk.IntVar(value=self.settings.max_turns)
        self.output_dir = tk.StringVar(value=self.settings.output_dir)
        self.show_thinking = tk.BooleanVar(value=False)
        
        self.status = tk.StringVar(value="Ready.")
        self.usage_text = tk.StringVar(value="")
        
        self._apply_styles()
        self._build()
        
        for f in self.settings.input_files:
            if Path(f).is_file():
                self.files.insert(tk.END, f)
                
        self.root.after(self.POLL_MS, self._poll)

    def _apply_styles(self):
        style = ttk.Style()
        # Theme setup
        style.theme_use("clam")
        
        # Configure overall defaults
        style.configure(".", background=COLORS["bg"], foreground=COLORS["text"], font=FONT_UI)
        
        # LabelFrames (Sidebar sections)
        style.configure("Sidebar.TLabelframe", background=COLORS["surface"], borderwidth=0)
        style.configure("Sidebar.TLabelframe.Label", background=COLORS["surface"], foreground=COLORS["text-dim"], font=FONT_UI_SMALL_BOLD)
        
        # Treeview (Plan)
        style.configure("Treeview", background=COLORS["bg"], foreground=COLORS["text"], fieldbackground=COLORS["bg"], borderwidth=0, font=FONT_UI)
        style.configure("Treeview.Heading", background=COLORS["surface"], foreground=COLORS["text-dim"], font=FONT_UI_SMALL_BOLD, borderwidth=0)
        style.map("Treeview", background=[("selected", COLORS["surface-2"])])

    def _build(self) -> None:
        main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=COLORS["border"], bd=0, sashwidth=1)
        main_paned.pack(fill=tk.BOTH, expand=True)

        # ------------------------------------------------------------------ SIDEBAR
        sidebar = tk.Frame(main_paned, bg=COLORS["surface"], width=300)
        sidebar.pack_propagate(False)
        main_paned.add(sidebar, minsize=260)
        
        # Header in Sidebar
        header = tk.Frame(sidebar, bg=COLORS["surface"], height=40)
        header.pack(fill=tk.X, padx=12, pady=12)
        tk.Label(header, text=f"✻ {APP_NAME}", bg=COLORS["surface"], fg=COLORS["text"], font=FONT_HEADER).pack(side=tk.LEFT)
        tk.Button(header, text="⚙", bg=COLORS["surface"], fg=COLORS["text-dim"], bd=0, command=self.open_settings, font=FONT_UI).pack(side=tk.RIGHT)
        
        # Container for sidebar content (scrollable if needed, using simple pack for now)
        sb_content = tk.Frame(sidebar, bg=COLORS["surface"])
        sb_content.pack(fill=tk.BOTH, expand=True, padx=12)
        
        # Provider
        tk.Label(sb_content, text="PROVIDER", bg=COLORS["surface"], fg=COLORS["text-dim"], font=FONT_UI_SMALL_BOLD).pack(anchor="w", pady=(8,2))
        self.provider_box = ttk.Combobox(sb_content, textvariable=self.provider_label, state="readonly", values=[p["label"] for p in PROVIDERS.values()])
        self.provider_box.pack(fill=tk.X)
        self.provider_box.bind("<<ComboboxSelected>>", lambda _e: self._provider_changed())
        
        self.provider_warning = tk.Label(sb_content, fg=COLORS["warning"], bg=COLORS["surface"], font=FONT_UI_SMALL)
        self.provider_warning.pack(anchor="w", pady=(2, 0))
        
        # API Key
        tk.Label(sb_content, text="API KEY", bg=COLORS["surface"], fg=COLORS["text-dim"], font=FONT_UI_SMALL_BOLD).pack(anchor="w", pady=(12,2))
        key_frame = tk.Frame(sb_content, bg=COLORS["surface"])
        key_frame.pack(fill=tk.X)
        
        # We need a custom entry for dark theme because ttk.Entry is hard to style perfectly
        self.key_entry = tk.Entry(key_frame, textvariable=self.api_key, show="•", bg=COLORS["bg"], fg=COLORS["text"], insertbackground=COLORS["text"], highlightthickness=1, highlightcolor=COLORS["accent"], highlightbackground=COLORS["border"], relief=tk.FLAT)
        self.key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(key_frame, text="👁", bg=COLORS["surface"], fg=COLORS["text"], bd=0, command=self._toggle_key).pack(side=tk.LEFT, padx=4)
        tk.Button(key_frame, text="Test", bg=COLORS["surface"], fg=COLORS["text"], bd=0, command=self.test_connection).pack(side=tk.LEFT)
        
        self.test_result_label = tk.Label(sb_content, text="", bg=COLORS["surface"], fg=COLORS["success"], font=FONT_UI_SMALL)
        self.test_result_label.pack(anchor="w")
        
        # Model
        tk.Label(sb_content, text="MODEL", bg=COLORS["surface"], fg=COLORS["text-dim"], font=FONT_UI_SMALL_BOLD).pack(anchor="w", pady=(12,2))
        self.model_box = ttk.Combobox(sb_content, textvariable=self.model, values=PROVIDERS[self.provider_key]["models"])
        self.model_box.pack(fill=tk.X)
        tk.Checkbutton(sb_content, text="Thinking", variable=self.thinking, bg=COLORS["surface"], fg=COLORS["text"], selectcolor=COLORS["bg"], activebackground=COLORS["surface"], activeforeground=COLORS["text"]).pack(anchor="w", pady=2)
        
        # Inputs
        inp_head = tk.Frame(sb_content, bg=COLORS["surface"])
        inp_head.pack(fill=tk.X, pady=(12,2))
        tk.Label(inp_head, text="INPUTS", bg=COLORS["surface"], fg=COLORS["text-dim"], font=FONT_UI_SMALL_BOLD).pack(side=tk.LEFT)
        tk.Button(inp_head, text="+ Add", bg=COLORS["surface"], fg=COLORS["text"], bd=0, command=self.add_files).pack(side=tk.RIGHT)
        
        self.files_frame = tk.Frame(sb_content, bg=COLORS["bg"], highlightthickness=1, highlightbackground=COLORS["border"])
        self.files_frame.pack(fill=tk.X)
        self.files = tk.Listbox(self.files_frame, height=4, selectmode=tk.EXTENDED, bg=COLORS["bg"], fg=COLORS["text"], bd=0, highlightthickness=0)
        self.files.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        
        files_btn_frame = tk.Frame(sb_content, bg=COLORS["surface"])
        files_btn_frame.pack(fill=tk.X, pady=2)
        tk.Button(files_btn_frame, text="Use samples", bg=COLORS["surface"], fg=COLORS["text"], bd=0, command=self.use_samples).pack(side=tk.LEFT)
        tk.Button(files_btn_frame, text="Remove selected", bg=COLORS["surface"], fg=COLORS["text"], bd=0, command=self.remove_files).pack(side=tk.RIGHT)
        
        # Output
        out_head = tk.Frame(sb_content, bg=COLORS["surface"])
        out_head.pack(fill=tk.X, pady=(12,2))
        tk.Label(out_head, text="OUTPUT", bg=COLORS["surface"], fg=COLORS["text-dim"], font=FONT_UI_SMALL_BOLD).pack(side=tk.LEFT)
        tk.Button(out_head, text="Browse", bg=COLORS["surface"], fg=COLORS["text"], bd=0, command=self.browse_output).pack(side=tk.RIGHT)
        
        self.out_entry = tk.Entry(sb_content, textvariable=self.output_dir, bg=COLORS["bg"], fg=COLORS["text"], insertbackground=COLORS["text"], highlightthickness=1, highlightcolor=COLORS["accent"], highlightbackground=COLORS["border"], relief=tk.FLAT)
        self.out_entry.pack(fill=tk.X)
        
        # Generate Action Area
        action_frame = tk.Frame(sb_content, bg=COLORS["surface"])
        action_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=16)
        
        # Canvas for the primary accent button
        self.gen_btn_canvas = tk.Canvas(action_frame, height=36, bg=COLORS["surface"], bd=0, highlightthickness=0)
        self.gen_btn_canvas.pack(fill=tk.X, pady=4)
        self._draw_btn(self.gen_btn_canvas, "▶ Generate  ⌘↵", COLORS["accent"], self.start)
        
        self.stop_btn = tk.Button(action_frame, text="■ Stop (Esc)", bg=COLORS["surface"], fg=COLORS["text"], bd=1, command=self.stop, state=tk.DISABLED)
        self.stop_btn.pack(fill=tk.X)
        
        self.sidebar_widgets = [self.provider_box, self.key_entry, self.model_box, self.out_entry, self.files]
        self.sidebar_buttons = [] # Store buttons to disable
        
        # ------------------------------------------------------------------ MAIN AREA (Transcript)
        main_area = tk.Frame(main_paned, bg=COLORS["bg"])
        main_paned.add(main_area, weight=1)
        
        # Plan panel at the top, collapsible
        self.plan_frame = tk.Frame(main_area, bg=COLORS["surface"], height=150)
        self.plan_frame.pack(fill=tk.X, side=tk.TOP)
        self.plan = ttk.Treeview(self.plan_frame, columns=("status",), show="tree headings", height=5)
        self.plan.heading("#0", text="Plan (live)")
        self.plan.heading("status", text="Status")
        self.plan.column("status", width=90, anchor="center", stretch=False)
        self.plan.pack(fill=tk.BOTH, expand=True)
        # Initially hide the plan
        self.plan_frame.pack_forget()
        
        # Log
        log_container = tk.Frame(main_area, bg=COLORS["bg"])
        log_container.pack(fill=tk.BOTH, expand=True)
        
        self.log = ScrolledText(log_container, wrap=tk.WORD, font=FONT_MONO, bg=COLORS["bg"], fg=COLORS["text"], bd=0, highlightthickness=0, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        
        # Configure tags
        self.log.tag_configure("tool", foreground=COLORS["text"])
        self.log.tag_configure("tool_bold", font=FONT_MONO + ("bold",), foreground=COLORS["text"])
        self.log.tag_configure("tool_bullet", foreground=COLORS["accent"])
        self.log.tag_configure("ok", foreground=COLORS["text-dim"])
        self.log.tag_configure("ok_check", foreground=COLORS["success"])
        self.log.tag_configure("warn", foreground=COLORS["warning"])
        self.log.tag_configure("error", foreground=COLORS["error"])
        self.log.tag_configure("thinking", foreground=COLORS["text-dim"], font=FONT_MONO + ("italic",))
        self.log.tag_configure("status", foreground=COLORS["text-dim"])
        self.log.tag_configure("assistant", foreground=COLORS["text"])
        self.log.tag_configure("bold", font=FONT_MONO + ("bold",))
        self.log.tag_configure("todo_done", foreground=COLORS["text-dim"], overstrike=True)
        self.log.tag_configure("todo_prog", foreground=COLORS["accent"], font=FONT_MONO + ("bold",))
        self.log.tag_configure("todo_pend", foreground=COLORS["text"])
        
        # Status Bar
        self.status_bar = tk.Frame(main_area, bg=COLORS["bg"], height=28)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM, padx=16, pady=(0,8))
        self.status_label = tk.Label(self.status_bar, textvariable=self.status, bg=COLORS["bg"], fg=COLORS["text-dim"], font=FONT_MONO, anchor="w")
        self.status_label.pack(side=tk.LEFT, fill=tk.X)
        
        # Footer
        self.footer = tk.Frame(main_area, bg=COLORS["bg"], height=28)
        self.footer.pack(fill=tk.X, side=tk.BOTTOM, padx=16, pady=(0, 4))
        tk.Frame(self.footer, height=1, bg=COLORS["border"]).pack(side=tk.TOP, fill=tk.X)
        self.footer_label = tk.Label(self.footer, textvariable=self.usage_text, bg=COLORS["bg"], fg=COLORS["text-dim"], font=FONT_UI_SMALL, anchor="w")
        self.footer_label.pack(side=tk.LEFT, pady=4)
        
        self._update_provider_widgets()
        
        # Key bindings
        self.root.bind("<Control-Return>", lambda e: self.start())
        self.root.bind("<Command-Return>", lambda e: self.start())
        self.root.bind("<Escape>", lambda e: self.stop())

    def _draw_btn(self, canvas, text, color, command):
        canvas.delete("all")
        # Round rectangle approximation
        width = 276
        height = 36
        r = 6
        points = [r, 0, width-r, 0, width, 0, width, r, width, height-r, width, height, width-r, height, r, height, 0, height, 0, height-r, 0, r, 0, 0]
        canvas.create_polygon(points, fill=color, smooth=True)
        canvas.create_text(width/2, height/2, text=text, fill=COLORS["bg"], font=FONT_UI_BOLD)
        canvas.bind("<Button-1>", lambda e: command())
        canvas.bind("<Enter>", lambda e: canvas.itemconfig(1, fill=COLORS["accent-hover"]))
        canvas.bind("<Leave>", lambda e: canvas.itemconfig(1, fill=color))

    def open_settings(self):
        SettingsDialog(self)

    # --------------------------------------------------------------- helpers
    def _provider_changed(self) -> None:
        new = next(k for k, p in PROVIDERS.items() if p["label"] == self.provider_label.get())
        if new == self.provider_key:
            return
        self._keys[self.provider_key] = self.api_key.get().strip()
        self.provider_key = new
        self.api_key.set(self._keys.get(new, ""))
        self.model.set(PROVIDERS[new]["models"][0])
        self.base_url.set(PROVIDERS[new]["base_url"])
        self._update_provider_widgets()

    def _update_provider_widgets(self) -> None:
        self.model_box.configure(values=PROVIDERS[self.provider_key]["models"])
        if self.provider_key == "gemini":
            self.provider_warning.configure(text="Testing only: final runs must use DeepSeek")
        else:
            self.provider_warning.configure(text="")

    def _toggle_key(self) -> None:
        self.key_entry.configure(show="" if self.show_key.get() else "•")
        self.show_key.set(not self.show_key.get())

    def _collect_settings(self) -> Settings:
        s = self.settings
        self._keys[self.provider_key] = self.api_key.get().strip()
        s.provider = self.provider_key
        s.api_key = self._keys["deepseek"]
        s.gemini_api_key = self._keys["gemini"]
        s.remember_key = self.remember_key.get()
        s.model = self.model.get().strip() or PROVIDERS[s.provider]["models"][0]
        s.base_url = self.base_url.get().strip() or PROVIDERS[s.provider]["base_url"]
        s.thinking = self.thinking.get()
        try:
            s.max_turns = max(10, int(self.max_turns.get()))
        except (tk.TclError, ValueError):
            s.max_turns = 120
        s.input_files = list(self.files.get(0, tk.END))
        s.output_dir = self.output_dir.get().strip()
        return s

    def _save(self) -> None:
        try:
            save_settings(self._collect_settings())
        except OSError as exc:
            self.events.put(("warning", f"Could not save settings: {exc}"))

    # ... (rest of actions similar, modifying _log and formatting)
    
    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select input files",
            filetypes=[("Architecture inputs", "*.md *.markdown *.puml *.plantuml *.json *.txt"), ("All files", "*.*")],
        )
        existing = set(self.files.get(0, tk.END))
        for p in paths:
            if p not in existing:
                self.files.insert(tk.END, p)

    def remove_files(self) -> None:
        for idx in reversed(self.files.curselection()):
            self.files.delete(idx)

    def use_samples(self) -> None:
        self.files.delete(0, tk.END)
        for p in sorted(SAMPLES_DIR.glob("*.md")):
            self.files.insert(tk.END, str(p))
        if not self.output_dir.get():
            self.output_dir.set(str(Path.home() / "CodeAgent-output" / "space-fractions"))

    def browse_output(self) -> None:
        path = filedialog.askdirectory(title="Select output directory", mustexist=False)
        if path:
            self.output_dir.set(path)

    def open_output(self) -> None:
        path = Path(self.output_dir.get())
        if path.is_dir():
            _open_path(path)
        else:
            messagebox.showinfo(APP_NAME, "The output directory does not exist yet.")

    def test_connection(self) -> None:
        s = self._collect_settings()
        if not s.effective_api_key():
            self.test_result_label.configure(text="✗ API key is empty", fg=COLORS["error"])
            return
        self.test_result_label.configure(text="Testing...", fg=COLORS["text-dim"])

        def work() -> None:
            try:
                client = DeepSeekClient(s.effective_api_key(), model=s.model, base_url=s.base_url, max_retries=1,
                                        timeout=30, provider=s.provider)
                models = client.list_models()
                if s.model in models:
                    msg = "✓ Connected"
                else:
                    msg = f"✓ Connected (model '{s.model}' missing)"
                self.events.put(("test_res", (msg, True)))
            except Exception as exc:
                self.events.put(("test_res", (f"✗ {type(exc).__name__}", False)))

        threading.Thread(target=work, daemon=True).start()

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
            
        s = self._collect_settings()
        problems = []
        if not s.effective_api_key():
            problems.append("- API key is empty")
        if not s.input_files:
            problems.append("- no input files selected")
        if not s.output_dir:
            problems.append("- no output directory selected")
        if problems:
            messagebox.showwarning(APP_NAME, "Cannot start:\n" + "\n".join(problems))
            return
        out = Path(s.output_dir)
        if out.is_dir() and any(p.name != META_DIR for p in out.iterdir()):
            if not messagebox.askyesno(APP_NAME, f"{out}\nis not empty. Files with the same names will be "
                                                 "overwritten. Continue?"):
                return
        self._save()

        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)
        self.plan.delete(*self.plan.get_children())
        self.plan_frame.pack_forget() # Hide plan until todos arrive
        
        self.stop_btn.configure(state=tk.NORMAL, text="■ Stop (Esc)")
        self.cancel_event = threading.Event()
        self.started_at = time.monotonic()
        
        # Lock sidebar
        for w in self.sidebar_widgets:
            try:
                w.configure(state=tk.DISABLED)
            except tk.TclError:
                pass
                
        def work() -> None:
            try:
                result = run_pipeline(s, on_event=lambda e: self.events.put(("event", e)),
                                      cancel_event=self.cancel_event)
                self.events.put(("finished", result))
            except Exception as exc:
                self.events.put(("crashed", f"{type(exc).__name__}: {exc}"))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def stop(self) -> None:
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self.stop_btn.configure(state=tk.DISABLED, text="Stopping...")
            self.events.put(("status", "Stopping after current request..."))

    def on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "The agent is still running. Stop it and quit?"):
                return
            self.cancel_event.set()
        self._save()
        self.root.destroy()

    # ------------------------------------------------------------ event pump
    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "event":
                    self._handle_event(payload)
                elif kind == "finished":
                    self._finished(payload)
                elif kind == "crashed":
                    self.events.put(("error", payload))
                    self._reset_controls()
                elif kind == "test_res":
                    msg, ok = payload
                    self.test_result_label.configure(text=msg, fg=COLORS["success"] if ok else COLORS["error"])
                elif kind == "info":
                    self.status.set(payload)
        except queue.Empty:
            pass
            
        if self.worker and self.worker.is_alive():
            elapsed = int(time.monotonic() - self.started_at)
            # Spinner animation
            spinners = ["·", "✢", "✳", "✶", "✻", "✽", "✻", "✶", "✳", "✢"]
            idx = int(time.monotonic() * 8) % len(spinners)
            spin_char = spinners[idx]
            
            # Gerund logic
            gerund = "Planning…"
            
            self.status.set(f"{spin_char} {gerund} ({elapsed // 60}:{elapsed % 60:02d} elapsed)")
            
        self.root.after(self.POLL_MS, self._poll)
        
    def _log_raw(self, text, tags=()):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text, tags)
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _handle_event(self, e: Event) -> None:
        pass # To be implemented in next step

    def _render_plan(self, todos: list[dict]) -> None:
        self.plan.delete(*self.plan.get_children())
        label = {"pending": "pending", "in_progress": "▶ working", "completed": "✔ done"}
        for t in todos:
            self.plan.insert("", tk.END, text=f"{t['id']}. {t['content']}", values=(label.get(t["status"], ""),))

    def _reset_controls(self) -> None:
        self.stop_btn.configure(state=tk.DISABLED, text="■ Stop (Esc)")
        for w in self.sidebar_widgets:
            try:
                w.configure(state=tk.NORMAL)
            except tk.TclError:
                pass
        self.provider_box.configure(state="readonly")

    def _finished(self, r: AgentResult) -> None:
        self._reset_controls()
        
def launch() -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()

if __name__ == "__main__":
    launch()
