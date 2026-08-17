import json
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

# ---------------------------------------------------------------------------
# Paths: sempre relativos à pasta onde o .exe/script está, para funcionar
# tanto rodando com "python translator_gui.py" quanto como .exe empacotado.
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ROM_INPUT = os.path.join(BASE_DIR, "starflight_original.bin")
ROM_OUTPUT = os.path.join(BASE_DIR, "starflight_translated.bin")
JSON_PATH = os.path.join(BASE_DIR, "texts_to_translate.json")

EXPANDED_SIZE = 2 * 1024 * 1024
START_EXPANDED_OFFSET = 0x100000
EA_CHECKSUM_BNE_OFFSET = 0xFFFD0
EA_CHECKSUM_BNE_BYTES = b"\x66\x02"
EA_CHECKSUM_NOP_BYTES = b"\x4E\x71"


# ---------------------------------------------------------------------------
# Heurística de risco: sinaliza itens que provavelmente NÃO devem ser
# traduzidos (nomes próprios, dados binários/gráficos capturados por engano
# pelo extrator). Não bloqueia edição, só avisa visualmente.
# ---------------------------------------------------------------------------
def is_risky(english_text):
    text = english_text.strip()
    if not text:
        return False
    alpha_count = sum(1 for c in text if c.isalpha())
    ratio = alpha_count / len(text)
    if ratio < 0.5:
        # Majoritariamente dígitos/símbolos -> provável dado binário/gráfico
        return True
    if " " not in text and text.isupper() and len(text) <= 16 and alpha_count == len(text):
        # Palavra única, toda maiúscula, sem espaço -> provável nome próprio
        return True
    return False


def compute_locked_offsets(blocks):
    """Itens sem referência própria (references == []) e a âncora que os
    precede imediatamente - o compilador não aplica tradução nenhuma deles
    (ver compile_rom), porque mexer nesse grupo corrompe gráficos de UI em
    outras telas. Usado só pra sinalizar na interface, não bloqueia edição
    de fato (o usuário pode editar, só não vai ter efeito na ROM)."""
    locked = set()
    for block in blocks:
        items = block["items"]
        for i, item in enumerate(items):
            if not item["references"]:
                locked.add(item["offset"])
                if i > 0 and items[i - 1]["references"]:
                    locked.add(items[i - 1]["offset"])
    return locked


def load_items():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        blocks = json.load(f)
    items = []
    for block in blocks:
        for item in block["items"]:
            items.append(item)
    return blocks, items


def save_json(blocks):
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(blocks, f, indent=2, ensure_ascii=False)


def compile_rom(log_callback):
    if not os.path.exists(ROM_INPUT):
        raise FileNotFoundError(f"ROM original não encontrada em '{ROM_INPUT}'")
    if not os.path.exists(JSON_PATH):
        raise FileNotFoundError(f"Arquivo JSON não encontrado em '{JSON_PATH}'")

    with open(ROM_INPUT, "rb") as f:
        original_data = f.read()

    rom_data = bytearray(EXPANDED_SIZE)
    rom_data[0:len(original_data)] = original_data
    for i in range(len(original_data), EXPANDED_SIZE):
        rom_data[i] = 0xFF

    log_callback(f"ROM carregada e expandida para {EXPANDED_SIZE} bytes.")

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        translation_blocks = json.load(f)

    # Itens "sem referência própria" (references == []) só funcionam por
    # estarem fisicamente colados, na ROM original, logo após um item com
    # referência (a "âncora") - o jogo parece acessá-los por deslocamento
    # fixo a partir da âncora, calculado com base no tamanho ORIGINAL em
    # inglês. Realocar a âncora (ou mudar seu tamanho) corrompe essas linhas.
    # Correção segura: não mexer em nada desse grupo (nem a âncora).
    skip_offsets = set()
    for block in translation_blocks:
        items = block["items"]
        for i, item in enumerate(items):
            if not item["references"]:
                skip_offsets.add(item["offset"])
                if i > 0 and items[i - 1]["references"]:
                    skip_offsets.add(items[i - 1]["offset"])

    current_write_offset = START_EXPANDED_OFFSET
    updated_pointers_count = 0
    total_strings_written = 0
    skipped_count = 0

    for block in translation_blocks:
        for item in block["items"]:
            if item["offset"] in skip_offsets:
                skipped_count += 1
                continue

            text_bytes = item["portuguese"].encode("latin1", errors="replace")
            terminator_byte = item["terminator"]

            new_offset = current_write_offset
            rom_data[new_offset:new_offset + len(text_bytes)] = text_bytes
            rom_data[new_offset + len(text_bytes)] = terminator_byte

            current_write_offset += len(text_bytes) + 1
            if current_write_offset % 2 != 0:
                rom_data[current_write_offset] = 0xFF
                current_write_offset += 1

            total_strings_written += 1

            new_offset_bytes = new_offset.to_bytes(4, "big")
            for ref_hex in item["references"]:
                ref_offset = int(ref_hex, 16)
                rom_data[ref_offset:ref_offset + 4] = new_offset_bytes
                updated_pointers_count += 1

    log_callback(f"Strings gravadas: {total_strings_written}")
    log_callback(f"Itens pulados (grupos sem referência própria, preservados intactos): {skipped_count}")
    log_callback(f"Ponteiros atualizados: {updated_pointers_count}")
    log_callback(f"Dados escritos até 0x{current_write_offset:06X}")

    # Cabeçalho: mantém fim da ROM em 1MB (testado empiricamente - necessário
    # pro boot funcionar no BlastEm/Kega, mesmo com o arquivo tendo 2MB reais).
    calculated_checksum = 0
    for i in range(0x200, len(original_data), 2):
        val = int.from_bytes(rom_data[i:i + 2], "big")
        calculated_checksum = (calculated_checksum + val) & 0xFFFF
    rom_data[0x18E:0x190] = calculated_checksum.to_bytes(2, "big")
    log_callback(f"Checksum da Sega recalculado: 0x{calculated_checksum:04X}")

    # Neutraliza a rotina de checksum proprietária da EA (0x0FFFB0-0x0FFFFE),
    # que senão trava o jogo em tela preta com qualquer byte alterado na ROM.
    if rom_data[EA_CHECKSUM_BNE_OFFSET:EA_CHECKSUM_BNE_OFFSET + 2] == EA_CHECKSUM_BNE_BYTES:
        rom_data[EA_CHECKSUM_BNE_OFFSET:EA_CHECKSUM_BNE_OFFSET + 2] = EA_CHECKSUM_NOP_BYTES
        log_callback("Rotina de checksum da EA neutralizada (BNE -> NOP).")
    else:
        log_callback("AVISO: padrão da rotina de checksum da EA não encontrado - pulei o patch!")

    with open(ROM_OUTPUT, "wb") as f:
        f.write(rom_data)
    log_callback(f"ROM traduzida salva em '{ROM_OUTPUT}'.")


