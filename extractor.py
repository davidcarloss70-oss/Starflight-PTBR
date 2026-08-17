import os
import json

ROM_PATH = "starflight_original.bin"
JSON_OUTPUT = "texts_to_translate.json"

def extract():
    if not os.path.exists(ROM_PATH):
        print(f"Erro: ROM original não encontrada em '{ROM_PATH}'")
        return

    with open(ROM_PATH, "rb") as f:
        rom_data = f.read()

    print(f"Analisando ROM '{ROM_PATH}' ({len(rom_data)} bytes)...")

    VALID_OPCODES = set([
        b"\x41\xf9", b"\x43\xf9", b"\x45\xf9", b"\x47\xf9", b"\x49\xf9", b"\x4b\xf9", b"\x4d\xf9", b"\x4f\xf9",
        b"\x48\x79",
        b"\x20\x3c", b"\x22\x3c", b"\x24\x3c", b"\x26\x3c", b"\x28\x3c", b"\x2a\x3c", b"\x2c\x3c", b"\x2e\x3c",
        b"\x20\x7c", b"\x22\x7c", b"\x24\x7c", b"\x26\x7c", b"\x28\x7c", b"\x2a\x7c", b"\x2c\x7c", b"\x2e\x7c"
    ])

    CPU_CONTROL_CODES = {
        b"\x4e\x71": "Nq",
        b"\x4e\x73": "Ns",
        b"\x4e\x75": "Nu",
        b"\x4e\x77": "Nw"
    }

    # -------------------------------------------------------------
    # 1. SENSOR / EXTRAÇÃO DE STRINGS PADRÃO DE TEXTO (ASCII DIRECT)
    # -------------------------------------------------------------
    std_strings = []
    current_str = []
    current_start = 0

    for idx in range(0x002000, len(rom_data)):
        byte = rom_data[idx]
        if 32 <= byte <= 126:
            if not current_str:
                current_start = idx
            current_str.append(chr(byte))
        else:
            if len(current_str) >= 6:
                text = "".join(current_str)
                start_offset = current_start
                
                first_two = rom_data[start_offset : start_offset + 2]
                if first_two in CPU_CONTROL_CODES:
                    start_offset += 2
                    text = text[2:]
                
                if len(text) >= 4:
                    std_strings.append({
                        "offset": start_offset,
                        "text": text,
                        "terminator": byte,
                        "type": "standard"
                    })
            current_str = []

    string_dict = {s["offset"]: s for s in std_strings}

    # Mapear referências para strings padrão
    referenced_std_strings = {}
    for s in std_strings:
        offset = s["offset"]
        text = s["text"]
        addr_bytes = offset.to_bytes(4, "big")
        
        refs = []
        pos = 0
        while True:
            pos = rom_data.find(addr_bytes, pos)
            if pos == -1:
                break
            if pos % 2 == 0 and pos < 0x0FE000:
                if not (offset <= pos < offset + len(text)):
                    pre = rom_data[pos-2 : pos]
                    if pre in VALID_OPCODES:
                        refs.append(pos)
                    else:
                        # Tabela contígua
                        if pos >= 4:
                            p_ptr = int.from_bytes(rom_data[pos-4 : pos], "big")
                            if p_ptr in string_dict:
                                p_str = string_dict[p_ptr]
                                if 0 <= offset - (p_ptr + len(p_str["text"]) + 1) <= 8:
                                    refs.append(pos)
                        if pos not in refs and pos + 8 <= len(rom_data):
                            n_ptr = int.from_bytes(rom_data[pos+4 : pos+8], "big")
                            if n_ptr in string_dict:
                                n_str = string_dict[n_ptr]
                                if 0 <= n_ptr - (offset + len(text) + 1) <= 8:
                                    refs.append(pos)
            pos += 2
        if refs:
            referenced_std_strings[offset] = refs

    # -------------------------------------------------------------
    # 1b. Agrupar strings padrão em blocos e marcar as regiões já cobertas
    #     por blocos padrão VÁLIDOS (com referência confirmada). O scanner
    #     de blocos compactos (seção 2) usa essa marcação pra não reclassificar
    #     strings padrão que já foram corretamente identificadas - sem isso,
    #     opcodes de CPU que terminam logo antes de uma string padrão (ex:
    #     0x4E75 = RTS, que coincide com os bytes ASCII "Nu") eram confundidos
    #     com o par de bytes de controle do formato compacto, criando uma
    #     entrada DUPLICADA e corrompida (com o opcode vazando pro texto).
    # -------------------------------------------------------------
    std_strings.sort(key=lambda x: x["offset"])
    std_blocks = []
    curr_b = []
    for s in std_strings:
        if not curr_b:
            curr_b.append(s)
        else:
            prev_end = curr_b[-1]["offset"] + len(curr_b[-1]["text"]) + 1
            if s["offset"] - prev_end <= 10:
                curr_b.append(s)
            else:
                std_blocks.append(curr_b)
                curr_b = [s]
    if curr_b:
        std_blocks.append(curr_b)

    covered = bytearray(len(rom_data))
    for b in std_blocks:
        if any(s["offset"] in referenced_std_strings for s in b):
            start = b[0]["offset"]
            end = b[-1]["offset"] + len(b[-1]["text"]) + 1
            for pos in range(max(0, start - 2), min(len(rom_data), end)):
                covered[pos] = 1

    # -------------------------------------------------------------
    # 2. SENSOR DE BLOCOS DE TEXTO COMPACTO (SISTEMA SECUNDÁRIO DA EA)
    # -------------------------------------------------------------
    compact_blocks = []
    i = 0x002000
    while i < len(rom_data) - 10:
        if covered[i]:
            i += 1
            continue

        snippet = rom_data[i+2 : i+10]
        printable_len = sum(1 for b in snippet if 32 <= b <= 126)
        b1, b2 = rom_data[i], rom_data[i+1]

        # Descarta de cara se os 2 bytes de controle coincidem com um opcode
        # de CPU conhecido (RTS-family) - forte indício de que isso é o fim
        # de uma sub-rotina, não um cabeçalho de controle do sistema compacto.
        if (b1, b2) == (0x4e, 0x71) or (b1, b2) == (0x4e, 0x73) or \
           (b1, b2) == (0x4e, 0x75) or (b1, b2) == (0x4e, 0x77):
            i += 1
            continue

        if printable_len >= 3 and not (32 <= b1 <= 126 and 32 <= b2 <= 126):
            block_start = i
            items = []
            curr = i
            valid = True
            
            while curr < len(rom_data) - 5:
                # Se QUALQUER parte deste item cair numa região já coberta
                # por um bloco padrão válido, este candidato inteiro é
                # inválido - o bloco compacto pode ter começado numa área
                # "livre" mas atravessado pra dentro de uma string padrão
                # real logo depois (foi exatamente assim que o bug do
                # opcode "Nu" vazando pro texto aconteceu).
                if covered[curr]:
                    valid = False
                    break

                cb1 = rom_data[curr]
                cb2 = rom_data[curr+1]

                if cb1 == 0xFF and cb2 == 0xFF:
                    curr += 2
                    break

                str_start = curr + 2
                str_end = str_start
                while str_end < len(rom_data) and rom_data[str_end] != 0xFF:
                    str_end += 1

                if str_end >= len(rom_data):
                    valid = False
                    break

                if any(covered[p] for p in range(str_start, min(str_end + 1, len(rom_data)))):
                    valid = False
                    break

                text_bytes = rom_data[str_start:str_end]
                if not text_bytes or not all(32 <= b <= 126 for b in text_bytes):
                    valid = False
                    break
                
                items.append({
                    "ctrl": (cb1, cb2),
                    "ctrl_offset": curr,
                    "text_offset": str_start,
                    "text": text_bytes.decode("ascii", errors="ignore"),
                    "terminator": 0xFF
                })
                
                curr = str_end + 1
                if curr < len(rom_data) and rom_data[curr] == 0xFF:
                    curr += 1
                    break
            
            if valid and len(items) >= 1:
                # Procurar referências de código LEA para o início do bloco compacto
                b_bytes = block_start.to_bytes(4, "big")
                refs = []
                pos = 0
                while True:
                    pos = rom_data.find(b_bytes, pos)
                    if pos == -1:
                        break
                    if pos % 2 == 0 and pos < 0x0FE000:
                        pre = rom_data[pos-2:pos]
                        if pre in VALID_OPCODES:
                            refs.append(pos)
                    pos += 2
                
                # Também verificar se o ctrl_offset de algum item individual tem referência LEA
                for item in items:
                    t_bytes = item["ctrl_offset"].to_bytes(4, "big")
                    pos = 0
                    while True:
                        pos = rom_data.find(t_bytes, pos)
                        if pos == -1:
                            break
                        if pos % 2 == 0 and pos < 0x0FE000:
                            pre = rom_data[pos-2:pos]
                            if pre in VALID_OPCODES and pos not in refs:
                                refs.append(pos)
                        pos += 2

                if refs:
                    compact_blocks.append({
                        "start": block_start,
                        "end": curr,
                        "items": items,
                        "refs": refs
                    })
                i = curr
                continue
        i += 1

    print(f"Blocos padrão com referências válidas: {len(referenced_std_strings)}")
    print(f"Blocos compactos com referências de código encontradas: {len(compact_blocks)}")

    # -------------------------------------------------------------
    # 3. COMBINAR E ARMAZENAR NO JSON DE TRADUÇÃO
    # -------------------------------------------------------------
    json_data = []

    # A) Adicionar blocos de texto padrão (agrupamento já calculado na seção 1b)
    b_id = 0
    for b in std_blocks:
        if any(s["offset"] in referenced_std_strings for s in b):
            items_data = []
            for s in b:
                off = s["offset"]
                r_list = referenced_std_strings.get(off, [])
                items_data.append({
                    "offset_hex": f"0x{off:06X}",
                    "offset": off,
                    "english": s["text"],
                    "portuguese": s["text"],
                    "terminator": s["terminator"],
                    "references": [f"0x{r:06X}" for r in r_list],
                    "type": "standard"
                })
            json_data.append({
                "block_id": b_id,
                "start_offset_hex": f"0x{b[0]['offset']:06X}",
                "end_offset_hex": f"0x{b[-1]['offset'] + len(b[-1]['text']):06X}",
                "type": "standard",
                "items": items_data
            })
            b_id += 1

    # B) Adicionar blocos compactos
    for cb in compact_blocks:
        items_data = []
        for idx_item, s in enumerate(cb["items"]):
            r_list = cb["refs"] if idx_item == 0 else []
            items_data.append({
                "offset_hex": f"0x{s['text_offset']:06X}",
                "ctrl_offset_hex": f"0x{s['ctrl_offset']:06X}",
                "offset": s["text_offset"],
                "ctrl_bytes": [s["ctrl"][0], s["ctrl"][1]],
                "english": s["text"],
                "portuguese": s["text"],
                "terminator": s["terminator"],
                "references": [f"0x{r:06X}" for r in r_list],
                "type": "compact"
            })
        json_data.append({
            "block_id": b_id,
            "start_offset_hex": f"0x{cb['start']:06X}",
            "end_offset_hex": f"0x{cb['end']:06X}",
            "type": "compact",
            "items": items_data
        })
        b_id += 1

    with open(JSON_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)

    print(f"\nArquivo de tradução final gerado com sucesso em '{JSON_OUTPUT}'!")
    print(f"Total de blocos combinados para tradução: {len(json_data)}")

if __name__ == "__main__":
    extract()
