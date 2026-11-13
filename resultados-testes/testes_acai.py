#!/usr/bin/env python3
"""
Roteiro de testes T1-T14 do sistema "Açaí do Nando" (Grupo 11 - Sistemas Distribuídos).

O script compila (opcionalmente), sobe o servidor Java real como subprocesso e
abre conexões TCP cruas (socket do Python), falando o protocolo de texto
diretamente. Toda linha enviada (>>) e recebida (<<) é registrada com timestamp
relativo ao início da execução e o nome do cliente. A saída do servidor
(System.out) também entra no log, marcada como [SERVIDOR].

Nada é corrigido: o que o servidor responde é o que fica registrado. Cada teste
compara o obtido com o esperado e grava o veredito em resultados.json.

Uso (a partir da raiz do repositório, com as classes em build/):
    python3 resultados-testes/testes_acai.py [--compilar] [--repeticoes-t12 N]

Saídas (em resultados-testes/):
    log_completo.log   todas as linhas de todos os clientes e do servidor
    dialogo_ana.log    só as linhas da Ana (e da reconexão da Ana no T14)
    resultados.json    veredito de cada teste, tempos do T7 e placar do T12
"""
import argparse
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SAIDA = os.path.join(RAIZ, "resultados-testes")
CLASSPATH = os.path.join(RAIZ, "build")
JAVA_ENV = {k: v for k, v in os.environ.items() if k != "JAVA_TOOL_OPTIONS"}

T0 = time.monotonic()
_lock_log = threading.Lock()
_log_completo = []   # linhas já formatadas
_log_ana = []


def agora():
    return time.monotonic() - T0


def registrar(rotulo, seta, texto, t=None):
    t = agora() if t is None else t
    linha = "+%9.3fs  %-14s %s %s" % (t, "[" + rotulo + "]", seta, texto)
    with _lock_log:
        _log_completo.append(linha)
        if rotulo.startswith("Ana"):
            _log_ana.append(linha)
        sys.stdout.write(linha + "\n")
        sys.stdout.flush()


def marcador(titulo):
    linha = "\n===== %s =====" % titulo
    with _lock_log:
        _log_completo.append(linha)
        _log_ana.append(linha)
        sys.stdout.write(linha + "\n")


def nota(texto):
    linha = "           # " + texto
    with _lock_log:
        _log_completo.append(linha)
        sys.stdout.write(linha + "\n")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Servidor
