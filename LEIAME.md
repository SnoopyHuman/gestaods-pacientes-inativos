# Pacientes Inativos — GestãoDS

Aplicativo de desktop que gera uma planilha com os pacientes que **não consultam há X tempo**,
puxando os dados direto da API v2 do GestãoDS.

Você informa a chave de API, escolhe os médicos, o período e a pasta de destino — o app
faz o resto e salva um CSV pronto para abrir no Excel.

---

## Como gerar o executável (.exe)

O `.exe` precisa ser gerado **em um computador com Windows** (é uma limitação do
PyInstaller: ele não compila para Windows a partir de Mac ou Linux). Só precisa ser feito
uma vez — depois o `.exe` roda em qualquer PC com Windows, sem instalar nada.

1. No PC com Windows, instale o Python 3: <https://www.python.org/downloads/>
   **Importante:** na primeira tela do instalador, marque a caixa **"Add Python to PATH"**.
2. Copie esta pasta inteira (`gestaods-inativos`) para o PC.
3. Dê **duplo-clique em `build.bat`**.
4. Ao terminar, o executável estará em `dist\Pacientes Inativos GestaoDS.exe`.

Esse `.exe` é autossuficiente — pode ser copiado para outros computadores Windows e
executado direto, sem Python instalado.

### Alternativa: gerar pelo GitHub Actions

Se preferir não usar uma máquina Windows, dá para subir esta pasta para um repositório no
GitHub e deixar o GitHub gerar o `.exe` automaticamente (em um runner Windows). Peça e eu
monto o workflow.

---

## Como usar o aplicativo

**1. Chave de API**
Cole a chave (token de agenda do GestãoDS). Marque *"Lembrar a chave neste computador"*
para não precisar digitar de novo. Depois clique em **Carregar médicos**.

**2. Médicos**
A lista mostra os médicos vinculados àquela chave. Selecione um ou vários
(use Ctrl+clique ou Shift+clique). **Sem nenhum selecionado = todos os médicos.**

**3. Período sem consultar**
Escolha uma faixa pronta (1 ano ou mais, entre 1 e 2 anos, 2 anos ou mais…) ou selecione
**Personalizado** e digite os dias à mão. Referência: 365 dias = 1 ano. Deixar o campo
*"Até (dias)"* vazio significa "sem limite máximo".

Também dá para escolher se o corte é pelo **último atendimento** (padrão) ou pelo
**último agendamento**.

**4. Pasta de destino**
Escolha onde salvar. O arquivo sai com o nome `pacientes_inativos_AAAA-MM-DD_HHMM.csv`.

**5. Gerar planilha**
A barra mostra o progresso página a página. Buscas grandes levam alguns minutos — a API do
GestãoDS limita a 100 requisições por minuto, e o app respeita esse limite automaticamente
(cerca de 100 pacientes a cada segundo e meio). Dá para interromper a qualquer momento com
**Cancelar**.

---

## O arquivo gerado

CSV com separador `;` e codificação UTF-8 com BOM — abre corretamente no Excel em português
com um duplo-clique, sem passos de importação.

| Nome completo | Telefone de contato | Tempo da ultima consulta | Data da ultima consulta | E-mail |
|---|---|---|---|---|
| Fulano de Tal | +55 (51) 99999-9999 | 400 dias (~1,1 anos) | 01/07/2025 | fulano@exemplo.com |

Os pacientes vêm ordenados do mais antigo para o mais recente (quem está sem consultar há
mais tempo aparece primeiro).

---

## Observações

- **A chave de API fica salva em texto puro** em
  `%APPDATA%\GestaoDS-PacientesInativos\config.json`, junto com a última pasta e o último
  período usados. Se o computador for compartilhado, desmarque
  *"Lembrar a chave neste computador"*.
- **Os dados são de produção** (pacientes reais). Trate o CSV gerado como informação
  sensível de saúde.
- O app só **lê** dados da API — não altera, cadastra nem apaga nada no GestãoDS.
- Rodar sem gerar o `.exe`: com Python instalado, `python gestaods_inativos.py` (funciona
  também em Mac e Linux; usa apenas a biblioteca padrão, sem dependências externas).
