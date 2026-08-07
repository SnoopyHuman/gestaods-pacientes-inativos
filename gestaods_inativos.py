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
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

APP_NOME = "Pacientes Inativos - GestaoDS"
APP_VERSAO = "1.1"

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


# ------------------------------------------------------------ tema "vidro"

# Paleta escura inspirada no Liquid Glass: fundo profundo, painel translucido,
# borda clara de vidro e um brilho especular no topo de cada cartao.
C_FUNDO = "#0B0D12"
C_CARTAO = "#161A23"
C_CARTAO_ALT = "#1C2130"
C_BORDA = "#2A3040"
C_BRILHO = "#3A4356"
C_CAMPO = "#0F131B"
C_TEXTO = "#F2F4F8"
C_TEXTO_2 = "#98A2B3"
C_TEXTO_3 = "#6B7484"
C_ACENTO = "#0A84FF"
C_ACENTO_CLARO = "#3D9DFF"
C_ACENTO_ESCURO = "#0060DF"
C_SUCESSO = "#30D158"
C_PERIGO = "#FF453A"

RAIO_CARTAO = 16
RAIO_BOTAO = 11


def _fonte(preferidas, tamanho, peso="normal"):
    """Escolhe a primeira fonte disponivel da lista (SF Pro, Segoe UI, ...)."""
    try:
        familias = set(tkfont.families())
    except Exception:
        familias = set()
    for nome in preferidas:
        if nome in familias:
            return (nome, tamanho, peso)
    return ("Helvetica", tamanho, peso)


_DISPLAY = [
    "SF Pro Display",
    "Segoe UI Variable Display",
    "Segoe UI Semibold",
    "Segoe UI",
    "Helvetica Neue",
]
_TEXTO = [
    "SF Pro Text",
    "Segoe UI Variable Text",
    "Segoe UI",
    "Helvetica Neue",
]
_MONO = ["SF Mono", "Cascadia Mono", "Consolas", "Menlo", "Courier New"]


def _retangulo_arredondado(tela, x1, y1, x2, y2, raio, **opcoes):
    """Retangulo de cantos arredondados desenhado como poligono suavizado."""
    pontos = [
        x1 + raio, y1,
        x2 - raio, y1,
        x2, y1,
        x2, y1 + raio,
        x2, y2 - raio,
        x2, y2,
        x2 - raio, y2,
        x1 + raio, y2,
        x1, y2,
        x1, y2 - raio,
        x1, y1 + raio,
        x1, y1,
    ]
    return tela.create_polygon(pontos, smooth=True, **opcoes)


