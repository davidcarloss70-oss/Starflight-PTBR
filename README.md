# Starflight PT-BR

Tradução para o português brasileiro (PT-BR) do clássico jogo **Starflight** (Sega Mega Drive / Genesis).

Este repositório contém as ferramentas de tradução, o arquivo de texto já traduzido, e um aplicativo com interface gráfica (**StarflightTradutor.exe**) que permite revisar, editar e recompilar a tradução sem precisar mexer em código.

> [!IMPORTANT]
> **Este repositório NÃO contém a ROM do jogo.** Por questões legais, nem a ROM original nem a traduzida são distribuídas aqui. Você precisa fornecer sua própria cópia legalmente obtida do Starflight (Mega Drive) — veja a seção [Como Usar](#-como-usar) abaixo.

---

## 🚀 Como Usar

1. Baixe **todo o conteúdo** deste repositório.
2. Substitua o arquivo `starflight_original.bin` (que está vazio, como placeholder) pela sua própria cópia legal da ROM do Starflight — **mantendo exatamente esse nome de arquivo**.
3. Execute **`StarflightTradutor.exe`**.
4. Clique em **"Compilar ROM"**. Isso vai gerar o arquivo `starflight_translated.bin` já com a tradução aplicada, pronto pra abrir em qualquer emulador de Mega Drive (BlastEm, RetroArch/Genesis Plus GX, Kega Fusion, etc.).

Não precisa de Python instalado — o `.exe` é standalone.

---

## 🛠️ Ferramenta de Edição

O **StarflightTradutor.exe** também é um editor completo dos textos:

- **Busca e filtro**: encontre qualquer texto por palavra (inglês ou português), ou filtre por "Não traduzidos" / "Revisar (risco)".
- **Itens em amarelo**: o programa sinaliza textos que provavelmente são nomes próprios ou dados binários/gráficos capturados por engano — normalmente não devem ser traduzidos.
- **Editar**: selecione um item, edite a coluna em português, e clique em "Aplicar alteração a este item".
- **Salvar tudo (JSON)**: grava suas edições em `texts_to_translate.json`.
- **Compilar ROM**: gera a ROM traduzida com todas as mudanças aplicadas.

Se quiser mexer no código-fonte, `translator_gui.py` é o programa completo em Python (Tkinter, sem dependências externas).

---

## 📝 Sobre o Processo de Tradução

A tradução foi um processo de engenharia reversa completo, feito com bastante auxílio de IA (Claude, Anthropic). Resumo:

* Extração automática de ~1085 blocos de texto da ROM original, mapeando os ponteiros de memória que referenciam cada um (`extractor.py`).
* Tradução automatizada em massa via API do Google Tradutor, com limpeza de acentos/maiúsculas para respeitar a fonte original do jogo (`auto_translate.py`).
* Recompilação da ROM expandindo-a de 1MB para 2MB, reescrevendo todos os ponteiros afetados (`compiler.py`).
* **O maior desafio técnico**: qualquer alteração de byte na ROM travava o jogo em tela preta. Engenharia reversa do código 68k revelou uma rotina de checksum proprietária da Electronic Arts (proteção anti-cópia da época), que precisou ser localizada e neutralizada por patch binário para a tradução funcionar.

Detalhes técnicos completos, incluindo todas as limitações conhecidas, estão em **[`COMO_FUNCIONA_E_LIMITACOES.txt`](COMO_FUNCIONA_E_LIMITACOES.txt)**.

---

## ⚠️ Limitações Conhecidas (resumo)

- Sem acentos/cedilha — a fonte original do jogo não tem esses caracteres, e a edição dos tiles da fonte ainda não foi feita.
- Alguns nomes próprios (criaturas, tripulação, raças alienígenas) foram deixados como sinalização de revisão — podem ser ajustados via o editor.
- Algumas telas de UI específicas (ex: tela de digitar o nome do capitão) usam um mecanismo de referência que a extração automática não capturou, e continuam em inglês.
- Testado no emulador BlastEm — comportamento em hardware real ou outros emuladores não foi verificado.

Lista completa em [`COMO_FUNCIONA_E_LIMITACOES.txt`](COMO_FUNCIONA_E_LIMITACOES.txt).

---

## 🏆 Créditos

* **Tradução e Engenharia Reversa:** [davidcarloss70-oss](https://github.com/davidcarloss70-oss), com Claude (Anthropic)

Boa viagem, capitão!