# ---------------------------------------------------------------------------
# Interface gráfica
# ---------------------------------------------------------------------------
class TranslatorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Starflight - Editor de Tradução")
        self.geometry("1150x700")
        self.minsize(900, 550)

        self.blocks = []
        self.items = []
        self.filtered_indices = []
        self.dirty = False

        self._build_ui()
        self._load_data()

    # -- construção da interface -----------------------------------------
    def _build_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(side="top", fill="x", padx=8, pady=6)

        ttk.Label(toolbar, text="Buscar:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._apply_filter())
        search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=30)
        search_entry.pack(side="left", padx=(4, 12))

        ttk.Label(toolbar, text="Filtro:").pack(side="left")
        self.filter_var = tk.StringVar(value="Todos")
        filter_box = ttk.Combobox(
            toolbar, textvariable=self.filter_var, state="readonly", width=22,
            values=["Todos", "Não traduzidos", "Revisar (risco)", "Bloqueados (não aplicado)"]
        )
        filter_box.pack(side="left", padx=(4, 12))
        filter_box.bind("<<ComboboxSelected>>", lambda e: self._apply_filter())

        ttk.Button(toolbar, text="Salvar tudo (JSON)", command=self._save_all).pack(side="right", padx=4)
        ttk.Button(toolbar, text="Compilar ROM", command=self._compile).pack(side="right", padx=4)

        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var, foreground="#555").pack(side="top", anchor="w", padx=10)

        # --- painel principal: lista + detalhe ---
        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(side="top", fill="both", expand=True, padx=8, pady=4)

        list_frame = ttk.Frame(paned)
        paned.add(list_frame, weight=3)

        columns = ("offset", "english", "portuguese", "flag")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("offset", text="Offset")
        self.tree.heading("english", text="Inglês")
        self.tree.heading("portuguese", text="Português")
        self.tree.heading("flag", text="Aviso")
        self.tree.column("offset", width=90, anchor="w")
        self.tree.column("english", width=380, anchor="w")
        self.tree.column("portuguese", width=380, anchor="w")
        self.tree.column("flag", width=140, anchor="w")

        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.tag_configure("risky", background="#fff2cc")
        self.tree.tag_configure("untranslated", foreground="#888888")
        self.tree.tag_configure("locked", background="#f5c6c6")

        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # --- painel de edição ---
        detail_frame = ttk.Frame(paned)
        paned.add(detail_frame, weight=2)

        self.detail_flag_var = tk.StringVar(value="")
        ttk.Label(detail_frame, textvariable=self.detail_flag_var, foreground="#a05a00",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=4, pady=(4, 0))

        ttk.Label(detail_frame, text="Inglês (original, referência):").pack(anchor="w", padx=4, pady=(6, 0))
        self.english_text = tk.Text(detail_frame, height=5, wrap="word", state="disabled", bg="#f4f4f4")
        self.english_text.pack(fill="x", padx=4)

        ttk.Label(detail_frame, text="Português (editável):").pack(anchor="w", padx=4, pady=(8, 0))
        self.portuguese_text = tk.Text(detail_frame, height=6, wrap="word")
        self.portuguese_text.pack(fill="both", expand=True, padx=4)

        btn_row = ttk.Frame(detail_frame)
        btn_row.pack(fill="x", padx=4, pady=6)
        ttk.Button(btn_row, text="Aplicar alteração a este item", command=self._apply_item_edit).pack(side="left")

        self.current_index = None  # índice em self.items do item selecionado

    # -- dados ---------------------------------------------------------
    def _load_data(self):
        try:
            self.blocks, self.items = load_items()
            self.locked_offsets = compute_locked_offsets(self.blocks)
        except Exception as exc:
            messagebox.showerror("Erro ao carregar", str(exc))
            self.items = []
            self.blocks = []
            self.locked_offsets = set()
        self._apply_filter()
        self._update_status()

    def _update_status(self):
        total = len(self.items)
        untranslated = sum(1 for it in self.items if it["portuguese"] == it["english"])
        risky = sum(1 for it in self.items if is_risky(it["english"]))
        locked = sum(1 for it in self.items if it["offset"] in self.locked_offsets)
        self.status_var.set(
            f"{total} textos no total  |  {untranslated} ainda não traduzidos  |  "
            f"{risky} sinalizados para revisão (nomes próprios / dados binários)  |  "
            f"{locked} bloqueados (sem referência própria - tradução não é aplicada na ROM)"
        )

    # -- filtro / listagem ----------------------------------------------
    def _apply_filter(self):
        query = self.search_var.get().strip().lower()
        mode = self.filter_var.get()

        self.tree.delete(*self.tree.get_children())
        self.filtered_indices = []

        for idx, item in enumerate(self.items):
            en = item["english"]
            pt = item["portuguese"]

            locked = item["offset"] in self.locked_offsets

            if mode == "Não traduzidos" and pt != en:
                continue
            if mode == "Revisar (risco)" and not is_risky(en):
                continue
            if mode == "Bloqueados (não aplicado)" and not locked:
                continue

            if query and query not in en.lower() and query not in pt.lower():
                continue

            risky = is_risky(en)
            tags = []
            if locked:
                tags.append("locked")
            elif risky:
                tags.append("risky")
            if pt == en:
                tags.append("untranslated")

            preview_en = en if len(en) <= 80 else en[:77] + "..."
            preview_pt = pt if len(pt) <= 80 else pt[:77] + "..."
            if locked:
                flag_text = "bloqueado (sem ref.)"
            elif risky:
                flag_text = "revisar (nome/dado)"
            else:
                flag_text = ""

            self.tree.insert(
                "", "end", iid=str(idx),
                values=(item["offset_hex"], preview_en, preview_pt, flag_text),
                tags=tags,
            )
            self.filtered_indices.append(idx)

    # -- seleção / edição -------------------------------------------------
    def _on_select(self, event):
        selection = self.tree.selection()
        if not selection:
            return
        idx = int(selection[0])
        self.current_index = idx
        item = self.items[idx]

        self.english_text.configure(state="normal")
        self.english_text.delete("1.0", "end")
        self.english_text.insert("1.0", item["english"])
        self.english_text.configure(state="disabled")

        self.portuguese_text.delete("1.0", "end")
        self.portuguese_text.insert("1.0", item["portuguese"])

        if item["offset"] in self.locked_offsets:
            self.detail_flag_var.set(
                "🔒 Este item não tem referência (ponteiro) própria - o compilador "
                "NÃO aplica a tradução dele na ROM (evita corromper gráficos de UI "
                "em outras telas). Editar aqui não muda o jogo compilado."
            )
        elif is_risky(item["english"]):
            self.detail_flag_var.set(
                "⚠ Este texto parece ser nome próprio ou dado binário/gráfico — "
                "provavelmente NÃO deve ser traduzido."
            )
        else:
            self.detail_flag_var.set("")

    def _apply_item_edit(self):
        if self.current_index is None:
            return
        new_text = self.portuguese_text.get("1.0", "end-1c")
        self.items[self.current_index]["portuguese"] = new_text
        self.dirty = True
        self._apply_filter()
        self._update_status()
        self.status_var.set(self.status_var.get() + "   (alteração aplicada - lembre de salvar)")

    # -- ações de arquivo/compilação -------------------------------------
    def _save_all(self):
        try:
            save_json(self.blocks)
            self.dirty = False
            messagebox.showinfo("Salvo", "texts_to_translate.json atualizado com sucesso.")
        except Exception as exc:
            messagebox.showerror("Erro ao salvar", str(exc))

    def _compile(self):
        if self.dirty:
            if not messagebox.askyesno(
                "Salvar antes de compilar?",
                "Você tem alterações não salvas no JSON. Salvar agora antes de compilar a ROM?"
            ):
                return
            self._save_all()

        log_lines = []

        def log_callback(msg):
            log_lines.append(msg)

        def worker():
            try:
                compile_rom(log_callback)
                self.after(0, lambda: messagebox.showinfo(
                    "ROM compilada", "\n".join(log_lines)
                ))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Erro ao compilar", str(exc)))

        threading.Thread(target=worker, daemon=True).start()


def main():
    app = TranslatorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
