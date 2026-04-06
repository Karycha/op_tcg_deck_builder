import tkinter as tk
from tkinter import ttk, messagebox
import json
from pathlib import Path
import requests
from PIL import Image, ImageTk
from io import BytesIO
import threading

# API Config
OPTCG_API_BASE = "https://api.egmanevents.com/api/cards"

META_DECKS = {
    "Black Imu": {
        "name": "Black Imu",
        "description": "Dominujący S-Tier (41% meta)",
        "winrate": "41%",
        "cards": ["OP08-001", "OP08-002", "OP08-003", "OP08-004", "OP08-005",
                  "OP08-006", "OP08-010", "OP08-011", "OP08-020", "OP08-025"],
        "tier": "S"
    },
    "Red Blue Ace": {
        "name": "Red/Blue Ace",
        "description": "Aggressive S-Tier (37% meta)",
        "winrate": "37%",
        "cards": ["OP03-087", "OP04-030", "OP04-031", "OP05-014", "OP05-015",
                  "OP06-034", "OP07-020", "OP07-021", "OP07-028", "OP07-029"],
        "tier": "S"
    },
    "Green Zoro": {
        "name": "Green Zoro",
        "description": "Control S-Tier (16% meta)",
        "winrate": "16%",
        "cards": ["OP01-012", "OP02-006", "OP03-008", "OP04-009", "OP05-010",
                  "OP06-011", "OP07-012", "OP01-043", "OP02-044", "OP03-045"],
        "tier": "S"
    },
    "Purple Enel": {
        "name": "Purple Enel (JPN)",
        "description": "Japan Meta (65% WR)",
        "winrate": "65%",
        "cards": ["OP10-001", "OP10-002", "OP10-003", "OP10-010", "OP10-011",
                  "OP10-020", "OP10-021", "OP10-030", "OP10-031", "OP10-040"],
        "tier": "S"
    },
    "Luffy OP-12": {
        "name": "Luffy (OP-12)",
        "description": "Popular Red deck",
        "winrate": "35%",
        "cards": ["OP12-001", "OP12-002", "OP12-005", "OP12-010", "OP12-015",
                  "OP12-020", "OP12-025", "OP12-030", "OP12-031", "OP12-040"],
        "tier": "A"
    },
    "Green Bonney": {
        "name": "Green Bonney",
        "description": "Control counter",
        "winrate": "32%",
        "cards": ["OP11-001", "OP11-002", "OP11-010", "OP11-015", "OP11-020",
                  "OP11-025", "OP11-030", "OP11-035", "OP11-040", "OP11-045"],
        "tier": "A"
    }
}


