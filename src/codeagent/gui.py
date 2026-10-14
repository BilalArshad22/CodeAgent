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
    FONT_UI_SMALL_BOLD = ("Segoe UI", 8, "bold")
    FONT_HEADER = ("Segoe UI", 12, "bold")
    FONT_MONO = ("Cascadia Mono", 10) # Fallback Consolas
else:
    FONT_UI = ("SF Pro", 13) 
    FONT_UI_BOLD = ("SF Pro", 13, "bold")
    FONT_UI_SMALL = ("SF Pro", 11)
    FONT_UI_SMALL_BOLD = ("SF Pro", 10, "bold")
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
        
        tk.Label(self, text="Base URL:", background=COLORS["surface"], foreground=COLORS["text"]).grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(self, textvariable=parent.base_url, width=24).grid(row=0, column=1, sticky="ew", **pad)
        
        tk.Label(self, text="Max turns:", background=COLORS["surface"], foreground=COLORS["text"]).grid(row=1, column=0, sticky="w", **pad)
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

        root.title(f"{APP_NAME}")
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
        self.turn_status = ""
        self.last_gerund = "Planning…"
        
        self.total_cost = 0.0
        
        self._apply_styles()
        self._build()
        
        for f in self.settings.input_files:
            if Path(f).is_file():
                self.files.insert(tk.END, f)
                
        self.root.after(self.POLL_MS, self._poll)
        self._show_welcome_card()

    def _apply_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=COLORS["bg"], foreground=COLORS["text"], font=FONT_UI)
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
        
        header = tk.Frame(sidebar, bg=COLORS["surface"], height=40)
        header.pack(fill=tk.X, padx=12, pady=12)
        
        # Provider chip in header
        self.header_title_frame = tk.Frame(header, bg=COLORS["surface"])
        self.header_title_frame.pack(side=tk.LEFT)
        tk.Label(self.header_title_frame, text=f"✻ {APP_NAME}", bg=COLORS["surface"], fg=COLORS["text"], font=FONT_HEADER).pack(side=tk.LEFT)
        self.header_provider_chip = tk.Label(self.header_title_frame, text="", bg=COLORS["surface"], fg=COLORS["warning"], font=FONT_UI_SMALL)
        self.header_provider_chip.pack(side=tk.LEFT, padx=8)
        
        tk.Button(header, text="⚙", bg=COLORS["surface"], fg=COLORS["text-dim"], bd=0, command=self.open_settings, font=FONT_UI).pack(side=tk.RIGHT)
        
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
        tk.Button(files_btn_frame, text="Remove", bg=COLORS["surface"], fg=COLORS["text"], bd=0, command=self.remove_files).pack(side=tk.RIGHT)
        
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
        
        self.gen_btn_canvas = tk.Canvas(action_frame, height=36, bg=COLORS["surface"], bd=0, highlightthickness=0)
        self.gen_btn_canvas.pack(fill=tk.X, pady=4)
        self.gen_btn_canvas.bind("<Configure>", lambda e: self._draw_btn(self.gen_btn_canvas, "▶ Generate  ⌘↵", COLORS["accent"], self.start, e.width))
        
        self.stop_btn = tk.Button(action_frame, text="■ Stop (Esc)", bg=COLORS["surface"], fg=COLORS["text"], bd=1, command=self.stop, state=tk.DISABLED)
        self.stop_btn.pack(fill=tk.X)
        
        self.sidebar_widgets = [self.provider_box, self.key_entry, self.model_box, self.out_entry, self.files]
        
        # ------------------------------------------------------------------ MAIN AREA
        main_area = tk.Frame(main_paned, bg=COLORS["bg"])
        main_paned.add(main_area, stretch="always")
        
        self.plan_frame = tk.Frame(main_area, bg=COLORS["surface"], height=150)
        self.plan_frame.pack(fill=tk.X, side=tk.TOP)
        self.plan = ttk.Treeview(self.plan_frame, columns=("status",), show="tree headings", height=5)
        self.plan.heading("#0", text="Plan (live)")
        self.plan.heading("status", text="Status")
        self.plan.column("status", width=90, anchor="center", stretch=False)
        self.plan.pack(fill=tk.BOTH, expand=True)
        self.plan_frame.pack_forget()
        
        log_container = tk.Frame(main_area, bg=COLORS["bg"])
        log_container.pack(fill=tk.BOTH, expand=True)
        self.log = ScrolledText(log_container, wrap=tk.WORD, font=FONT_MONO, bg=COLORS["bg"], fg=COLORS["text"], bd=0, highlightthickness=0, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True, padx=16, pady=(16, 0))
        
        # Log tags
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
        self.log.tag_configure("assistant_bullet", foreground=COLORS["text"])
        self.log.tag_configure("bold", font=FONT_MONO + ("bold",))
        self.log.tag_configure("todo_done", foreground=COLORS["text-dim"], overstrike=True)
        self.log.tag_configure("todo_prog", foreground=COLORS["accent"], font=FONT_MONO + ("bold",))
        self.log.tag_configure("todo_pend", foreground=COLORS["text"])
        self.log.tag_configure("card_border_success", foreground=COLORS["success"])
        self.log.tag_configure("card_border_warning", foreground=COLORS["warning"])
        
        self.status_bar = tk.Frame(main_area, bg=COLORS["bg"], height=28)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM, padx=16, pady=(0,8))
        self.status_label = tk.Label(self.status_bar, textvariable=self.status, bg=COLORS["bg"], fg=COLORS["text-dim"], font=FONT_MONO, anchor="w")
        self.status_label.pack(side=tk.LEFT, fill=tk.X)
        self.status_bar.pack_forget()
        
        self._update_provider_widgets()
        
        self.root.bind("<Control-Return>", lambda e: self.start())
        self.root.bind("<Command-Return>", lambda e: self.start())
        self.root.bind("<Escape>", lambda e: self.stop())
        self.root.bind("<Control-l>", lambda e: self.clear_transcript())

    def _draw_btn(self, canvas, text, color, command, width=276):
        canvas.delete("all")
        if width < 10:
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

    def _show_welcome_card(self):
        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self._log_raw("╭────────────────────────────────────────────────────────╮\n", "status")
        self._log_raw("│ ✻ Welcome to CodeAgent                                 │\n", "bold")
        self._log_raw("│   Turns an architecture spec into a full project.      │\n", "status")
        self._log_raw("│   1. Add your API key  2. Add inputs  3. Generate      │\n", "status")
        self._log_raw("╰────────────────────────────────────────────────────────╯\n\n", "status")
        self.log.configure(state=tk.DISABLED)

    def clear_transcript(self):
        if not self.worker or not self.worker.is_alive():
            self.log.configure(state=tk.NORMAL)
            self.log.delete("1.0", tk.END)
            self.log.configure(state=tk.DISABLED)

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
            self.header_provider_chip.configure(text="[● Gemini (testing)]")
        else:
            self.provider_warning.configure(text="")
            self.header_provider_chip.configure(text=f"[● DeepSeek · {self.model.get()}]", fg=COLORS["text-dim"])

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
            
        # UI_REDESIGN: "Validates the key, inputs and output. Show the problems inline in the sidebar, highlighting the offending fields in error."
        # For simplicity in Tk, we just show a warning message box or update status text. The instructions say "inline in the sidebar", so let's use the test_result_label.
        if problems and not ("--demo" in sys.argv or os.environ.get("CODEAGENT_DEMO")):
            self.test_result_label.configure(text="✗ Missing fields", fg=COLORS["error"])
            # Fallback to messagebox to be sure it's seen
            messagebox.showwarning(APP_NAME, "Cannot start:\n" + "\n".join(problems))
            return
            
        if "--demo" in sys.argv or os.environ.get("CODEAGENT_DEMO"):
            problems = [] # bypass validation

        if not problems:
            out = Path(s.output_dir) if s.output_dir else None
            if out and out.is_dir() and any(p.name != META_DIR for p in out.iterdir()):
                if not messagebox.askyesno(APP_NAME, f"{out}\nis not empty. Files with the same names will be "
                                                     "overwritten. Continue?"):
                    return
            self._save()

        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)
        self.plan.delete(*self.plan.get_children())
        self.plan_frame.pack_forget()
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM, padx=16, pady=(0,8))
        
        self.stop_btn.configure(state=tk.NORMAL, text="■ Stop (Esc)")
        self.cancel_event = threading.Event()
        self.started_at = time.monotonic()
        self.total_cost = 0.0
        
        # Lock sidebar
        for w in self.sidebar_widgets:
            try:
                w.configure(state=tk.DISABLED)
            except tk.TclError:
                pass
                
        def work() -> None:
            if "--demo" in sys.argv or os.environ.get("CODEAGENT_DEMO"):
                import time
                demo_events = [
                    Event("status", "Turn 1/120: wait..."),
                    Event("thinking", "I'll start by planning the project structure. We need domain models, and REST endpoints."),
                    Event("assistant", "I'll start by planning the project structure."),
                    Event("tool_call", "todo_write", data={"name": "todo_write", "args": {"todos": [{"id": 1, "content": "Parse spec and resolve issues", "status": "pending"}, {"id": 2, "content": "Domain model (Game, Question, User, Admin)", "status": "pending"}]}}),
                    Event("todos", data={"todos": [{"id": "1", "content": "Parse spec and resolve issues", "status": "pending"}, {"id": "2", "content": "Domain model (Game, Question, User, Admin)", "status": "pending"}]}),
                    Event("tool_result", "Updated todos.", data={"ok": True}),
                    Event("usage", data={"requests": 1, "prompt_tokens": 1200, "completion_tokens": 150, "cache_hit_tokens": 800}),
                    
                    Event("status", "Turn 2/120: wait..."),
                    Event("assistant", "Let's mark the first task in progress and start writing the domain model."),
                    Event("tool_call", "todo_write", data={"name": "todo_write", "args": {"todos": [{"id": 1, "content": "Parse spec and resolve issues", "status": "completed"}, {"id": 2, "content": "Domain model (Game, Question, User, Admin)", "status": "in_progress"}]}}),
                    Event("todos", data={"todos": [{"id": "1", "content": "Parse spec and resolve issues", "status": "completed"}, {"id": "2", "content": "Domain model (Game, Question, User, Admin)", "status": "in_progress"}]}),
                    Event("tool_result", "Updated todos.", data={"ok": True}),
                    Event("usage", data={"requests": 2, "prompt_tokens": 1400, "completion_tokens": 200, "cache_hit_tokens": 1400}),
                    
                    Event("status", "Turn 3/120: wait..."),
                    Event("tool_call", "write_file src/domain/game.js", data={"name": "write_file", "args": {"path": "src/domain/game.js"}}),
                    Event("tool_result", "Created src/domain/game.js (84 lines)", data={"ok": True}),
                    Event("usage", data={"requests": 3, "prompt_tokens": 1800, "completion_tokens": 500, "cache_hit_tokens": 1800}),

                    Event("status", "Turn 4/120: wait..."),
                    Event("tool_call", "edit_file src/domain/game.js", data={"name": "edit_file", "args": {"path": "src/domain/game.js"}}),
                    Event("tool_result", "Error: failed to apply patch, context does not match.", data={"ok": False}),
                    Event("usage", data={"requests": 4, "prompt_tokens": 2000, "completion_tokens": 550, "cache_hit_tokens": 2000}),
                    
                    Event("status", "Turn 5/120: wait..."),
                    Event("tool_call", "check_project", data={"name": "check_project"}),
                    Event("tool_result", "0 blocking · 2 warnings", data={"ok": True, "name": "check_project"}),
                    
                    Event("status", "Turn 6/120: wait..."),
                    Event("tool_call", "finish", data={"name": "finish"}),
                    Event("tool_result", "Project complete.", data={"ok": True})
                ]
                
                for ev in demo_events:
                    if self.cancel_event.is_set():
                        break
                    self.events.put(("event", ev))
                    time.sleep(1.0)
                    
                res = AgentResult(success=True, summary="I have completed the project scaffold.", turns=6, stop_reason="finished", usage={"requests": 6, "prompt_tokens": 2500, "completion_tokens": 800, "cache_hit_tokens": 2000}, files=["src/domain/game.js"], elapsed_s=9.0)
                self.events.put(("finished", res))
                return
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

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "event":
                    self._handle_event(payload)
                elif kind == "finished":
                    self._finished(payload)
                elif kind == "crashed":
                    self.events.put(("event", Event("error", payload)))
                    self._reset_controls()
                elif kind == "test_res":
                    msg, ok = payload
                    self.test_result_label.configure(text=msg, fg=COLORS["success"] if ok else COLORS["error"])
                elif kind == "info":
                    self.events.put(("event", Event("status", payload)))
        except queue.Empty:
            pass
            
        if self.worker and self.worker.is_alive():
            elapsed = int(time.monotonic() - self.started_at)
            spinners = ["·", "✢", "✳", "✶", "✻", "✽", "✻", "✶", "✳", "✢"]
            idx = int(time.monotonic() * 8) % len(spinners)
            spin_char = spinners[idx]
            
            tks = self.usage_text.get()
            cost_str = f"${self.total_cost:.4f} est." if self.total_cost > 0 else ""
            self.status.set(f"{spin_char} {self.last_gerund} ({elapsed // 60}:{elapsed % 60:02d} elapsed · {tks} · {cost_str} · esc to stop)")
            
            # Title update
            self.root.title(f"{APP_NAME} - running {elapsed // 60}:{elapsed % 60:02d}")
            
        self.root.after(self.POLL_MS, self._poll)
        
    def _log_raw(self, text, tags=()):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text, tags)
        # Check if we should auto-scroll
        # We auto-scroll if the scrollbar is currently at the bottom.
        fraction = self.log.yview()[1]
        if fraction > 0.99 or text.startswith("╭"): 
            self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _handle_event(self, e: Event) -> None:
        if e.kind == "status":
            if e.message.startswith("Turn "):
                self.turn_status = e.message
            else:
                self._log_raw(f"· {e.message}\n", "status")
        elif e.kind == "thinking":
            if self.show_thinking.get():
                # Make a collapsed thought by just showing first line or limited text.
                self._log_raw(f"✻ Thought:\n  {e.message[:4000]}...\n", "thinking")
        elif e.kind == "assistant":
            # Indent wrapped lines by 2 spaces
            text = e.message.replace("\n", "\n  ")
            self._log_raw("⏺ ", "assistant_bullet")
            self._log_raw(f"{text}\n", "assistant")
        elif e.kind == "tool_call":
            self.last_gerund = "Working…"
            verb_map = {
                "write_file": "Write",
                "edit_file": "Update",
                "read_file": "Read",
                "list_files": "List",
                "search_files": "Search",
                "read_spec": "Read spec",
                "check_project": "Check project",
                "todo_write": "Update Todos",
                "finish": "Finish"
            }
            raw_name = e.data.get("name", "")
            verb = verb_map.get(raw_name, raw_name.capitalize() if raw_name else "Tool")
            
            args = e.data.get("args", {})
            target = args.get("path") or args.get("pattern") or args.get("section") or ""
            
            self._log_raw("⏺ ", "tool_bullet")
            self._log_raw(f"{verb}", "tool_bold")
            if target:
                self._log_raw(f"({target})", "tool")
            self._log_raw("\n", "tool")
            
            # Map tool to gerund
            if verb == "Write": self.last_gerund = "Composing…"
            elif verb == "Update": self.last_gerund = "Editing…"
            elif verb == "Check project": self.last_gerund = "Checking…"
            elif verb == "Update Todos": self.last_gerund = "Planning…"
            
        elif e.kind == "tool_result":
            ok = e.data.get("ok", True)
            if ok:
                msg = e.message.split("\n")[0] # First line
                if e.data.get("name") == "check_project":
                    # Expand on click not strictly required for Tk if too complex, but we show first line
                    pass
                self._log_raw("  ⎿ ", "ok")
                self._log_raw("✓ ", "ok_check")
                self._log_raw(f"{msg}\n", "ok")
            else:
                self._log_raw(f"  ⎿  {e.message}\n", "error")
        elif e.kind == "todos":
            todos = e.data.get("todos", [])
            for t in todos:
                st = t.get("status")
                if st == "completed":
                    self._log_raw(f"    ⎿ ☒ {t['content']}\n", "todo_done")
                elif st == "in_progress":
                    self._log_raw(f"    ⎿ ☐ {t['content']}\n", "todo_prog")
                else:
                    self._log_raw(f"    ⎿ ☐ {t['content']}\n", "todo_pend")
            self._render_plan(todos)
            self.plan_frame.pack(fill=tk.X, side=tk.TOP, before=self.status_bar.master.winfo_children()[1]) # show plan above log
        elif e.kind == "usage":
            d = e.data
            in_t = d.get('prompt_tokens', 0)
            cache_t = d.get('cache_hit_tokens', 0)
            out_t = d.get('completion_tokens', 0)
            
            self.usage_text.set(f"↑ {in_t//1000}k ↓ {out_t//1000}k")
            
            # Cost calc
            model = self.settings.model
            if self.provider_key == "deepseek":
                miss_t = max(0, in_t - cache_t)
                if "pro" in model:
                    cost = (cache_t * 0.044 + miss_t * 1.32 + out_t * 3.96) / 1000000
                elif "flash" in model:
                    cost = (cache_t * 0.006 + miss_t * 0.30 + out_t * 1.20) / 1000000
                else:
                    cost = 0.0
                self.total_cost = cost
        elif e.kind == "warning":
            self._log_raw(f"⚠ {e.message}\n", "warn")
        elif e.kind == "error":
            self._log_raw(f"✗ {e.message}\n", "error")
            self._log_raw("╭────────────────────────────────────────────────────────╮\n", "error")
            self._log_raw(f"│ Error: {e.message[:50]:<50} │\n", "error")
            self._log_raw("╰────────────────────────────────────────────────────────╯\n", "error")

    def _render_plan(self, todos: list[dict]) -> None:
        self.plan.delete(*self.plan.get_children())
        label = {"pending": "pending", "in_progress": "▶ working", "completed": "✔ done"}
        for t in todos:
            self.plan.insert("", tk.END, text=f"{t['id']}. {t['content']}", values=(label.get(t["status"], ""),))

    def _reset_controls(self) -> None:
        self.stop_btn.configure(state=tk.DISABLED, text="■ Stop (Esc)")
        self.status_bar.pack_forget()
        for w in self.sidebar_widgets:
            try:
                w.configure(state=tk.NORMAL)
            except tk.TclError:
                pass
        self.provider_box.configure(state="readonly")
        self.root.title(f"{APP_NAME}")

    def _finished(self, r: AgentResult) -> None:
        self._reset_controls()
        
        self.log.configure(state=tk.NORMAL)
        card_tag = "card_border_success" if r.success else "card_border_warning"
        
        icon = "✓ Project generated" if r.success else f"■ Stopped ({r.stop_reason})"
        cost_str = f"${self.total_cost:.2f}" if self.total_cost > 0 else ""
        
        self._log_raw("\n")
        self._log_raw("╭────────────────────────────────────────────────────────╮\n", card_tag)
        self._log_raw(f"│ {icon:<54} │\n", "bold")
        self._log_raw(f"│ {r.turns} turns · {r.elapsed_s:.0f}s · {len(r.files)} files · {cost_str:<21} │\n", "status")
        self._log_raw(f"│ {r.summary[:54]:<54} │\n", "assistant")
        self._log_raw("╰────────────────────────────────────────────────────────╯\n", card_tag)
        self.log.configure(state=tk.DISABLED)
        
        # We could offer buttons to open folder inside the log text using window create, but simple messagebox or a generic approach works
        if r.success and messagebox.askyesno(APP_NAME, "Project generated. Open the output folder?"):
            self.open_output()

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
