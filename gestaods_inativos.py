#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pacientes Inativos - GestaoDS

Aplicativo de desktop para gerar a planilha de pacientes que nao consultam ha X dias,
usando a API v2 do GestaoDS.

Rodar direto:  python gestaods_inativos.py
Gerar o .exe:  veja build.bat (precisa ser executado no Windows)
"""

import csv
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NOME = "Pacientes Inativos - GestaoDS"
APP_VERSAO = "1.0"

API_BASE = "https://devapi.gestaods.com.br"
ROTA_MEDICOS = "/api/v2/core/medicos/"
ROTA_INATIVOS = "/api/v2/paciente/ultima-atividade-pacientes/"

# A API aceita 100 requisicoes por minuto por IP em cada rota.
# 0,75s entre paginas = ~80/min, com folga.
PAUSA_ENTRE_PAGINAS = 0.75

CABECALHO_CSV = [
    "Nome completo",
    "Telefone de contato",
    "Tempo da ultima consulta",
    "Data da ultima consulta",
    "E-mail",
]

# (rotulo, dias_minimo, dias_maximo)  ->  dias_maximo None = sem limite
PERIODOS = [
    ("6 meses ou mais (180+ dias)", 180, None),
    ("1 ano ou mais (365+ dias)", 365, None),
    ("Entre 1 e 2 anos (365 a 729 dias)", 365, 729),
    ("2 anos ou mais (730+ dias)", 730, None),
    ("Entre 2 e 3 anos (730 a 1094 dias)", 730, 1094),
    ("3 anos ou mais (1095+ dias)", 1095, None),
    ("Personalizado", None, None),
]


# ---------------------------------------------------------------- configuracao


def caminho_config():
    """Guarda as preferencias no perfil do usuario (%APPDATA% no Windows)."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    pasta = os.path.join(base, "GestaoDS-PacientesInativos")
    try:
        os.makedirs(pasta, exist_ok=True)
        return os.path.join(pasta, "config.json")
    except OSError:
        return os.path.join(os.path.expanduser("~"), ".gestaods_inativos.json")


