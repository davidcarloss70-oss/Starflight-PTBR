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

    # 1. Encontrar todas as strings legíveis (apenas a partir de 0x002000)
    strings = []
    current_str = []
    current_start = 0

    CPU_CONTROL_CODES = {
        b"\x4e\x71": "Nq",
        b"\x4e\x73": "Ns",
        b"\x4e\x75": "Nu",
        b"\x4e\x77": "Nw"
    }

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
                
                # Tratar opcodes de controle que começam strings
                first_two_bytes = rom_data[start_offset : start_offset + 2]
                if first_two_bytes in CPU_CONTROL_CODES:
                    start_offset += 2
                    text = text[2:]
                
                if len(text) >= 4:
                    strings.append({
                        "offset": start_offset,
                        "text": text,
                        "terminator": byte
                    })
            current_str = []

    print(f"Total de strings legíveis detectadas (acima de 0x2000): {len(strings)}")

    # Dicionário de offset -> string para verificação rápida de contiguidade
    string_dict = {s["offset"]: s for s in strings}

    # 2. Procurar referências válidas na ROM
    referenced_strings = {}
    
    # Opcodes conhecidos de instruções do 68k
    VALID_OPCODES = set([
        b"\x41\xf9", b"\x43\xf9", b"\x45\xf9", b"\x47\xf9", b"\x49\xf9", b"\x4b\xf9", b"\x4d\xf9", b"\x4f\xf9",
        b"\x48\x79",
        b"\x20\x3c", b"\x22\x3c", b"\x24\x3c", b"\x26\x3c", b"\x28\x3c", b"\x2a\x3c", b"\x2c\x3c", b"\x2e\x3c",
        b"\x20\x7c", b"\x22\x7c", b"\x24\x7c", b"\x26\x7c", b"\x28\x7c", b"\x2a\x7c", b"\x2c\x7c", b"\x2e\x7c"
    ])

    total_refs_found = 0

    for string_info in strings:
        offset = string_info["offset"]
        text = string_info["text"]
        addr_bytes = offset.to_bytes(4, "big")
        
        references = []
        idx = 0
        while True:
            idx = rom_data.find(addr_bytes, idx)
            if idx == -1:
                break
            
            # Garantir alinhamento par
            if idx % 2 == 0:
                # Evitar referências dentro da própria string
                if not (offset <= idx < offset + len(text)):
                    
                    is_valid = False
                    
                    # Critério A: É um operando de instrução CPU (precedido por um opcode válido)
                    preceding_bytes = rom_data[idx - 2 : idx]
                    if preceding_bytes in VALID_OPCODES:
                        is_valid = True
                        
                    # Critério B: Faz parte de uma tabela contígua de ponteiros de strings
                    if not is_valid:
                        # Verificar o ponteiro anterior (ref - 4)
                        if idx >= 4:
                            prev_ptr = int.from_bytes(rom_data[idx - 4 : idx], "big")
                            if prev_ptr in string_dict:
                                prev_str = string_dict[prev_ptr]
                                prev_end = prev_ptr + len(prev_str["text"]) + 1
                                # Se as duas strings apontadas são fisicamente adjacentes na ROM, é uma tabela válida
                                if 0 <= offset - prev_end <= 8:
                                    is_valid = True
                                    
                        # Verificar o ponteiro posterior (ref + 4)
                        if not is_valid and idx + 8 <= len(rom_data):
                            next_ptr = int.from_bytes(rom_data[idx + 4 : idx + 8], "big")
                            if next_ptr in string_dict:
                                next_str = string_dict[next_ptr]
                                current_end = offset + len(text) + 1
                                # Se as duas strings apontadas são fisicamente adjacentes na ROM, é uma tabela válida
                                if 0 <= next_ptr - current_end <= 8:
                                    is_valid = True
                                
                    if is_valid:
                        references.append(idx)
                        total_refs_found += 1
                        
            idx += 2

        if references:
            referenced_strings[offset] = references

    print(f"Strings com referências válidas filtradas: {len(referenced_strings)} (Total de refs: {total_refs_found})")

    # 3. Agrupar em blocos contíguos de texto
    blocks = []
    current_block = []
    max_gap = 10

    strings.sort(key=lambda x: x["offset"])

    for s in strings:
        offset = s["offset"]
        if not current_block:
            current_block.append(s)
        else:
            prev_s = current_block[-1]
            prev_end = prev_s["offset"] + len(prev_s["text"]) + 1
            
            if offset - prev_end <= max_gap:
                current_block.append(s)
            else:
                blocks.append(current_block)
                current_block = [s]
                
    if current_block:
        blocks.append(current_block)

    valid_blocks = []
    for block in blocks:
        has_any_reference = any(s["offset"] in referenced_strings for s in block)
        if has_any_reference:
            valid_blocks.append(block)

    print(f"Total de blocos válidos agrupados: {len(valid_blocks)}")

    # 4. Formatar os dados para o JSON de tradução
    json_data = []
    for block_id, block in enumerate(valid_blocks):
        block_items = []
        for s in block:
            offset = s["offset"]
            refs = referenced_strings.get(offset, [])
            block_items.append({
                "offset_hex": f"0x{offset:06X}",
                "offset": offset,
                "english": s["text"],
                "portuguese": s["text"],
                "terminator": s["terminator"],
                "references": [f"0x{r:06X}" for r in refs]
            })
        
        json_data.append({
            "block_id": block_id,
            "start_offset_hex": f"0x{block[0]['offset']:06X}",
            "end_offset_hex": f"0x{block[-1]['offset'] + len(block[-1]['text']):06X}",
            "items": block_items
        })

    with open(JSON_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)

    print(f"Arquivo de tradução gerado com sucesso em '{JSON_OUTPUT}'!")
    print(f"Total de blocos de diálogo prontos para tradução: {len(json_data)}")

if __name__ == "__main__":
    extract()
