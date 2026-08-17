import os
import json

ROM_INPUT = "starflight_original.bin"
ROM_OUTPUT = "starflight_translated.bin"
JSON_INPUT = "texts_to_translate.json"
EXPANDED_SIZE = 2 * 1024 * 1024  # 2MB
START_EXPANDED_OFFSET = 0x100000 # 1MB

def compile_rom():
    if not os.path.exists(ROM_INPUT):
        print(f"Erro: ROM original não encontrada em '{ROM_INPUT}'")
        return
        
    if not os.path.exists(JSON_INPUT):
        print(f"Erro: Arquivo JSON de tradução não encontrado em '{JSON_INPUT}'")
        return

    with open(ROM_INPUT, "rb") as f:
        original_data = f.read()
        
    rom_data = bytearray(EXPANDED_SIZE)
    rom_data[0:len(original_data)] = original_data
    for i in range(len(original_data), EXPANDED_SIZE):
        rom_data[i] = 0xFF

    print(f"ROM carregada e expandida para {EXPANDED_SIZE} bytes.")

    with open(JSON_INPUT, "r", encoding="utf-8") as f:
        translation_blocks = json.load(f)

    current_write_offset = START_EXPANDED_OFFSET
    updated_pointers_count = 0
    total_strings_written = 0

    print("Escrevendo textos traduzidos e atualizando referências...")

    for block in translation_blocks:
        block_type = block.get("type", "standard")

        if block_type == "compact":
            # Início do bloco compacto na memória expandida
            block_new_start = current_write_offset
            
            for idx_item, item in enumerate(block["items"]):
                ctrl1, ctrl2 = item["ctrl_bytes"]
                text_bytes = item["portuguese"].encode("latin1", errors="replace")
                
                # Escrever bytes de controle
                rom_data[current_write_offset] = ctrl1
                rom_data[current_write_offset + 1] = ctrl2
                current_write_offset += 2
                
                # Escrever texto
                rom_data[current_write_offset : current_write_offset + len(text_bytes)] = text_bytes
                current_write_offset += len(text_bytes)
                
                # Escrever terminador de string (0xFF)
                rom_data[current_write_offset] = 0xFF
                current_write_offset += 1
                
                total_strings_written += 1

                # Atualizar referências se houver
                if item.get("references"):
                    new_offset_bytes = block_new_start.to_bytes(4, "big")
                    for ref_hex in item["references"]:
                        ref_offset = int(ref_hex, 16)
                        rom_data[ref_offset : ref_offset + 4] = new_offset_bytes
                        updated_pointers_count += 1
            
            # Adicionar o terminador duplo de fim de bloco (0xFF 0xFF)
            rom_data[current_write_offset] = 0xFF
            rom_data[current_write_offset + 1] = 0xFF
            current_write_offset += 2

            # Manter alinhamento par
            if current_write_offset % 2 != 0:
                rom_data[current_write_offset] = 0xFF
                current_write_offset += 1

        else:
            # Bloco padrão
            # Verificar regra do repositório: se o bloco contém itens sem referências (âncora + órfãos)
            # e a âncora foi marcada para não mover ou se é um grupo rígido, o compilador mantém intacto
            has_unreferenced_orphans = any(len(it.get("references", [])) == 0 for it in block["items"])
            
            if has_unreferenced_orphans:
                # Manter intacto para evitar desalinhamento visual na UI
                for item in block["items"]:
                    total_strings_written += 1
            else:
                for item in block["items"]:
                    text_bytes = item["portuguese"].encode("latin1", errors="replace")
                    terminator_byte = item["terminator"]

                    new_offset = current_write_offset
                    rom_data[new_offset : new_offset + len(text_bytes)] = text_bytes
                    rom_data[new_offset + len(text_bytes)] = terminator_byte
                    
                    current_write_offset += len(text_bytes) + 1
                    if current_write_offset % 2 != 0:
                        rom_data[current_write_offset] = 0xFF
                        current_write_offset += 1
                        
                    total_strings_written += 1

                    new_offset_bytes = new_offset.to_bytes(4, "big")
                    for ref_hex in item["references"]:
                        ref_offset = int(ref_hex, 16)
                        rom_data[ref_offset : ref_offset + 4] = new_offset_bytes
                        updated_pointers_count += 1

    print(f"Total de strings processadas: {total_strings_written}")
    print(f"Total de ponteiros atualizados: {updated_pointers_count}")
    print(f"Dados gravados de 0x{START_EXPANDED_OFFSET:06X} até 0x{current_write_offset:06X}")

    # 4. PATCH DE PROTEÇÃO ANTI-CÓPIA DA EA
    # Endereço 0x0FFFD0: Troca de BNE (0x66 0x02) por NOP (0x4E 0x71) para
    # desativar a trava da EA. Confere os 2 bytes exatos (não só o primeiro)
    # e AVISA se o padrão não bater, em vez de falhar silenciosamente -
    # se esse aviso aparecer, a ROM provavelmente vai travar em tela preta.
    if rom_data[0x0FFFD0:0x0FFFD2] == b"\x66\x02":
        rom_data[0x0FFFD0:0x0FFFD2] = b"\x4E\x71"
        print("Patch de proteção anti-cópia da EA aplicado em 0x0FFFD0 (BNE -> NOP)!")
    else:
        print("AVISO: padrão de bytes esperado da rotina de checksum da EA não encontrado em 0x0FFFD0 - pulei o patch! A ROM provavelmente vai travar.")

    # 5. Manter tamanho de 1MB no cabeçalho e recalcular Checksum dos primeiros 1MB
    rom_end_in_header = int.from_bytes(rom_data[0x1A4 : 0x1A8], "big")
    print(f"Fim da ROM mantido no cabeçalho: 0x{rom_end_in_header:08X}")

    calculated_checksum = 0
    for i in range(0x200, len(original_data), 2):
        val = int.from_bytes(rom_data[i : i+2], "big")
        calculated_checksum = (calculated_checksum + val) & 0xFFFF
        
    rom_data[0x18E : 0x190] = calculated_checksum.to_bytes(2, "big")
    print(f"Checksum recalculado (primeiros 1MB) e gravado: 0x{calculated_checksum:04X}")

    with open(ROM_OUTPUT, "wb") as f:
        f.write(rom_data)
        
    print(f"ROM traduzida salva com sucesso em '{ROM_OUTPUT}'!")

if __name__ == "__main__":
    compile_rom()
