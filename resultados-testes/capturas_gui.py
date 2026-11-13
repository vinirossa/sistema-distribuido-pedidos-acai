#!/usr/bin/env python3
"""
Gera fig_gui.png, fig_gui_concluido.png, fig_gui_bia_antes.png, fig_gui_bia.png e
fig_gui_erro_nome.png (T15).

Precisa de um X rodando (ex.: Xvfb :99 -screen 0 1920x1080x24 + openbox),
xdotool, xwininfo e ImageMagick. Abre o servidor e três instâncias reais do
TCPClientForm e as opera só com mouse e teclado (xdotool): nada é injetado no
socket por fora. As coordenadas são relativas à área interna da janela, medidas
numa captura da GUI (tamanho padrão 724x752 após pack()).

Uso (a partir da raiz do repositório): DISPLAY=:99 python3 resultados-testes/capturas_gui.py
"""
import os
import subprocess
import sys
import time

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SAIDA = os.path.join(RAIZ, "resultados-testes")
ENV = {k: v for k, v in os.environ.items() if k != "JAVA_TOOL_OPTIONS"}
DEBUG = "--debug" in sys.argv

# coordenadas (x, y) relativas à área interna da janela
NOME = (422, 123)
CONECTAR = (557, 123)
LINHA_CATALOGO = lambda i: (189, 202 + 18 * i)
QUANTIDADE = (298, 409)
FAZER_PEDIDO = (514, 409)


def sh(*cmd):
    return subprocess.check_output(cmd, text=True).strip()


def abrir_gui(rotulo):
    antes = set(janelas())
    subprocess.Popen(["java", "-cp", os.path.join(RAIZ, "build"), "multithreads2.TCPClientForm"],
                     env=ENV, stdin=subprocess.DEVNULL,
                     stdout=open("/tmp/gui_%s.log" % rotulo, "w"), stderr=subprocess.STDOUT)
    for _ in range(60):
        novas = set(janelas()) - antes
        if novas:
            time.sleep(1.0)
            return novas.pop()
        time.sleep(0.25)
    raise RuntimeError("GUI não abriu")


def janelas():
    try:
        return sh("xdotool", "search", "--onlyvisible", "--name", "^Açaí do Nando").split()
    except subprocess.CalledProcessError:
        return []


def mover(janela, x, y):
    sh("xdotool", "windowmove", "--sync", janela, str(x), str(y))
    time.sleep(0.4)


def clicar(janela, pos, vezes=1):
    sh("xdotool", "windowactivate", "--sync", janela)
    sh("xdotool", "mousemove", "--window", janela, str(pos[0]), str(pos[1]))
    sh("xdotool", "click", "--repeat", str(vezes), "1")
    time.sleep(0.3)


def digitar(janela, texto):
    # sem --window: o Java ignora eventos sintéticos (XSendEvent), então digita
    # via XTEST na janela que está com o foco
    sh("xdotool", "windowactivate", "--sync", janela)
    sh("xdotool", "type", "--delay", "60", texto)
    time.sleep(0.2)


def tecla(janela, *teclas):
    sh("xdotool", "windowactivate", "--sync", janela)
    sh("xdotool", "key", *teclas)
    time.sleep(0.2)


def moldura(janela):
    arvore = sh("xwininfo", "-children", "-id", janela)
    pai = [l for l in arvore.splitlines() if "Parent window id" in l][0].split()[3]
    v = {}
    for l in sh("xwininfo", "-id", pai).splitlines():
        l = l.strip()
        for chave in ("Absolute upper-left X:", "Absolute upper-left Y:", "Width:", "Height:"):
            if l.startswith(chave):
                v[chave] = int(l.split(":")[1])
    return v["Width:"], v["Height:"], v["Absolute upper-left X:"], v["Absolute upper-left Y:"]


def capturar(janela, arquivo, ativar=True):
    if ativar:
        sh("xdotool", "windowactivate", "--sync", janela)
        sh("xdotool", "mousemove", "1900", "1060")   # tira o cursor de cima da janela
    time.sleep(0.8)
    geo = "%dx%d+%d+%d" % moldura(janela)
    sh("import", "-window", "root", "-crop", geo, "+repage", os.path.join(SAIDA, arquivo))
    print("capturado", arquivo, geo, flush=True)


def debug(nome):
    if DEBUG:
        sh("import", "-window", "root", "/tmp/dbg_%s.png" % nome)


def conectar(janela, nome):
    clicar(janela, NOME)
    digitar(janela, nome)
    clicar(janela, CONECTAR)
    time.sleep(1.5)


servidor = subprocess.Popen(["java", "-cp", os.path.join(RAIZ, "build"),
                             "multithreads2.TCPServerAtivosMain", "5000"], env=ENV,
                            stdout=open("/tmp/servidor_gui.log", "w"), stderr=subprocess.STDOUT)
time.sleep(1.5)
try:
    ana = abrir_gui("ana")
    mover(ana, 0, 0)
    bia = abrir_gui("bia")
    mover(bia, 760, 0)

    conectar(ana, "Ana")
    conectar(bia, "Bia")
    debug("1_conectados")
    capturar(bia, "fig_gui_bia_antes.png")    # catálogo da Bia antes do pedido da Ana

    # Ana: seleciona "Acai Natural 400ml" (linha 1), quantidade 7, sem opcionais
    clicar(ana, LINHA_CATALOGO(1))
    clicar(ana, QUANTIDADE, vezes=3)
    tecla(ana, "ctrl+a")
    digitar(ana, "7")
    tecla(ana, "Return")
    debug("2_selecionado")
    clicar(ana, FAZER_PEDIDO)
    time.sleep(1.5)
    capturar(ana, "fig_gui.png")              # pedido em preparação
    capturar(bia, "fig_gui_bia.png")          # catálogo da Bia atualizado sozinho
    time.sleep(5)
    capturar(ana, "fig_gui_concluido.png")    # mesmo pedido, já concluído

    # T2 na GUI: terceira janela tenta entrar como "Ana"
    dup = abrir_gui("dup")
    mover(dup, 380, 120)
    conectar(dup, "Ana")
    time.sleep(1)
    debug("3_erro")
    capturar(dup, "fig_gui_erro_nome.png", ativar=False)
finally:
    time.sleep(0.5)
    subprocess.call(["pkill", "-f", "multithreads2.TCPClientForm"])
    servidor.terminate()
