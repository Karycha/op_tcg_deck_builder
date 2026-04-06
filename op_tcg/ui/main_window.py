import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import json
from datetime import datetime, timezone
import queue
import uuid
import requests
from PIL import Image, ImageTk
from io import BytesIO
import threading
from typing import Any, Optional

import customtkinter as ctk

from op_tcg.config import (
    CACHE_FILE,
    CARD_ID_RE,
    CARD_SOURCES,
    FILTER_ALL,
    OWNED_FILE,
    THUMB_WORKERS,
    USER_DECKS_FILE,
    parse_generic_cards,
)


class DeckBuilderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.root = self
        self.title("One Piece TCG — Deck Builder")
        self.geometry("1560x900")
        self.minsize(1100, 700)
        self.configure(fg_color="#0b1220")

        # Data
        self.cards_database = {}
        self.owned_cards = {}
        self.card_images = {}
        self.thumb_images: dict[str, ImageTk.PhotoImage] = {}
        self.user_decks_data: list[dict[str, Any]] = []
        self._thumb_queue: "queue.Queue[tuple[str, tk.Label]]" = queue.Queue()
        self.session = requests.Session()
        self.load_data()
        self._load_user_decks_from_disk()
        for _ in range(THUMB_WORKERS):
            threading.Thread(target=self._thumb_worker_loop, daemon=True).start()

        # Theme (simple, modern dark)
        self.C_BG = "#0b1220"
        self.C_SURFACE = "#0f1a2b"
        self.C_PANEL = "#111f33"
        self.C_TEXT = "#e7eefc"
        self.C_MUTED = "#a9b7d0"
        self.C_BORDER = "#22324f"
        self.C_ACCENT = "#6ba3ff"
        self.C_ACCENT_2 = "#22c55e"
        self.C_DANGER = "#ef4444"

        # Style
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background=self.C_BG)
        style.configure('TLabel', background=self.C_BG, foreground=self.C_TEXT)
        style.configure('Muted.TLabel', background=self.C_BG, foreground=self.C_MUTED)

        style.configure(
            'Primary.TButton',
            background=self.C_ACCENT,
            foreground="#0b1220",
            padding=(12, 7),
            borderwidth=0,
        )
        style.map('Primary.TButton', background=[('active', '#86b6ff')])

        style.configure(
            'TButton',
            background=self.C_PANEL,
            foreground=self.C_TEXT,
            padding=(10, 6),
            borderwidth=0,
        )
        style.map('TButton', background=[('active', '#1a2b46')])

        style.configure(
            'Treeview',
            background=self.C_SURFACE,
            foreground=self.C_TEXT,
            fieldbackground=self.C_SURFACE,
            bordercolor=self.C_BORDER,
            lightcolor=self.C_BORDER,
            darkcolor=self.C_BORDER,
            rowheight=26,
        )
        style.configure(
            'Treeview.Heading',
            background=self.C_PANEL,
            foreground=self.C_TEXT,
            relief='flat',
            padding=(8, 6),
        )
        style.map('Treeview.Heading', background=[('active', '#1a2b46')])
        # Zebra + hover (tags: odd, even, hover)
        style.map(
            'Treeview',
            background=[('selected', self.C_PANEL)],
            foreground=[('selected', self.C_TEXT)],
        )

        style.configure('TLabelframe', background=self.C_BG, foreground=self.C_TEXT, bordercolor=self.C_BORDER)
        style.configure('TLabelframe.Label', background=self.C_BG, foreground=self.C_TEXT)

        style.configure('TEntry', padding=(10, 6))
        style.configure(
            'TCombobox',
            fieldbackground=self.C_SURFACE,
            background=self.C_PANEL,
            foreground=self.C_TEXT,
            arrowcolor=self.C_TEXT,
            padding=(8, 4),
        )
        style.map('TCombobox', fieldbackground=[('readonly', self.C_SURFACE)], background=[('readonly', self.C_PANEL)])
        style.configure('TProgressbar', troughcolor=self.C_PANEL, background=self.C_ACCENT, bordercolor=self.C_BORDER)
        style.configure('TCheckbutton', background=self.C_BG, foreground=self.C_TEXT)

        self.status_var = tk.StringVar(value="Ładowanie kart…")
        self.loading_label = ctk.CTkLabel(
            self,
            textvariable=self.status_var,
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=self.C_MUTED,
        )
        self.loading_label.pack(pady=48)

        # Load karty w background
        threading.Thread(target=self.load_cards_from_api, daemon=True).start()

    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_var.set(text))

    def _tree_configure_zebra_hover(self, tree: ttk.Treeview) -> None:
        tree.tag_configure("odd", background=self.C_SURFACE, foreground=self.C_TEXT)
        tree.tag_configure("even", background="#0c1628", foreground=self.C_TEXT)
        tree.tag_configure("hover", background="#1a2b46", foreground=self.C_TEXT)

        tree._hover_iid = None  # type: ignore[attr-defined]

        def restore_tags(iid: str) -> None:
            tags = [t for t in tree.item(iid, "tags") if t != "hover"]
            tree.item(iid, tags=tags)

        def on_motion(event: tk.Event) -> None:
            iid = tree.identify_row(event.y)
            if iid == getattr(tree, "_hover_iid", None):
                return
            old = getattr(tree, "_hover_iid", None)
            if old:
                restore_tags(old)
            tree._hover_iid = iid  # type: ignore[attr-defined]
            if iid:
                tags = list(tree.item(iid, "tags"))
                if "hover" not in tags:
                    tags.append("hover")
                tree.item(iid, tags=tags)

        def on_leave(_event: tk.Event) -> None:
            old = getattr(tree, "_hover_iid", None)
            if old:
                restore_tags(old)
            tree._hover_iid = None  # type: ignore[attr-defined]

        tree.bind("<Motion>", on_motion)
        tree.bind("<Leave>", on_leave)

    def _zebra_tag_for_index(self, idx: int) -> str:
        return "odd" if idx % 2 == 0 else "even"

    def _tier_color(self, tier: str) -> tuple[str, str]:
        t = str(tier).upper().strip()
        if t == "S":
            return ("#a855f7", "#0b1220")
        if t == "A":
            return ("#3b82f6", "#0b1220")
        if t == "B":
            return ("#22c55e", "#0b1220")
        return ("#64748b", "#0b1220")

    def _rarity_color(self, rarity: str) -> tuple[str, str]:
        r = str(rarity).upper().strip()
        if r in ("L", "LEADER", "LEADER CARD"):
            return ("#f59e0b", "#0b1220")
        if r in ("SR", "SUPER RARE"):
            return ("#a855f7", "#0b1220")
        if r in ("R", "RARE"):
            return ("#38bdf8", "#0b1220")
        if r in ("UC", "UNCOMMON"):
            return ("#94a3b8", "#0b1220")
        if r in ("C", "COMMON"):
            return ("#64748b", "#0b1220")
        if r in ("PR", "PROMO"):
            return ("#f472b6", "#0b1220")
        return ("#64748b", "#0b1220")

    def _badge(self, parent: tk.Widget, text: str, bg: str, fg: str) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            bg=bg,
            fg=fg,
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=3,
        )

    def _reapply_zebra_tags(self, tree: ttk.Treeview) -> None:
        for idx, k in enumerate(tree.get_children("")):
            tags = [t for t in tree.item(k, "tags") if t not in ("odd", "even", "hover")]
            tags.append(self._zebra_tag_for_index(idx))
            tree.item(k, tags=tags)

    def _refresh_preview_badges(self, card: dict[str, Any]) -> None:
        if not hasattr(self, "preview_badges"):
            return
        for w in self.preview_badges.winfo_children():
            w.destroy()
        r_bg, r_fg = self._rarity_color(str(card.get("rarity", "")))
        self._badge(self.preview_badges, str(card.get("rarity", "")), r_bg, r_fg).pack(side=tk.LEFT, padx=(0, 6))
        self._badge(self.preview_badges, str(card.get("color", "")), self.C_PANEL, self.C_TEXT).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self._badge(self.preview_badges, str(card.get("type", "")), "#1e293b", self.C_MUTED).pack(side=tk.LEFT)

    def _load_thumb_into_label(self, card_id: str, lbl: tk.Label) -> None:
        if card_id in self.thumb_images:
            photo = self.thumb_images[card_id]
            self.root.after(0, lambda p=photo: self._apply_thumb_label_safe(lbl, p))
            return
        self._thumb_queue.put((card_id, lbl))

    def _thumb_worker_loop(self) -> None:
        while True:
            card_id, lbl = self._thumb_queue.get()
            try:
                self._thumb_fetch_one(card_id, lbl)
            finally:
                self._thumb_queue.task_done()

    def _thumb_fetch_one(self, card_id: str, lbl: tk.Label) -> None:
        try:
            if card_id in self.thumb_images:
                self.root.after(0, lambda p=self.thumb_images[card_id]: self._apply_thumb_label_safe(lbl, p))
                return
            url = self.cards_database.get(card_id, {}).get("image", "")
            if not url:
                return
            response = self.session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            if response.status_code != 200 or not response.content:
                return
            img = Image.open(BytesIO(response.content))
            img.thumbnail((72, 100))
            photo = ImageTk.PhotoImage(img)
            self.thumb_images[card_id] = photo
            self.root.after(0, lambda p=photo: self._apply_thumb_label_safe(lbl, p))
        except Exception:
            pass

    def _apply_thumb_label(self, lbl: tk.Label, photo: ImageTk.PhotoImage) -> None:
        lbl.config(image=photo, text="", width=0, height=0)
        lbl.image = photo  # keep ref

    def _apply_thumb_label_safe(self, lbl: tk.Label, photo: ImageTk.PhotoImage) -> None:
        try:
            if lbl.winfo_exists():
                self._apply_thumb_label(lbl, photo)
        except tk.TclError:
            pass

    def _load_user_decks_from_disk(self) -> None:
        if not USER_DECKS_FILE.exists():
            self.user_decks_data = []
            return
        try:
            with open(USER_DECKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            decks = data.get("decks") if isinstance(data, dict) else None
            if not isinstance(decks, list):
                self.user_decks_data = []
                return
            out: list[dict[str, Any]] = []
            for d in decks:
                if not isinstance(d, dict):
                    continue
                did = str(d.get("id") or uuid.uuid4())
                name = str(d.get("name") or "Bez nazwy")
                cards_raw = d.get("cards")
                cards: list[str] = []
                if isinstance(cards_raw, list):
                    for c in cards_raw:
                        if isinstance(c, str) and c.strip():
                            cards.append(c.strip())
                out.append({"id": did, "name": name, "cards": cards})
            self.user_decks_data = out
        except (OSError, json.JSONDecodeError):
            self.user_decks_data = []

    def _save_user_decks_to_disk(self) -> None:
        try:
            payload = {"version": 1, "decks": self.user_decks_data}
            with open(USER_DECKS_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _collect_unique_field(self, field: str) -> list[str]:
        seen: set[str] = set()
        for c in self.cards_database.values():
            v = str(c.get(field, "")).strip()
            if not v or v.lower() == "unknown":
                continue
            seen.add(v)
        return sorted(seen, key=lambda s: s.lower())

    def _populate_filter_values(self) -> None:
        if not hasattr(self, "cb_color"):
            return
        colors = self._collect_unique_field("color")
        types = self._collect_unique_field("type")
        rarities = self._collect_unique_field("rarity")
        self.cb_color["values"] = (FILTER_ALL, *colors)
        self.cb_type["values"] = (FILTER_ALL, *types)
        self.cb_rarity["values"] = (FILTER_ALL, *rarities)
        if self.filter_color_var.get() not in self.cb_color["values"]:
            self.filter_color_var.set(FILTER_ALL)
        if self.filter_type_var.get() not in self.cb_type["values"]:
            self.filter_type_var.set(FILTER_ALL)
        if self.filter_rarity_var.get() not in self.cb_rarity["values"]:
            self.filter_rarity_var.set(FILTER_ALL)

    def _card_matches_filters(self, card_id: str, card_info: dict[str, Any]) -> bool:
        search = self.search_var.get().lower().strip()
        if search:
            name = str(card_info.get("name", "")).lower()
            if search not in card_id.lower() and search not in name:
                return False

        col = self.filter_color_var.get()
        if col and col != FILTER_ALL:
            if str(card_info.get("color", "")).strip().lower() != col.strip().lower():
                return False

        typ = self.filter_type_var.get()
        if typ and typ != FILTER_ALL:
            if str(card_info.get("type", "")).strip().lower() != typ.strip().lower():
                return False

        rar = self.filter_rarity_var.get()
        if rar and rar != FILTER_ALL:
            if str(card_info.get("rarity", "")).strip().upper() != rar.strip().upper():
                return False

        if self.filter_owned_only_var.get():
            if int(self.owned_cards.get(card_id, 0)) <= 0:
                return False

        return True

    def export_collection(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Eksport kolekcji",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Wszystkie pliki", "*.*")],
        )
        if not path:
            return
        owned = {k: int(v) for k, v in self.owned_cards.items() if int(v) > 0}
        payload = {
            "version": 1,
            "format": "op_tcg_collection",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "owned": owned,
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("Eksport kolekcji", f"Zapisano {len(owned)} kart (posiadanych).")
        except OSError as e:
            messagebox.showerror("Eksport", str(e))

    def _clear_filters(self) -> None:
        if not hasattr(self, "filter_color_var"):
            return
        self.filter_color_var.set(FILTER_ALL)
        self.filter_type_var.set(FILTER_ALL)
        self.filter_rarity_var.set(FILTER_ALL)
        self.filter_owned_only_var.set(False)
        self.update_cards_list()

    def import_collection(self) -> None:
        path = filedialog.askopenfilename(
            title="Import kolekcji",
            filetypes=[("JSON", "*.json"), ("Wszystkie pliki", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            messagebox.showerror("Import", str(e))
            return

        parsed: dict[str, int] = {}
        if isinstance(data, dict):
            if "owned" in data and isinstance(data["owned"], dict):
                raw = data["owned"]
            else:
                raw = data
            for k, v in raw.items():
                if not isinstance(k, str):
                    continue
                try:
                    n = int(v)
                except (TypeError, ValueError):
                    n = 1 if v else 0
                parsed[k] = 1 if n > 0 else 0

        if not parsed:
            messagebox.showwarning("Import kolekcji", "Nie znaleziono żadnych wpisów „owned” w pliku.")
            return

        choice = messagebox.askyesnocancel(
            "Import kolekcji",
            "Tak — scal z obecną kolekcją (max z każdej karty)\n"
            "Nie — zastąp kolekcję importem\n"
            "Anuluj — przerwij",
        )
        if choice is None:
            return
        if choice:
            for k, v in parsed.items():
                self.owned_cards[k] = max(int(self.owned_cards.get(k, 0)), int(v))
        else:
            self.owned_cards = parsed

        self.save_data()
        self.update_cards_list()
        self.refresh_panels()
        messagebox.showinfo("Import kolekcji", f"Załadowano {len(parsed)} wpisów.")

    def _show_loading_screen(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self.status_var.set("Ładowanie kart…")
        ctk.CTkLabel(
            self,
            textvariable=self.status_var,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=self.C_MUTED,
        ).pack(pady=48)

    def refresh_cards_from_sources(self) -> None:
        self.cards_database = {}
        self.card_images = {}
        self.thumb_images = {}
        self._set_status("⏳ Odświeżanie kart…")
        self._show_loading_screen()
        threading.Thread(target=self.load_cards_from_api, daemon=True).start()

    def _normalize_image_url(self, url: str) -> str:
        if not url:
            return ""
        url = str(url).strip()
        if url.startswith("//"):
            return "https:" + url
        return url

    def _extract_image_url(self, card: dict[str, Any]) -> str:
        # Try common shapes across different card APIs
        candidates: list[Any] = [
            card.get("image"),
            card.get("image_url"),
            card.get("img"),
            card.get("thumbnail"),
            card.get("art"),
            card.get("card_image"),  # optcgapi
        ]
        images = card.get("images")
        if isinstance(images, dict):
            candidates.extend([images.get("large"), images.get("small"), images.get("thumb"), images.get("image")])
        elif isinstance(images, list) and images:
            candidates.append(images[0])

        for c in candidates:
            if isinstance(c, str) and c.strip():
                return self._normalize_image_url(c)
        return ""

    def _coerce_int(self, v: Any, default: int = 0) -> int:
        try:
            if v is None:
                return default
            if isinstance(v, bool):
                return int(v)
            return int(v)
        except Exception:
            return default

    def _load_cache(self) -> Optional[list[dict[str, Any]]]:
        if not CACHE_FILE.exists():
            return None
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
            cards = parse_generic_cards(payload)
            return cards if cards else None
        except Exception:
            return None

    def _save_cache(self, raw_cards: list[dict[str, Any]]) -> None:
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(raw_cards, f)
        except Exception:
            # cache is best-effort
            pass

    def load_cards_from_api(self):
        # To są Twoje karty awaryjne, gdy API nie działa
        emergency_data = [
            {"id": "OP01-001", "label": "Zoro (Leader)", "power": 5000, "cost": 0, "color": "Red"},
            {"id": "OP01-016", "label": "Nami", "power": 2000, "cost": 1, "color": "Red"},
            {"id": "OP05-060", "label": "Luffy", "power": 6000, "cost": 4, "color": "Purple"},
            {"id": "OP08-001", "label": "Imu", "power": 5000, "cost": 0, "color": "Black"},
            {"id": "OP03-087", "label": "Ace", "power": 7000, "cost": 5, "color": "Red/Blue"}
        ]

        headers = {"User-Agent": "Mozilla/5.0"}
        self._set_status("🔄 Łączenie z API kart…")

        all_cards: list[dict[str, Any]] = []
        used_source: Optional[str] = None

        for source in CARD_SOURCES:
            try:
                response = self.session.get(source.url, headers=headers, timeout=10)
                if response.status_code != 200:
                    continue
                payload = response.json()
                parsed = source.parse(payload)
                if parsed:
                    all_cards = parsed
                    used_source = source.name
                    self._save_cache(all_cards)
                    break
            except Exception:
                continue

        if not all_cards:
            cached = self._load_cache()
            if cached:
                all_cards = cached
                used_source = "Cache (offline)"
            else:
                all_cards = emergency_data
                used_source = "Awaryjna baza"

        # Przetwarzanie danych (niezależnie czy z sieci, czy awaryjnych)
        for card in all_cards:
            card_id = (
                card.get("id")
                or card.get("card_number")
                or card.get("code")
                or card.get("cardId")
                or card.get("card_set_id")   # optcgapi
                or card.get("card_image_id") # optcgapi (single-card endpoints)
            )
            if not card_id:
                continue
            card_id = str(card_id).strip()
            if not card_id:
                continue

            self.cards_database[card_id] = {
                "name": str(card.get("label") or card.get("name") or card.get("card_name") or "Unknown"),
                "power": self._coerce_int(card.get("power", 0)),
                "cost": self._coerce_int(card.get("cost", 0)),
                "color": str(card.get("color") or card.get("colors") or card.get("card_color") or "Unknown"),
                "type": str(card.get("type") or card.get("card_type") or "Unknown"),
                "image": self._extract_image_url(card),
                "rarity": str(card.get("rarity") or card.get("rarity_code") or "C"),
            }

        self._set_status(f"✅ Załadowano {len(self.cards_database)} kart • źródło: {used_source}")
        self.root.after(0, self.create_ui)

    def create_ui(self):
        for child in self.winfo_children():
            child.destroy()

        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.pack(side=tk.TOP, fill=tk.X, padx=20, pady=(16, 8))

        title_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        title_box.pack(side=tk.LEFT, fill=tk.Y)
        ctk.CTkLabel(
            title_box,
            text="One Piece TCG",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=self.C_TEXT,
        ).pack(anchor=tk.W)
        ctk.CTkLabel(
            title_box,
            text="Deck Builder — kolekcja, własne decki, statystyki",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=self.C_MUTED,
        ).pack(anchor=tk.W, pady=(2, 0))

        status_pill = ctk.CTkFrame(top_bar, fg_color=self.C_PANEL, corner_radius=20, border_width=1, border_color=self.C_BORDER)
        status_pill.pack(side=tk.LEFT, padx=(20, 0))
        ctk.CTkLabel(
            status_pill,
            textvariable=self.status_var,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=self.C_MUTED,
            padx=14,
            pady=8,
        ).pack()

        btn_bar = ctk.CTkFrame(top_bar, fg_color="transparent")
        btn_bar.pack(side=tk.RIGHT)
        ctk.CTkButton(
            btn_bar,
            text="Import kolekcji",
            width=130,
            height=36,
            corner_radius=8,
            fg_color=self.C_PANEL,
            hover_color="#1a2b46",
            command=self.import_collection,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ctk.CTkButton(
            btn_bar,
            text="Eksport kolekcji",
            width=130,
            height=36,
            corner_radius=8,
            fg_color=self.C_PANEL,
            hover_color="#1a2b46",
            command=self.export_collection,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ctk.CTkButton(
            btn_bar,
            text="Odśwież karty",
            width=130,
            height=36,
            corner_radius=10,
            fg_color=self.C_ACCENT,
            hover_color="#86b6ff",
            text_color="#0b1220",
            font=ctk.CTkFont(weight="bold"),
            command=self.refresh_cards_from_sources,
        ).pack(side=tk.LEFT)

        app = ctk.CTkFrame(self, fg_color="transparent")
        app.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))

        nav = ctk.CTkTabview(app, fg_color=self.C_SURFACE, segmented_button_fg_color=self.C_PANEL,
                             segmented_button_selected_color=self.C_ACCENT,
                             segmented_button_selected_hover_color="#86b6ff",
                             segmented_button_unselected_color="#1a2332",
                             border_width=0, corner_radius=12)
        nav.pack(fill=tk.BOTH, expand=True)

        nav.add("Karty")
        nav.add("Moje decki")
        nav.add("Statystyki")
        nav.add("Info")
        cards_screen = nav.tab("Karty")
        my_decks_screen = nav.tab("Moje decki")
        stats_screen = nav.tab("Statystyki")
        about_screen = nav.tab("Info")

        # --- Screen: Karty (resizable panes) ---
        cards_panes = ttk.Panedwindow(cards_screen, orient=tk.HORIZONTAL)
        cards_panes.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        left = ttk.Frame(cards_panes)
        right = ttk.Frame(cards_panes, width=330)
        right.pack_propagate(False)
        cards_panes.add(left, weight=3)
        cards_panes.add(right, weight=2)

        ttk.Label(left, text="Twoje karty", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W)

        search_frame = ttk.Frame(left)
        search_frame.pack(fill=tk.X, pady=(8, 6))
        ttk.Label(search_frame, text="Szukaj", style="Muted.TLabel").pack(side=tk.LEFT, padx=(0, 8))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self.update_cards_list)
        ttk.Entry(search_frame, textvariable=self.search_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.filter_color_var = tk.StringVar(value=FILTER_ALL)
        self.filter_type_var = tk.StringVar(value=FILTER_ALL)
        self.filter_rarity_var = tk.StringVar(value=FILTER_ALL)
        self.filter_owned_only_var = tk.BooleanVar(value=False)

        filters = ttk.LabelFrame(left, text="Filtry", padding=(8, 6))
        filters.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(filters, text="Kolor", style="Muted.TLabel").grid(row=0, column=0, sticky=tk.W, padx=(0, 6), pady=2)
        self.cb_color = ttk.Combobox(filters, textvariable=self.filter_color_var, width=18, state="readonly")
        self.cb_color.grid(row=0, column=1, sticky=tk.W, padx=(0, 16), pady=2)
        self.cb_color.bind("<<ComboboxSelected>>", lambda _e: self.update_cards_list())

        ttk.Label(filters, text="Typ", style="Muted.TLabel").grid(row=0, column=2, sticky=tk.W, padx=(0, 6), pady=2)
        self.cb_type = ttk.Combobox(filters, textvariable=self.filter_type_var, width=16, state="readonly")
        self.cb_type.grid(row=0, column=3, sticky=tk.W, pady=2)
        self.cb_type.bind("<<ComboboxSelected>>", lambda _e: self.update_cards_list())

        ttk.Label(filters, text="Rzadkość", style="Muted.TLabel").grid(row=1, column=0, sticky=tk.W, padx=(0, 6), pady=2)
        self.cb_rarity = ttk.Combobox(filters, textvariable=self.filter_rarity_var, width=18, state="readonly")
        self.cb_rarity.grid(row=1, column=1, sticky=tk.W, padx=(0, 16), pady=2)
        self.cb_rarity.bind("<<ComboboxSelected>>", lambda _e: self.update_cards_list())

        ttk.Checkbutton(
            filters,
            text="Tylko posiadane",
            variable=self.filter_owned_only_var,
            command=self.update_cards_list,
        ).grid(row=1, column=2, sticky=tk.W, pady=2)

        ttk.Button(filters, text="Wyczyść filtry", command=self._clear_filters).grid(
            row=1, column=3, sticky=tk.E, pady=2
        )

        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.cards_tree = ttk.Treeview(tree_frame, columns=('name', 'power', 'own'), height=22,
                                       yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.cards_tree.yview)

        self.cards_tree.heading('#0', text='ID', command=lambda: self.sort_tree(self.cards_tree, '#0', False))
        self.cards_tree.heading('name', text='Nazwa', command=lambda: self.sort_tree(self.cards_tree, 'name', False))
        self.cards_tree.heading('power', text='PWR', command=lambda: self.sort_tree(self.cards_tree, 'power', True))
        self.cards_tree.heading('own', text='✓', command=lambda: self.sort_tree(self.cards_tree, 'own', False))

        self.cards_tree.column('#0', width=90)
        self.cards_tree.column('name', width=260)
        self.cards_tree.column('power', width=60, anchor=tk.CENTER)
        self.cards_tree.column('own', width=40, anchor=tk.CENTER)

        self.cards_tree.pack(fill=tk.BOTH, expand=True)
        self._tree_configure_zebra_hover(self.cards_tree)
        self.cards_tree.bind('<Button-1>', self.on_tree_click)
        self.cards_tree.bind('<ButtonRelease-1>', self.show_card_image)
        self.cards_tree.bind('<Double-1>', self.open_card_window)

        self.count_label = ttk.Label(left, text="", style="Muted.TLabel")
        self.count_label.pack(anchor=tk.W, pady=(6, 0))

        # Right details panel
        ttk.Label(right, text="Podgląd karty", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W)

        preview_frame = tk.Frame(
            right,
            bg=self.C_SURFACE,
            highlightbackground=self.C_BORDER,
            highlightthickness=1,
        )
        preview_frame.pack(fill=tk.X, pady=(10, 10))

        self.image_label = tk.Label(
            preview_frame,
            text="Kliknij kartę po lewej,\naby zobaczyć podgląd",
            bg=self.C_SURFACE,
            fg=self.C_MUTED,
            font=("Segoe UI", 10),
            padx=10,
            pady=10,
        )
        self.image_label.pack()

        self.card_details_var = tk.StringVar(value="")
        self.card_details = ttk.Label(
            right,
            textvariable=self.card_details_var,
            style="Muted.TLabel",
            font=("Segoe UI", 9),
            justify=tk.LEFT,
            wraplength=320,
        )
        self.card_details.pack(anchor=tk.W, pady=(0, 6))

        self.preview_badges = tk.Frame(right, bg=self.C_BG)
        self.preview_badges.pack(anchor=tk.W, pady=(0, 8))

        ttk.Label(right, text="Tip: kliknij wiersz aby zaznaczyć posiadanie • dwuklik = szczegóły",
                  style="Muted.TLabel").pack(anchor=tk.W)

        # Populate now that widgets exist
        self._populate_filter_values()
        self.update_cards_list()

        # --- Screen: Moje decki ---
        self._build_my_decks_tab(my_decks_screen)

        # --- Screen: Statystyki ---
        self._build_stats_tab(stats_screen)

        # --- Screen: Info ---
        ttk.Label(about_screen, text="O aplikacji", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(10, 6))
        ttk.Label(
            about_screen,
            text="To prosty deck builder dla One Piece TCG.\n\n"
                 "• Karty z API (OPTCGAPI); filtry i kolekcja (✓).\n"
                 "• Moje decki: własne listy, kopiowanie ID, eksport JSON.\n"
                 "• Statystyki: podsumowanie posiadanych kart (rzadkość, kolor).\n"
                 "• Eksport/import kolekcji (JSON) — backup.\n"
                 "• Zakładka Karty: podgląd, dwuklik = szczegóły; klik = posiadanie.\n"
                 "• Brak „oficjalnego meta” w aplikacji — źródła turniejowe są poza programem.\n",
            style="Muted.TLabel",
            justify=tk.LEFT,
        ).pack(anchor=tk.W)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=(0, 14))
        ctk.CTkLabel(
            bottom,
            text="Lokalna aplikacja • dane w plikach JSON obok programu",
            font=ctk.CTkFont(size=11),
            text_color=self.C_MUTED,
        ).pack(side=tk.LEFT)

    def _build_stats_tab(self, parent: Any) -> None:
        wrap = ttk.Frame(parent)
        wrap.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(wrap, text="Statystyki kolekcji", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W)
        ttk.Label(
            wrap,
            text="Liczone są tylko karty oznaczone jako posiadane (✓) i obecne w aktualnej bazie z API.",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(4, 8))

        self.stats_text = tk.Text(
            wrap,
            height=26,
            width=96,
            bg=self.C_SURFACE,
            fg=self.C_TEXT,
            insertbackground=self.C_TEXT,
            highlightthickness=1,
            highlightbackground=self.C_BORDER,
            font=("Consolas", 10),
            relief=tk.FLAT,
        )
        self.stats_text.pack(fill=tk.BOTH, expand=True)

        ttk.Button(wrap, text="Przelicz", command=self.refresh_collection_stats).pack(anchor=tk.W, pady=(8, 0))
        self.refresh_collection_stats()

    def refresh_collection_stats(self) -> None:
        if not hasattr(self, "stats_text"):
            return
        owned_in_db: list[str] = []
        for cid, v in self.owned_cards.items():
            if int(v) <= 0:
                continue
            if cid in self.cards_database:
                owned_in_db.append(cid)

        by_rarity: dict[str, int] = {}
        by_color: dict[str, int] = {}
        for cid in owned_in_db:
            c = self.cards_database[cid]
            r = str(c.get("rarity", "?")).strip() or "?"
            col = str(c.get("color", "?")).strip() or "?"
            by_rarity[r] = by_rarity.get(r, 0) + 1
            by_color[col] = by_color.get(col, 0) + 1

        total_db = len(self.cards_database)
        lines: list[str] = [
            f"Posiadane (w bazie): {len(owned_in_db)} unikalnych kart",
            f"Wpisów w kolekcji (łącznie kluczy): {len(self.owned_cards)}",
            f"Kart w aktualnej bazie API: {total_db}",
            "",
            "— Rzadkość (posiadane) —",
        ]
        for k in sorted(by_rarity.keys(), key=lambda x: x.lower()):
            lines.append(f"  {k}: {by_rarity[k]}")
        lines.append("")
        lines.append("— Kolor (posiadane) —")
        for k in sorted(by_color.keys(), key=lambda x: x.lower()):
            lines.append(f"  {k}: {by_color[k]}")
        lines.append("")
        lines.append("— Meta —")
        lines.append("  Aplikacja nie podaje „top decków” z turniejów — zbuduj listę w „Moje decki”.")

        self.stats_text.delete("1.0", tk.END)
        self.stats_text.insert("1.0", "\n".join(lines))

    def _build_my_decks_tab(self, parent: Any) -> None:
        wrap = ttk.Frame(parent)
        wrap.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(wrap, text="Własne decki", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W)
        ttk.Label(
            wrap,
            text="Zapis: plik op_tcg_user_decks.json • Dodawaj karty z zakładki „Karty” (zaznacz wiersz) lub wklej listę ID.",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(2, 8))

        body = ttk.Panedwindow(wrap, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.LabelFrame(body, text="Lista decków", padding=8)
        right = ttk.LabelFrame(body, text="Edycja", padding=8)
        body.add(left, weight=1)
        body.add(right, weight=3)

        self.user_deck_listbox = tk.Listbox(
            left,
            height=22,
            bg=self.C_SURFACE,
            fg=self.C_TEXT,
            selectbackground=self.C_PANEL,
            selectforeground=self.C_TEXT,
            highlightthickness=1,
            highlightbackground=self.C_BORDER,
            font=("Segoe UI", 10),
        )
        self.user_deck_listbox.pack(fill=tk.BOTH, expand=True)
        self.user_deck_listbox.bind("<<ListboxSelect>>", lambda _e: self._user_deck_load_tree())

        btns = ttk.Frame(left)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btns, text="Nowy", command=self._user_deck_new).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="Zmień nazwę", command=self._user_deck_rename).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="Duplikuj", command=self._user_deck_duplicate).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="Usuń", command=self._user_deck_delete).pack(side=tk.LEFT)

        top_r = ttk.Frame(right)
        top_r.pack(fill=tk.X)
        self.user_deck_title_var = tk.StringVar(value="")
        ttk.Label(top_r, textvariable=self.user_deck_title_var, font=("Segoe UI", 11, "bold")).pack(anchor=tk.W)

        row_add = ttk.Frame(right)
        row_add.pack(fill=tk.X, pady=(8, 6))
        ttk.Button(row_add, text="Dodaj zaznaczoną kartę (z „Karty”)", command=self._user_deck_add_from_cards).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(row_add, text="Usuń zaznaczoną z decku", command=self._user_deck_remove_selected).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(row_add, text="Kopiuj listę ID", command=self._user_deck_copy_ids).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(row_add, text="Eksport decku (JSON)", command=self._user_deck_export_file).pack(side=tk.LEFT)

        paste_fr = ttk.LabelFrame(right, text="Wklej ID (jedna linia = jedna karta)", padding=6)
        paste_fr.pack(fill=tk.X, pady=(0, 8))
        self.user_deck_paste = tk.Text(paste_fr, height=4, bg=self.C_SURFACE, fg=self.C_TEXT, font=("Consolas", 9))
        self.user_deck_paste.pack(fill=tk.X)
        ttk.Button(paste_fr, text="Dodaj z tekstu", command=self._user_deck_add_from_paste).pack(anchor=tk.E, pady=(6, 0))

        tree_fr = ttk.Frame(right)
        tree_fr.pack(fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(tree_fr)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.user_deck_cards_tree = ttk.Treeview(
            tree_fr,
            columns=("name", "have"),
            height=16,
            yscrollcommand=sb.set,
        )
        sb.config(command=self.user_deck_cards_tree.yview)
        self.user_deck_cards_tree.heading("#0", text="ID")
        self.user_deck_cards_tree.heading("name", text="Nazwa")
        self.user_deck_cards_tree.heading("have", text="Mam")
        self.user_deck_cards_tree.column("#0", width=100)
        self.user_deck_cards_tree.column("name", width=260)
        self.user_deck_cards_tree.column("have", width=50, anchor=tk.CENTER)
        self.user_deck_cards_tree.pack(fill=tk.BOTH, expand=True)
        self._tree_configure_zebra_hover(self.user_deck_cards_tree)

        def on_ud_release(event: Any) -> None:
            row = self.user_deck_cards_tree.identify_row(event.y)
            if not row:
                return
            cid = self.user_deck_cards_tree.item(row, "text")
            if cid in self.cards_database:
                self.open_card_window(card_id=cid)

        self.user_deck_cards_tree.bind("<ButtonRelease-1>", on_ud_release)

        self.user_deck_size_label = ttk.Label(right, text="", style="Muted.TLabel")
        self.user_deck_size_label.pack(anchor=tk.W, pady=(6, 0))

        self.user_deck_thumb_outer = ttk.LabelFrame(right, text="Miniatury (kolejka pobierań)", padding=6)
        self.user_deck_thumb_outer.pack(fill=tk.X, pady=(8, 0))
        self.user_deck_thumb_canvas = tk.Canvas(
            self.user_deck_thumb_outer,
            height=108,
            bg=self.C_SURFACE,
            highlightthickness=1,
            highlightbackground=self.C_BORDER,
        )
        self.user_deck_thumb_scroll = ttk.Scrollbar(
            self.user_deck_thumb_outer, orient=tk.HORIZONTAL, command=self.user_deck_thumb_canvas.xview
        )
        self.user_deck_thumb_canvas.configure(xscrollcommand=self.user_deck_thumb_scroll.set)
        self.user_deck_thumb_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.user_deck_thumb_canvas.pack(side=tk.TOP, fill=tk.X, expand=True)
        self.user_deck_thumb_inner = tk.Frame(self.user_deck_thumb_canvas, bg=self.C_SURFACE)
        self._ud_thumb_window = self.user_deck_thumb_canvas.create_window((0, 0), window=self.user_deck_thumb_inner, anchor=tk.NW)

        def _ud_thumb_cfg(_event=None):
            self.user_deck_thumb_canvas.configure(scrollregion=self.user_deck_thumb_canvas.bbox("all"))
            self.user_deck_thumb_canvas.itemconfig(
                self._ud_thumb_window,
                width=max(self.user_deck_thumb_inner.winfo_reqwidth(), self.user_deck_thumb_canvas.winfo_width()),
            )

        self.user_deck_thumb_inner.bind("<Configure>", _ud_thumb_cfg)
        self.user_deck_thumb_canvas.bind("<Configure>", _ud_thumb_cfg)

        self.refresh_user_deck_listbox(select_index=0)

    def _user_deck_selected_index(self) -> Optional[int]:
        if not hasattr(self, "user_deck_listbox"):
            return None
        sel = self.user_deck_listbox.curselection()
        if not sel:
            return None
        return int(sel[0])

    def refresh_user_deck_listbox(self, select_index: Optional[int] = None) -> None:
        if not hasattr(self, "user_deck_listbox"):
            return
        self.user_deck_listbox.delete(0, tk.END)
        for d in self.user_decks_data:
            self.user_deck_listbox.insert(tk.END, d.get("name", "Bez nazwy"))
        if self.user_decks_data:
            idx = 0 if select_index is None else max(0, min(select_index, len(self.user_decks_data) - 1))
            self.user_deck_listbox.selection_clear(0, tk.END)
            self.user_deck_listbox.selection_set(idx)
            self.user_deck_listbox.activate(idx)
        self._user_deck_load_tree()

    def _user_deck_load_tree(self) -> None:
        if not hasattr(self, "user_deck_cards_tree"):
            return
        for i in self.user_deck_cards_tree.get_children():
            self.user_deck_cards_tree.delete(i)
        idx = self._user_deck_selected_index()
        if idx is None or not self.user_decks_data:
            self.user_deck_title_var.set("Wybierz lub utwórz deck")
            self.user_deck_size_label.config(text="")
            if hasattr(self, "user_deck_thumb_inner"):
                for w in self.user_deck_thumb_inner.winfo_children():
                    w.destroy()
            return
        deck = self.user_decks_data[idx]
        self.user_deck_title_var.set(f"{deck.get('name', '')}  •  {len(deck.get('cards', []))} kart")
        cards: list[str] = list(deck.get("cards", []))
        for i, cid in enumerate(cards):
            tag = self._zebra_tag_for_index(i)
            if cid in self.cards_database:
                c = self.cards_database[cid]
                have = "✓" if int(self.owned_cards.get(cid, 0)) > 0 else "✗"
                self.user_deck_cards_tree.insert("", tk.END, text=cid, values=(c.get("name", "")[:40], have), tags=(tag,))
            else:
                self.user_deck_cards_tree.insert(
                    "", tk.END, text=cid, values=("Brak w bazie — sprawdź ID", "?"), tags=(tag,)
                )
        warn = ""
        n = len(cards)
        if n > 60:
            warn = " (uwaga: > 60 — typowy limit gry to 50 + 10 DON)"
        self.user_deck_size_label.config(text=f"Kart w liście: {n}{warn}")

        if hasattr(self, "user_deck_thumb_inner"):
            for w in self.user_deck_thumb_inner.winfo_children():
                w.destroy()
            for cid in cards[:40]:
                cell = tk.Frame(self.user_deck_thumb_inner, bg=self.C_SURFACE, padx=3, pady=3)
                cell.pack(side=tk.LEFT)
                lbl = tk.Label(
                    cell,
                    text=cid,
                    bg=self.C_PANEL,
                    fg=self.C_MUTED,
                    font=("Segoe UI", 7),
                    width=9,
                    height=4,
                    wraplength=64,
                )
                lbl.pack()
                if cid in self.cards_database and self.cards_database[cid].get("image"):
                    self._load_thumb_into_label(cid, lbl)

    def _user_deck_new(self) -> None:
        name = simpledialog.askstring("Nowy deck", "Nazwa decku:", parent=self.root)
        if not name:
            return
        self.user_decks_data.append({"id": str(uuid.uuid4()), "name": name.strip(), "cards": []})
        self._save_user_decks_to_disk()
        self.refresh_user_deck_listbox(select_index=len(self.user_decks_data) - 1)

    def _user_deck_rename(self) -> None:
        idx = self._user_deck_selected_index()
        if idx is None:
            return
        cur = str(self.user_decks_data[idx].get("name", ""))
        name = simpledialog.askstring("Zmień nazwę", "Nowa nazwa:", initialvalue=cur, parent=self.root)
        if not name:
            return
        self.user_decks_data[idx]["name"] = name.strip()
        self._save_user_decks_to_disk()
        self.refresh_user_deck_listbox(select_index=idx)

    def _user_deck_duplicate(self) -> None:
        idx = self._user_deck_selected_index()
        if idx is None:
            return
        src = self.user_decks_data[idx]
        copy = {
            "id": str(uuid.uuid4()),
            "name": f"{src.get('name', 'Deck')} (kopia)",
            "cards": list(src.get("cards", [])),
        }
        self.user_decks_data.append(copy)
        self._save_user_decks_to_disk()
        self.refresh_user_deck_listbox(select_index=len(self.user_decks_data) - 1)

    def _user_deck_delete(self) -> None:
        idx = self._user_deck_selected_index()
        if idx is None:
            return
        if not messagebox.askyesno("Usuń deck", "Na pewno usunąć ten deck?"):
            return
        self.user_decks_data.pop(idx)
        self._save_user_decks_to_disk()
        self.refresh_user_deck_listbox(select_index=max(0, idx - 1))

    def _user_deck_current(self) -> Optional[dict[str, Any]]:
        idx = self._user_deck_selected_index()
        if idx is None:
            return None
        return self.user_decks_data[idx]

    def _user_deck_add_from_cards(self) -> None:
        deck = self._user_deck_current()
        if not deck:
            messagebox.showinfo("Deck", "Najpierw wybierz deck po lewej (lub utwórz „Nowy”).")
            return
        sel = self.cards_tree.selection()
        if not sel:
            messagebox.showinfo("Deck", "Zaznacz kartę w zakładce „Karty”, potem kliknij tutaj.")
            return
        cid = self.cards_tree.item(sel[0], "text")
        cards: list[str] = list(deck.get("cards", []))
        if cid in cards:
            messagebox.showinfo("Deck", "Ta karta jest już na liście.")
            return
        cards.append(cid)
        deck["cards"] = cards
        self._save_user_decks_to_disk()
        self._user_deck_load_tree()

    def _user_deck_remove_selected(self) -> None:
        deck = self._user_deck_current()
        if not deck:
            return
        sel = self.user_deck_cards_tree.selection()
        if not sel:
            return
        cid = self.user_deck_cards_tree.item(sel[0], "text")
        cards = [c for c in deck.get("cards", []) if c != cid]
        deck["cards"] = cards
        self._save_user_decks_to_disk()
        self._user_deck_load_tree()

    def _user_deck_add_from_paste(self) -> None:
        deck = self._user_deck_current()
        if not deck:
            messagebox.showinfo("Deck", "Wybierz deck po lewej.")
            return
        raw = self.user_deck_paste.get("1.0", tk.END)
        added = 0
        cards: list[str] = list(deck.get("cards", []))
        for m in CARD_ID_RE.findall(raw):
            if m not in cards:
                cards.append(m)
                added += 1
        deck["cards"] = cards
        self._save_user_decks_to_disk()
        self.user_deck_paste.delete("1.0", tk.END)
        self._user_deck_load_tree()
        messagebox.showinfo("Deck", f"Dodano {added} nowych ID (pominięto duplikaty).")

    def _user_deck_copy_ids(self) -> None:
        deck = self._user_deck_current()
        if not deck:
            return
        text = "\n".join(deck.get("cards", []))
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()
        messagebox.showinfo("Schowek", "Skopiowano listę ID (jedna karta na linię).")

    def _user_deck_export_file(self) -> None:
        deck = self._user_deck_current()
        if not deck:
            return
        path = filedialog.asksaveasfilename(
            title="Eksport decku",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        payload = {
            "version": 1,
            "format": "op_tcg_user_deck",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "name": deck.get("name", ""),
            "cards": list(deck.get("cards", [])),
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("Eksport", "Zapisano deck.")
        except OSError as e:
            messagebox.showerror("Eksport", str(e))

    def open_card_window(self, event=None, card_id: Optional[str] = None) -> None:
        if card_id is None:
            selection = self.cards_tree.selection()
            if not selection:
                return
            card_id = self.cards_tree.item(selection[0], 'text')
        if card_id not in self.cards_database:
            return

        card = self.cards_database[card_id]
        win = tk.Toplevel(self.root)
        win.title(f"{card_id} • {card.get('name','')}")
        win.configure(bg=self.C_BG)
        win.geometry("520x760")

        header = tk.Frame(win, bg=self.C_BG)
        header.pack(fill=tk.X, padx=16, pady=(16, 10))
        tk.Label(header, text=card.get("name", ""), bg=self.C_BG, fg=self.C_TEXT,
                 font=("Segoe UI", 14, "bold")).pack(anchor=tk.W)
        badge_row = tk.Frame(header, bg=self.C_BG)
        badge_row.pack(anchor=tk.W, pady=(6, 0))
        tk.Label(badge_row, text=card_id, bg=self.C_BG, fg=self.C_MUTED, font=("Segoe UI", 10, "bold")).pack(
            side=tk.LEFT
        )
        r_bg, r_fg = self._rarity_color(str(card.get("rarity", "")))
        self._badge(badge_row, str(card.get("rarity", "")), r_bg, r_fg).pack(side=tk.LEFT, padx=(8, 0))
        self._badge(badge_row, str(card.get("color", "")), self.C_PANEL, self.C_TEXT).pack(side=tk.LEFT, padx=(6, 0))
        self._badge(badge_row, str(card.get("type", "")), "#1e293b", self.C_MUTED).pack(side=tk.LEFT, padx=(6, 0))

        preview = tk.Frame(win, bg=self.C_SURFACE, highlightbackground=self.C_BORDER, highlightthickness=1)
        preview.pack(padx=16, pady=(0, 10))
        img_label = tk.Label(preview, bg=self.C_SURFACE, fg=self.C_MUTED, padx=10, pady=10)
        img_label.pack()

        # reuse cached image if possible, but upscale a bit
        def render():
            if card_id in self.card_images:
                img_label.config(image=self.card_images[card_id])
                img_label.image = self.card_images[card_id]
            else:
                img_label.config(text="Ładowanie obrazka…")

        render()

        if card.get("image"):
            threading.Thread(target=self._load_image_for_window, args=(card_id, card["image"], img_label), daemon=True).start()
        else:
            img_label.config(text="Brak obrazka dla tej karty.")

        body = tk.Frame(win, bg=self.C_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))
        tk.Label(body, text=f"Cost: {card.get('cost',0)}    Power: {card.get('power',0)}",
                 bg=self.C_BG, fg=self.C_TEXT, font=("Segoe UI", 11)).pack(anchor=tk.W)
        owned = "Tak" if self.owned_cards.get(card_id, 0) > 0 else "Nie"
        tk.Label(body, text=f"Posiadam: {owned}", bg=self.C_BG, fg=self.C_MUTED, font=("Segoe UI", 10)).pack(
            anchor=tk.W, pady=(6, 0)
        )

    def _load_image_for_window(self, card_id: str, image_url: str, label: tk.Label) -> None:
        try:
            if card_id not in self.card_images:
                response = self.session.get(image_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
                if response.status_code != 200 or not response.content:
                    raise Exception(f"HTTP {response.status_code}")
                img = Image.open(BytesIO(response.content))
                img.thumbnail((360, 500))
                self.card_images[card_id] = ImageTk.PhotoImage(img)
            self.root.after(0, lambda: (label.config(image=self.card_images[card_id], text=""),
                                        setattr(label, "image", self.card_images[card_id])))
        except Exception:
            self.root.after(0, lambda: label.config(text="Nie udało się pobrać obrazka."))

    def sort_tree(self, tree: ttk.Treeview, col: str, numeric: bool) -> None:
        items = [(tree.set(k, col) if col != "#0" else tree.item(k, "text"), k) for k in tree.get_children("")]

        def to_key(v: str):
            if numeric:
                try:
                    return float(str(v).replace("%", "").strip() or 0)
                except Exception:
                    return 0.0
            return str(v).lower()

        items.sort(key=lambda t: to_key(t[0]))
        for idx, (_val, k) in enumerate(items):
            tree.move(k, "", idx)
        self._reapply_zebra_tags(tree)

    def update_cards_list(self, *args):
        for item in self.cards_tree.get_children():
            self.cards_tree.delete(item)

        count = 0

        rows: list[tuple[str, dict[str, Any]]] = []
        for card_id, card_info in self.cards_database.items():
            if self._card_matches_filters(card_id, card_info):
                rows.append((card_id, card_info))

        for idx, (card_id, card_info) in enumerate(rows):
            have = "✓" if self.owned_cards.get(card_id, 0) > 0 else ""
            self.cards_tree.insert(
                '',
                tk.END,
                text=card_id,
                values=(card_info['name'][:20], card_info['power'], have),
                tags=(self._zebra_tag_for_index(idx),),
            )
            count += 1

        owned = sum(self.owned_cards.values())
        self.count_label.config(text=f"Posiadane: {owned} | Znalezione: {count}")

    def show_card_image(self, event):
        selection = self.cards_tree.selection()
        if not selection:
            return

        card_id = self.cards_tree.item(selection[0], 'text')
        if card_id not in self.cards_database:
            return

        card = self.cards_database[card_id]
        self.card_details_var.set(
            f"{card.get('name','')}\n"
            f"{card_id} • {card.get('rarity','')} • {card.get('color','')} • {card.get('type','')}\n"
            f"Cost: {card.get('cost',0)}    Power: {card.get('power',0)}"
        )
        self._refresh_preview_badges(card)

        image_url = card.get("image", "")
        if image_url:
            threading.Thread(target=self.load_and_display_image, args=(card_id, image_url), daemon=True).start()
        else:
            threading.Thread(target=self.load_and_display_placeholder, args=(card_id,), daemon=True).start()

    def load_and_display_image(self, card_id, image_url):
        try:
            if card_id not in self.card_images:
                response = self.session.get(image_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                if response.status_code != 200 or not response.content:
                    raise Exception(f"HTTP {response.status_code}")
                img = Image.open(BytesIO(response.content))
                img.thumbnail((240, 330))
                self.card_images[card_id] = ImageTk.PhotoImage(img)

            self.root.after(0, lambda: self.image_label.config(image=self.card_images[card_id], text=""))
        except Exception as e:
            print(f"Błąd zdjęcia: {e}")
            self.load_and_display_placeholder(card_id)

    def load_and_display_placeholder(self, card_id: str) -> None:
        # Always show something clearly (image area + readable text)
        if card_id in self.card_images:
            self.root.after(0, lambda: self.image_label.config(image=self.card_images[card_id], compound="center"))
            return

        card = self.cards_database.get(card_id, {})
        title = str(card.get("name") or "").strip()[:28]
        subtitle = f"{card_id}"

        img = Image.new("RGB", (240, 330), color=(42, 42, 42))
        try:
            from PIL import ImageDraw, ImageFont

            draw = ImageDraw.Draw(img)
            # Simple centered text; default font works cross-platform
            text = f"{subtitle}\n{title}\n\n(brak obrazka)"
            draw.multiline_text((12, 120), text, fill=(190, 190, 190), spacing=6, align="left")
            draw.rectangle([0, 0, 239, 329], outline=(70, 70, 70), width=2)
        except Exception:
            pass

        self.card_images[card_id] = ImageTk.PhotoImage(img)
        self.root.after(
            0,
            lambda: self.image_label.config(
                image=self.card_images[card_id],
                text="",
                compound="center",
            ),
        )

    def on_tree_click(self, event):
        selection = self.cards_tree.selection()
        if not selection:
            return

        item = selection[0]
        card_id = self.cards_tree.item(item, 'text')

        if self.owned_cards.get(card_id, 0) > 0:
            self.owned_cards[card_id] = 0
        else:
            self.owned_cards[card_id] = 1

        self.save_data()
        self.update_cards_list()
        self.refresh_panels()

    def refresh_panels(self) -> None:
        if hasattr(self, "user_deck_listbox"):
            idx = self._user_deck_selected_index()
            self.refresh_user_deck_listbox(select_index=idx if idx is not None else 0)
        self.refresh_collection_stats()

    def load_data(self) -> None:
        if OWNED_FILE.exists():
            with open(OWNED_FILE, "r", encoding="utf-8") as f:
                self.owned_cards = json.load(f)

    def save_data(self) -> None:
        with open(OWNED_FILE, "w", encoding="utf-8") as f:
            json.dump(self.owned_cards, f)