# ---------------------------------------------------------------------------
class Servidor:
    def __init__(self, porta, rotulo="SERVIDOR", silencioso=False):
        self.porta = porta
        self.rotulo = rotulo
        self.silencioso = silencioso
        self.linhas = []
        self.pronto = threading.Event()
        cmd = ["java", "-cp", CLASSPATH, "multithreads2.TCPServerAtivosMain", str(porta)]
        if not silencioso:
            nota("iniciando: " + " ".join(cmd[0:1] + ["-cp", "build"] + cmd[3:]))
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     env=JAVA_ENV, text=True, encoding="utf-8")
        threading.Thread(target=self._ler, daemon=True).start()
        if not self.pronto.wait(10):
            raise RuntimeError("servidor não subiu na porta %d" % porta)

    def _ler(self):
        for linha in self.proc.stdout:
            linha = linha.rstrip("\n")
            self.linhas.append((agora(), linha))
            if not self.silencioso:
                registrar(self.rotulo, "::", linha)
            if "rodando na porta" in linha:
                self.pronto.set()

    def parar(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


# ---------------------------------------------------------------------------
# Cliente (socket cru)
# ---------------------------------------------------------------------------
class Cliente:
    def __init__(self, rotulo, porta, host="127.0.0.1", silencioso=False):
        self.rotulo = rotulo
        self.silencioso = silencioso
        self.msgs = []           # lista de (t, linha)
        self.cond = threading.Condition()
        self.fechado = False
        self.sock = socket.create_connection((host, porta), timeout=5)
        self.sock.settimeout(None)
        self.local = self.sock.getsockname()
        self.remoto = self.sock.getpeername()
        if not silencioso:
            nota("%s conectou o socket %s:%d -> %s:%d" %
                 (rotulo, self.local[0], self.local[1], self.remoto[0], self.remoto[1]))
        self.arquivo = self.sock.makefile("r", encoding="utf-8", newline="\n")
        threading.Thread(target=self._receber, daemon=True).start()

    def _receber(self):
        try:
            for linha in self.arquivo:
                t = agora()
                linha = linha.rstrip("\r\n")
                with self.cond:
                    self.msgs.append((t, linha))
                    self.cond.notify_all()
                if not self.silencioso:
                    registrar(self.rotulo, "<<", linha, t)
        except OSError as ex:
            if not self.silencioso:
                registrar(self.rotulo, "!!", "recepção encerrada: %s" % ex)
        with self.cond:
            self.fechado = True
            self.cond.notify_all()
        if not self.silencioso:
            registrar(self.rotulo, "!!", "fim do fluxo (EOF): conexão encerrada")

    def enviar(self, linha):
        t = agora()
        if not self.silencioso:
            registrar(self.rotulo, ">>", linha, t)
        self.sock.sendall((linha + "\n").encode("utf-8"))
        return t

    def marca(self):
        with self.cond:
            return len(self.msgs)

    def esperar(self, pred, desde=0, timeout=3.0):
        """Devolve (indice, t, linha) da primeira linha a partir de 'desde' que satisfaz pred."""
        limite = time.monotonic() + timeout
        with self.cond:
            while True:
                for i in range(desde, len(self.msgs)):
                    if pred(self.msgs[i][1]):
                        return i, self.msgs[i][0], self.msgs[i][1]
                resta = limite - time.monotonic()
                if resta <= 0 or self.fechado:
                    return None
                self.cond.wait(resta)

    def esperar_fechar(self, timeout=3.0):
        limite = time.monotonic() + timeout
        with self.cond:
            while not self.fechado and time.monotonic() < limite:
                self.cond.wait(limite - time.monotonic())
            return self.fechado

    def linhas_desde(self, desde):
        with self.cond:
            return [l for _, l in self.msgs[desde:]]

    def fechar(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()

    def derrubar(self):
        """Queda abrupta: SO_LINGER=0 faz o kernel mandar RST em vez de FIN."""
        # Obs.: só fechar o socket não basta em Python, porque o arquivo do makefile()
        # mantém o descritor vivo. SHUT_RD acorda a thread leitora sem enviar nada;
        # ao fechar arquivo + socket com linger 0, o kernel envia RST.
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        self.sock.shutdown(socket.SHUT_RD)
        with self.cond:
            while not self.fechado:
                self.cond.wait(2)
        self.arquivo.close()
        self.sock.close()


def comeca(prefixo):
    return lambda l: l.startswith(prefixo)


def bloco_catalogo(linhas, inicio):
    """Lê as linhas CATALOGO_ITEM a partir de 'inicio' até FIM_CATALOGO."""
    itens = []
    for l in linhas[inicio:]:
        if l.startswith("CATALOGO_ITEM|"):
            itens.append(l.split("|"))
        elif l == "FIM_CATALOGO":
            return itens, True
    return itens, False


RESULTADOS = []


def resultado(tid, nome, esperado, obtido, passou, obs=""):
    RESULTADOS.append(dict(id=tid, nome=nome, esperado=esperado, obtido=obtido,
                           passou=passou, obs=obs))
    nota("RESULTADO %s: %s | obtido: %s%s" % (tid, "PASSOU" if passou else "FALHOU", obtido,
                                              (" | obs: " + obs) if obs else ""))


# ---------------------------------------------------------------------------
# Cenário principal (um servidor, T1-T11, T13, T14)
# ---------------------------------------------------------------------------
def cenario_principal(porta, ip_rede):
    extra = {}
    marcador("T1 Conexão")
    srv = Servidor(porta)
    ana = Cliente("Ana", porta)
    m = ana.marca()
    ana.enviar("CONECTAR|Ana")
    r_ana = ana.esperar(lambda l: True, m)
    bia = Cliente("Bia", porta)
    m = bia.marca()
    bia.enviar("CONECTAR|Bia")
    r_bia = bia.esperar(lambda l: True, m)
    ok = bool(r_ana and r_ana[2] == "CONECTADO|Ana" and r_bia and r_bia[2] == "CONECTADO|Bia")
    resultado("T1", "Conexão", "Ana e Bia recebem CONECTADO|nome",
              "%s / %s" % (r_ana and r_ana[2], r_bia and r_bia[2]), ok)

    marcador("T2 Nome repetido e nome vazio")
    outro = Cliente("Outro", porta)
    obtidos = []
    for cmd in ["CONECTAR|ana", "CONECTAR|", "CONECTAR| "]:
        m = outro.marca()
        outro.enviar(cmd)
        r = outro.esperar(lambda l: True, m)
        obtidos.append((cmd, r and r[2]))
    ok_rep = obtidos[0][1] is not None and obtidos[0][1].startswith("ERRO|NOME_EM_USO|")
    ok_vazio = obtidos[1][1] is not None and obtidos[1][1].startswith("ERRO|NOME_INVALIDO|")
    resultado("T2", "Nome repetido / vazio",
              "CONECTAR|ana -> ERRO|NOME_EM_USO; CONECTAR| -> ERRO|NOME_INVALIDO",
              "; ".join("%s -> %s" % o for o in obtidos), ok_rep and ok_vazio,
              "" if ok_vazio else "CONECTAR| (vazio) não devolveu NOME_INVALIDO")
    extra["t2"] = obtidos

    marcador("T3 Comando sem identificação")
    cru = Cliente("Cru", porta)
    m = cru.marca()
    cru.enviar("CATALOGO")
    r = cru.esperar(lambda l: True, m)
    resultado("T3", "Sem identificação", "ERRO|NAO_CONECTADO|...", r and r[2],
              bool(r and r[2].startswith("ERRO|NAO_CONECTADO|")))

    marcador("T4 Catálogo")
    m = ana.marca()
    ana.enviar("CATALOGO")
    ana.esperar(comeca("FIM_CATALOGO"), m)
    itens, fim = bloco_catalogo(ana.linhas_desde(m), 0)
    qtds = [int(i[5]) for i in itens]
    ok = (fim and len(itens) == 7 and all(i[4] == "1" for i in itens)
          and qtds == [25, 12, 25, 12, 25, 12, 20])
    resultado("T4", "Catálogo", "7 CATALOGO_ITEM disponíveis (25/12/25/12/25/12/20) + FIM_CATALOGO",
              "%d itens, disponivel=%s, quantidades=%s, FIM_CATALOGO=%s" %
              (len(itens), "".join(i[4] for i in itens), qtds, fim), ok)

    marcador("T5 Pedido aceito (+ T6 logo em seguida)")
    ma, mb, mo, mc = ana.marca(), bia.marca(), outro.marca(), cru.marca()
    t_envio = ana.enviar("PEDIR|1|7|NENHUM")
    # T6: Bia pede o mesmo logo em seguida
    m6 = bia.marca()
    t_envio6 = bia.enviar("PEDIR|1|7|NENHUM")
    r_criado = ana.esperar(comeca("PEDIDO_CRIADO|"), ma)
    r_cat_ana = ana.esperar(comeca("CATALOGO_ATUALIZADO"), ma)
    r_cat_bia = bia.esperar(comeca("CATALOGO_ATUALIZADO"), mb)
    ana.esperar(comeca("FIM_CATALOGO"), r_cat_ana[0] if r_cat_ana else ma)
    bia.esperar(comeca("FIM_CATALOGO"), r_cat_bia[0] if r_cat_bia else mb)

    def qtd_itens(cli, r):
        if not r:
            return None
        itens, _ = bloco_catalogo(cli.linhas_desde(0), r[0] + 1)
        return [int(i[5]) for i in itens]
    q_ana = qtd_itens(ana, r_cat_ana)
    q_bia = qtd_itens(bia, r_cat_bia)
    ok = bool(r_criado and r_criado[2] == "PEDIDO_CRIADO|1|AGUARDANDO|5"
              and q_ana and q_ana[0] == 11 and q_ana[1] == 5
              and q_bia and q_bia[0] == 11 and q_bia[1] == 5)
    ordem_ana = [l.split("|")[0] for l in ana.linhas_desde(ma)][:3]
    resultado("T5", "Pedido aceito",
              "PEDIDO_CRIADO|1|AGUARDANDO|5; Ana e Bia recebem CATALOGO_ATUALIZADO com item0=11 e item1=5",
              "%s; quantidades no CATALOGO_ATUALIZADO: Ana=%s, Bia=%s" %
              (r_criado and r_criado[2], q_ana, q_bia), ok,
              "ordem das primeiras mensagens da Ana após o pedido: " + ", ".join(ordem_ana))

    r6 = bia.esperar(lambda l: l.startswith("ERRO|") or l.startswith("PEDIDO_CRIADO|"), m6)
    resultado("T6", "Estoque compartilhado", "Bia: ERRO|SEM_ESTOQUE|...",
              "%s (%.0f ms após o pedido da Ana)" % (r6 and r6[2], (t_envio6 - t_envio) * 1000),
              bool(r6 and r6[2].startswith("ERRO|SEM_ESTOQUE|")))

    # vazamento: conexões não identificadas recebem o broadcast?
    time.sleep(0.5)
    vaz_outro = any(l.startswith("CATALOGO_ATUALIZADO") for l in outro.linhas_desde(mo))
    vaz_cru = any(l.startswith("CATALOGO_ATUALIZADO") for l in cru.linhas_desde(mc))
    extra["broadcast_nao_identificados"] = {"Outro": vaz_outro, "Cru": vaz_cru}
    nota("conexões sem CONECTAR que receberam CATALOGO_ATUALIZADO: Outro=%s, Cru=%s"
         % (vaz_outro, vaz_cru))

    marcador("T7 Notificações assíncronas")
    r_prep = ana.esperar(comeca("EVENTO_STATUS|1|EM_PREPARACAO"), ma, timeout=3)
    r_conc = ana.esperar(comeca("EVENTO_STATUS|1|CONCLUIDO"), ma, timeout=10)
    tempos = {}
    if r_criado:
        tempos["envio_ate_PEDIDO_CRIADO_ms"] = round((r_criado[1] - t_envio) * 1000, 1)
    if r_prep:
        tempos["envio_ate_EM_PREPARACAO_ms"] = round((r_prep[1] - t_envio) * 1000, 1)
    if r_conc:
        tempos["envio_ate_CONCLUIDO_ms"] = round((r_conc[1] - t_envio) * 1000, 1)
    if r_prep and r_conc:
        tempos["EM_PREPARACAO_ate_CONCLUIDO_ms"] = round((r_conc[1] - r_prep[1]) * 1000, 1)
    extra["t7"] = tempos
    nota("tempos T7: %s" % tempos)
    ok = bool(r_prep and r_conc and 4500 <= tempos["EM_PREPARACAO_ate_CONCLUIDO_ms"] <= 5800)
    resultado("T7", "Notificações", "EVENTO_STATUS|1|EM_PREPARACAO e ~5 s depois EVENTO_STATUS|1|CONCLUIDO",
              "%s / %s; intervalo %.3f s" % (r_prep and r_prep[2], r_conc and r_conc[2],
                                             tempos.get("EM_PREPARACAO_ate_CONCLUIDO_ms", 0) / 1000),
              ok)

    marcador("T8 Consulta de status")
    m = ana.marca()
    ana.enviar("STATUS|1")
    ra = ana.esperar(lambda l: True, m)
    m = bia.marca()
    bia.enviar("STATUS|1")
    rb = bia.esperar(lambda l: True, m)
    ok = bool(ra and ra[2] == "STATUS_PEDIDO|1|CONCLUIDO|5" and rb
              and rb[2].startswith("ERRO|PEDIDO_NAO_ENCONTRADO|"))
    resultado("T8", "Consulta", "Ana: STATUS_PEDIDO|1|CONCLUIDO|5; Bia: ERRO|PEDIDO_NAO_ENCONTRADO",
              "Ana: %s; Bia: %s" % (ra and ra[2], rb and rb[2]), ok)

    marcador("T9 Opcional BANANA")
    m = bia.marca()
    bia.enviar("PEDIR|0|1|BANANA")
    r9 = bia.esperar(lambda l: l.startswith("PEDIDO_CRIADO|") or l.startswith("ERRO|"), m)
    nota("o catálogo não expõe o estoque de banana; verificação indireta com o Açaí Zero "
         "(5000 ml intactos, então só a banana pode faltar):")
    m = bia.marca()
    bia.enviar("PEDIR|4|20|BANANA")
    r9b = bia.esperar(lambda l: l.startswith("PEDIDO_CRIADO|") or l.startswith("ERRO|"), m)
    m = bia.marca()
    bia.enviar("PEDIR|4|19|BANANA")
    r9c = bia.esperar(lambda l: l.startswith("PEDIDO_CRIADO|") or l.startswith("ERRO|"), m)
    ok = bool(r9 and r9[2].startswith("PEDIDO_CRIADO|") and r9b
              and r9b[2].startswith("ERRO|SEM_ESTOQUE") and r9c and r9c[2].startswith("PEDIDO_CRIADO|"))
    resultado("T9", "Opcional", "pedido aceito; banana 20 -> 19",
              "PEDIR|0|1|BANANA -> %s; PEDIR|4|20|BANANA -> %s; PEDIR|4|19|BANANA -> %s"
              % (r9 and r9[2], r9b and r9b[2], r9c and r9c[2]), ok,
              "estoque de banana não é visível no protocolo; 20 recusado e 19 aceito implica exatamente 19")

    marcador("T10 Opcional inválido")
    m = ana.marca()
    ana.enviar("PEDIR|6|1|BIS")
    r = ana.esperar(lambda l: l.startswith("ERRO|") or l.startswith("PEDIDO_CRIADO|"), m)
    resultado("T10", "Opcional inválido", "ERRO|OPCIONAL_INVALIDO|...", r and r[2],
              bool(r and r[2].startswith("ERRO|OPCIONAL_INVALIDO|")))

    marcador("T11 Validações")
    esperados = [("PEDIR|9|1|NENHUM", "PRODUTO_INVALIDO"), ("PEDIR|0|0|NENHUM", "QUANTIDADE_INVALIDA"),
                 ("PEDIR|0|1", "FORMATO_INVALIDO"), ("XYZ", "COMANDO_INVALIDO")]
    obtidos = []
    for cmd, cod in esperados:
        m = ana.marca()
        ana.enviar(cmd)
        r = ana.esperar(lambda l: l.startswith("ERRO|") or l.startswith("PEDIDO_CRIADO|"), m)
        obtidos.append(r[2].split("|")[1] if r and r[2].startswith("ERRO|") else (r and r[2]))
    ok = obtidos == [c for _, c in esperados]
    resultado("T11", "Validações", ", ".join(c for _, c in esperados), ", ".join(map(str, obtidos)), ok)

    outro.fechar()
    cru.fechar()

    marcador("T13 Rede (simulada pelo IP não-loopback do container)")
    caio = Cliente("Caio(rede)", porta, host=ip_rede)
    m = caio.marca()
    caio.enviar("CONECTAR|Caio")
    r1 = caio.esperar(lambda l: True, m)
    m = caio.marca()
    caio.enviar("CATALOGO")
    r2 = caio.esperar(comeca("FIM_CATALOGO"), m)
    n_itens = sum(1 for l in caio.linhas_desde(m) if l.startswith("CATALOGO_ITEM|"))
    ok = bool(r1 and r1[2] == "CONECTADO|Caio" and r2 and n_itens == 7)
    resultado("T13", "Rede (simulada)", "cliente conecta pelo IP %s e é atendido" % ip_rede,
              "socket %s:%d -> %s:%d; %s; catálogo com %d itens" %
              (caio.local[0], caio.local[1], caio.remoto[0], caio.remoto[1], r1 and r1[2], n_itens), ok,
              "simulação: mesma máquina, mas pela interface de rede %s em vez de 127.0.0.1" % ip_rede)
    caio.enviar("SAIR")
    caio.esperar_fechar()

    marcador("T14 Saída normal e queda abrupta")
    # Bia sai com SAIR
    bia.enviar("SAIR")
    bia_fechou = bia.esperar_fechar(3)
    nota("Bia: servidor fechou a conexão após SAIR = %s" % bia_fechou)
    # Ana é derrubada abruptamente (RST)
    nota("Ana: socket fechado com SO_LINGER=0 (RST, sem SAIR)")
    ana.derrubar()
    # Dani: cliente de console Java morto com SIGKILL
    nota("Dani: TCPClientConsole (Java) iniciado e morto com kill -9")
    dani = subprocess.Popen(["java", "-cp", CLASSPATH, "multithreads2.TCPClientConsole",
                             "127.0.0.1", str(porta), "Dani"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=JAVA_ENV, text=True)
    saida_dani = []
    threading.Thread(target=lambda: [saida_dani.append(l.rstrip()) or registrar("Dani(console)", "<<", l.rstrip())
                                     for l in dani.stdout], daemon=True).start()
    time.sleep(1.5)
    dani.send_signal(signal.SIGKILL)
    dani.wait()
    nota("Dani: processo terminou com código %s" % dani.returncode)
    time.sleep(0.8)
    recon = {}
    novos = []
    for nome in ["Ana", "Bia", "Dani"]:
        c = Cliente(nome + "#2", porta)
        m = c.marca()
        c.enviar("CONECTAR|" + nome)
        r = c.esperar(lambda l: True, m)
        recon[nome] = r and r[2]
        novos.append(c)
    ana2 = novos[0]
    m = ana2.marca()
    ana2.enviar("CATALOGO")
    r = ana2.esperar(comeca("FIM_CATALOGO"), m)
    itens, _ = bloco_catalogo(ana2.linhas_desde(m), 0)
    ok = (bia_fechou and all(recon[n] == "CONECTADO|" + n for n in recon) and r is not None
          and len(itens) == 7)
    resultado("T14", "Saída e queda",
              "nomes liberados após SAIR / queda; servidor continua atendendo",
              "Bia fechou após SAIR=%s; reconexões: %s; catálogo depois: %d itens (quantidades %s)" %
              (bia_fechou, recon, len(itens), [int(i[5]) for i in itens]), ok)
    for c in novos:
        c.enviar("SAIR")
        c.esperar_fechar()
    time.sleep(0.3)
    srv.parar()
    extra["servidor_stdout"] = [l for _, l in srv.linhas]
    return extra


# ---------------------------------------------------------------------------
# T12 - concorrência com barreira, servidor reiniciado a cada repetição
# ---------------------------------------------------------------------------
def rodada_t12(porta, n):
    srv = Servidor(porta, rotulo="SERVIDOR", silencioso=True)
    c1 = Cliente("P1", porta, silencioso=True)
    c2 = Cliente("P2", porta, silencioso=True)
    for c, nome in ((c1, "P1"), (c2, "P2")):
        m = c.marca()
        c.enviar("CONECTAR|" + nome)
        c.esperar(lambda l: True, m)
    barreira = threading.Barrier(2)
    envio = {}
    marcas = {"P1": c1.marca(), "P2": c2.marca()}

    def disparar(c, nome):
        barreira.wait()
        envio[nome] = agora()
        c.sock.sendall(b"PEDIR|3|7|NENHUM\n")
    th = [threading.Thread(target=disparar, args=(c1, "P1")),
          threading.Thread(target=disparar, args=(c2, "P2"))]
    for t in th:
        t.start()
    for t in th:
        t.join()
    pred = lambda l: l.startswith("PEDIDO_CRIADO|") or l.startswith("ERRO|")
    r1 = c1.esperar(pred, marcas["P1"])
    r2 = c2.esperar(pred, marcas["P2"])
    respostas = {"P1": r1 and r1[2], "P2": r2 and r2[2]}
    criados = sum(1 for v in respostas.values() if v and v.startswith("PEDIDO_CRIADO|"))
    sem = sum(1 for v in respostas.values() if v and v.startswith("ERRO|SEM_ESTOQUE"))
    ok = criados == 1 and sem == 1
    vencedor = [k for k, v in respostas.items() if v and v.startswith("PEDIDO_CRIADO|")]
    defasagem = abs(envio["P1"] - envio["P2"]) * 1e6
    linha = ("rodada %2d porta %d: P1 -> %-40s P2 -> %-40s defasagem envio %6.0f us  %s"
             % (n, porta, respostas["P1"], respostas["P2"], defasagem, "OK" if ok else "FALHOU"))
    nota(linha)
    for c in (c1, c2):
        c.fechar()
    srv.parar()
    return dict(rodada=n, porta=porta, P1=respostas["P1"], P2=respostas["P2"], ok=ok,
                vencedor=vencedor[0] if vencedor else None, defasagem_us=round(defasagem))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compilar", action="store_true")
    ap.add_argument("--porta", type=int, default=5000)
    ap.add_argument("--repeticoes-t12", type=int, default=30)
    ap.add_argument("--ip-rede", default=None)
    args = ap.parse_args()

    if args.compilar:
        subprocess.check_call("javac --release 8 -encoding UTF-8 -d build src/multithreads2/*.java",
                              shell=True, cwd=RAIZ, env=JAVA_ENV)
    ip = args.ip_rede or subprocess.check_output(["hostname", "-I"], text=True).split()[0]

    marcador("Execução iniciada em %s (ip não-loopback: %s)" % (time.strftime("%Y-%m-%d %H:%M:%S"), ip))
    extra = cenario_principal(args.porta, ip)

    marcador("T12 Concorrência: PEDIR|3|7|NENHUM simultâneo (barreira), servidor reiniciado a cada rodada")
    rodadas = [rodada_t12(args.porta + 100 + i, i + 1) for i in range(args.repeticoes_t12)]
    acertos = sum(r["ok"] for r in rodadas)
    venc = {"P1": sum(r["vencedor"] == "P1" for r in rodadas),
            "P2": sum(r["vencedor"] == "P2" for r in rodadas)}
    resultado("T12", "Concorrência", "em cada rodada, exatamente um PEDIDO_CRIADO e um SEM_ESTOQUE",
              "%d/%d rodadas corretas (vencedor P1=%d, P2=%d)" %
              (acertos, len(rodadas), venc["P1"], venc["P2"]), acertos == len(rodadas))

    with open(os.path.join(SAIDA, "log_completo.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(_log_completo) + "\n")
    with open(os.path.join(SAIDA, "dialogo_ana.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(_log_ana) + "\n")
    with open(os.path.join(SAIDA, "resultados.json"), "w", encoding="utf-8") as f:
        json.dump(dict(resultados=RESULTADOS, extra=extra, t12=rodadas, ip=ip), f,
                  ensure_ascii=False, indent=2)
    print("\nResumo:")
    for r in RESULTADOS:
        print("  %-4s %-24s %s" % (r["id"], r["nome"], "PASSOU" if r["passou"] else "FALHOU"))


if __name__ == "__main__":
    main()