def carregar_config():
    try:
        with open(caminho_config(), "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def salvar_config(dados):
    try:
        with open(caminho_config(), "w", encoding="utf-8") as arquivo:
            json.dump(dados, arquivo, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ------------------------------------------------------------------------ API


class ErroApi(Exception):
    pass


def _requisicao(rota, token, corpo=None, timeout=30):
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    pedido = urllib.request.Request(
        API_BASE + rota,
        data=dados,
        method="POST" if dados is not None else "GET",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
        return json.loads(resposta.read().decode("utf-8"))


def requisicao(rota, token, corpo=None, tentativas=4):
    """Chama a API com retry para falhas temporarias (429, rede, timeout)."""
    ultimo_erro = None
    for tentativa in range(tentativas):
        try:
            return _requisicao(rota, token, corpo)
        except urllib.error.HTTPError as erro:
            if erro.code == 401:
                raise ErroApi(
                    "Chave de API invalida ou revogada.\n"
                    "Confira a chave e tente novamente."
                )
            if erro.code == 429:
                ultimo_erro = ErroApi("Limite de requisicoes da API atingido.")
                time.sleep(5 + tentativa * 5)
                continue
            detalhe = ""
            try:
                detalhe = erro.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            raise ErroApi("Erro HTTP {} na API.\n{}".format(erro.code, detalhe))
        except urllib.error.URLError as erro:
            ultimo_erro = ErroApi("Falha de conexao com a API: {}".format(erro.reason))
            time.sleep(3)
        except ValueError as erro:
            ultimo_erro = ErroApi("Resposta invalida da API: {}".format(erro))
            time.sleep(3)
        except OSError as erro:
            ultimo_erro = ErroApi("Falha de rede: {}".format(erro))
            time.sleep(3)
    raise ultimo_erro or ErroApi("Nao foi possivel falar com a API.")


def listar_medicos(token):
    resposta = requisicao(ROTA_MEDICOS, token)
    medicos = []
    for item in resposta.get("data") or []:
        if not item.get("id"):
            continue
        medicos.append(
            {
                "id": item["id"],
                "nome": (item.get("nome") or "").strip(),
                "especialidade": (item.get("especialidade") or "").strip(),
            }
        )
    medicos.sort(key=lambda m: m["nome"].lower())
    return medicos


def buscar_inativos(token, dias_min, medicos_ids, tipo_filtro, progresso, cancelar):
    """Percorre todas as paginas do relatorio de ultima atividade."""

    def corpo(pagina):
        dados = {"page": pagina, "dias": dias_min, "tipo_filtro": tipo_filtro}
        if medicos_ids:
            dados["filtros"] = {"medicos": list(medicos_ids)}
        return dados

    primeira = requisicao(ROTA_INATIVOS, token, corpo(1))
    total_paginas = int(primeira.get("total_pages") or 1)
    total_registros = int(primeira.get("count") or 0)
    linhas = list(primeira.get("data") or [])
    progresso(1, total_paginas, total_registros)

    for pagina in range(2, total_paginas + 1):
        if cancelar.is_set():
            break
        time.sleep(PAUSA_ENTRE_PAGINAS)
        resposta = requisicao(ROTA_INATIVOS, token, corpo(pagina))
        linhas.extend(resposta.get("data") or [])
        progresso(pagina, total_paginas, total_registros)

    return linhas


# ---------------------------------------------------------------------- dados


def formatar_telefone(celular):
    if not celular:
        return ""
    digitos = "".join(c for c in str(celular) if c.isdigit())
    if len(digitos) >= 12 and digitos.startswith("55"):
        ddd, numero = digitos[2:4], digitos[4:]
        if len(numero) == 9:
            return "+55 ({}) {}-{}".format(ddd, numero[:5], numero[5:])
        if len(numero) == 8:
            return "+55 ({}) {}-{}".format(ddd, numero[:4], numero[4:])
    return str(celular)


def filtrar_e_ordenar(linhas, dias_min, dias_max):
    """A API so aceita o minimo de dias; o maximo e aplicado aqui."""
    resultado = []
    for linha in linhas:
        dias = linha.get("tempo_em_dias")
        if dias is None:
            continue
        dias = int(dias)
        if dias < dias_min:
            continue
        if dias_max is not None and dias > dias_max:
            continue
        resultado.append(linha)
    resultado.sort(key=lambda l: int(l.get("tempo_em_dias") or 0), reverse=True)
    return resultado


def gravar_csv(linhas, caminho):
    # utf-8-sig + separador ';' faz o Excel em portugues abrir com acentos e
    # colunas corretas em um duplo-clique.
    with open(caminho, "w", newline="", encoding="utf-8-sig") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(CABECALHO_CSV)
        for linha in linhas:
            dias = int(linha.get("tempo_em_dias") or 0)
            tempo = "{} dias (~{:.1f} anos)".format(dias, dias / 365).replace(".", ",")
            escritor.writerow(
                [
                    (linha.get("nome_paciente") or "").strip(),
                    formatar_telefone(linha.get("celular")),
                    tempo,
                    linha.get("data_ultimo_atendimento") or "",
                    linha.get("email") or "",
                ]
            )


def abrir_no_explorador(caminho):
    try:
        if sys.platform.startswith("win"):
            os.startfile(caminho)  # so existe no Windows
        elif sys.platform == "darwin":
            subprocess.Popen(["open", caminho])
        else:
            subprocess.Popen(["xdg-open", caminho])
    except Exception:
        pass


# ------------------------------------------------------------------ interface


class Aplicativo(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("{} v{}".format(APP_NOME, APP_VERSAO))
        self.minsize(780, 660)

        self.config_salva = carregar_config()
        self.medicos = []
        self.fila = queue.Queue()
        self.cancelar = threading.Event()
        self.trabalhando = False

        self._montar_interface()
        self._restaurar_config()
        self.after(100, self._consumir_fila)

    # ------------------------------------------------------------ construcao

    def _montar_interface(self):
        raiz = ttk.Frame(self, padding=12)
        raiz.pack(fill="both", expand=True)
        raiz.columnconfigure(0, weight=1)

        # 1. chave de API
        caixa_chave = ttk.LabelFrame(raiz, text="1. Chave de API", padding=10)
        caixa_chave.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        caixa_chave.columnconfigure(0, weight=1)

        self.var_chave = tk.StringVar()
        self.campo_chave = ttk.Entry(caixa_chave, textvariable=self.var_chave, show="*")
        self.campo_chave.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.var_mostrar_chave = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            caixa_chave,
            text="Mostrar",
            variable=self.var_mostrar_chave,
            command=self._alternar_chave,
        ).grid(row=0, column=1, padx=(0, 6))

        self.botao_medicos = ttk.Button(
            caixa_chave, text="Carregar medicos", command=self._carregar_medicos
        )
        self.botao_medicos.grid(row=0, column=2)

        self.var_lembrar = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            caixa_chave,
            text="Lembrar a chave neste computador",
            variable=self.var_lembrar,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # 2. medicos
        caixa_medicos = ttk.LabelFrame(raiz, text="2. Medicos", padding=10)
        caixa_medicos.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        caixa_medicos.columnconfigure(0, weight=1)
        caixa_medicos.rowconfigure(1, weight=1)
        raiz.rowconfigure(1, weight=1)

        self.rotulo_medicos = ttk.Label(
            caixa_medicos, text="Informe a chave e clique em 'Carregar medicos'."
        )
        self.rotulo_medicos.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        moldura_lista = ttk.Frame(caixa_medicos)
        moldura_lista.grid(row=1, column=0, sticky="nsew")
        moldura_lista.columnconfigure(0, weight=1)
        moldura_lista.rowconfigure(0, weight=1)

        self.lista_medicos = tk.Listbox(
            moldura_lista, selectmode="extended", height=8, exportselection=False
        )
        self.lista_medicos.grid(row=0, column=0, sticky="nsew")
        barra = ttk.Scrollbar(
            moldura_lista, orient="vertical", command=self.lista_medicos.yview
        )
        barra.grid(row=0, column=1, sticky="ns")
        self.lista_medicos.configure(yscrollcommand=barra.set)

        botoes_medicos = ttk.Frame(caixa_medicos)
        botoes_medicos.grid(row=1, column=1, sticky="n", padx=(8, 0))
        ttk.Button(
            botoes_medicos, text="Selecionar todos", command=self._selecionar_todos
        ).pack(fill="x", pady=(0, 4))
        ttk.Button(
            botoes_medicos, text="Limpar selecao", command=self._limpar_selecao
        ).pack(fill="x")
        ttk.Label(
            botoes_medicos,
            text="Sem selecao =\ntodos os medicos",
            justify="left",
            foreground="#555555",
        ).pack(pady=(8, 0))

        # 3. periodo
        caixa_periodo = ttk.LabelFrame(raiz, text="3. Periodo sem consultar", padding=10)
        caixa_periodo.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        ttk.Label(caixa_periodo, text="Faixa:").grid(row=0, column=0, sticky="w")
        self.var_periodo = tk.StringVar(value=PERIODOS[1][0])
        self.combo_periodo = ttk.Combobox(
            caixa_periodo,
            textvariable=self.var_periodo,
            values=[p[0] for p in PERIODOS],
            state="readonly",
            width=32,
        )
        self.combo_periodo.grid(row=0, column=1, sticky="w", padx=(6, 16))
        self.combo_periodo.bind("<<ComboboxSelected>>", self._aplicar_periodo)

        ttk.Label(caixa_periodo, text="De (dias):").grid(row=0, column=2, sticky="w")
        self.var_dias_min = tk.StringVar(value="365")
        self.campo_dias_min = ttk.Spinbox(
            caixa_periodo, from_=0, to=20000, textvariable=self.var_dias_min, width=8
        )
        self.campo_dias_min.grid(row=0, column=3, padx=(6, 16))

        ttk.Label(caixa_periodo, text="Ate (dias):").grid(row=0, column=4, sticky="w")
        self.var_dias_max = tk.StringVar(value="")
        self.campo_dias_max = ttk.Spinbox(
            caixa_periodo, from_=0, to=20000, textvariable=self.var_dias_max, width=8
        )
        self.campo_dias_max.grid(row=0, column=5, padx=(6, 0))

        ttk.Label(
            caixa_periodo,
            text="365 dias = 1 ano. Deixe 'Ate' vazio para nao ter limite maximo.",
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=6, sticky="w", pady=(6, 6))

        ttk.Label(caixa_periodo, text="Considerar:").grid(row=2, column=0, sticky="w")
        self.var_tipo = tk.StringVar(value="atendimento")
        ttk.Radiobutton(
            caixa_periodo,
            text="Ultimo atendimento",
            variable=self.var_tipo,
            value="atendimento",
        ).grid(row=2, column=1, sticky="w")
        ttk.Radiobutton(
            caixa_periodo,
            text="Ultimo agendamento",
            variable=self.var_tipo,
            value="agendamento",
        ).grid(row=2, column=2, columnspan=2, sticky="w")

        self._aplicar_periodo()

        # 4. pasta de destino
        caixa_saida = ttk.LabelFrame(raiz, text="4. Pasta de destino", padding=10)
        caixa_saida.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        caixa_saida.columnconfigure(0, weight=1)

        self.var_pasta = tk.StringVar(value=os.path.expanduser("~"))
        ttk.Entry(caixa_saida, textvariable=self.var_pasta).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(caixa_saida, text="Escolher...", command=self._escolher_pasta).grid(
            row=0, column=1
        )

        # 5. execucao
        caixa_acao = ttk.Frame(raiz)
        caixa_acao.grid(row=4, column=0, sticky="ew")
        caixa_acao.columnconfigure(1, weight=1)

        self.botao_gerar = ttk.Button(
            caixa_acao, text="Gerar planilha", command=self._gerar
        )
        self.botao_gerar.grid(row=0, column=0, padx=(0, 8))

        self.barra_progresso = ttk.Progressbar(caixa_acao, mode="determinate")
        self.barra_progresso.grid(row=0, column=1, sticky="ew")

        self.botao_cancelar = ttk.Button(
            caixa_acao, text="Cancelar", command=self._cancelar, state="disabled"
        )
        self.botao_cancelar.grid(row=0, column=2, padx=(8, 0))

        self.registro = tk.Text(raiz, height=9, wrap="word", state="disabled")
        self.registro.grid(row=5, column=0, sticky="nsew", pady=(10, 0))
        raiz.rowconfigure(5, weight=1)

        self._log("{} v{} pronto.".format(APP_NOME, APP_VERSAO))

    def _restaurar_config(self):
        chave = self.config_salva.get("chave_api") or ""
        if chave:
            self.var_chave.set(chave)
        pasta = self.config_salva.get("pasta_saida")
        if pasta and os.path.isdir(pasta):
            self.var_pasta.set(pasta)
        periodo = self.config_salva.get("periodo")
        if periodo in [p[0] for p in PERIODOS]:
            self.var_periodo.set(periodo)
            self._aplicar_periodo()

    # ------------------------------------------------------------ auxiliares

    def _log(self, texto):
        marca = datetime.now().strftime("%H:%M:%S")
        self.registro.configure(state="normal")
        self.registro.insert("end", "[{}] {}\n".format(marca, texto))
        self.registro.see("end")
        self.registro.configure(state="disabled")

    def _alternar_chave(self):
        self.campo_chave.configure(show="" if self.var_mostrar_chave.get() else "*")

    def _aplicar_periodo(self, _evento=None):
        rotulo = self.var_periodo.get()
        for nome, minimo, maximo in PERIODOS:
            if nome != rotulo:
                continue
            personalizado = minimo is None and maximo is None
            if not personalizado:
                self.var_dias_min.set(str(minimo))
                self.var_dias_max.set("" if maximo is None else str(maximo))
            estado = "normal" if personalizado else "readonly"
            self.campo_dias_min.configure(state=estado)
            self.campo_dias_max.configure(state=estado)
            return

    def _selecionar_todos(self):
        self.lista_medicos.select_set(0, "end")

    def _limpar_selecao(self):
        self.lista_medicos.selection_clear(0, "end")

    def _escolher_pasta(self):
        pasta = filedialog.askdirectory(
            title="Escolha a pasta de destino", initialdir=self.var_pasta.get()
        )
        if pasta:
            self.var_pasta.set(pasta)

    def _travar_interface(self, travado):
        self.trabalhando = travado
        estado = "disabled" if travado else "normal"
        self.botao_gerar.configure(state=estado)
        self.botao_medicos.configure(state=estado)
        self.botao_cancelar.configure(state="normal" if travado else "disabled")

    def _persistir_config(self):
        dados = dict(self.config_salva)
        dados["pasta_saida"] = self.var_pasta.get()
        dados["periodo"] = self.var_periodo.get()
        if self.var_lembrar.get():
            dados["chave_api"] = self.var_chave.get().strip()
        else:
            dados.pop("chave_api", None)
        self.config_salva = dados
        salvar_config(dados)

    def _validar_chave(self):
        chave = self.var_chave.get().strip()
        if not chave:
            messagebox.showwarning(APP_NOME, "Informe a chave de API.")
            return None
        return chave

    # ----------------------------------------------------------------- acoes

    def _carregar_medicos(self):
        chave = self._validar_chave()
        if not chave or self.trabalhando:
            return
        self._travar_interface(True)
        self.botao_cancelar.configure(state="disabled")
        self._log("Carregando medicos...")

        def tarefa():
            try:
                self.fila.put(("medicos", listar_medicos(chave)))
            except ErroApi as erro:
                self.fila.put(("erro", str(erro)))
            except Exception as erro:
                self.fila.put(("erro", "Falha inesperada: {}".format(erro)))

        threading.Thread(target=tarefa, daemon=True).start()

    def _gerar(self):
        chave = self._validar_chave()
        if not chave or self.trabalhando:
            return

        try:
            dias_min = int(self.var_dias_min.get())
        except ValueError:
            messagebox.showwarning(APP_NOME, "'De (dias)' precisa ser um numero.")
            return

        texto_max = self.var_dias_max.get().strip()
        dias_max = None
        if texto_max:
            try:
                dias_max = int(texto_max)
            except ValueError:
                messagebox.showwarning(APP_NOME, "'Ate (dias)' precisa ser um numero.")
                return
            if dias_max < dias_min:
                messagebox.showwarning(
                    APP_NOME, "'Ate (dias)' precisa ser maior ou igual a 'De (dias)'."
                )
                return

        pasta = self.var_pasta.get().strip()
        if not os.path.isdir(pasta):
            messagebox.showwarning(APP_NOME, "Escolha uma pasta de destino valida.")
            return

        if self.medicos:
            indices = self.lista_medicos.curselection()
            selecionados = [self.medicos[i]["id"] for i in indices]
            if not selecionados:
                selecionados = [m["id"] for m in self.medicos]
                self._log("Nenhum medico marcado - usando todos.")
        else:
            selecionados = []
            self._log("Lista de medicos nao carregada - buscando todos.")

        self._persistir_config()
        self.cancelar.clear()
        self._travar_interface(True)
        self.barra_progresso.configure(value=0, maximum=100)
        self._log(
            "Buscando pacientes sem {} ha {}+ dias{}...".format(
                self.var_tipo.get(),
                dias_min,
                "" if dias_max is None else " (ate {} dias)".format(dias_max),
            )
        )

        tipo = self.var_tipo.get()

        def tarefa():
            try:

                def progresso(pagina, total, registros):
                    self.fila.put(("progresso", pagina, total, registros))

                linhas = buscar_inativos(
                    chave, dias_min, selecionados, tipo, progresso, self.cancelar
                )
                if self.cancelar.is_set():
                    self.fila.put(("cancelado", None))
                    return

                filtradas = filtrar_e_ordenar(linhas, dias_min, dias_max)
                if not filtradas:
                    self.fila.put(("vazio", None))
                    return

                nome = "pacientes_inativos_{}.csv".format(
                    datetime.now().strftime("%Y-%m-%d_%H%M")
                )
                caminho = os.path.join(pasta, nome)
                gravar_csv(filtradas, caminho)
                self.fila.put(("fim", caminho, len(filtradas)))
            except ErroApi as erro:
                self.fila.put(("erro", str(erro)))
            except OSError as erro:
                self.fila.put(
                    ("erro", "Nao foi possivel gravar o arquivo: {}".format(erro))
                )
            except Exception as erro:
                self.fila.put(("erro", "Falha inesperada: {}".format(erro)))

        threading.Thread(target=tarefa, daemon=True).start()

    def _cancelar(self):
        if self.trabalhando:
            self.cancelar.set()
            self._log("Cancelando apos a pagina atual...")

    # ------------------------------------------------------------------ fila

    def _consumir_fila(self):
        try:
            while True:
                mensagem = self.fila.get_nowait()
                tipo = mensagem[0]

                if tipo == "medicos":
                    self._receber_medicos(mensagem[1])
                elif tipo == "progresso":
                    _, pagina, total, registros = mensagem
                    self.barra_progresso.configure(value=pagina, maximum=max(total, 1))
                    self._log(
                        "Pagina {}/{} ({} registros no total)".format(
                            pagina, total, registros
                        )
                    )
                elif tipo == "fim":
                    _, caminho, quantidade = mensagem
                    self._travar_interface(False)
                    self.barra_progresso.configure(
                        value=self.barra_progresso["maximum"]
                    )
                    self._log("Pronto: {} pacientes em {}".format(quantidade, caminho))
                    if messagebox.askyesno(
                        APP_NOME,
                        "Planilha gerada com {} pacientes:\n\n{}\n\nAbrir a pasta?".format(
                            quantidade, caminho
                        ),
                    ):
                        abrir_no_explorador(os.path.dirname(caminho))
                elif tipo == "vazio":
                    self._travar_interface(False)
                    self._log("Nenhum paciente encontrado para esse filtro.")
                    messagebox.showinfo(
                        APP_NOME, "Nenhum paciente encontrado para esse filtro."
                    )
                elif tipo == "cancelado":
                    self._travar_interface(False)
                    self.barra_progresso.configure(value=0)
                    self._log("Busca cancelada. Nenhum arquivo foi gerado.")
                elif tipo == "erro":
                    self._travar_interface(False)
                    self.barra_progresso.configure(value=0)
                    self._log("ERRO: {}".format(mensagem[1]))
                    messagebox.showerror(APP_NOME, mensagem[1])
        except queue.Empty:
            pass
        self.after(100, self._consumir_fila)

    def _receber_medicos(self, medicos):
        self._travar_interface(False)
        self.medicos = medicos
        self.lista_medicos.delete(0, "end")
        for medico in medicos:
            rotulo = medico["nome"]
            if medico["especialidade"]:
                rotulo += "  -  {}".format(medico["especialidade"])
            self.lista_medicos.insert("end", rotulo)
        self.rotulo_medicos.configure(
            text="{} medicos nesta chave. Selecione um ou mais "
            "(sem selecao = todos).".format(len(medicos))
        )
        self._log("{} medicos carregados.".format(len(medicos)))
        self._persistir_config()


def main():
    Aplicativo().mainloop()


if __name__ == "__main__":
    main()
