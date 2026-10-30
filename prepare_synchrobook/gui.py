"""Windows desktop workflow: audio + original EPUB → reviewed anchors → API."""
from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .client import NokturnClient
from .core import Cancelled, make_package, save_json
from .transcribe import prepare


class ScrollableTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        canvas = tk.Canvas(self, background="#f4f6f9", highlightthickness=0, height=350)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.content = ttk.Frame(canvas, padding=20)
        window = canvas.create_window((0, 0), window=self.content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.content.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))

        def wheel(event):
            widget = event.widget
            while widget is not None:
                if widget == self:
                    if self.content.winfo_height() > canvas.winfo_height():
                        canvas.yview_scroll(-int(event.delta / 120), "units")
                    break
                widget = getattr(widget, "master", None)
        self.bind_all("<MouseWheel>", wheel, add="+")


class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"PrepareSynchrobook {__version__} · Nokturn")
        self.geometry("1000x780")
        self.minsize(800, 640)
        icon = Path(__file__).resolve().parent.parent / "assets" / "prepare-synchrobook.ico"
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except tk.TclError:
                pass
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f6f9")
        style.configure("TLabel", background="#f4f6f9", foreground="#233044", font=("Segoe UI", 11))
        style.configure("TButton", padding=(14, 9), font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"))
        style.configure("TCheckbutton", background="#f4f6f9", font=("Segoe UI", 10))
        self.configure(background="#f4f6f9")
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.busy = False
        self.buttons = []
        self.project = None
        self.project_file = None
        self.package_path = None
        self.client = None
        self.books = []
        self.rows = []
        self.editing = None
        self.folder = tk.StringVar()
        self.epub_file = tk.StringVar()
        self.book_title = tk.StringVar()
        self.author = tk.StringVar()
        self.model = tk.StringVar(value="small")
        self.language = tk.StringVar(value="pl")
        self.status = tk.StringVar(value="Wybierz folder audiobooka. Oryginalne pliki pozostaną bez zmian.")
        self.server = tk.StringVar(value="https://nokturn-library.pl")
        self.api_key = tk.StringVar()
        self.search_text = tk.StringVar()
        self.reviewed = tk.BooleanVar()
        outer = ttk.Frame(self, padding=24)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Twoja historia. Tekst i dźwięk razem.", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Dopasuj nagranie do właściwego e-booka. Prześlij synchronizację do Nokturna.", wraplength=900).pack(anchor="w", pady=(6, 20))
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True)
        self.prepare_tab = ScrollableTab(self.tabs)
        self.review_tab = ttk.Frame(self.tabs, padding=20)
        self.upload_tab = ScrollableTab(self.tabs)
        for tab, name in [(self.prepare_tab, "1. Przygotuj"), (self.review_tab, "2. Sprawdź dopasowania"), (self.upload_tab, "3. Nokturn")]:
            self.tabs.add(tab, text=name)
        self.build_prepare()
        self.build_review()
        self.build_upload()
        footer = ttk.Frame(outer)
        footer.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Label(footer, textvariable=self.status, wraplength=740).pack(side="left", fill="x", expand=True)
        self.cancel_button = ttk.Button(footer, text="Przerwij", command=self.stop.set, state="disabled")
        self.cancel_button.pack(side="right", padx=(12, 0))
        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.pack(side="bottom", fill="x", pady=(10, 0))
        self.tabs.pack_forget()
        self.tabs.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self.poll)

    def button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=command)
        self.buttons.append(button)
        return button

    def field(self, parent, label, variable, row, *, show=""):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=8)
        entry = ttk.Entry(parent, textvariable=variable, show=show, font=("Segoe UI", 11))
        entry.grid(row=row, column=1, sticky="ew", pady=8)
        parent.columnconfigure(1, weight=1)
        return entry

    def build_prepare(self):
        panel = self.prepare_tab.content
        self.field(panel, "Folder z plikami audio", self.folder, 0)
        self.button(panel, "Wybierz…", self.pick_folder).grid(row=0, column=2, padx=(12, 0))
        self.field(panel, "Właściwy EPUB książki", self.epub_file, 1)
        self.button(panel, "Wybierz EPUB…", self.pick_epub).grid(row=1, column=2, padx=(12, 0))
        self.button(panel, "Lub pobierz EPUB z Nokturna →", lambda: self.tabs.select(self.upload_tab)).grid(row=2, column=1, sticky="e", pady=8)
        self.field(panel, "Tytuł", self.book_title, 3)
        self.field(panel, "Autor", self.author, 4)
        ttk.Label(panel, text="Model rozpoznawania").grid(row=5, column=0, sticky="w", pady=8)
        ttk.Combobox(panel, textvariable=self.model, values=("tiny", "base", "small", "medium", "large-v3", "turbo"), state="readonly").grid(row=5, column=1, sticky="ew", pady=8)
        self.field(panel, "Język (pl, en, de…)", self.language, 6)
        ttk.Label(panel, text="Transkrypcja jest materiałem pomocniczym do odnalezienia miejsc w prawdziwym EPUB. Tekst książki pozostaje bez zmian. Rozpoznawanie odbywa się lokalnie na CPU. Pierwsze użycie modelu wymaga pobrania go z internetu.", wraplength=720).grid(row=7, column=0, columnspan=3, sticky="w", pady=12)
        actions = ttk.Frame(panel)
        actions.grid(row=8, column=0, columnspan=3, sticky="w", pady=8)
        self.button(actions, "Rozpoznaj i dopasuj", self.start_prepare).pack(side="left")
        self.button(actions, "Otwórz istniejący projekt…", self.open_project).pack(side="left", padx=12)

    def build_review(self):
        panel = self.review_tab
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)
        ttk.Label(panel, text="Sprawdź dopasowania: fragment oryginalnego EPUB i rozpoznane słowa z nagrania.", wraplength=740).grid(row=0, column=0, sticky="w", pady=(0, 12))
        listing = ttk.Frame(panel)
        listing.grid(row=1, column=0, sticky="nsew")
        self.segments = ttk.Treeview(listing, columns=("chapter", "time", "text"), show="headings", height=8, selectmode="browse")
        for key, title, width in [("chapter", "EPUB", 80), ("time", "Audio (sekundy)", 140), ("text", "Oryginalny tekst książki", 580)]:
            self.segments.heading(key, text=title)
            self.segments.column(key, width=width, minwidth=60, stretch=key == "text")
        scroll = ttk.Scrollbar(listing, orient="vertical", command=self.segments.yview)
        self.segments.configure(yscrollcommand=scroll.set)
        self.segments.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.segments.bind("<<TreeviewSelect>>", self.select_segment)
        self.editor = tk.Text(panel, height=5, wrap="word", font=("Segoe UI", 12), padx=12, pady=10, undo=True)
        self.editor.grid(row=2, column=0, sticky="ew", pady=12)
        self.editor.configure(state="disabled")
        actions = ttk.Frame(panel)
        actions.grid(row=3, column=0, sticky="ew")
        self.button(actions, "Sprawdź dopasowania", self.show_alignment).pack(side="left")
        self.button(actions, "Zbuduj / odśwież paczkę ZIP", self.export_package).pack(side="right")

    def build_upload(self):
        panel = self.upload_tab.content
        self.field(panel, "Adres serwera Nokturn", self.server, 0)
        self.field(panel, "Klucz API synchrobooków", self.api_key, 1, show="●")
        ttk.Label(panel, text="Wygeneruj oddzielny klucz w Nokturnie. Nie podawaj hasła do konta. Klucz ma dostęp tylko do przygotowania i importu synchronizacji i można go odwołać.", wraplength=720).grid(row=2, column=0, columnspan=3, sticky="w", pady=12)
        self.button(panel, "Połącz z Nokturnem", self.login).grid(row=3, column=1, sticky="e", pady=10)
        self.field(panel, "Wyszukaj tytuł w bibliotece", self.search_text, 4)
        self.button(panel, "Szukaj", self.search_books).grid(row=4, column=2, padx=(12, 0))
        self.book_picker = ttk.Combobox(panel, state="readonly", font=("Segoe UI", 11))
        self.book_picker.grid(row=5, column=0, columnspan=3, sticky="ew", pady=12)
        self.button(panel, "Pobierz EPUB wybranego audiobooka", self.download_epub).grid(row=6, column=1, sticky="e", pady=8)
        ttk.Checkbutton(panel, text="Sprawdziłem dopasowanie i wybrałem właściwy audiobook", variable=self.reviewed).grid(row=7, column=0, columnspan=3, sticky="w", pady=12)
        self.button(panel, "Prześlij sprawdzoną synchronizację", self.upload).grid(row=8, column=1, sticky="e", pady=12)
        ttk.Label(panel, text="Klucz nie jest zapisywany na dysku. Nokturn sprawdzi zgodność nagrania oraz oryginalnego EPUB. Wysyłane są wyłącznie znaczniki synchronizacji. Tekst e-booka i postęp audio pozostają bez zmian.", wraplength=720).grid(row=9, column=0, columnspan=3, sticky="w", pady=10)

    def run_job(self, action, success, *, cancellable=True):
        if self.busy:
            return
        self.busy = True
        self.stop.clear()
        for button in self.buttons:
            button.configure(state="disabled")
        self.cancel_button.configure(state="normal" if cancellable else "disabled")
        self.progress.start(15)
        self.editor.configure(state="disabled")
        self.book_picker.configure(state="disabled")
        def worker():
            try:
                value = action()
                self.events.put(("done", (success, value)))
            except Cancelled:
                self.events.put(("cancelled", None))
            except Exception as error:
                self.events.put(("error", str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self.status.set(value)
                    continue
                self.busy = False
                self.progress.stop()
                self.editor.configure(state="disabled")
                self.book_picker.configure(state="readonly")
                self.cancel_button.configure(state="disabled")
                for button in self.buttons:
                    button.configure(state="normal")
                if kind == "done":
                    callback, result = value
                    try:
                        callback(result)
                    except Exception as error:
                        self.status.set("Nie udało się wyświetlić wyniku operacji.")
                        messagebox.showerror("PrepareSynchrobook", str(error), parent=self)
                elif kind == "cancelled":
                    self.status.set("Przerwano. Zakończone pliki są zachowane w pamięci projektu.")
                else:
                    self.status.set("Nie ukończono operacji. Sprawdź komunikat.")
                    messagebox.showerror("PrepareSynchrobook", value, parent=self)
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def pick_folder(self):
        folder = filedialog.askdirectory(title="Wybierz folder jednego audiobooka", parent=self)
        if folder:
            self.folder.set(folder)
            if not self.book_title.get():
                self.book_title.set(Path(folder).name)

    def start_prepare(self):
        folder, title, author = Path(self.folder.get()), self.book_title.get().strip(), self.author.get().strip()
        language, model = self.language.get().strip().lower(), self.model.get()
        epub_path = Path(self.epub_file.get())
        if not folder.is_dir() or not title or not epub_path.is_file():
            messagebox.showerror("Przygotowanie", "Wybierz katalog z audiobookiem, właściwy EPUB i wpisz tytuł.", parent=self)
            return
        output_value = filedialog.askdirectory(title="Wybierz folder projektu (wyniki i pamięć rozpoznawania)", parent=self)
        if not output_value:
            return
        output = Path(output_value)
        if output == folder or folder in output.parents:
            messagebox.showerror("Przygotowanie", "Wybierz folder projektu poza oryginalnym katalogiem audiobooka.", parent=self)
            return
        if (output / "project.json").exists() and not messagebox.askyesno("Istniejący projekt", "Zastąpić istniejący projekt? Zgodne wyniki rozpoznawania zostaną wykorzystane z pamięci.", parent=self):
            return
        self.status.set("Rozpoczynanie przygotowania…")
        self.run_job(lambda: prepare(folder, output, title, author, model, language,
                                    notify=lambda text: self.events.put(("progress", text)), cancel=self.stop.is_set, epub_file=epub_path),
                     lambda project: self.load_project(project, output / "project.json"))

    def open_project(self):
        value = filedialog.askopenfilename(title="Otwórz project.json", filetypes=[("Projekt", "*.json")], parent=self)
        if value:
            try:
                project = json.loads(Path(value).read_text(encoding="utf-8-sig"))
                self.load_project(project, Path(value))
            except Exception as error:
                messagebox.showerror("Projekt", str(error), parent=self)

    def pick_epub(self):
        value = filedialog.askopenfilename(title="Wybierz oryginalny EPUB książki", filetypes=[("EPUB", "*.epub")], parent=self)
        if value:
            self.epub_file.set(value)

    def load_project(self, project, path):
        self.project, self.project_file, self.package_path = project, path, None
        self.epub_file.set(project.get("epub_file", ""))
        self.reviewed.set(False)
        self.rows = []
        self.segments.delete(*self.segments.get_children())
        self.tabs.select(self.review_tab)
        self.status.set("Rozpoznawanie zapisane. Sprawdź dopasowania do oryginalnego EPUB.")
        self.show_alignment()

    def store_edit(self):
        pass  # Original EPUB and recognized word times are never edited by this UI.

    def show_alignment(self):
        if not self.project:
            messagebox.showinfo("Synchronizacja", "Najpierw przygotuj lub otwórz projekt.", parent=self)
            return
        from .alignment import align_project, epub_paragraphs
        project = self.project
        def action():
            stamps, report, _ = align_project(project)
            paragraphs, _ = epub_paragraphs(Path(project["epub_file"]))
            save_json(self.project_file.parent / "alignment-report.json", report)
            return stamps, report, paragraphs
        def display(result):
            stamps, report, paragraphs = result
            texts = {(p["chapter_idx"], p["para_idx"]): p["text"] for p in paragraphs}
            self.rows = [{**stamp, "text": texts[stamp["chapter_idx"], stamp["para_idx"]]} for stamp in stamps]
            self.segments.delete(*self.segments.get_children())
            for index, stamp in enumerate(self.rows):
                self.segments.insert("", "end", iid=str(index), values=(f'{stamp["chapter_idx"] + 1}/{stamp["para_idx"] + 1}', f'{stamp["start_sec"]:.1f}–{stamp["end_sec"]:.1f}', stamp["text"]))
            self.status.set(f'Dopasowano {report["matched_paragraphs"]}/{report["total_paragraphs"]} akapitów · pokrycie tekstu {report["text_coverage"]:.0%}. Sprawdź próbki oraz alignment-report.json.')
            if self.rows:
                self.segments.selection_set("0")
        self.run_job(action, display, cancellable=False)

    def select_segment(self, _=None):
        selected = self.segments.selection()
        if not selected or self.busy:
            return
        stamp = self.rows[int(selected[0])]
        recognized = []
        offset = 0.0
        for chapter in self.project["chapters"]:
            for segment in chapter["segments"]:
                if offset + segment["end"] >= stamp["start_sec"] and offset + segment["start"] <= stamp["end_sec"]:
                    recognized.append(segment["text"])
            offset += chapter["source"]["duration_sec"]
        self.editor.configure(state="normal")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", "EPUB (oryginalny tekst):\n" + stamp["text"] + "\n\nRozpoznane audio w tym przedziale:\n" + " ".join(recognized))
        self.editor.configure(state="disabled")

    def export_package(self):
        if not self.project:
            messagebox.showinfo("Paczka", "Najpierw przygotuj lub otwórz projekt.", parent=self)
            return
        project, destination = self.project, self.project_file.parent / "synchrobook.nokturn-sync.zip"
        def action():
            data, metadata = make_package(project)
            temporary = destination.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(destination)
            save_json(destination.parent / "alignment-report.json", metadata["alignment_report"])
            return destination, metadata["alignment_report"]
        def exported(result):
            self.package_path, report = result
            self.reviewed.set(False)
            self.status.set(f'Paczka gotowa · {report["text_coverage"]:.0%} tekstu dopasowane. Zawiera tylko dane synchronizacji; EPUB pozostaje bez zmian.')
            self.tabs.select(self.upload_tab)
        self.run_job(action, exported, cancellable=False)

    def download_epub(self):
        if not self.client or self.book_picker.current() < 0:
            messagebox.showinfo("EPUB", "Połącz się z Nokturnem, wyszukaj i wybierz audiobook.", parent=self)
            return
        book = self.books[self.book_picker.current()]
        value = filedialog.asksaveasfilename(title="Zapisz oryginalny EPUB z Nokturna", initialfile=f'nokturn-{book["id"]}.epub', defaultextension=".epub", filetypes=[("EPUB", "*.epub")], parent=self)
        if not value:
            return
        client, destination = self.client, Path(value)
        def downloaded(path):
            self.epub_file.set(str(path))
            self.book_title.set(book["title"])
            self.author.set(book["authors"])
            self.status.set("Pobrano oryginalny EPUB. Wybierz lokalny folder nagrania i przygotuj dopasowanie.")
            self.tabs.select(self.prepare_tab)
        self.run_job(lambda: client.download_epub(book["id"], destination), downloaded, cancellable=False)

    def login(self):
        try:
            client = NokturnClient(self.server.get())
        except ValueError as error:
            messagebox.showerror("Połączenie", str(error), parent=self)
            return
        api_key = self.api_key.get()
        self.api_key.set("")
        self.client = None
        self.books = []
        self.book_picker.set("")
        self.book_picker.configure(values=())
        def connected(display_name):
            self.client = client
            self.status.set(f"Połączono: {display_name}. Wyszukaj i wybierz audiobook.")
        self.status.set("Łączenie z Nokturnem…")
        self.run_job(lambda: client.connect(api_key), connected, cancellable=False)

    def search_books(self):
        if not self.client:
            messagebox.showinfo("Nokturn", "Najpierw połącz się z serwerem.", parent=self)
            return
        client, query = self.client, self.search_text.get().strip()
        def found(books):
            self.books = books
            self.book_picker.set("")
            self.book_picker.configure(values=[f'#{b["id"]} · {b["authors"]} — {b["title"]}' for b in books])
            self.status.set(f"Znaleziono {len(books)} tytułów (maksymalnie 100). Wybierz właściwe wydanie.")
        self.run_job(lambda: client.search(query), found, cancellable=False)

    def upload(self):
        try:
            self.store_edit()
        except ValueError as error:
            messagebox.showerror("Korekta tekstu", str(error), parent=self)
            return
        if not self.client or not self.package_path or not self.reviewed.get() or self.book_picker.current() < 0:
            messagebox.showinfo("Import", "Połącz się, zbuduj paczkę, wybierz tytuł i potwierdź sprawdzenie tekstu.", parent=self)
            return
        book = self.books[self.book_picker.current()]
        if not messagebox.askyesno("Prześlij do biblioteki", f'Przesłać synchrobook do:\n{book["authors"]} — {book["title"]} (#{book["id"]})?\n\nZastąpisz dane synchronizacji. Tekst EPUB oraz postęp audio pozostaną bez zmian.', parent=self):
            return
        client, path = self.client, self.package_path
        self.status.set("Przesyłanie i sprawdzanie nagrania na serwerze. Duże audiobooki wymagają czasu…")
        self.run_job(lambda: client.upload(book["id"], path),
                     lambda result: self.status.set(f'Zaimportowano synchronizację: #{result["audiobook_id"]}, {result["paragraphs"]} fragmentów. Otwórz książkę ponownie w Nokturnie.'),
                     cancellable=False)

    def close(self):
        if self.busy:
            messagebox.showinfo("Trwa praca", "Poczekaj na zakończenie. Przy rozpoznawaniu możesz wybrać Przerwij; zakończone pliki zostaną zachowane.", parent=self)
            return
        try:
            self.store_edit()
        except ValueError as error:
            messagebox.showerror("Korekta", str(error), parent=self)
            return
        if self.client:
            self.client.token = ""
        self.destroy()


def main():
    Application().mainloop()