class OPTCGApp:
    def __init__(self, root):
        self.root = root
        self.root.title("One Piece TCG - Deck Builder")
        self.root.geometry("1500x850")
        self.root.configure(bg="#1a1a1a")

        # Data
        self.cards_database = {}
        self.owned_cards = {}
        self.card_images = {}
        self.load_data()

        # Style
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#1a1a1a')
        style.configure('TLabel', background='#1a1a1a', foreground='#ffffff')
        style.configure('TButton', background='#2a2a2a', foreground='#ffffff')
        style.configure('Treeview', background='#2a2a2a', foreground='#ffffff', fieldbackground='#2a2a2a')
        style.configure('Treeview.Heading', background='#3a3a3a', foreground='#ffffff')

        # Loading label
        self.loading_label = ttk.Label(self.root, text="⏳ Ładowanie kart z OPTCG API...", font=("Arial", 16, "bold"))
        self.loading_label.pack(pady=20)

        # Load karty w background
        threading.Thread(target=self.load_cards_from_api, daemon=True).start()

    def load_cards_from_api(self):
        # To są Twoje karty awaryjne, gdy API nie działa
        emergency_data = [
            {"id": "OP01-001", "label": "Zoro (Leader)", "power": 5000, "cost": 0, "color": "Red"},
            {"id": "OP01-016", "label": "Nami", "power": 2000, "cost": 1, "color": "Red"},
            {"id": "OP05-060", "label": "Luffy", "power": 6000, "cost": 4, "color": "Purple"},
            {"id": "OP08-001", "label": "Imu", "power": 5000, "cost": 0, "color": "Black"},
            {"id": "OP03-087", "label": "Ace", "power": 7000, "cost": 5, "color": "Red/Blue"}
        ]

        try:
            print("🔄 Próba połączenia z API...")
            url = "https://nav-api.nakamadecks.com/cards"
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, headers=headers, timeout=5)

            if response.status_code == 200:
                all_cards = response.json()
                print("✅ Sukces! Dane pobrane z sieci.")
            else:
                raise Exception("API Offline")

        except Exception as e:
            print(f"❌ API nie odpowiedziało ({e}). Ładuję bazę awaryjną...")
            # Używamy danych awaryjnych, żeby program się nie wywalił
            all_cards = emergency_data

        # Przetwarzanie danych (niezależnie czy z sieci, czy awaryjnych)
        count = 0
        for card in all_cards:
            card_id = card.get('id') or card.get('card_number')
            if not card_id: continue

            self.cards_database[card_id] = {
                'name': card.get('label', card.get('name', 'Unknown')),
                'power': card.get('power', 0),
                'cost': card.get('cost', 0),
                'color': card.get('color', 'Unknown'),
                'type': card.get('type', 'Unknown'),
                'image': card.get('image', ''),
                'rarity': card.get('rarity', 'C')
            }
            count += 1

        print(f"✓ Załadowano {len(self.cards_database)} kart.")
        self.root.after(0, self.create_ui)

    def create_ui(self):
        # Wyczyść
        for child in self.root.winfo_children():
            child.destroy()

        # Main frames
        left_frame = ttk.Frame(self.root)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        center_frame = ttk.Frame(self.root, width=280)
        center_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=5, pady=10)
        center_frame.pack_propagate(False)

        right_frame = ttk.Frame(self.root)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # LEFT: Karty
        ttk.Label(left_frame, text="📦 Twoje Karty z API", font=("Arial", 13, "bold")).pack()

        search_frame = ttk.Frame(left_frame)
        search_frame.pack(fill=tk.X, pady=5)
        ttk.Label(search_frame, text="🔍").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self.update_cards_list)
        ttk.Entry(search_frame, textvariable=self.search_var, width=30).pack(side=tk.LEFT, fill=tk.X, padx=5)

        tree_frame = ttk.Frame(left_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        scrollbar = ttk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.cards_tree = ttk.Treeview(tree_frame, columns=('name', 'power', 'own'), height=30,
                                       yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.cards_tree.yview)

        self.cards_tree.heading('#0', text='ID')
        self.cards_tree.heading('name', text='Nazwa')
        self.cards_tree.heading('power', text='PWR')
        self.cards_tree.heading('own', text='✓')

        self.cards_tree.column('#0', width=80)
        self.cards_tree.column('name', width=100)
        self.cards_tree.column('power', width=40)
        self.cards_tree.column('own', width=25)

        self.cards_tree.pack(fill=tk.BOTH, expand=True)
        self.cards_tree.bind('<Button-1>', self.on_tree_click)
        self.cards_tree.bind('<ButtonRelease-1>', self.show_card_image)

        # Najpierw tworzymy etykietę
        self.count_label = ttk.Label(left_frame, text="", font=("Arial", 9))
        self.count_label.pack()

        # Dopiero gdy etykieta istnieje, możemy zaktualizować listę (która z niej korzysta)
        self.update_cards_list()

        # CENTER: Zdjęcie karty
        ttk.Label(center_frame, text="🃏 Podgląd\nKarty", font=("Arial", 11, "bold"), justify=tk.CENTER).pack(pady=5)
        self.image_label = tk.Label(center_frame, text="Kliknij kartę\naby zobaczyć",
                                    bg="#2a2a2a", fg="#888", font=("Arial", 10), width=30, height=20)
        self.image_label.pack(pady=10)

        # RIGHT: Meta Decki
        ttk.Label(right_frame, text="🎯 Meta Decki (2025/2026)", font=("Arial", 13, "bold")).pack()

        deck_notebook = ttk.Notebook(right_frame)
        deck_notebook.pack(fill=tk.BOTH, expand=True, pady=5)

        self.deck_frames = {}
        for deck_name, deck_info in META_DECKS.items():
            tab = ttk.Frame(deck_notebook)
            deck_notebook.add(tab, text=f"{deck_info['tier']} {deck_name[:10]}")
            self.deck_frames[deck_name] = tab
            self.create_deck_tab(tab, deck_name)

    def create_deck_tab(self, parent, deck_name):
        deck_info = META_DECKS[deck_name]

        header = ttk.Frame(parent)
        header.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(header, text=f"📊 {deck_info['name']}", font=("Arial", 11, "bold")).pack(anchor=tk.W)
        ttk.Label(header, text=f"Tier: {deck_info['tier']} | WR: {deck_info['winrate']}", foreground="#888").pack(
            anchor=tk.W)
        ttk.Label(header, text=deck_info['description'], foreground="#6ba3ff").pack(anchor=tk.W, pady=3)

        cards_frame = ttk.LabelFrame(parent, text="Karty w decku", padding=10)
        cards_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        tree = ttk.Treeview(cards_frame, columns=('name', 'have'), height=12)
        tree.heading('#0', text='ID')
        tree.heading('name', text='Nazwa')
        tree.heading('have', text='Mam')

        tree.column('#0', width=80)
        tree.column('name', width=120)
        tree.column('have', width=35)

        for card_id in deck_info['cards']:
            if card_id in self.cards_database:
                card = self.cards_database[card_id]
                have = "✓" if self.owned_cards.get(card_id, 0) > 0 else "✗"
                tree.insert('', tk.END, text=card_id, values=(card['name'][:20], have))
            else:
                tree.insert('', tk.END, text=card_id, values=("Loading...", "?"))

        scrollbar = ttk.Scrollbar(cards_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(fill=tk.BOTH, expand=True)

        progress_frame = ttk.Frame(parent)
        progress_frame.pack(fill=tk.X, padx=10, pady=10)

        owned_count = sum(1 for card in deck_info['cards'] if self.owned_cards.get(card, 0) > 0)
        total_count = len(deck_info['cards'])
        completion = int((owned_count / total_count) * 100) if total_count > 0 else 0

        ttk.Label(progress_frame, text=f"Postęp: {owned_count}/{total_count} ({completion}%)").pack(anchor=tk.W)
        progress = ttk.Progressbar(progress_frame, length=250, mode='determinate', value=completion)
        progress.pack(fill=tk.X, pady=5)

    def update_cards_list(self, *args):
        for item in self.cards_tree.get_children():
            self.cards_tree.delete(item)

        search = self.search_var.get().lower()
        count = 0

        for card_id, card_info in self.cards_database.items():
            if search in card_id.lower() or search in card_info['name'].lower():
                have = "✓" if self.owned_cards.get(card_id, 0) > 0 else ""
                self.cards_tree.insert('', tk.END, text=card_id,
                                       values=(card_info['name'][:20], card_info['power'], have))
                count += 1

        owned = sum(self.owned_cards.values())
        self.count_label.config(text=f"Posiadane: {owned} | Znalezione: {count}")

    def show_card_image(self, event):
        selection = self.cards_tree.selection()
        if not selection:
            return

        card_id = self.cards_tree.item(selection[0], 'text')
        if card_id in self.cards_database and self.cards_database[card_id]['image']:
            image_url = self.cards_database[card_id]['image']
            threading.Thread(target=self.load_and_display_image, args=(card_id, image_url), daemon=True).start()

    def load_and_display_image(self, card_id, image_url):
        try:
            if card_id not in self.card_images:
                response = requests.get(image_url, timeout=10)
                img = Image.open(BytesIO(response.content))
                img.thumbnail((240, 330))
                self.card_images[card_id] = ImageTk.PhotoImage(img)

            self.root.after(0, lambda: self.image_label.config(image=self.card_images[card_id], text=""))
        except Exception as e:
            print(f"Błąd zdjęcia: {e}")

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
        self.refresh_all_decks()

    def refresh_all_decks(self):
        for deck_name, frame in self.deck_frames.items():
            for child in frame.winfo_children():
                child.destroy()
            self.create_deck_tab(frame, deck_name)

    def load_data(self):
        data_file = Path("op_tcg_data.json")
        if data_file.exists():
            with open(data_file, 'r') as f:
                self.owned_cards = json.load(f)

    def save_data(self):
        with open("op_tcg_data.json", 'w') as f:
            json.dump(self.owned_cards, f)


if __name__ == "__main__":
    root = tk.Tk()
    app = OPTCGApp(root)
    root.mainloop()