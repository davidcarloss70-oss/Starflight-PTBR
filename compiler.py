import os
import json

ROM_INPUT = "starflight_original.bin"
ROM_OUTPUT = "starflight_translated.bin"
JSON_INPUT = "texts_to_translate.json"
EXPANDED_SIZE = 2 * 1024 * 1024  # 2MB
START_EXPANDED_OFFSET = 0x100000 # 1MB (Fim da ROM original)

def compile_rom():
    if not os.path.exists(ROM_INPUT):
        print(f"Erro: ROM original não encontrada em '{ROM_INPUT}'")
        return
        
    if not os.path.exists(JSON_INPUT):
        print(f"Erro: Arquivo JSON de tradução não encontrado em '{JSON_INPUT}'")
        return

    # 1. Carregar ROM original e expandir
    with open(ROM_INPUT, "rb") as f:
        original_data = f.read()
        
    rom_data = bytearray(EXPANDED_SIZE)
    rom_data[0:len(original_data)] = original_data
    # Preencher a área expandida restante com 0xFF
    for i in range(len(original_data), EXPANDED_SIZE):
        rom_data[i] = 0xFF

    print(f"ROM carregada e expandida para {EXPANDED_SIZE} bytes.")

    # 2. Carregar JSON de tradução
    with open(JSON_INPUT, "r", encoding="utf-8") as f:
        translation_blocks = json.load(f)

    # 3. Gravar strings traduzidas e atualizar ponteiros
    current_write_offset = START_EXPANDED_OFFSET
    updated_pointers_count = 0
    total_strings_written = 0

    print("Escrevendo textos traduzidos e atualizando referências...")

    for block in translation_blocks:
        for item in block["items"]:
            text_bytes = item["portuguese"].encode("latin1", errors="replace")
            terminator_byte = item["terminator"]

            new_offset = current_write_offset
            
            # Escrever a string traduzida no espaço expandido
            rom_data[new_offset : new_offset + len(text_bytes)] = text_bytes
            rom_data[new_offset + len(text_bytes)] = terminator_byte
            
            # Avançar o cursor de escrita (garantindo alinhamento par)
            current_write_offset += len(text_bytes) + 1
            if current_write_offset % 2 != 0:
                rom_data[current_write_offset] = 0xFF
                current_write_offset += 1
                
            total_strings_written += 1

            # Atualizar todas as referências apontadas para esta string
            new_offset_bytes = new_offset.to_bytes(4, "big")
            for ref_hex in item["references"]:
                ref_offset = int(ref_hex, 16)
                rom_data[ref_offset : ref_offset + 4] = new_offset_bytes
                updated_pointers_count += 1

    print(f"Total de strings gravadas na área expandida: {total_strings_written}")
    print(f"Total de ponteiros/referências atualizados na ROM: {updated_pointers_count}")
    print(f"Dados escritos de 0x{START_EXPANDED_OFFSET:06X} até 0x{current_write_offset:06X}")

    # 4. Corrigir o cabeçalho da ROM (checksum apenas nos primeiros 1MB)
    # A) IMPORTANTE (confirmado empiricamente no BlastEm): NÃO alterar o fim da ROM no
    # cabeçalho (offset 0x1A4 - 0x1A7). Testado: com o cabeçalho declarando 2MB + checksum
    # recalculado sobre o arquivo inteiro, o BlastEm dá tela preta. Com o cabeçalho mantido
    # em 0x000FFFFF (1MB) e checksum só sobre o 1MB original, o boot funciona normalmente
    # (mesmo com o arquivo físico tendo 2MB e os ponteiros apontando pra segunda metade).
    rom_end_in_header = int.from_bytes(rom_data[0x1A4 : 0x1A8], "big")
    print(f"Fim da ROM mantido no cabeçalho: 0x{rom_end_in_header:08X}")

    # B) Calcular e atualizar o Checksum apenas para os primeiros 1MB
    calculated_checksum = 0
    for i in range(0x200, len(original_data), 2):
        val = int.from_bytes(rom_data[i : i+2], "big")
        calculated_checksum = (calculated_checksum + val) & 0xFFFF

    rom_data[0x18E : 0x190] = calculated_checksum.to_bytes(2, "big")
    print(f"Checksum recalculado (primeiros 1MB) e gravado: 0x{calculated_checksum:04X}")

    # C) Neutralizar a rotina de checksum proprietária da EA (proteção anti-cópia à parte
    # do checksum padrão da Sega). Em 0x0FFFB0-0x0FFFFE o jogo soma os primeiros ~1MB da
    # ROM (pulando o campo do checksum da Sega) e compara com a constante fixa 0xEE496DD1;
    # se não bater, salta para uma rotina que limpa a paleta (tela preta) e trava num loop
    # infinito. Qualquer edição de texto muda essa soma, então a verificação sempre falha.
    # Corrige-se trocando o BNE.b em 0x0FFFD0 (bytes 66 02) por um NOP (4E 71), fazendo a
    # execução sempre cair no RTS logo depois, independente do resultado do checksum.
    if rom_data[0xFFFD0:0xFFFD2] == b"\x66\x02":
        rom_data[0xFFFD0:0xFFFD2] = b"\x4E\x71"
        print("Rotina de checksum da EA neutralizada (BNE em 0x0FFFD0 -> NOP).")
    else:
        print("AVISO: padrão de bytes esperado da rotina de checksum da EA não encontrado em 0x0FFFD0 - pulei o patch.")

    # 5. Salvar a nova ROM compilada
    with open(ROM_OUTPUT, "wb") as f:
        f.write(rom_data)
        
    print(f"Nova ROM traduzida salva com sucesso em '{ROM_OUTPUT}'!")

if __name__ == "__main__":
    compile_rom()