def aplicar_aparencia_nativa(janela):
    """No Windows 11: barra de titulo escura, cantos arredondados e fundo Mica.

    Tudo protegido: se a versao do Windows nao suportar, a janela continua
    normal, sem erro.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        janela.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(janela.winfo_id())
        definir = ctypes.windll.dwmapi.DwmSetWindowAttribute

        def atributo(codigo, valor):
            try:
                dado = ctypes.c_int(valor)
                definir(hwnd, codigo, ctypes.byref(dado), ctypes.sizeof(dado))
            except Exception:
                pass

        atributo(20, 1)  # DWMWA_USE_IMMERSIVE_DARK_MODE (Win 10 20H1+)
        atributo(19, 1)  # mesmo atributo em builds antigas
        atributo(33, 2)  # DWMWA_WINDOW_CORNER_PREFERENCE = ROUND
        atributo(38, 2)  # DWMWA_SYSTEMBACKDROP_TYPE = MICA
    except Exception:
        pass


class Cartao(tk.Frame):
    """Painel de vidro: fundo arredondado, borda sutil e brilho no topo.

    O Canvas do fundo e posicionado com place(), que nao propaga tamanho ao
    pai. Assim a altura do cartao vem apenas do conteudo (corpo), e o Canvas so
    pinta atras - sem realimentar eventos de redimensionamento.

    A margem precisa ser >= RAIO_CARTAO: o corpo e um retangulo, e so fica
    invisivel dentro da area arredondada se estiver recuado das quinas.
    """

    MARGEM = 20

    def __init__(self, master, titulo=None, cor=C_CARTAO):
        super().__init__(master, bg=C_FUNDO, highlightthickness=0, bd=0)
        self._cor = cor

        self.fundo = tk.Canvas(self, bg=C_FUNDO, highlightthickness=0, bd=0)
        self.fundo.place(x=0, y=0, relwidth=1, relheight=1)

        self.corpo = tk.Frame(self, bg=cor)
        self.corpo.pack(fill="both", expand=True, padx=self.MARGEM, pady=self.MARGEM)

        if titulo:
            tk.Label(
                self.corpo,
                text=titulo.upper(),
                bg=cor,
                fg=C_TEXTO_3,
                font=_fonte(_TEXTO, 9, "bold"),
            ).pack(anchor="w", pady=(0, 12))

        self.bind("<Configure>", self._ao_redimensionar)

    def _ao_redimensionar(self, evento):
        self._desenhar(evento.width, evento.height)

    def _desenhar(self, largura, altura):
        self.fundo.delete("all")
        if largura < 8 or altura < 8:
            return
        _retangulo_arredondado(
            self.fundo,
            1,
            1,
            largura - 1,
            altura - 1,
            RAIO_CARTAO,
            fill=self._cor,
            outline=C_BORDA,
            width=1,
        )
        # brilho especular: linha clara no topo, como a quina de um vidro
        self.fundo.create_line(
            RAIO_CARTAO + 2,
            2,
            largura - RAIO_CARTAO - 2,
            2,
            fill=C_BRILHO,
        )


class Botao(tk.Canvas):
    """Botao arredondado desenhado a mao, com hover e press."""

    ALTURA = 40

    def __init__(self, master, texto, comando, tipo="primario", largura=None, fundo=C_CARTAO):
        self.tipo = tipo
        self.comando = comando
        self.texto = texto
        self._ativo = True
        self._sobre = False
        self._pressionado = False

        fonte = _fonte(_TEXTO, 11, "bold")
        if largura is None:
            medidor = tkfont.Font(family=fonte[0], size=fonte[1], weight=fonte[2])
            largura = medidor.measure(texto) + 40

        super().__init__(
            master,
            width=largura,
            height=self.ALTURA,
            bg=fundo,
            highlightthickness=0,
            bd=0,
        )
        self._fonte = fonte
        self.bind("<Enter>", self._entrar)
        self.bind("<Leave>", self._sair)
        self.bind("<Button-1>", self._pressionar)
        self.bind("<ButtonRelease-1>", self._soltar)
        self._desenhar()

    def _cores(self):
        if not self._ativo:
            return C_CARTAO_ALT, C_TEXTO_3, C_BORDA
        if self.tipo == "primario":
            fundo = C_ACENTO
            if self._pressionado:
                fundo = C_ACENTO_ESCURO
            elif self._sobre:
                fundo = C_ACENTO_CLARO
            return fundo, "#FFFFFF", fundo
        if self.tipo == "perigo":
            return (C_CARTAO_ALT if not self._sobre else "#2A1F24"), C_PERIGO, C_BORDA
        fundo = C_CARTAO_ALT if not self._sobre else "#242A3A"
        return fundo, C_TEXTO, C_BORDA

    def _desenhar(self):
        self.delete("all")
        largura = int(self["width"])
        altura = int(self["height"])
        fundo, cor_texto, borda = self._cores()
        deslocamento = 1 if self._pressionado and self._ativo else 0

        _retangulo_arredondado(
            self,
            1,
            1 + deslocamento,
            largura - 1,
            altura - 1 + deslocamento,
            RAIO_BOTAO,
            fill=fundo,
            outline=borda,
            width=1,
        )
        # brilho superior do botao primario (reflexo de vidro)
        if self.tipo == "primario" and self._ativo and not self._pressionado:
            self.create_line(
                RAIO_BOTAO + 2, 2, largura - RAIO_BOTAO - 2, 2, fill="#7FBEFF"
            )
        self.create_text(
            largura / 2,
            altura / 2 + deslocamento,
            text=self.texto,
            fill=cor_texto,
            font=self._fonte,
        )

    def _entrar(self, _e=None):
        self._sobre = True
        self.configure(cursor="hand2" if self._ativo else "")
        self._desenhar()

    def _sair(self, _e=None):
        self._sobre = False
        self._pressionado = False
        self._desenhar()

    def _pressionar(self, _e=None):
        if not self._ativo:
            return
        self._pressionado = True
        self._desenhar()

    def _soltar(self, _e=None):
        if not self._ativo:
            return
        estava = self._pressionado
        self._pressionado = False
        self._desenhar()
        if estava and self.comando:
            self.comando()

    def definir_estado(self, ativo):
        self._ativo = bool(ativo)
        self._desenhar()

    def definir_texto(self, texto):
        self.texto = texto
        self._desenhar()


class Barra(tk.Canvas):
    """Barra de progresso arredondada, no tom de acento."""

    ALTURA = 8

    def __init__(self, master, fundo=C_CARTAO):
        super().__init__(
            master, height=self.ALTURA, bg=fundo, highlightthickness=0, bd=0
        )
        self._fracao = 0.0
        self.bind("<Configure>", lambda _e: self._desenhar())

    def definir(self, valor, maximo):
        self._fracao = 0.0 if not maximo else max(0.0, min(1.0, valor / maximo))
        self._desenhar()

    def _desenhar(self):
        self.delete("all")
        largura = self.winfo_width()
        if largura < 8:
            return
        raio = self.ALTURA / 2
        _retangulo_arredondado(
            self, 0, 0, largura, self.ALTURA, raio, fill=C_CAMPO, outline=""
        )
        preenchido = largura * self._fracao
        if preenchido >= self.ALTURA:
            _retangulo_arredondado(
                self, 0, 0, preenchido, self.ALTURA, raio, fill=C_ACENTO, outline=""
            )


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
        self.title("Pacientes Inativos")
        self.configure(bg=C_FUNDO)
        self.geometry("880x1000")
        self.minsize(820, 680)

        self.config_salva = carregar_config()
        self.medicos = []
        self.fila = queue.Queue()
        self.cancelar = threading.Event()
        self.trabalhando = False

        self._preparar_estilos()
        self._montar_interface()
        self._restaurar_config()

        aplicar_aparencia_nativa(self)
        self.after(100, self._consumir_fila)

    # ------------------------------------------------------------ aparencia

    def _preparar_estilos(self):
        self.fonte_titulo = _fonte(_DISPLAY, 24, "bold")
        self.fonte_sub = _fonte(_TEXTO, 12)
        self.fonte_corpo = _fonte(_TEXTO, 11)
        self.fonte_rotulo = _fonte(_TEXTO, 10)
        self.fonte_mono = _fonte(_MONO, 10)

        estilo = ttk.Style(self)
        try:
            estilo.theme_use("clam")
        except tk.TclError:
            pass

        comum = dict(
            fieldbackground=C_CAMPO,
            background=C_CAMPO,
            foreground=C_TEXTO,
            bordercolor=C_BORDA,
            lightcolor=C_BORDA,
            darkcolor=C_BORDA,
            insertcolor=C_TEXTO,
            arrowcolor=C_TEXTO_2,
            selectbackground=C_ACENTO,
            selectforeground="#FFFFFF",
        )
        estilo.configure("Vidro.TEntry", padding=9, **comum)
        estilo.configure("Vidro.TSpinbox", padding=7, **comum)
        estilo.configure("Vidro.TCombobox", padding=7, **comum)
        for nome in ("Vidro.TEntry", "Vidro.TSpinbox", "Vidro.TCombobox"):
            estilo.map(
                nome,
                bordercolor=[("focus", C_ACENTO)],
                lightcolor=[("focus", C_ACENTO)],
                darkcolor=[("focus", C_ACENTO)],
                fieldbackground=[("readonly", C_CAMPO), ("disabled", C_CARTAO_ALT)],
                foreground=[("disabled", C_TEXTO_3)],
            )

        # lista suspensa do combobox
        self.option_add("*TCombobox*Listbox.background", C_CARTAO_ALT)
        self.option_add("*TCombobox*Listbox.foreground", C_TEXTO)
        self.option_add("*TCombobox*Listbox.selectBackground", C_ACENTO)
        self.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
        self.option_add("*TCombobox*Listbox.borderWidth", 0)

    def _rotulo(self, pai, texto, fonte=None, cor=C_TEXTO_2, fundo=C_CARTAO):
        return tk.Label(
            pai,
            text=texto,
            bg=fundo,
            fg=cor,
            font=fonte or self.fonte_rotulo,
            anchor="w",
            justify="left",
        )

    def _caixa_selecao(self, pai, texto, variavel, fundo=C_CARTAO, comando=None):
        return tk.Checkbutton(
            pai,
            text=texto,
            variable=variavel,
            command=comando,
            bg=fundo,
            fg=C_TEXTO_2,
            selectcolor=C_CAMPO,
            activebackground=fundo,
            activeforeground=C_TEXTO,
            highlightthickness=0,
            bd=0,
            font=self.fonte_rotulo,
            cursor="hand2",
        )

    # ------------------------------------------------------------ construcao

    def _montar_interface(self):
        raiz = tk.Frame(self, bg=C_FUNDO)
        raiz.pack(fill="both", expand=True, padx=26, pady=(20, 22))

        self._montar_cabecalho(raiz)
        self._montar_cartao_chave(raiz)
        self._montar_cartao_medicos(raiz)
        self._montar_cartao_periodo(raiz)
        self._montar_cartao_destino(raiz)
        self._montar_rodape(raiz)
        self._montar_registro(raiz)

        self._log("Pronto. Informe a chave de API para comecar.")

    def _montar_cabecalho(self, pai):
        topo = tk.Frame(pai, bg=C_FUNDO)
        topo.pack(fill="x", pady=(0, 18))

        tk.Label(
            topo,
            text="Pacientes Inativos",
            bg=C_FUNDO,
            fg=C_TEXTO,
            font=self.fonte_titulo,
        ).pack(anchor="w")
        tk.Label(
            topo,
            text="Relatorio de pacientes sem consulta  ·  GestaoDS",
            bg=C_FUNDO,
            fg=C_TEXTO_3,
            font=self.fonte_sub,
        ).pack(anchor="w", pady=(2, 0))

    def _montar_cartao_chave(self, pai):
        cartao = Cartao(pai, "Chave de API")
        cartao.pack(fill="x", pady=(0, 12))
        corpo = cartao.corpo

        linha = tk.Frame(corpo, bg=C_CARTAO)
        linha.pack(fill="x")

        self.var_chave = tk.StringVar()
        self.campo_chave = ttk.Entry(
            linha,
            textvariable=self.var_chave,
            show="•",
            style="Vidro.TEntry",
            font=self.fonte_corpo,
        )
        self.campo_chave.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.botao_medicos = Botao(
            linha, "Carregar medicos", self._carregar_medicos, tipo="secundario"
        )
        self.botao_medicos.pack(side="left")

        opcoes = tk.Frame(corpo, bg=C_CARTAO)
        opcoes.pack(fill="x", pady=(10, 0))

        self.var_mostrar_chave = tk.BooleanVar(value=False)
        self._caixa_selecao(
            opcoes, "Mostrar chave", self.var_mostrar_chave, comando=self._alternar_chave
        ).pack(side="left")

        self.var_lembrar = tk.BooleanVar(value=True)
        self._caixa_selecao(
            opcoes, "Lembrar neste computador", self.var_lembrar
        ).pack(side="left", padx=(18, 0))

    def _montar_cartao_medicos(self, pai):
        cartao = Cartao(pai, "Medicos")
        cartao.pack(fill="x", pady=(0, 12))
        corpo = cartao.corpo

        self.rotulo_medicos = self._rotulo(
            corpo, "Informe a chave e clique em “Carregar medicos”."
        )
        self.rotulo_medicos.pack(fill="x", pady=(0, 10))

        linha = tk.Frame(corpo, bg=C_CARTAO)
        linha.pack(fill="both", expand=True)

        moldura = tk.Frame(linha, bg=C_BORDA, padx=1, pady=1)
        moldura.pack(side="left", fill="both", expand=True)

        self.lista_medicos = tk.Listbox(
            moldura,
            selectmode="extended",
            height=6,
            exportselection=False,
            bg=C_CAMPO,
            fg=C_TEXTO,
            selectbackground=C_ACENTO,
            selectforeground="#FFFFFF",
            highlightthickness=0,
            bd=0,
            relief="flat",
            font=self.fonte_corpo,
            activestyle="none",
        )
        self.lista_medicos.pack(side="left", fill="both", expand=True)

        barra = ttk.Scrollbar(
            moldura, orient="vertical", command=self.lista_medicos.yview
        )
        barra.pack(side="right", fill="y")
        self.lista_medicos.configure(yscrollcommand=barra.set)

        lado = tk.Frame(linha, bg=C_CARTAO)
        lado.pack(side="left", fill="y", padx=(12, 0))
        Botao(
            lado, "Selecionar todos", self._selecionar_todos, tipo="secundario", largura=150
        ).pack(pady=(0, 8))
        Botao(
            lado, "Limpar selecao", self._limpar_selecao, tipo="secundario", largura=150
        ).pack()
        self._rotulo(
            lado, "Sem selecao =\ntodos os medicos", cor=C_TEXTO_3
        ).pack(anchor="w", pady=(12, 0))

    def _montar_cartao_periodo(self, pai):
        cartao = Cartao(pai, "Periodo sem consultar")
        cartao.pack(fill="x", pady=(0, 12))
        corpo = cartao.corpo

        linha = tk.Frame(corpo, bg=C_CARTAO)
        linha.pack(fill="x")

        self._rotulo(linha, "Faixa").pack(side="left", padx=(0, 8))
        self.var_periodo = tk.StringVar(value=PERIODOS[1][0])
        self.combo_periodo = ttk.Combobox(
            linha,
            textvariable=self.var_periodo,
            values=[p[0] for p in PERIODOS],
            state="readonly",
            width=30,
            style="Vidro.TCombobox",
            font=self.fonte_corpo,
        )
        self.combo_periodo.pack(side="left", padx=(0, 20))
        self.combo_periodo.bind("<<ComboboxSelected>>", self._aplicar_periodo)

        self._rotulo(linha, "De").pack(side="left", padx=(0, 6))
        self.var_dias_min = tk.StringVar(value="365")
        self.campo_dias_min = ttk.Spinbox(
            linha,
            from_=0,
            to=20000,
            textvariable=self.var_dias_min,
            width=7,
            style="Vidro.TSpinbox",
            font=self.fonte_corpo,
        )
        self.campo_dias_min.pack(side="left", padx=(0, 16))

        self._rotulo(linha, "Ate").pack(side="left", padx=(0, 6))
        self.var_dias_max = tk.StringVar(value="")
        self.campo_dias_max = ttk.Spinbox(
            linha,
            from_=0,
            to=20000,
            textvariable=self.var_dias_max,
            width=7,
            style="Vidro.TSpinbox",
            font=self.fonte_corpo,
        )
        self.campo_dias_max.pack(side="left", padx=(0, 6))
        self._rotulo(linha, "dias", cor=C_TEXTO_3).pack(side="left")

        self._rotulo(
            corpo,
            "365 dias = 1 ano.  Deixe “Ate” vazio para nao ter limite maximo.",
            cor=C_TEXTO_3,
        ).pack(fill="x", pady=(10, 12))

        tipo = tk.Frame(corpo, bg=C_CARTAO)
        tipo.pack(fill="x")
        self._rotulo(tipo, "Considerar").pack(side="left", padx=(0, 12))
        self.var_tipo = tk.StringVar(value="atendimento")
        for texto, valor in (
            ("Ultimo atendimento", "atendimento"),
            ("Ultimo agendamento", "agendamento"),
        ):
            tk.Radiobutton(
                tipo,
                text=texto,
                variable=self.var_tipo,
                value=valor,
                bg=C_CARTAO,
                fg=C_TEXTO_2,
                selectcolor=C_CAMPO,
                activebackground=C_CARTAO,
                activeforeground=C_TEXTO,
                highlightthickness=0,
                bd=0,
                font=self.fonte_rotulo,
                cursor="hand2",
            ).pack(side="left", padx=(0, 16))

        self._aplicar_periodo()

    def _montar_cartao_destino(self, pai):
        cartao = Cartao(pai, "Pasta de destino")
        cartao.pack(fill="x", pady=(0, 16))
        corpo = cartao.corpo

        linha = tk.Frame(corpo, bg=C_CARTAO)
        linha.pack(fill="x")

        self.var_pasta = tk.StringVar(value=os.path.expanduser("~"))
        ttk.Entry(
            linha,
            textvariable=self.var_pasta,
            style="Vidro.TEntry",
            font=self.fonte_corpo,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))

        Botao(linha, "Escolher…", self._escolher_pasta, tipo="secundario").pack(
            side="left"
        )

    def _montar_rodape(self, pai):
        rodape = tk.Frame(pai, bg=C_FUNDO)
        rodape.pack(fill="x", pady=(0, 14))

        self.botao_gerar = Botao(
            rodape,
            "Gerar planilha",
            self._gerar,
            tipo="primario",
            largura=180,
            fundo=C_FUNDO,
        )
        self.botao_gerar.pack(side="left")

        self.botao_cancelar = Botao(
            rodape, "Cancelar", self._cancelar, tipo="perigo", largura=120, fundo=C_FUNDO
        )
        self.botao_cancelar.pack(side="right")
        self.botao_cancelar.definir_estado(False)

        meio = tk.Frame(rodape, bg=C_FUNDO)
        meio.pack(side="left", fill="x", expand=True, padx=18)
        self.barra_progresso = Barra(meio, fundo=C_FUNDO)
        self.barra_progresso.pack(fill="x", pady=(16, 4))
        self.rotulo_progresso = tk.Label(
            meio,
            text="",
            bg=C_FUNDO,
            fg=C_TEXTO_3,
            font=self.fonte_rotulo,
            anchor="w",
        )
        self.rotulo_progresso.pack(fill="x")

    def _montar_registro(self, pai):
        cartao = Cartao(pai, "Atividade", cor=C_CARTAO)
        cartao.pack(fill="both", expand=True)

        self.registro = tk.Text(
            cartao.corpo,
            height=5,
            wrap="word",
            state="disabled",
            bg=C_CAMPO,
            fg=C_TEXTO_2,
            insertbackground=C_TEXTO,
            highlightthickness=0,
            bd=0,
            relief="flat",
            padx=12,
            pady=10,
            font=self.fonte_mono,
            spacing1=1,
            spacing3=3,
        )
        self.registro.pack(fill="both", expand=True)
        self.registro.tag_configure("erro", foreground=C_PERIGO)
        self.registro.tag_configure("ok", foreground=C_SUCESSO)

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

    def _log(self, texto, marcador=None):
        marca = datetime.now().strftime("%H:%M:%S")
        self.registro.configure(state="normal")
        self.registro.insert("end", "{}  {}\n".format(marca, texto), marcador or ())
        self.registro.see("end")
        self.registro.configure(state="disabled")

    def _alternar_chave(self):
        self.campo_chave.configure(
            show="" if self.var_mostrar_chave.get() else "•"
        )

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
        self.botao_gerar.definir_estado(not travado)
        self.botao_medicos.definir_estado(not travado)
        self.botao_cancelar.definir_estado(travado)

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
        self.botao_cancelar.definir_estado(False)
        self._log("Carregando medicos…")

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
            messagebox.showwarning(APP_NOME, "“De” precisa ser um numero.")
            return

        texto_max = self.var_dias_max.get().strip()
        dias_max = None
        if texto_max:
            try:
                dias_max = int(texto_max)
            except ValueError:
                messagebox.showwarning(APP_NOME, "“Ate” precisa ser um numero.")
                return
            if dias_max < dias_min:
                messagebox.showwarning(
                    APP_NOME, "“Ate” precisa ser maior ou igual a “De”."
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
                self._log("Nenhum medico marcado — usando todos.")
        else:
            selecionados = []
            self._log("Lista de medicos nao carregada — buscando todos.")

        self._persistir_config()
        self.cancelar.clear()
        self._travar_interface(True)
        self.barra_progresso.definir(0, 100)
        self._log(
            "Buscando pacientes sem {} ha {}+ dias{}…".format(
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
            self._log("Cancelando apos a pagina atual…")

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
                    self.barra_progresso.definir(pagina, max(total, 1))
                    self.rotulo_progresso.configure(
                        text="Pagina {} de {}  ·  {} registros".format(
                            pagina, total, registros
                        )
                    )
                    if pagina == 1 or pagina % 10 == 0 or pagina == total:
                        self._log(
                            "Pagina {}/{} — {} registros".format(
                                pagina, total, registros
                            )
                        )

                elif tipo == "fim":
                    _, caminho, quantidade = mensagem
                    self._travar_interface(False)
                    self.barra_progresso.definir(1, 1)
                    self.rotulo_progresso.configure(
                        text="Concluido — {} pacientes".format(quantidade)
                    )
                    self._log(
                        "Planilha gerada: {} pacientes".format(quantidade), "ok"
                    )
                    self._log(caminho)
                    if messagebox.askyesno(
                        APP_NOME,
                        "Planilha gerada com {} pacientes:\n\n{}\n\nAbrir a pasta?".format(
                            quantidade, caminho
                        ),
                    ):
                        abrir_no_explorador(os.path.dirname(caminho))

                elif tipo == "vazio":
                    self._travar_interface(False)
                    self.rotulo_progresso.configure(text="Nenhum resultado")
                    self._log("Nenhum paciente encontrado para esse filtro.")
                    messagebox.showinfo(
                        APP_NOME, "Nenhum paciente encontrado para esse filtro."
                    )

                elif tipo == "cancelado":
                    self._travar_interface(False)
                    self.barra_progresso.definir(0, 1)
                    self.rotulo_progresso.configure(text="Cancelado")
                    self._log("Busca cancelada. Nenhum arquivo foi gerado.")

                elif tipo == "erro":
                    self._travar_interface(False)
                    self.barra_progresso.definir(0, 1)
                    self.rotulo_progresso.configure(text="Erro")
                    self._log(mensagem[1].replace("\n", " "), "erro")
                    messagebox.showerror(APP_NOME, mensagem[1])
        except queue.Empty:
            pass
        self.after(100, self._consumir_fila)

    def _receber_medicos(self, medicos):
        self._travar_interface(False)
        self.medicos = medicos
        self.lista_medicos.delete(0, "end")
        for medico in medicos:
            rotulo = "  " + medico["nome"]
            if medico["especialidade"]:
                rotulo += "   ·   {}".format(medico["especialidade"].title())
            self.lista_medicos.insert("end", rotulo)
        self.rotulo_medicos.configure(
            text="{} medicos nesta chave. Selecione um ou mais "
            "(sem selecao = todos).".format(len(medicos))
        )
        self._log("{} medicos carregados.".format(len(medicos)), "ok")
        self._persistir_config()


def main():
    Aplicativo().mainloop()


if __name__ == "__main__":
    main()
