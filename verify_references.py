import os
import json

ROM_PATH = "starflight_original.bin"
JSON_PATH = "texts_to_translate.json"

def verify():
    if not os.path.exists(ROM_PATH) or not os.path.exists(JSON_PATH):
        print("Erro: Arquivos não encontrados.")
        return
        
    with open(ROM_PATH, "rb") as f:
        rom_data = f.read()
        
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        blocks = json.load(f)
        
    VALID_OPCODES = {
        b"\x41\xf9": "LEA a0", b"\x43\xf9": "LEA a1", b"\x45\xf9": "LEA a2", b"\x47\xf9": "LEA a3", 
        b"\x49\xf9": "LEA a4", b"\x4b\xf9": "LEA a5", b"\x4d\xf9": "LEA a6", b"\x4f\xf9": "LEA a7",
        b"\x48\x79": "PEA",
        b"\x20\x3c": "MOVE.L d0", b"\x22\x3c": "MOVE.L d1", b"\x24\x3c": "MOVE.L d2", b"\x26\x3c": "MOVE.L d3", 
        b"\x28\x3c": "MOVE.L d4", b"\x2a\x3c": "MOVE.L d5", b"\x2c\x3c": "MOVE.L d6", b"\x2e\x3c": "MOVE.L d7",
        b"\x20\x7c": "MOVE.L a0", b"\x22\x7c": "MOVE.L a1", b"\x24\x7c": "MOVE.L a2", b"\x26\x7c": "MOVE.L a3", 
        b"\x28\x7c": "MOVE.L a4", b"\x2a\x7c": "MOVE.L a5", b"\x2c\x7c": "MOVE.L a6", b"\x2e\x7c": "MOVE.L a7"
    }

    code_refs = 0
    table_refs = 0
    both_refs = 0
    unclassified_refs = 0
    
    print("Classificando referências encontradas:")
    
    # Vamos coletar todos os offsets de string para a verificação de tabela
    string_offsets = set()
    for block in blocks:
        for item in block["items"]:
            string_offsets.add(item["offset"])

    for block in blocks:
        for item in block["items"]:
            english = item["english"]
            offset = item["offset"]
            
            for ref_hex in item["references"]:
                ref = int(ref_hex, 16)
                
                # Verificar se é código
                preceding = rom_data[ref-2 : ref]
                is_code = preceding in VALID_OPCODES
                opcode_name = VALID_OPCODES.get(preceding, "")
                
                # Verificar se é tabela
                is_table = False
                prev_ptr = 0
                next_ptr = 0
                if ref >= 4:
                    prev_ptr = int.from_bytes(rom_data[ref-4 : ref], "big")
                if ref + 8 <= len(rom_data):
                    next_ptr = int.from_bytes(rom_data[ref+4 : ref+8], "big")
                
                if prev_ptr in string_offsets or next_ptr in string_offsets:
                    is_table = True
                    
                if is_code and is_table:
                    both_refs += 1
                elif is_code:
                    code_refs += 1
                elif is_table:
                    table_refs += 1
                else:
                    unclassified_refs += 1
                    print(f"Ref NÃO CLASSIFICADA em 0x{ref:06X} para string \"{english[:30]}\" (valor na ROM: {rom_data[ref:ref+4].hex()})")

    print(f"\nResumo:")
    print(f"Referências apenas de Código (LEA/PEA/MOVE): {code_refs}")
    print(f"Referências apenas de Tabela (ponteiros adjacentes): {table_refs}")
    print(f"Referências que atendem a AMBOS os critérios: {both_refs}")
    print(f"Referências não classificadas (anomalias): {unclassified_refs}")

if __name__ == "__main__":
    verify()
