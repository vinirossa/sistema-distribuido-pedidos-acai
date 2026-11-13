#!/usr/bin/env python3
"""
Gera fig_servidor.png e fig_cliente_console.png.

Precisa de um X rodando (ex.: Xvfb :99 + openbox) e de xterm, xdotool e
ImageMagick. Os comandos são digitados de verdade nos xterms com xdotool type;
nada é colado na tela depois. A Bia é um socket Python que só se conecta
(para haver broadcast) e no fim cai com RST, para o servidor registrar a queda.

Uso (a partir da raiz do repositório): DISPLAY=:99 python3 resultados-testes/capturas_console.py
"""
import os
import socket
import struct
import subprocess
import time

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SAIDA = os.path.join(RAIZ, "resultados-testes")
RC = os.path.join("/tmp", "acai_bashrc")

with open(RC, "w") as f:
    f.write("unset JAVA_TOOL_OPTIONS\nPS1='$ '\ncd %s\nclear\n" % RAIZ)


def sh(*cmd):
    return subprocess.check_output(cmd, text=True).strip()


def xterm(titulo, geometria):
    subprocess.Popen(["xterm", "-T", titulo, "-fa", "DejaVu Sans Mono", "-fs", "12",
                      "-bg", "white", "-fg", "black", "-geometry", geometria,
                      "-xrm", "XTerm*scrollBar: false", "-e", "bash", "--rcfile", RC, "-i"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            return sh("xdotool", "search", "--name", "^" + titulo + "$").split()[0]
        except subprocess.CalledProcessError:
            time.sleep(0.2)
    raise RuntimeError("janela não apareceu: " + titulo)


def digitar(janela, texto, enter=True):
    sh("xdotool", "windowactivate", "--sync", janela)
    sh("xdotool", "type", "--delay", "35", "--window", janela, texto)
    if enter:
        sh("xdotool", "key", "--window", janela, "Return")


def capturar(janela, arquivo):
    """Recorta a tela só na moldura da janela (com a barra de título do openbox)."""
    sh("xdotool", "windowactivate", "--sync", janela)
    sh("xdotool", "windowraise", janela)
    time.sleep(0.6)
    # janela-pai = moldura do gerenciador de janelas
    arvore = sh("xwininfo", "-children", "-id", janela)
    pai = [l for l in arvore.splitlines() if "Parent window id" in l][0].split()[3]
    info = sh("xwininfo", "-id", pai)
    v = {}
    for l in info.splitlines():
        l = l.strip()
        for chave in ("Absolute upper-left X:", "Absolute upper-left Y:", "Width:", "Height:"):
            if l.startswith(chave):
                v[chave] = int(l.split(":")[1])
    geo = "%dx%d+%d+%d" % (v["Width:"], v["Height:"], v["Absolute upper-left X:"],
                           v["Absolute upper-left Y:"])
    sh("import", "-window", "root", "-crop", geo, "+repage", os.path.join(SAIDA, arquivo))
    print("capturado", arquivo, geo)


srv = xterm("Servidor - TCPServerAtivosMain", "84x6+10+10")
time.sleep(1)
digitar(srv, "java -cp build multithreads2.TCPServerAtivosMain 5000")
time.sleep(2)

# Bia: só conecta, para receber o broadcast (e cair depois)
bia = socket.create_connection(("127.0.0.1", 5000))
bia.sendall(b"CONECTAR|Bia\n")

ana = xterm("Cliente Ana - TCPClientConsole", "84x30+10+10")
time.sleep(1)
digitar(ana, "java -cp build multithreads2.TCPClientConsole 127.0.0.1 5000 Ana")
time.sleep(2)
digitar(ana, "CATALOGO")
time.sleep(1.5)
digitar(ana, "PEDIR|1|7|NENHUM")
time.sleep(7.5)    # preparo de ~5 s + folga
capturar(ana, "fig_cliente_console.png")

# queda abrupta da Bia (RST) para o servidor registrar algo no console
bia.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
bia.close()
time.sleep(1)
digitar(ana, "SAIR")
time.sleep(1)
capturar(srv, "fig_servidor.png")
