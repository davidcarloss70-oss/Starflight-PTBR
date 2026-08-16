import os
import json
import re
import requests
import urllib.parse
import time
import unicodedata

JSON_PATH = "texts_to_translate.json"
BATCH_SIZE = 40

def remove_accents(input_str):
    # Decompor caracteres acentuados em caractere base + acento combinado
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    # Filtrar apenas os caracteres que não sejam marcas de acentuação
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

def clean_text(text):
    if not text:
        return ""
    # Remover acentos
    text = remove_accents(text)
    # Converter para maiúsculas
    text = text.upper()
    # Substituir qualquer caractere Ç residual por C (caso o normalizer não pegue)
    text = text.replace('Ç', 'C')
    # Remover caracteres não-ASCII imprimíveis remanescentes para evitar travar a ROM
    text = "".join(c if 32 <= ord(c) <= 126 else "?" for c in text)
    return text

def translate_batch(texts_list, target_lang='pt'):
    if not texts_list:
        return []
        
    combined_text = "\n".join(texts_list)
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl={target_lang}&dt=t"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        # Usar POST para evitar limites de tamanho de URL
        response = requests.post(url, data={"q": combined_text}, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            # O Google retorna uma lista de fragmentos
            parts = [part[0] for part in data[0] if part[0] is not None]
            translated_combined = "".join(parts)
            
            # Dividir de volta em linhas
            translated_list = translated_combined.split("\n")
            
            # Garantir que o número de itens corresponde para evitar desalinhamento
            if len(translated_list) == len(texts_list):
                return translated_list
            else:
                # Se houver divergência, traduzir um por um neste lote como fallback
                print(f"Divergência no lote (Enviados: {len(texts_list)}, Recebidos: {len(translated_list)}). Traduzindo individualmente...")
                fallback_list = []
                for t in texts_list:
                    fallback_list.append(translate_single(t, target_lang))
                    time.sleep(0.1) # Evitar rate limit
                return fallback_list
        else:
            print(f"Erro HTTP {response.status_code} no lote. Tentando individualmente...")
            fallback_list = []
            for t in texts_list:
                fallback_list.append(translate_single(t, target_lang))
                time.sleep(0.1)
            return fallback_list
    except Exception as e:
        print(f"Erro ao traduzir lote: {e}. Tentando individualmente...")
        fallback_list = []
        for t in texts_list:
            fallback_list.append(translate_single(t, target_lang))
            time.sleep(0.1)
        return fallback_list

def translate_single(text, target_lang='pt'):
    if not text.strip():
        return text
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl={target_lang}&dt=t&q={urllib.parse.quote(text)}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            parts = [part[0] for part in data[0] if part[0] is not None]
            return "".join(parts).strip()
    except Exception as e:
        print(f"Erro na tradução individual de '{text[:20]}': {e}")
    return text

def run_translation():
    if not os.path.exists(JSON_PATH):
        print(f"Erro: Arquivo '{JSON_PATH}' não encontrado!")
        return

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        blocks = json.load(f)

    print("Coletando textos para tradução...")
    
    # 1. Mapear todas as strings únicas de texto que precisam ser traduzidas
    # Separamos códigos de controle (letras minúsculas) de textos em maiúsculas
    unique_text_parts = set()
    string_cache = {} # Mapeamento de texto_original -> texto_traduzido_completo

    # Passo 1: Analisar todas as strings e quebrar em partes
    all_items = []
    for block in blocks:
        for item in block["items"]:
            english_text = item["english"]
            all_items.append(item)
            
            # Se for apenas espaços, números ou símbolos, não precisamos traduzir
            if not any(c.isalpha() for c in english_text):
                string_cache[english_text] = english_text
                continue
                
            # Separar por caracteres de controle minúsculos (ex: r, rr, a, l, etc.)
            parts = re.split(r'([a-z]+)', english_text)
            for part in parts:
                # Apenas traduzir partes que tenham letras e não sejam de controle (maiúsculas)
                if part and any(c.isalpha() for c in part) and not part.islower():
                    # Limpar espaços extras antes de adicionar ao set de tradução
                    stripped = part.strip()
                    if len(stripped) >= 2:
                        unique_text_parts.add(stripped)

    unique_list = list(unique_text_parts)
    print(f"Total de strings únicas detectadas: {len(all_items)}")
    print(f"Total de sub-segmentos de texto únicos para tradução: {len(unique_list)}")

    # 2. Traduzir sub-segmentos únicos em lotes
    translation_map = {} # Mapeamento de english_part -> portuguese_part
    
    print(f"Iniciando tradução de {len(unique_list)} itens em lotes de {BATCH_SIZE}...")
    for i in range(0, len(unique_list), BATCH_SIZE):
        batch = unique_list[i : i + BATCH_SIZE]
        print(f"Traduzindo lote {i//BATCH_SIZE + 1} de {len(unique_list)//BATCH_SIZE + 1}...")
        
        translated_batch = translate_batch(batch)
        
        for original, translated in zip(batch, translated_batch):
            if translated:
                # Limpar texto traduzido (remover acentos e converter para maiúsculas)
                cleaned = clean_text(translated)
                translation_map[original] = cleaned
            else:
                translation_map[original] = clean_text(original)
                
        # Dormir brevemente entre lotes para respeitar a API
        time.sleep(0.5)

    print("Tradução dos segmentos concluída! Montando as strings originais...")

    # 3. Reconstruir as strings com as partes traduzidas e códigos de controle preservados
    for item in all_items:
        english_text = item["english"]
        
        if english_text in string_cache:
            item["portuguese"] = string_cache[english_text]
            continue
            
        parts = re.split(r'([a-z]+)', english_text)
        reconstructed_parts = []
        
        for part in parts:
            if not part:
                continue
            
            # Se for código de controle (letras minúsculas), manter intacto
            if part.islower():
                reconstructed_parts.append(part)
            else:
                # Se for texto, buscar no dicionário de traduções
                stripped = part.strip()
                if stripped in translation_map:
                    translated_part = translation_map[stripped]
                    # Preservar os espaços originais em volta da palavra
                    leading_spaces = len(part) - len(part.lstrip())
                    trailing_spaces = len(part) - len(part.rstrip())
                    reconstructed_parts.append(" " * leading_spaces + translated_part + " " * trailing_spaces)
                else:
                    reconstructed_parts.append(clean_text(part))
                    
        translated_text = "".join(reconstructed_parts)
        item["portuguese"] = translated_text
        string_cache[english_text] = translated_text

    # Salvar o JSON atualizado
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(blocks, f, indent=2, ensure_ascii=False)

    print(f"Tradução finalizada com sucesso! Todas as strings atualizadas em '{JSON_PATH}'.")

if __name__ == "__main__":
    run_translation()
