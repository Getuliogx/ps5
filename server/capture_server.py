#!/usr/bin/env python3
"""
Servidor do online de Capcom vs. SNK 2 - Millionaire Fighting 2001 (PS2, Japao).  Versao 27 (jogador x jogador pela ponte de MODEM VIRTUAL).

Base: servidor do MvC2 v26.1 (login, perfis, salas, fila de busca, placar/rank, painel web). O que e do CvS2 (decifrado no ELF):
  - lobby: 6810 -> 6861 -> 700c (TrInfomation) -> 7007 (TrEntryJoin) -> 6144 -> 6145 -> 6148/6851 ; 7006/7010 = status do torneio
  - partida encontrada: servidor manda 6901 aos dois; jogo -> 6902 lado (1 = quem DISCA, 2 = quem ATENDE) -> 6903 perfil do oponente
    -> 6904 regras (48 bytes) -> 6905 codigo -> (so o lado 1) 6906 "numero de telefone" = codigo da partida
  - depois o jogo faz logout (6002) e usa a camada de MODEM (API Com*): o AVEWRAP2 (modem Hayes virtual) liga na porta P2P deste
    servidor. Protocolo de controle (linhas de texto): PS2->srv "HELLO", "DIAL <numero>", "ANSWER"; srv->PS2 "RING", "CONNECT",
    "NOCARRIER", "BUSY". Depois do CONNECT o servidor repassa os bytes de um PS2 para o outro (ponte); os dois PS2 falam o
    handshake PING/PONG, READY/OK, START e os pacotes de 20 bytes por frame (ver NOTAS_TECNICAS.md).
Mensagens: cabecalho de 12 bytes + corpo.
    jogo -> servidor : 81 cc TT TT LL LL 00 00 00 FF FF FF  [corpo]
    servidor -> jogo : 28 02 TT TT LL LL 00 00 00 FF FF FF  [corpo]     (byte 8 = status, 0 = ok)
  Strings no corpo: [u16 tamanho big-endian][bytes].
"""
import argparse, socket, struct, threading, time, sys, os, json, unicodedata
import io, zipfile, secrets, base64, hmac, re, string, urllib.parse, random
import html as _html
from datetime import datetime, timezone, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

LOG = open("capture.log", "a", encoding="utf-8")
LOCK = threading.Lock()

BOT = False                  # --com-bot liga o BOT (so para teste sozinho). Padrao v25: SO JOGADORES REAIS
IP_PUBLICO = None            # --ip-publico: IP que o PS2 usa para chegar neste servidor (Oracle: IP publico da VM)
MATCH_LOCK = threading.RLock()
FILA = []                    # sessoes esperando oponente
CONTADOR = [0]
SALAS_TOTAL = 10
ONLINE = []                  # sessoes conectadas (painel / contador do menu)
PARES_ATIVOS = []
RELAXAR_APOS = 20.0          # --relaxar-apos: busca fora de sala junta modos diferentes depois desse tempo (0 = nunca)
BOT_SALA_BUSCA = 1.5   # v19: segundos entre apertar 'busca automatica' na sala e o BOT aparecer
SALA_ESPERA = 6.0   # v18: segundos apos entrar na sala antes de empurrar o 6901 (se o jogo nao pedir nada)

TOKEN = b"MVC2TKN1"          # 8 bytes: o jogo devolve isto no 6102
CHAVE = b"MVC2"              # duas strings iguais no 6820 => o jogo pula a lista de escolha

NOMES = {
    0x6901: "partida-encontrada", 0x6902: "lado", 0x6903: "perfil-do-oponente", 0x6904: "regras", 0x6905: "codigo-da-batalha",
    0x6906: "numero-do-oponente", 0x700c: "tr-info(700c)", 0x7007: "tr-entry-join(7007)", 0x7006: "torneio-status(7006)",
    0x7010: "torneio-hora(7010)", 0x7001: "tr-entry-again(7001)",
    0x6001: "ping/pong", 0x6002: "logout", 0x6101: "login-1", 0x6102: "login-2 (token)", 0x6103: "aviso",
    0x6110: "login-fim", 0x6111: "lista-de-perfis", 0x6112: "perfil-confirmado", 0x613A: "cadastro-inicio",
    0x6131: "cadastro-1", 0x6132: "cadastro-2", 0x6133: "cadastro-3", 0x6134: "cadastro-4", 0x6135: "cadastro-5",
    0x6136: "cadastro-6", 0x6137: "cadastro-7", 0x6138: "cadastro-8", 0x6139: "cadastro-9",
    0x6114: "perfil-1", 0x6115: "perfil-2", 0x6116: "perfil-3", 0x6117: "perfil-4", 0x6118: "perfil-fim",
    0x6120: "perfil-5", 0x6122: "perfil-dados", 0x6820: "pedido-lista", 0x6821: "item-lista", 0x6822: "fim-lista", 0x6823: "escolha",
    0x6801: "lista-de-salas", 0x6802: "descricao-da-sala", 0x6142: "lobby-pronto", 0x6143: "lobby-143", 0x6841: "lista-841",
    0x6810: "info-810", 0x6861: "handshake-861", 0x6144: "info-144", 0x6145: "info-145", 0x6148: "cliente-148", 0x6851: "lista-851", 0x6149: "info-149", 0x6141: "fim-141", 0x6207: "entrar-lobby", 0x6205: "contagem-205", 0x6303: "contagem-303", 0x6305: "entrar-sala", 0x6306: "sala-306", 0x6209: "buscar-oponente", 0x6401: "salas-total", 0x6402: "sala-nome", 0x6403: "sala-pessoas", 0x6404: "sala-estado", 0x6406: "sala-406", 0x6504: "busca-504", 0x6910: "partida-encontrada(BOT)", 0x6911: "partida-911", 0x6912: "partida-912", 0x6913: "partida-913(perfil do oponente)", 0x6914: "partida-914", 0x6915: "partida-915", 0x6916: "partida-916(IP do oponente)", 0x6917: "partida-917(iniciar)", 0x6506: "sala-506", 0x6501: "sala-501", 0x6408: "salas-atualizar", 0x6702: "chat-sala", 0x6830: "info-830", 0x6831: "info-831", 0x6832: "info-832", 0x6833: "info-833", 0x6835: "info-835",
}


BASE = os.path.dirname(os.path.abspath(__file__))
LOGDIR = os.path.join(BASE, "logs")
os.makedirs(LOGDIR, exist_ok=True)
HIST_ARQ = os.path.join(LOGDIR, "partidas.jsonl")
WEB_SENHA_ARQ = os.path.join(BASE, "web_senha.txt")
WEB_INFO_ARQ = os.path.join(BASE, "web_info.txt")
FUSO = timezone(timedelta(hours=-3))          # horario de Brasilia (a VM da Oracle usa UTC)
TL = threading.local()                        # arquivo de log da sessao da thread atual
IP_LOGS = {}                                  # ip do PS2 -> arquivo da sessao mais recente (recebe tambem os logs UDP do PS2)


def out(msg, ip=None):
    line = "%s %s" % (datetime.now(FUSO).strftime("%d/%m %H:%M:%S"), msg)
    with LOCK:
        print(line); sys.stdout.flush()
        LOG.write(line + "\n"); LOG.flush()
        f1 = getattr(TL, "logf", None)
        f2 = IP_LOGS.get(ip) if ip else None
        for f in (f1, f2 if f2 is not f1 else None):
            if f:
                try:
                    f.write(line + "\n"); f.flush()
                except Exception:
                    pass


def hist(ev):
    """historico das partidas (logs/partidas.jsonl): uma linha JSON por evento (par / fim / resultado)"""
    ev["t"] = int(time.time())
    try:
        with MATCH_LOCK:
            with open(HIST_ARQ, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception as e:
        out("[hist] erro: %s" % e)


def nick_texto(hn):
    return hn.decode("cp932", "replace")


def abrir_log_sessao(ss):
    """cria logs/sessao_<data>_<ip>_n<id>.log quando a conexao fala o protocolo do jogo (robos da internet nao geram arquivo)"""
    if ss.get("logf"):
        return
    nome = "sessao_%s_%s_n%d.log" % (datetime.now(FUSO).strftime("%Y%m%d_%H%M%S"), str(ss["cli"]).replace(":", "-"), ss["id"])
    try:
        f = open(os.path.join(LOGDIR, nome), "a", encoding="utf-8")
    except Exception:
        return
    ss["logf"], ss["logarq"] = f, nome
    TL.logf = f
    with LOCK:
        antigo = IP_LOGS.get(ss["cli"])
        IP_LOGS[ss["cli"]] = f
    f.write("# sessao de %s iniciada em %s (servidor v26.1)\n" % (ss["cli"], datetime.now(FUSO).strftime("%d/%m/%Y %H:%M:%S")))
    if antigo is not None and antigo is not f:
        try:
            antigo.close()
        except Exception:
            pass


def fechar_log_depois(ss, seg=300):
    """a luta acontece DEPOIS do login fechar (conexao do oponente): mantem o arquivo aberto mais um tempo"""
    f = ss.get("logf")
    if not f:
        return

    def _fecha():
        with LOCK:
            if IP_LOGS.get(ss["cli"]) is f:
                IP_LOGS.pop(ss["cli"], None)
        try:
            f.close()
        except Exception:
            pass
    t = threading.Timer(seg, _fecha)
    t.daemon = True
    t.start()


def hexdump(b):
    rows = []
    for i in range(0, len(b), 16):
        c = b[i:i + 16]
        rows.append("%04x  %-47s  %s" % (i, " ".join("%02x" % x for x in c),
                    "".join(chr(x) if 32 <= x < 127 else "." for x in c)))
    return "\n".join(rows)


def s16(b):
    """string com prefixo de tamanho (u16 big-endian)"""
    return struct.pack(">H", len(b)) + b


def frame(tipo, corpo=b"", classe=0x02, status=0):
    ln = len(corpo)
    return bytes([0x28, classe, (tipo >> 8) & 255, tipo & 255, (ln >> 8) & 255, ln & 255, 0, 0, status, 0xFF, 0xFF, 0xFF]) + corpo


def split_frames(buf):
    frames = []
    while len(buf) >= 12:
        total = 12 + ((buf[4] << 8) | buf[5])
        if len(buf) < total:
            break
        frames.append(bytes(buf[:total]))
        buf = buf[total:]
    return frames, buf


def resposta(tipo, corpo):
    """Passos A e B (sem estado)."""
    if tipo == 0x6001:                       # pong do jogo
        return []
    if tipo == 0x6101:                       # jogo aceitou o login-1  -> pede o token
        return [(0x6102, b"")]
    if tipo == 0x6102:                       # jogo devolveu o token   -> aviso vazio (o jogo pula a tela de aviso)
        return [(0x6103, b"\x00" + s16(b"") + s16(b"") + struct.pack(">H", 0))]
    if tipo == 0x6103:                       # jogo confirmou o aviso
        return [(0x6110, b"")]
    if tipo == 0x6820:                       # pedido de lista (versao do jogo) -> duas strings iguais + fim de lista
        return [(0x6820, s16(CHAVE) + s16(CHAVE)), (0x6822, b"")]
    if tipo == 0x6823:                       # escolha confirmada
        return [(0x6823, s16(b""))]
    return None


# v25: PERFIS de TODOS os jogadores (ID + nick "HN" + placar), gravados em perfis.json ao lado deste script.
#   Quem e quem: o ID de 6 bytes que o servidor entrega ao cadastrar o nick (0x6112) fica no memory card do jogador. Nos logins
#   seguintes o jogo manda 0x6110 modo 3 + 0x6113 [ID] e o servidor acha o perfil por esse ID.
#   Lista de escolha (0x6110 modo 0, ELF 0x43dd80): so aparecem os perfis criados pelo MESMO IP; jogador novo (lista vazia) cai direto no nick.
#   Placar: o jogo calcula sozinho a luta e, no PROXIMO login, manda 0x6120 com o resultado (ELF 0x43e0a0):
#     [blob 14 = nome do oponente][..][u8 partidas @17][u8 vitorias @18][u8 derrotas @19][u8 empates @20]. Cada jogador soma o SEU resultado.
#   O servidor devolve o placar em 0x6145 = [u16 partidas][u16 vitorias][u16 derrotas][u16 empates][u16 ?][u32][u32]   (ELF 0x43e8e0)
#   e a posicao em 0x6144 = [u8 CLASSE DE RANK 0..19][u32 POSICAO][u32 TOTAL DE JOGADORES]  (ELF 0x43e880; "%8u位／%8u人中").
PERFIS_ARQ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perfis.json")
MAX_PERFIS = 3          # perfis mostrados na lista de escolha (mais recentes do mesmo IP)
RANK_VIT = 3            # 1 classe de rank a cada RANK_VIT vitorias liquidas (palpite: ajuste a gosto; classes 0..19)
BOT_ID = b"BOT"
BOT_NICK = b"BOT"
BOT_STATS = [0, 0, 0, 0]
DB = {}                 # ID (6 bytes) -> {"hn": nick em bytes cp932, "ip": ip do dono ou None, "stats": [partidas, vit, der, emp], "ultimo": epoch}


def id_do_nick(hn, usados):
    """o ID (campo de cima nas telas VS/RESULT) e o PROPRIO NICK em ASCII com exatamente 6 bytes (o jogo guarda o ID em 6 bytes).
    Letras largas japonesas viram comuns (ＸＹＺＧＸ -> XYZGX). Nick sem letras/numeros comuns (katakana...) usa P00001, P00002..."""
    t = unicodedata.normalize("NFKC", hn.decode("cp932", "replace"))
    t = "".join(c for c in t if c.isascii() and c.isalnum())[:6]
    if t:
        c = t.ljust(6).encode("ascii")
        n = 2
        while c in usados:                       # nick repetido: acrescenta numero no fim
            suf = str(n)
            c = (t[:6 - len(suf)] + suf).ljust(6).encode("ascii")
            n += 1
        return c
    n = 1
    while (b"P%05d" % n) in usados:
        n += 1
    return b"P%05d" % n


def carregar_perfis():
    try:
        with open(PERFIS_ARQ, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = []
    for x in d:
        try:
            hn = bytes.fromhex(x["hn"])
        except Exception:
            continue
        if not hn.strip(b"*"):
            continue                                  # descarta o perfil quebrado "**" da v21
        pid = str(x.get("id", "")).encode("ascii", "ignore")
        if len(pid) != 6 or pid in DB:
            pid = id_do_nick(hn, set(DB))
        st = ([int(v) for v in x.get("stats", [])] + [0, 0, 0, 0])[:4]
        DB[pid] = {"hn": hn, "ip": x.get("ip"), "stats": st, "ultimo": float(x.get("ultimo", 0))}
        if "bot_stats" in x:
            BOT_STATS[:] = ([int(v) for v in x["bot_stats"]] + [0, 0, 0, 0])[:4]


def salvar_perfis():
    with MATCH_LOCK:
        try:
            d = [{"id": i.decode("ascii", "replace"), "hn": p["hn"].hex(), "hn_texto": p["hn"].decode("cp932", "replace"),
                  "ip": p.get("ip"), "ultimo": p.get("ultimo", 0), "stats": p["stats"]} for i, p in DB.items()]
            if d:
                d[0]["bot_stats"] = BOT_STATS
            tmp = PERFIS_ARQ + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=1, ensure_ascii=False)
            os.replace(tmp, PERFIS_ARQ)
        except Exception as e:
            out("[perfis] erro ao gravar %s: %s" % (PERFIS_ARQ, e))


def nick_de(ss):
    p = DB.get(ss.get("perfil"))
    return p["hn"] if p else b"PLAYER%d" % ss.get("id", 0)


def rotulo(ss):
    """texto para o log: nick + IP"""
    return "%s (%s)" % (nick_de(ss).decode("cp932", "replace"), ss.get("cli", "?"))


def perfis_do_ip(ip):
    with MATCH_LOCK:
        l = [(i, p) for i, p in DB.items() if p.get("ip") == ip]
    l.sort(key=lambda t: -t[1].get("ultimo", 0))
    return l[:MAX_PERFIS]


def classe_rank(st):
    return max(0, min(19, (st[1] - st[2]) // RANK_VIT))


def posicao_rank(pid):
    """posicao entre os jogadores que ja lutaram (mais vitorias liquidas primeiro) e total de jogadores ranqueados"""
    with MATCH_LOCK:
        ids = [i for i, p in DB.items() if p["stats"][0] > 0 or i == pid]
        ids.sort(key=lambda i: (-(DB[i]["stats"][1] - DB[i]["stats"][2]), -DB[i]["stats"][1], DB[i]["stats"][0], i))
        return (ids.index(pid) + 1 if pid in ids else 0), len(ids)


def aplicar_resultado(ss, corpo):
    """0x6120 do jogo: resultado das lutas desde o ultimo login -> soma no placar do PROPRIO jogador"""
    pid = ss.get("perfil")
    if not pid or len(corpo) < 22:
        return
    g, v, d, e = corpo[17], corpo[18], corpo[19], corpo[20]
    if not g and not (v or d or e):
        return
    n = g or (v + d + e)
    op = corpo[2:2 + 14].split(b"\x00")[0]
    with MATCH_LOCK:
        p = DB.get(pid)
        if p is None:
            return
        st = p["stats"]
        st[0] += n; st[1] += v; st[2] += d; st[3] += e
        if BOT and op and op == BOT_NICK[:14]:        # lutou contra o BOT: o BOT fica com o resultado inverso
            BOT_STATS[0] += n; BOT_STATS[1] += d; BOT_STATS[2] += v; BOT_STATS[3] += e
        total = list(st)
    salvar_perfis()
    hist({"ev": "resultado", "perfil": pid.decode("ascii", "replace"), "nick": p["hn"].decode("cp932", "replace"),
          "contra": op.decode("cp932", "replace"), "g": n, "v": v, "d": d, "e": e})
    out("[placar] %s: +%d partida(s) (+%d vit, +%d der, +%d emp) contra %s -> total %s | rank classe %d" % (
        p["hn"].decode("cp932", "replace"), n, v, d, e, op.decode("cp932", "replace") or "?", total, classe_rank(total)))


def cadastrar_perfil(ss, corpo):
    """0x6112 do jogo: [string ID "******"][string HN]  (string = [u16 tamanho][bytes]). Resposta: ID novo com EXATAMENTE 6 bytes."""
    def ler(b, o):
        n = (b[o] << 8) | b[o + 1]
        return b[o + 2:o + 2 + n], o + 2 + n
    try:
        _idc, o = ler(corpo, 0)
        hn, o = ler(corpo, o)
        hn = hn.split(b"\x00")[0][:17]
    except Exception:
        hn = b""
    hn = hn or b"PLAYER"
    with MATCH_LOCK:
        novo = id_do_nick(hn, set(DB))
        DB[novo] = {"hn": hn, "ip": ss.get("cli"), "stats": [0, 0, 0, 0], "ultimo": time.time()}
    salvar_perfis()
    out("[perfis] NOVO perfil: ID=%r HN=%s (hex %s) criado por %s" % (novo.decode(), hn.decode("cp932", "replace"), hn.hex(), ss.get("cli")))
    return novo


def escolher_perfil(ss, corpo):
    """0x6113 do jogo: [string ID] = perfil escolhido/guardado no memory card"""
    try:
        pid = corpo[2:2 + ((corpo[0] << 8) | corpo[1])]
    except Exception:
        return
    with MATCH_LOCK:
        p = DB.get(pid)
        if p is None:                                  # ID que este servidor nao conhece (arquivo apagado...): recria com o ID como nick
            p = DB[pid] = {"hn": pid.strip(b"* ") or b"PLAYER", "ip": ss.get("cli"), "stats": [0, 0, 0, 0], "ultimo": 0}
            out("[perfis] ID desconhecido %r: perfil recriado" % pid.decode("ascii", "replace"))
        p["ip"] = ss.get("cli")
        p["ultimo"] = time.time()
        ss["perfil"] = pid
    salvar_perfis()
    out("[perfis] %s entrou como ID=%s HN=%s  placar=%s" % (ss.get("cli"), pid.decode("ascii", "replace"), p["hn"].decode("cp932", "replace"), p["stats"]))


def lista_perfis(ss):
    """0x6111: [u8 N] + N x ([string id][string nome]) -- so os perfis deste IP"""
    l = perfis_do_ip(ss.get("cli"))
    return (0x6111, bytes([len(l)]) + b"".join(s16(i) + s16(p["hn"]) for i, p in l))


carregar_perfis()
salvar_perfis()


G_SEQ = [(0x6114, b""), (0x6115, b""), (0x6116, b""), (0x6117, b""), (0x6120, b""), (0x6118, b"")]


SALAS = [(b"MVC2 Lobby", b"Sala principal do servidor revivido")]


def lobby(tipo, corpo):
    """Passo H (decifrado no ELF, tratador 0x435250):
    jogo 6801 (pede lista)  -> servidor 6801 [u8 N][N x string nome(<=63)]
    jogo 6802 [u8 idx]      -> servidor 6802 [string descricao(<=767)]     (o jogo pede uma por indice)
    (depois de todas) jogo 6142 vazio -> servidor 6142 [u32 BE]
    jogo 6841 vazio         -> servidor 6841 [u8 N][N x (string nome(<=127) + string descricao(<=767))]"""
    if tipo == 0x6801:
        return [(0x6801, bytes([len(SALAS)]) + b"".join(s16(n) for n, d in SALAS))]
    if tipo == 0x6802:
        i = corpo[0] if corpo else 0
        d = SALAS[i][1] if i < len(SALAS) else b""
        return [(0x6802, s16(d))]
    if tipo == 0x6142:
        return [(0x6142, struct.pack(">I", 1))]
    if tipo == 0x6841:
        return [(0x6841, bytes([len(SALAS)]) + b"".join(s16(n) + s16(d) for n, d in SALAS))]
    # --- v9: decifrado no ELF (tratador 0x435250, estado 1) ---
    if tipo == 0x6810:      # servidor 6810 status 0: [string][string][u8]  (0x440560)
        return [(0x6810, s16(b"") + s16(b"") + bytes([0]))]
    # --- CvS2 (lobby_act_00_08 @0x316180): apos o 6861 (status != 0) o jogo manda 700c e ESPERA a resposta ---
    if tipo == 0x700c:      # Acc_TrInfomation: [u8][string]
        return [(0x700c, bytes([0]) + s16(b""), 0)]
    if tipo == 0x7007:      # Acc_TourEntryJoin: [u8][u8]
        return [(0x7007, bytes([0, 0]), 0)]
    if tipo == 0x7006:      # Acc_TournamentStatus: [u8]
        return [(0x7006, bytes([0]), 0)]
    if tipo == 0x7010:      # Acc_TrEntryTime: [u16]
        return [(0x7010, struct.pack(">H", 0), 0)]
    if tipo == 0x6861:      # jogo manda 6861 [u8][u8][4 bytes]. Resposta com STATUS != 0 pula o download (0x4354b0
        return [(0x6861, b"", 1)]      # -> manda 6144). Com status 0 o jogo le um u32 e entra no download 6862..6865.
    if tipo == 0x6144:      # servidor 6144: [u8][u32][u32]  (0x43e880)
        return [(0x6144, bytes([0]) + struct.pack(">II", 0, 0))]
    if tipo == 0x6145:      # servidor 6145: 5 x u16 + 2 x u32  (0x43e8e0)
        return [(0x6145, struct.pack(">HHHHH", 0, 0, 0, 0, 0) + struct.pack(">II", 0, 0))]
    if tipo == 0x6851:      # servidor 6851: [u8 N][N x string(<=63)]  (0x440340); o jogo depois manda 6149
        return [(0x6851, bytes([1]) + s16(b"CVS2"))]
    if tipo == 0x6149:      # servidor 6149: 4 x u16  (0x43db70); se struct+268 < 100000 o jogo avanca para o passo I
        return [(0x6149, struct.pack(">HHHH", 0, 0, 0, 0))]
    # --- v11: menu principal (CAPCOM 通信ゲームシステム) ---
    if tipo == 0x6207:      # jogo escolheu o lobby [u16 1]. O ELF (0x435ea0) so olha o STATUS: 0 = sucesso, !=0 = erro
        return [(0x6207, b"", 0)]
    # Maquina de "informacoes/download" (0x43cea0, estado gp-18652): o jogo pede, o servidor responde na ordem
    if tipo == 0x6830:      # [u8]
        return [(0x6830, bytes([0]))]
    if tipo == 0x6832:      # [u16]
        return [(0x6832, struct.pack(">H", 0))]
    if tipo == 0x6833:      # [u16 total de blocos][u32]; total 0 = nada para baixar
        return [(0x6833, struct.pack(">HI", 0, 0))]
    if tipo == 0x6835:      # idem
        return [(0x6835, struct.pack(">HI", 0, 0))]
    if tipo == 0x6831:      # [string]
        return [(0x6831, s16(b""))]
    # --- v12: menu do lobby (对戦ルーム / 無差別対戦 ...), tratador 0x4370d0 / 0x4373a0 ---
    if tipo in (0x6205, 0x6303):   # jogo pede [u16 idx]; servidor responde [u16 idx][u16 valor] (contador mostrado no menu)
        idx = corpo[:2] if len(corpo) >= 2 else b"\x00\x01"
        return [(tipo, idx + struct.pack(">H", 0))]
    if tipo == 0x6305:             # jogo escolheu a opcao [u16]; o ELF so olha o STATUS (0 = ok) e vai para a fase 2
        return [(0x6305, b"", 0)]
    if tipo == 0x6306:             # idem (fase seguinte, 0x437440): status 0 = ok
        return [(0x6306, b"", 0)]
    # --- v13/v25: lista de salas (对戦ルーム) com pessoas de verdade (quem entra/sai e tratado em reagir) ---
    if tipo == 0x6401:             # servidor 6401 [u16 total de salas]; o jogo depois pede 6402/6403/6404 por sala
        return [(0x6401, struct.pack(">H", SALAS_TOTAL))]
    if tipo in (0x6402, 0x6403, 0x6404):   # jogo pede [u16 id da sala]
        rid = corpo[:2] if len(corpo) >= 2 else b"\x00\x01"
        n = (rid[0] << 8) | rid[1]
        if tipo == 0x6402:         # [u16 id][string nome]
            return [(0x6402, rid + s16(b"BOT (aguardando)" if bot_na_sala(n) else b"Sala %d" % n))]
        if tipo == 0x6403:         # [u16 id][u16 pessoas na sala]
            return [(0x6403, rid + struct.pack(">H", pessoas_na_sala(n)))]
        return [(0x6404, rid + bytes([0]))]    # [u16 id][u8 estado]
    if tipo == 0x6209:             # jogo pede busca [u16][u16][u16]; resposta = [string] + status 0 (o pareamento e feito em reagir)
        return [(0x6209, s16(b""), 0)]
    if tipo == 0x6408:             # o jogo manda 6408 (sem corpo) periodicamente na lista de salas (0x437f8c): atualizar. Status 0 = ok
        return [(0x6408, b"", 0)]
    return None




# ---------------------------------------------------------------------------------------------
# v25: SALAS e PAREAMENTO entre jogadores reais
#   Sala (对戦ルーム): 6406 [u16 sala][u16] entra | 6501 sai | 6506 = "quantas pessoas na sala" (o jogo so habilita o botao
#   自動選抜対戦 com >= 2) | 6504 [1] = iniciar busca automatica, [0] = cancelar. Quando dois jogadores da MESMA sala estao
#   buscando, o servidor manda 6910 aos dois. Busca fora de sala (6209, 無差別対戦) usa a fila "sem sala".
#   Quem ja esta na sala e avisado na hora de quem entra/sai (6506 com o novo total + uma mensagem no chat 6702).
# ---------------------------------------------------------------------------------------------
SALAS_ONLINE = {n: [] for n in range(1, SALAS_TOTAL + 1)}      # sala -> sessoes
BOT_APOS = 5.0


def bot_na_sala(n):
    return BOT and n == 1


def pessoas_na_sala(n):
    with MATCH_LOCK:
        return len(SALAS_ONLINE.get(n, [])) + (1 if bot_na_sala(n) else 0)


def msg_chat(texto, quem=b"MVC2"):
    """6702 (servidor -> jogo): [string quem][string texto][string][4 bytes]   (formato visto com o BOT)"""
    return s16(quem[:17]) + s16(texto[:60]) + s16(b"") + bytes(4)


def empurrar(ss, tipo, corpo, rotulo_=""):
    """manda uma mensagem NAO pedida para outro jogador (a conexao dele fica em outra thread)"""
    cx = ss.get("cx")
    if cx and ss.get("vivo"):
        try:
            enviar(cx, ss["port"], tipo, corpo, rotulo_ or "aviso")
        except Exception:
            pass


def avisar_sala(n, quem, texto):
    with MATCH_LOCK:
        outros = [o for o in SALAS_ONLINE.get(n, []) if o is not quem]
    cnt = pessoas_na_sala(n)
    for o in outros:
        empurrar(o, 0x6506, struct.pack(">H", cnt), "sala: pessoas=%d" % cnt)
        empurrar(o, 0x6702, msg_chat(nick_de(quem)[:17] + b" " + texto), "sala: aviso")


def entrar_sala(ss, n):
    if n not in SALAS_ONLINE:
        return False
    sair_sala(ss)
    with MATCH_LOCK:
        outros = list(SALAS_ONLINE[n])
        SALAS_ONLINE[n].append(ss)
        ss["sala"] = n
    out("[SALA %d] %s entrou (%d pessoas)" % (n, rotulo(ss), pessoas_na_sala(n)))
    avisar_sala(n, ss, b"entrou na sala")
    if outros:
        texto = b"Na sala: " + b", ".join(nick_de(o)[:12] for o in outros)
    elif bot_na_sala(n):
        texto = b"Aperte o botao da direita para lutar comigo"
    else:
        texto = b"Voce esta sozinho. Aguarde alguem entrar."
    ss.setdefault("pendentes", []).append((time.time() + 1.5, 0x6702, msg_chat(texto, b"BOT" if (bot_na_sala(n) and not outros) else b"MVC2"), "sala: boas-vindas"))
    return True


def sair_sala(ss):
    with MATCH_LOCK:
        n = ss.pop("sala", None)
        if n and ss in SALAS_ONLINE.get(n, []):
            SALAS_ONLINE[n].remove(ss)
        else:
            n = None
    cancelar_busca(ss)
    if n:
        out("[SALA %d] %s saiu (%d pessoas)" % (n, rotulo(ss), pessoas_na_sala(n)))
        avisar_sala(n, ss, b"saiu da sala")


class Cx:
    """socket com trava de envio (varias threads podem escrever na mesma conexao)"""
    def __init__(self, s):
        self.s = s
        self.lock = threading.Lock()

    def sendall(self, d):
        with self.lock:
            self.s.sendall(d)

    def recv(self, n):
        return self.s.recv(n)

    def settimeout(self, t):
        self.s.settimeout(t)

    def getsockname(self):
        return self.s.getsockname()

    def close(self):
        try:
            self.s.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self.s.close()
        except Exception:
            pass


PAR_POR_CODIGO = {}          # codigo da partida (o "numero de telefone" do 6906) -> Par
LINKS = []                   # links de modem virtual abertos pelos PS2 (porta P2P)
P2P_PORT = 9877
P2P_MASH = True
BOT_CODIGO = "0000"          # numero discado quando o oponente e o BOT
MASH_BITS = (0x0010, 0x0020, 0x0040, 0x0080, 0x1000, 0x2000, 0x4000, 0x8000, 0x0400, 0x0800)


def novo_codigo():
    while True:
        c = "7%05d" % random.randint(0, 99999)
        if c not in PAR_POR_CODIGO:
            return c


class Par:
    """uma partida entre dois jogadores humanos. e[0] = lado 1 (quem DISCA), e[1] = lado 2 (quem ATENDE).
    O "fio" entre os dois PS2 e o modem virtual: cada um liga na porta P2P e o servidor repassa os bytes (ponte)."""
    def __init__(self, a, b):
        self.lock = threading.RLock()
        self.e = [{"ss": a, "link": None}, {"ss": b, "link": None}]
        self.fechado = False
        self.criado = time.time()
        self.mid = 0
        self.cont = [0, 0]           # pacotes (de 20 bytes) J1->J2 e J2->J1
        self.ligado = False
        self.codigo = novo_codigo()
        PAR_POR_CODIGO[self.codigo] = self

    def idx(self, ss):
        return 0 if self.e[0]["ss"] is ss else 1

    def outro(self, ss):
        return self.e[1 - self.idx(ss)]["ss"]

    def fechar(self):
        with self.lock:
            if self.fechado:
                return
            self.fechado = True
            links = [e.get("link") for e in self.e]
        PAR_POR_CODIGO.pop(self.codigo, None)
        for lk in links:
            if lk:
                lk.fechar()
        if self.ligado:
            out("[PAR] partida encerrada (pacotes J1->J2: %d, J2->J1: %d)" % tuple(self.cont))
            hist({"ev": "fim", "mid": self.mid, "seg": int(time.time() - self.criado), "pacotes": list(self.cont)})
        else:
            out("[PAR] par desfeito antes da luta (codigo %s)" % self.codigo)


def sair_fila(ss):
    with MATCH_LOCK:
        if ss in FILA:
            FILA.remove(ss)


def cancelar_busca(ss):
    """6504 [0] / saiu da sala: tira da fila (se ja foi pareado nao desfaz)"""
    with MATCH_LOCK:
        if ss in FILA:
            FILA.remove(ss)
            if ss.get("estado") == "espera":
                ss["estado"] = None
                out("[FILA] %s cancelou a busca" % rotulo(ss))


def descr_chave(chave):
    if isinstance(chave, tuple):
        return "busca " + chave[1].hex()
    return ("sala %d" % chave) if chave else "busca"


def info_jogador(s):
    pid = s.get("perfil")
    return {"id": pid.decode("ascii", "replace") if pid else None, "nick": nick_de(s).decode("cp932", "replace"),
            "ip": s.get("cli"), "log": s.get("logarq")}


def _parear(a, b, chave, motivo=""):
    """(com MATCH_LOCK) a = quem esperava (lado 1), b = quem chegou (lado 2): forma o par e manda 6901 aos dois"""
    par = Par(a, b)
    a["par"] = b["par"] = par
    a["role"], b["role"] = 1, 2
    for x in (a, b):
        x["estado"] = "pareado"
        x["send6901"] = True
    PARES_ATIVOS.append(par)
    par.mid = int(time.time() * 1000)
    hist({"ev": "par", "mid": par.mid, "modo": descr_chave(chave), "motivo": motivo, "j1": info_jogador(a), "j2": info_jogador(b)})
    out("[FILA] *** PAR FORMADO (%s%s): %s (lado 1)  x  %s (lado 2) ***" % (descr_chave(chave), (", " + motivo) if motivo else "", rotulo(a), rotulo(b)))


def entrar_fila(ss, chave=0, busca=b""):
    """busca de oponente: 6504 [1] na sala (chave = numero da sala) ou 6209 fora de sala (chave = ("busca", corpo): um modo
    por corpo, ex.: 無差別対戦 e 初心者専用対戦). Se ja tem alguem esperando com a MESMA chave, forma o par."""
    with MATCH_LOCK:
        if ss in FILA:
            FILA.remove(ss)
        if ss.get("par"):
            ss["par"].fechar()
        ss["par"] = None
        ss["pediu6905"] = False
        ss["estado"] = "espera"
        ss["chave"] = chave
        ss["espera_desde"] = time.time()
        for o in list(FILA):
            if not o.get("vivo") or o.get("estado") != "espera":
                FILA.remove(o)
                continue
            if o.get("chave") != chave:
                continue
            FILA.remove(o)
            _parear(o, ss, chave)
            return
        FILA.append(ss)
        out("[FILA] %s esperando oponente (%s). Na fila: %d" % (rotulo(ss), descr_chave(chave), len(FILA)))


def relaxar_fila(ss):
    """Busca fora de sala: se ninguem do MESMO modo apareceu em RELAXAR_APOS s, junta com qualquer outro jogador que tambem
    esteja esperando ha esse tempo (assim a partida acontece mesmo se o 'modo' vier num campo diferente do que supus)."""
    with MATCH_LOCK:
        if ss not in FILA or ss.get("estado") != "espera":
            return
        agora = time.time()
        for o in list(FILA):
            if o is ss or not o.get("vivo") or o.get("estado") != "espera" or not isinstance(o.get("chave"), tuple):
                continue
            if agora - o.get("espera_desde", agora) < RELAXAR_APOS:
                continue
            FILA.remove(o)
            FILA.remove(ss)
            a, b = (o, ss) if o["espera_desde"] <= ss["espera_desde"] else (ss, o)
            _parear(a, b, ss["chave"], "modos diferentes, esperaram %ds" % RELAXAR_APOS)
            return


def blob_n(n):
    """bloco binario [u16 tamanho BE][n bytes]"""
    return struct.pack(">H", n) + bytes(n)


def regras_padrao():
    """48 bytes = o que net_rule_default (0x1a2820) grava no jogo (Acc_RuleData @0x325880 copia em 0x46aeb0)"""
    b = bytearray(48)
    b[0:4] = bytes([1, 1, 2, 2])
    b[27:32] = bytes([11, 7, 16, 28, 40])
    b[32:36] = b"\xff\xff\xff\xff"
    b[36:40] = struct.pack("<I", 0x9fff)
    b[40:44] = b"\xff\xff\xff\xff"
    b[44:48] = struct.pack("<I", 0x9fff)
    return bytes(b)


def online_count():
    with MATCH_LOCK:
        return sum(1 for s in ONLINE if s.get("vivo") and s.get("perfil"))


def dados_oponente(ss):
    """(id, nick, [partidas, vit, der, emp]) do oponente: o outro jogador do par (do perfil dele) ou o BOT"""
    par = ss.get("par")
    if par:
        o = par.outro(ss)
        with MATCH_LOCK:
            p = DB.get(o.get("perfil"))
            if p:
                return o["perfil"], p["hn"], list(p["stats"])
        return b"P%05d" % (o.get("id", 0) % 100000), b"PLAYER%d" % o.get("id", 0), [0, 0, 0, 0]
    return BOT_ID, BOT_NICK, list(BOT_STATS)


def partida(ss, tipo, corpo):
    """Preparo de batalha do CvS2 (ELF: To_ReadyBattle / lobby_act_16_02 @0x31afd0). Servidor manda 6901 (sem corpo).
    jogo 6902 [u8 lado]  -> srv 6902 [u8]: 1 = quem DISCA (e pede o 6906), 2 = quem ATENDE. Com 2 humanos o SERVIDOR decide
    jogo 6903            -> srv 6903 [str ID][str nick][blob 560][5 x u16 (classe, vit, der, emp, 0)]   (perfil do oponente)
    jogo 6904            -> srv 6904 [blob 48 bytes]  (regras)
    jogo 6905            -> srv 6905 [str codigo]
    jogo 6906 (lado 1)   -> srv 6906 [str numero a discar] = codigo da partida; o AVEWRAP2 manda 'DIAL <numero>' a este servidor"""
    par = ss.get("par")
    if tipo == 0x6902:
        pedido = corpo[0] if corpo else 3
        role = ss["role"] if par else 1
        ss["role"] = role
        out("[%s] 6902: %s pediu lado %d -> servidor decidiu %d (%s)" % ("PAR" if par else "BOT", rotulo(ss), pedido, role, "disca" if role == 1 else "atende"))
        return [(0x6902, bytes([role]), 0)]
    if tipo == 0x6903:
        oid, onick, st = dados_oponente(ss)
        out("[PAR] %s vai enfrentar ID=%s nick=%s placar=%s" % (rotulo(ss), oid.decode("ascii", "replace"), onick.decode("cp932", "replace"), st))
        return [(0x6903, s16(oid.ljust(6)[:6]) + s16(onick) + blob_n(560) + struct.pack(">HHHHH", classe_rank(st), st[1], st[2], st[3], 0), 0)]
    if tipo == 0x6904:
        return [(0x6904, s16(regras_padrao()), 0)]
    if tipo == 0x6905:
        ss["pediu6905"] = True
        return [(0x6905, s16(par.codigo.encode() if par else b"CVS2BOT1"), 0)]
    if tipo == 0x6906:
        num = par.codigo if par else BOT_CODIGO
        out("[%s] 6906: %s vai discar %s" % ("PAR" if par else "BOT", rotulo(ss), num))
        return [(0x6906, s16(num.encode()), 0)]
    return None


def reagir(ss, tipo, corpo):
    """Conversa de login + lobby + salas. A decisao e por TIPO de mensagem do jogo (decifrado no ELF).
    O 0x6110 do fim do passo B leva 1 byte = MODO (gp-18208) que decide o proximo passo:
        modo 0 -> passo D (o jogo espera a lista de perfis 0x6111)
        modo 1 ou 2 -> passo C (cadastro: o servidor manda 0x6131..0x6139)
        modo 3 -> passo G (o jogo pede 0x6113 sozinho, com o ID guardado no memory card)"""
    if tipo in (0x6001, 0x613A, 0x6148, 0x6143):
        return []
    # ---- salas e busca ----
    if tipo == 0x6504:
        # na SALA o jogo manda 6504 [1] ao apertar 自動選抜対戦 (iniciar busca) e 6504 [0] ao cancelar
        if corpo[:1] == b"\x01":
            if ss.get("estado") not in ("espera", "pareado"):
                entrar_fila(ss, ss.get("sala") or 0)
        else:
            cancelar_busca(ss)
        return [(0x6504, b"", 0)]
    if tipo == 0x6209 and ss.get("estado") not in ("espera", "pareado"):
        entrar_fila(ss, ("busca", bytes(corpo)), corpo)   # busca fora de sala; cada corpo = um modo (無差別 / 初心者). Resposta 6209 sai em lobby()
        out("[FILA] 6209 modo=%s" % bytes(corpo).hex(" "))
    if tipo == 0x6406:                             # entrar na sala [u16 sala][u16]; o ELF (0x437d20) so olha o STATUS: 0 = ok
        sala = (corpo[0] << 8 | corpo[1]) if len(corpo) >= 2 else 0
        ok = entrar_sala(ss, sala)
        return [(0x6406, b"", 0 if ok else 1)]
    if tipo == 0x6501:                             # sair da sala
        sair_sala(ss)
        return [(0x6501, b"", 0)]
    if tipo == 0x6506:                             # "quantas pessoas na sala" (ELF 0x43f3d0 le 1 u16; 0x4432dc habilita os botoes so com >= 2)
        n = pessoas_na_sala(ss["sala"]) if ss.get("sala") else 1
        return [(0x6506, struct.pack(">H", n), 0)]
    # ---- placar / rank ----
    if tipo == 0x6120:                             # resultado da(s) luta(s) -> soma no placar do perfil
        aplicar_resultado(ss, corpo)
        return []
    if tipo == 0x6144 and ss.get("perfil") in DB:  # [u8 classe de rank][u32 posicao][u32 total]
        pid = ss["perfil"]
        pos, tot = posicao_rank(pid)
        return [(0x6144, bytes([classe_rank(DB[pid]["stats"])]) + struct.pack(">II", pos, tot), 0)]
    if tipo == 0x6145 and ss.get("perfil") in DB:  # [partidas][vitorias][derrotas][empates][?] + 2 x u32
        st = DB[ss["perfil"]]["stats"]
        return [(0x6145, struct.pack(">HHHHH", st[0], st[1], st[2], st[3], 0) + struct.pack(">II", 0, 0), 0)]
    if tipo == 0x6205:                             # contador "参加人数" do menu = jogadores online
        idx = corpo[:2] if len(corpo) >= 2 else b"\x00\x01"
        return [(0x6205, idx + struct.pack(">H", online_count()), 0)]
    r = partida(ss, tipo, corpo)
    if r is not None:
        return r
    if tipo == 0x6110:
        modo = corpo[0] if corpo else 0
        out("[sessao] %s: fim do passo B, modo=%d" % (ss.get("cli"), modo))
        if modo == 0:
            return [lista_perfis(ss)]
        if modo in (1, 2):
            return [(0x6131, b"")]
        return []
    if 0x6131 <= tipo <= 0x6138:             # passo C: o jogo respondeu um campo do cadastro -> proximo
        return [(tipo + 1, b"")]
    if tipo == 0x6139:                       # ultimo do passo C -> passo D
        return [lista_perfis(ss)]
    if tipo == 0x6112:                       # cadastro de nick novo: grava em perfis.json e devolve o ID novo
        novo = cadastrar_perfil(ss, corpo)
        return [(0x6112, s16(novo), 0)]
    if tipo == 0x6113:                       # passo G: jogo pede os dados do perfil -> 6114..6120 e 6118 (fim)
        escolher_perfil(ss, corpo)
        return list(G_SEQ)
    r = lobby(tipo, corpo)
    if r is not None:
        return r
    return resposta(tipo, corpo)


def enviar(conn, port, tipo, corpo, rotulo="", status=0):
    m = frame(tipo, corpo, status=status)
    conn.sendall(m)
    out("[TCP %d] >>> servidor envia %04x %s  (%d bytes de corpo)%s" % (
        port, tipo, NOMES.get(tipo, ""), len(corpo), ("  [" + rotulo + "]") if rotulo else ""))
    out("[TCP %d]     %s" % (port, m.hex(" ")))


def handle(conn, addr, port, idle):
    out("[TCP %d] conexao de %s:%d" % (port, addr[0], addr[1]))
    buf = b""
    conn.settimeout(0.3)
    vistos = []
    CONTADOR[0] += 1
    ss = {"fase": "A", "ip": conn.getsockname()[0], "cli": addr[0], "vivo": True,
          "id": CONTADOR[0], "nome": b"PLAYER%d" % CONTADOR[0], "cx": conn, "port": port, "logf": None}
    TL.logf = None
    with MATCH_LOCK:
        ONLINE.append(ss)
    try:
        enviar(conn, port, 0x6001, b"", "inicio"); time.sleep(0.2)
        enviar(conn, port, 0x6004, b"", "inicio"); time.sleep(0.2)
        enviar(conn, port, 0x6101, s16(TOKEN), "inicio do login")
        t_rx = time.time(); t_ping = time.time()
        while True:
            try:
                data = conn.recv(4096)
                if data == b"":
                    break
            except socket.timeout:
                data = None
            agora = time.time()
            if ss.pop("send6901", False):
                out("[FILA] servidor envia 6901 (partida encontrada) para %s" % rotulo(ss))
                enviar(conn, port, 0x6901, b"", "partida encontrada")
            pend = ss.get("pendentes")
            if pend:
                for x in [x for x in pend if x[0] <= agora]:
                    pend.remove(x)
                    enviar(conn, port, x[1], x[2], x[3])
            if RELAXAR_APOS > 0 and ss.get("estado") == "espera" and isinstance(ss.get("chave"), tuple) and agora - ss.get("espera_desde", agora) >= RELAXAR_APOS:
                relaxar_fila(ss)
            if BOT and ss.get("estado") == "espera" and agora - ss.get("espera_desde", agora) >= BOT_APOS:
                go = False
                with MATCH_LOCK:
                    if ss in FILA and ss.get("estado") == "espera":
                        FILA.remove(ss)
                        ss["estado"] = "bot"
                        go = True
                if go:
                    out("[BOT] ninguem apareceu em %.0fs: BOT aceita a luta (6901) para %s" % (BOT_APOS, rotulo(ss)))
                    enviar(conn, port, 0x6901, b"", "BOT")
            if data:
                t_rx = agora
                buf += data
                frames, buf = split_frames(buf)
                for f in frames:
                    tipo = (f[2] << 8) | f[3]
                    corpo = f[12:]
                    vistos.append(tipo)
                    conhecido = tipo in NOMES
                    if tipo == 0x6101 and not ss.get("logf"):
                        abrir_log_sessao(ss)
                    out("[TCP %d] <<< jogo envia %04x %s  classe=%02x corpo=%d bytes%s" % (
                        port, tipo, NOMES.get(tipo, "*** NOVO ***"), f[1], len(corpo), "" if conhecido else "   <== PROXIMA ETAPA A DECIFRAR"))
                    out("[TCP %d]     %s" % (port, f.hex(" ")))
                    if tipo == 0x6002:
                        out("[TCP %d]     (o jogo desistiu da conexao)" % port)
                    r = reagir(ss, tipo, corpo)
                    for it in (r or []):
                        enviar(conn, port, it[0], it[1], "resposta", it[2] if len(it) > 2 else 0)
                        time.sleep(0.15)
                continue
            if agora - t_ping >= 45:
                enviar(conn, port, 0x6001, b"", "ping"); t_ping = agora
            if agora - t_rx > idle:
                out("[TCP %d] sem atividade ha %ds: encerrando" % (port, idle))
                break
        out("[TCP %d] resumo - mensagens do jogo nesta conexao: %s" % (port, ", ".join("%04x" % t for t in vistos) or "nenhuma"))
    except Exception as e:
        out("[TCP %d] erro: %s" % (port, e))
    finally:
        out("[TCP %d] conexao encerrada" % port)
        ss["vivo"] = False
        sair_sala(ss)                  # tira da sala/fila e avisa quem ficou
        sair_fila(ss)
        if ss.get("par") and not ss.get("pediu6905"):
            ss["par"].fechar()         # saiu antes de a partida ser preparada
        with MATCH_LOCK:
            if ss in ONLINE:
                ONLINE.remove(ss)
        conn.close()
        fechar_log_depois(ss)



# ---------------------------------------------------------------------------------------------
# v27 - MODEM VIRTUAL (a luta do CvS2 passa pela camada de modem Com*; o AVEWRAP2 liga aqui). ELF: modem_connect_* @0x19b500,
# match_IO_* @0x19c460. Handshake em TEXTO entre os dois PS2 (a ponte so repassa):
#   quem disca:  "\nPING\n" ... ate 8 PONG ... "START\n"      quem atende: responde "PONG\n" a cada PING e espera START
#   sincronia:   "\nREADY\n" -> "\nOK\n" -> "START\n"
#   luta:        pacotes de 20 bytes por frame, little-endian: +0 entrada A (u16) +4 entrada B +8 (tipo de controle | flags<<8)
#                +12 frame (6 bits, comeca em 1); lockstep: o jogo exige o pacote do oponente com o MESMO numero de frame.
# ---------------------------------------------------------------------------------------------
def pacote20(in0, in1, h2, frame):
    return struct.pack("<HHHHHHHHI", in0 & 0xffff, 0, in1 & 0xffff, 0, h2 & 0xffff, 0, frame & 0x3f, 0, 0)


class Link:
    """uma conexao de modem virtual (um PS2)"""
    def __init__(self, conn, addr):
        self.cx = Cx(conn)
        self.ip = addr[0]
        self.buf = b""
        self.estado = "hello"        # hello -> tocando -> atendido -> ponte
        self.par = None
        self.criado = time.time()
        self.atendeu = threading.Event()
        self.fim = threading.Event()

    def ctl(self, txt):
        try:
            self.cx.sendall(txt.encode("ascii") + b"\n")
        except OSError:
            pass

    def ler_linha(self):
        """None = timeout; levanta EOFError se o PS2 fechou"""
        while b"\n" not in self.buf:
            try:
                d = self.cx.recv(4096)
            except socket.timeout:
                return None
            if not d:
                raise EOFError()
            self.buf += d
            if len(self.buf) > 400:
                self.buf = b""
        i = self.buf.index(b"\n")
        linha, self.buf = self.buf[:i], self.buf[i + 1:]
        return linha.strip(b"\r\x00 ").decode("ascii", "replace")

    def fechar(self):
        self.fim.set()
        self.cx.close()


def _fio(par, i, a, b):
    """repassa tudo que chega de a para b (i = 0: J1->J2, 1: J2->J1)"""
    try:
        while not par.fechado:
            try:
                d = a.cx.recv(4096)
            except socket.timeout:
                continue
            if not d:
                break
            b.cx.sendall(d)
            par.cont[i] += max(1, len(d) // 20)
    except (OSError, EOFError):
        pass
    finally:
        par.fechar()


def modem_discar(lk, numero):
    """o PS2 'lk' (lado 1) discou. Espera o outro PS2 ligar o modem, toca (RING), espera ATA e liga os dois (ponte)."""
    cod = numero.split(",")[-1].strip()
    if cod == BOT_CODIGO:
        return modem_bot(lk)
    par = PAR_POR_CODIGO.get(cod)
    if not par or par.fechado:
        out("[MODEM] %s discou %r: nao ha partida com esse codigo -> NO CARRIER" % (lk.ip, numero))
        lk.ctl("NOCARRIER")
        return
    ic = 0 if par.e[0]["ss"].get("role", 1) == 1 else 1
    par.e[ic]["link"] = lk
    lk.par = par
    resp = par.e[1 - ic]["ss"]
    out("[MODEM] %s (lado 1) discou %s: esperando o modem de %s (%s) ..." % (lk.ip, cod, rotulo(resp), resp.get("cli")))
    t0 = time.time()
    alvo = None
    while time.time() - t0 < 50 and not par.fechado and not lk.fim.is_set():
        with MATCH_LOCK:
            cand = [x for x in LINKS if x is not lk and x.estado == "hello" and x.par is None]
            alvo = next((x for x in cand if x.ip == resp.get("cli")), None)
            if alvo is None and time.time() - t0 > 15 and len(cand) == 1:
                alvo = cand[0]                      # IP diferente (NAT): se so existe um candidato, e ele
            if alvo is not None:
                alvo.par = par
                alvo.estado = "tocando"
        if alvo is not None:
            break
        time.sleep(0.25)
    if alvo is None:
        out("[MODEM] o lado 2 nao ligou o modem a tempo -> NO CARRIER")
        lk.ctl("NOCARRIER")
        par.fechar()
        return
    par.e[1 - ic]["link"] = alvo
    out("[MODEM] RING para %s ..." % alvo.ip)
    alvo.ctl("RING")
    if not alvo.atendeu.wait(25):
        out("[MODEM] o lado 2 nao atendeu (ATA) -> NO CARRIER")
        lk.ctl("NOCARRIER")
        par.fechar()
        return
    lk.estado = alvo.estado = "ponte"
    par.ligado = True
    par.mid = par.mid or int(time.time() * 1000)
    out("[PAR] === PONTE LIGADA: %s (disca)  <->  %s (atende) ===" % (rotulo(par.e[ic]["ss"]), rotulo(resp)))
    for x in (lk, alvo):
        x.cx.settimeout(1.0)
    lk.ctl("CONNECT")
    alvo.ctl("CONNECT")
    t = threading.Thread(target=_fio, args=(par, 1 - ic, alvo, lk), daemon=True)
    t.start()
    _fio(par, ic, lk, alvo)


def modem_bot(lk):
    """o oponente e o BOT: ele 'atende' sozinho e fala o protocolo da luta (handshake de texto + pacotes de 20 bytes)"""
    out("[MODEM] %s discou o BOT -> CONNECT" % lk.ip)
    lk.ctl("CONNECT")
    lk.cx.settimeout(1.0)
    buf = lk.buf
    lk.buf = b""
    fase, pings, n_in, bot_frame, esperado = "ping", 0, 0, 1, None
    mash = {"bit": 0}
    ultimo = time.time()
    try:
        while not lk.fim.is_set():
            if not buf or (fase != "bin" and b"\n" not in buf) or (fase == "bin" and len(buf) < 20):
                try:
                    d = lk.cx.recv(4096)
                except socket.timeout:
                    if time.time() - ultimo > 90:
                        break
                    continue
                if not d:
                    break
                ultimo = time.time()
                buf += d
            while True:
                if fase in ("ping", "sync"):
                    i = buf.find(b"\n")
                    if i < 0:
                        break
                    linha = buf[:i].strip(b"\r\n\x00 "); buf = buf[i + 1:]
                    if not linha:
                        continue
                    t = linha.decode("ascii", "replace")
                    if t == "PING":
                        pings += 1
                        lk.cx.sendall(b"PONG\n")
                    elif t == "START" and fase == "ping":
                        fase = "sync"
                        out("[BOT] START (apos %d PINGs) -> sincronizacao" % pings)
                    elif t == "READY":
                        fase = "sync"
                        lk.cx.sendall(b"\nOK\n")
                    elif t == "START" and fase == "sync":
                        fase = "bin"
                        out("[BOT] === LUTA COMECOU (pacotes de 20 bytes) ===")
                    else:
                        out("[BOT] linha inesperada: %r" % t)
                else:
                    if len(buf) < 20:
                        break
                    p, buf = buf[:20], buf[20:]
                    in0, _, in1, _, h2, _, fr, _, extra = struct.unpack("<HHHHHHHHI", p)
                    n_in += 1
                    if esperado is not None and (fr & 0x3f) != esperado:
                        out("[BOT] AVISO: frame %d recebido, esperava %d" % (fr, esperado))
                    esperado = ((fr & 0x3f) + 1) & 0x3f
                    if n_in <= 5 or n_in % 600 == 0:
                        out("[BOT] pacote #%d frame=%d in0=%04x in1=%04x h2=%04x" % (n_in, fr, in0, in1, h2))
                    ph = n_in % 24
                    if ph == 1:
                        mash["bit"] = random.choice(MASH_BITS)
                    bot_in = mash["bit"] if (P2P_MASH and ph < 4) else 0
                    lk.cx.sendall(pacote20(bot_in, 0, h2 & ~0x0010, bot_frame))
                    bot_frame = (bot_frame + 1) & 0x3f
    except (OSError, EOFError) as e:
        out("[BOT] link encerrado: %s" % e)
    finally:
        out("[BOT] === fim (fase=%s, pacotes do PS2=%d) ===" % (fase, n_in))


def modem_link(conn, addr):
    try:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass
    conn.settimeout(1.0)
    lk = Link(conn, addr)
    with MATCH_LOCK:
        LINKS.append(lk)
    out("[MODEM] %s ligou o modem virtual (porta %d)" % (addr[0], P2P_PORT))
    try:
        while not lk.fim.is_set():
            try:
                linha = lk.ler_linha()
            except EOFError:
                break
            if linha is None:
                if time.time() - lk.criado > 900 and lk.estado == "hello":
                    out("[MODEM] %s: link ocioso ha 15 min, fechando" % lk.ip)
                    break
                continue
            if not linha:
                continue
            if linha == "HELLO":
                continue
            if linha.startswith("DIAL"):
                modem_discar(lk, linha[4:].strip())
                break
            if linha == "ANSWER":
                if lk.estado == "tocando":
                    lk.estado = "atendido"
                    lk.atendeu.set()
                    lk.fim.wait()               # a ponte (thread de quem discou) assume o socket
                else:
                    out("[MODEM] %s mandou ANSWER sem RING" % lk.ip)
                    lk.ctl("NOCARRIER")
                break
            out("[MODEM] %s: linha de controle desconhecida %r" % (lk.ip, linha))
    except OSError as e:
        out("[MODEM] %s: %s" % (lk.ip, e))
    finally:
        if lk.par is not None:
            lk.par.fechar()
        with MATCH_LOCK:
            if lk in LINKS:
                LINKS.remove(lk)
        lk.cx.close()
        out("[MODEM] %s: link encerrado" % lk.ip)


def modem_listener(port):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.listen(16)
    out("escutando TCP %d (modem virtual: luta jogador x jogador / BOT)" % port)
    while True:
        c, a = s.accept()
        threading.Thread(target=modem_link, args=(c, a), daemon=True).start()


def tcp_listener(port, idle):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.listen(5)
    out("escutando TCP %d" % port)
    while True:
        c, a = s.accept()
        threading.Thread(target=handle, args=(Cx(c), a, port, idle), daemon=True).start()


def local_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ips.add(s.getsockname()[0]); s.close()
    except Exception:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


def udp_logger(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    out("escutando logs UDP %d (mensagens do PS2)" % port)
    last = {}
    while True:
        d, a = s.recvfrom(2048)
        if d.startswith(b"MVC2-DISCOVER"):
            s.sendto(b"MVC2-SERVER", a)
            continue
        t = d.decode("latin-1").rstrip()
        if "PppGetUsbDeviceId" in t:
            continue
        key = "hb" if "hb:" in t else ("cnt" if "cnt:" in t else None)
        if key:
            if last.get(key) == t:
                continue
            last[key] = t
        if "TcpStat" in t or "TcpSend h=" in t or ("McsReceive" in t and "062102800280" in t):
            continue
        out("[PS2 %s] %s" % (a[0], t), ip=a[0])


# ---------------------------------------------------------------------------------------------
# v26: PAINEL WEB (logs das partidas, historico, ranking, quem esta online). Roda junto com o servidor, porta --web-porta (8787).
#   Usuario "admin" + senha (arquivo web_senha.txt, gerada sozinha na 1a vez). So le arquivos da pasta logs/, capture.log e perfis.json.
# ---------------------------------------------------------------------------------------------
WEB_PORTA = 8787
WEB_SENHA = ""
WEB_FALHAS = {}


def web_carregar_senha(arg):
    global WEB_SENHA
    if arg:
        WEB_SENHA = arg
    else:
        try:
            with open(WEB_SENHA_ARQ, encoding="utf-8") as f:
                WEB_SENHA = f.read().strip()
        except Exception:
            WEB_SENHA = ""
        if not WEB_SENHA:
            alfa = string.ascii_letters + string.digits
            WEB_SENHA = "".join(secrets.choice(alfa) for _ in range(14))
            with open(WEB_SENHA_ARQ, "w", encoding="utf-8") as f:
                f.write(WEB_SENHA + "\n")
    try:
        with open(WEB_INFO_ARQ, "w", encoding="utf-8") as f:
            f.write("%d %s\n" % (WEB_PORTA, WEB_SENHA))
        os.chmod(WEB_INFO_ARQ, 0o600); os.chmod(WEB_SENHA_ARQ, 0o600)
    except Exception:
        pass


def quando(t):
    return datetime.fromtimestamp(t, FUSO).strftime("%d/%m %H:%M:%S")


def ler_hist(maxn=3000):
    try:
        with open(HIST_ARQ, encoding="utf-8") as f:
            linhas = f.readlines()[-maxn:]
    except Exception:
        return []
    r = []
    for l in linhas:
        try:
            r.append(json.loads(l))
        except Exception:
            pass
    return r


def montar_partidas(evs):
    """junta os eventos par/fim/resultado do historico em uma linha por partida (mais nova primeiro)"""
    ps = {}
    ordem = []
    for e in evs:
        if e.get("ev") == "par":
            ps[e["mid"]] = {"mid": e["mid"], "t": e["t"], "modo": e.get("modo", ""), "j1": e["j1"], "j2": e["j2"], "fim": None, "res": {}}
            ordem.append(e["mid"])
        elif e.get("ev") == "fim" and e.get("mid") in ps:
            ps[e["mid"]]["fim"] = e
        elif e.get("ev") == "resultado":
            for mid in reversed(ordem):
                p = ps[mid]
                if p["t"] <= e["t"] and e.get("perfil") in (p["j1"]["id"], p["j2"]["id"]) and e["perfil"] not in p["res"]:
                    p["res"][e["perfil"]] = e
                    break
    return [ps[m] for m in reversed(ordem)]


def arquivos_web():
    """nome -> caminho dos arquivos que o painel pode mostrar/baixar"""
    m = {"capture.log": os.path.abspath(LOG.name), "perfis.json": PERFIS_ARQ, "partidas.jsonl": HIST_ARQ}
    try:
        for n in os.listdir(LOGDIR):
            if n.startswith("sessao_") and n.endswith(".log"):
                m[n] = os.path.join(LOGDIR, n)
    except Exception:
        pass
    return {k: v for k, v in m.items() if os.path.isfile(v)}


def nick_do_arquivo(caminho):
    try:
        with open(caminho, encoding="utf-8", errors="replace") as f:
            txt = f.read(200000)
        m = re.search(r"entrou como ID=(.{1,6}) HN=(.*?)\s+placar=", txt)
        return m.group(2) if m else ""
    except Exception:
        return ""


def status():
    with MATCH_LOCK:
        online = [{"nick": nick_de(s).decode("cp932", "replace"), "id": (s.get("perfil") or b"").decode("ascii", "replace"),
                   "ip": s.get("cli"), "sala": s.get("sala"), "estado": s.get("estado")} for s in ONLINE if s.get("vivo")]
        fila = [{"nick": nick_de(s).decode("cp932", "replace"), "modo": descr_chave(s.get("chave")),
                 "espera_s": int(time.time() - s.get("espera_desde", time.time()))} for s in FILA]
        salas = {str(n): [nick_de(s).decode("cp932", "replace") for s in l] for n, l in SALAS_ONLINE.items() if l}
        PARES_ATIVOS[:] = [p for p in PARES_ATIVOS if not p.fechado]
        ativos = [{"mid": p.mid, "j1": nick_de(p.e[0]["ss"]).decode("cp932", "replace"), "j2": nick_de(p.e[1]["ss"]).decode("cp932", "replace"),
                   "seg": int(time.time() - p.criado), "pacotes": list(p.cont)} for p in PARES_ATIVOS]
    return {"online": online, "fila": fila, "salas": salas, "partidas_ativas": ativos, "agora": quando(time.time())}


def ranking_web(n=20):
    with MATCH_LOCK:
        ids = [i for i, p in DB.items() if p["stats"][0] > 0]
        ids.sort(key=lambda i: (-(DB[i]["stats"][1] - DB[i]["stats"][2]), -DB[i]["stats"][1], DB[i]["stats"][0], i))
        return [(k + 1, i, DB[i]["hn"], list(DB[i]["stats"])) for k, i in enumerate(ids[:n])]


def humano(n):
    return "%.0f KB" % (n / 1024) if n < 1048576 else "%.1f MB" % (n / 1048576)


WEB_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--tx:#1b1f24;--mu:#66707c;--bd:#dfe3e8;--ac:#0b62d6;--ok:#16794a;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#10141a;--card:#181e26;--tx:#e6eaef;--mu:#93a0ae;--bd:#2a323d;--ac:#6aa8ff;--ok:#5fd39a;--bad:#ff8a80}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.45 system-ui,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 48px}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 10px}
.sub{color:var(--mu);margin:0 0 18px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px 14px}.card b{display:block;font-size:26px}.card span{color:var(--mu);font-size:13px}
.tb{background:var(--card);border:1px solid var(--bd);border-radius:10px;overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:560px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--bd);white-space:nowrap}th{color:var(--mu);font-weight:600;font-size:13px}tr:last-child td{border-bottom:0}
a{color:var(--ac);text-decoration:none}a:hover{text-decoration:underline}.mu{color:var(--mu)}.ok{color:var(--ok)}.bad{color:var(--bad)}
.btn{display:inline-block;background:var(--ac);color:#fff;padding:9px 14px;border-radius:8px;font-weight:600}.btn:hover{text-decoration:none;opacity:.9}
.vazio{padding:14px;color:var(--mu)}
"""


def _t(linhas, cab, vazio):
    if not linhas:
        return '<div class="tb"><div class="vazio">%s</div></div>' % vazio
    return '<div class="tb"><table><tr>%s</tr>%s</table></div>' % (
        "".join("<th>%s</th>" % c for c in cab), "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in l) for l in linhas))


def pagina():
    e = _html.escape
    st = status()
    evs = ler_hist()
    partidas = montar_partidas(evs)
    cards = [(len(st["online"]), "online agora"), (len(st["fila"]), "buscando oponente"), (len(st["partidas_ativas"]), "partidas em andamento"),
             (len(partidas), "partidas registradas")]
    h = ['<!doctype html><html lang="pt-br"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
         '<meta http-equiv="refresh" content="30"><title>MvC2 Online - Painel</title><style>%s</style></head><body><main>' % WEB_CSS,
         '<h1>MvC2 Online - Painel</h1><p class="sub">Atualiza sozinho a cada 30 s. Horario de Brasilia: %s</p>' % e(st["agora"]),
         '<div class="cards">%s</div>' % "".join('<div class="card"><b>%d</b><span>%s</span></div>' % c for c in cards)]
    h.append('<h2>Baixar</h2><p><a class="btn" href="/tudo.zip">Baixar tudo (.zip)</a> &nbsp; '
             '<a href="/arquivo/capture.log">capture.log</a> &middot; <a href="/arquivo/partidas.jsonl">partidas.jsonl</a> &middot; '
             '<a href="/arquivo/perfis.json">perfis.json</a></p>')
    h.append("<h2>Online agora</h2>" + _t([[e(o["nick"]), e(o["id"]), e(o["ip"] or ""), ("sala %s" % o["sala"]) if o["sala"] else "-", e(o["estado"] or "-")]
                                           for o in st["online"]], ["Nick", "ID", "IP", "Sala", "Estado"], "Ninguem online."))
    h.append("<h2>Buscando oponente</h2>" + _t([[e(o["nick"]), e(o["modo"]), "%d s" % o["espera_s"]] for o in st["fila"]],
                                               ["Nick", "Modo", "Esperando"], "Ninguem na fila."))
    if st["partidas_ativas"]:
        h.append("<h2>Partidas em andamento</h2>" + _t([[e(p["j1"]), e(p["j2"]), "%d s" % p["seg"], "%d / %d" % tuple(p["pacotes"])] for p in st["partidas_ativas"]],
                                                       ["Jogador 1", "Jogador 2", "Tempo", "Pacotes (1 -> 2 / 2 -> 1)"], ""))
    linhas = []
    for p in partidas[:60]:
        res = " &middot; ".join("%s: %dV %dD %dE" % (e(r["nick"]), r["v"], r["d"], r["e"]) for r in p["res"].values()) or '<span class="mu">sem resultado ainda</span>'
        fim = p["fim"]
        dur = ("%d s" % fim["seg"]) if fim else "..."
        pk = ("%d / %d" % tuple(fim["pacotes"])) if fim else "-"
        lg = " ".join('<a href="/ver/%s">log %s</a>' % (e(urllib.parse.quote(j["log"])), n) for n, j in (("J1", p["j1"]), ("J2", p["j2"])) if j.get("log"))
        linhas.append([quando(p["t"]), e(p["modo"]), e(p["j1"]["nick"]), e(p["j2"]["nick"]), dur, pk, res, lg or "-"])
    h.append("<h2>Partidas recentes</h2>" + _t(linhas, ["Quando", "Modo", "Jogador 1", "Jogador 2", "Duracao", "Pacotes", "Resultado (cada jogador informa no proximo login)", "Logs"],
                                              "Nenhuma partida ainda."))
    h.append("<h2>Ranking</h2>" + _t([[str(pos), e(nick_texto(hn)), e(i.decode("ascii", "replace")), str(s[0]), "%d / %d / %d" % (s[1], s[2], s[3]), str(classe_rank(s))]
                                     for pos, i, hn, s in ranking_web()], ["Pos", "Nick", "ID", "Partidas", "V / D / E", "Classe"], "Ninguem lutou ainda."))
    arqs = arquivos_web()
    sess = sorted((n for n in arqs if n.startswith("sessao_")), reverse=True)[:100]
    linhas = []
    for n in sess:
        c = arqs[n]
        linhas.append([e(n), e(nick_do_arquivo(c)) or '<span class="mu">-</span>', humano(os.path.getsize(c)), quando(os.path.getmtime(c)),
                       '<a href="/ver/%s">ver</a> &middot; <a href="/arquivo/%s">baixar</a>' % ((e(urllib.parse.quote(n)),) * 2)])
    h.append("<h2>Logs por conexao (um por login de cada jogador)</h2>" + _t(linhas, ["Arquivo", "Jogador", "Tamanho", "Modificado", ""], "Nenhum log ainda."))
    h.append("</main></body></html>")
    return "".join(h)


class WebHandler(BaseHTTPRequestHandler):
    server_version = "MVC2Painel"

    def log_message(self, *a):
        pass

    def _auth(self):
        ip = self.client_address[0]
        agora = time.time()
        falhas = [t for t in WEB_FALHAS.get(ip, []) if agora - t < 300]
        WEB_FALHAS[ip] = falhas
        if len(falhas) >= 10:
            self.send_error(429, "muitas tentativas, espere 5 minutos")
            return False
        h = self.headers.get("Authorization", "")
        ok = False
        if h.startswith("Basic "):
            try:
                u, _, p = base64.b64decode(h[6:]).decode("utf-8", "replace").partition(":")
                ok = hmac.compare_digest(u.encode(), b"admin") and hmac.compare_digest(p.encode(), WEB_SENHA.encode())
            except Exception:
                ok = False
        if not ok:
            if h:
                falhas.append(agora)
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="MvC2 Online"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        return True

    def _enviar(self, dados, tipo, extra=None):
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        if not self._auth():
            return
        caminho = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        try:
            if caminho == "/":
                self._enviar(pagina().encode("utf-8"), "text/html; charset=utf-8")
            elif caminho == "/status.json":
                self._enviar(json.dumps(status(), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            elif caminho == "/tudo.zip":
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    for n, c in arquivos_web().items():
                        z.write(c, n)
                self._enviar(buf.getvalue(), "application/zip", {"Content-Disposition": 'attachment; filename="mvc2_logs_%s.zip"' % datetime.now(FUSO).strftime("%Y%m%d_%H%M")})
            elif caminho.startswith("/arquivo/") or caminho.startswith("/ver/"):
                baixar = caminho.startswith("/arquivo/")
                nome = caminho.split("/", 2)[2]
                c = arquivos_web().get(nome)                       # so nomes da lista: nada de caminhos livres
                if not c:
                    self.send_error(404)
                    return
                with open(c, "rb") as f:
                    if baixar:
                        dados = f.read()
                    else:                                          # ver: ultimos 600 KB
                        f.seek(0, 2)
                        tam = f.tell()
                        f.seek(max(0, tam - 600000))
                        dados = (b"[... inicio omitido, baixe o arquivo inteiro ...]\n" if tam > 600000 else b"") + f.read()
                self._enviar(dados, "text/plain; charset=utf-8", {"Content-Disposition": 'attachment; filename="%s"' % nome} if baixar else None)
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as ex:
            out("[web] erro: %s" % ex)
            try:
                self.send_error(500)
            except Exception:
                pass


def web_iniciar():
    if WEB_PORTA <= 0:
        out("[web] painel desligado")
        return
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", WEB_PORTA), WebHandler)
    except Exception as ex:
        out("[web] NAO consegui abrir a porta %d (%s): painel desligado, o servidor do jogo segue normal" % (WEB_PORTA, ex))
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out("[web] painel em http://IP-DO-SERVIDOR:%d/  usuario: admin  senha: (arquivo %s)" % (WEB_PORTA, WEB_SENHA_ARQ))


def limpar_logs_velhos(dias):
    """apaga logs de sessao mais velhos que 'dias' (a cada hora)"""
    while True:
        try:
            limite = time.time() - dias * 86400
            for n in os.listdir(LOGDIR):
                c = os.path.join(LOGDIR, n)
                if n.startswith("sessao_") and os.path.getmtime(c) < limite:
                    os.remove(c)
        except Exception:
            pass
        time.sleep(3600)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ports", default="9876")
    ap.add_argument("--logport", type=int, default=9999)
    ap.add_argument("--idle", type=int, default=120, help="segundos de silencio antes de encerrar")
    ap.add_argument("--sem-bot", action="store_true", help="(ignorado: desde a v25 o BOT ja vem desligado)")
    ap.add_argument("--com-bot", action="store_true", help="liga o BOT (teste sozinho): ele aceita a luta se ninguem aparecer")
    ap.add_argument("--bot-apos", type=float, default=5.0, help="segundos esperando um humano antes do BOT aceitar (com --com-bot)")
    ap.add_argument("--web-porta", type=int, default=8787, help="porta do painel web de logs (0 = desliga)")
    ap.add_argument("--web-senha", default=None, help="senha do painel (padrao: gerada sozinha em web_senha.txt)")
    ap.add_argument("--relaxar-apos", type=float, default=20.0, help="busca fora de sala: depois de N s junta modos diferentes (0 = nunca)")
    ap.add_argument("--guardar-dias", type=int, default=30, help="dias que os logs de sessao ficam guardados")
    ap.add_argument("--ip-publico", default=None, help="IP publico deste servidor (OBRIGATORIO no Oracle/internet; na LAN pode omitir)")
    ap.add_argument("--nick-bot", default="BOT", help="ID/nick que o BOT mostra na tela VS (ate 17 bytes)")
    ap.add_argument("--p2p-port", type=int, default=9877, help="porta TCP do modem virtual (a mesma de P2P_PORT em iop/avewrap/config.h)")
    ap.add_argument("--sem-mash", action="store_true", help="o BOT fica parado na luta (sem apertar botoes aleatorios)")
    a = ap.parse_args()
    P2P_PORT = a.p2p_port
    P2P_MASH = not a.sem_mash
    BOT = a.com_bot
    BOT_APOS = a.bot_apos
    IP_PUBLICO = a.ip_publico
    RELAXAR_APOS = a.relaxar_apos
    WEB_PORTA = a.web_porta
    BOT_NICK = a.nick_bot.encode("cp932", "replace")[:17] or b"BOT"
    BOT_ID = (unicodedata.normalize("NFKC", a.nick_bot).encode("ascii", "ignore")[:8] or BOT_NICK[:8])
    out("[perfis] arquivo: %s | %d perfis: %s" % (PERFIS_ARQ, len(DB), ", ".join("%s/%s" % (i.decode(), p["hn"].decode("cp932", "replace")) for i, p in DB.items())))
    for p in a.ports.split(","):
        threading.Thread(target=tcp_listener, args=(int(p), a.idle), daemon=True).start()
    threading.Thread(target=udp_logger, args=(a.logport,), daemon=True).start()
    web_carregar_senha(a.web_senha)
    web_iniciar()
    threading.Thread(target=limpar_logs_velhos, args=(a.guardar_dias,), daemon=True).start()
    threading.Thread(target=modem_listener, args=(P2P_PORT,), daemon=True).start()
    out("=== SERVIDOR CvS2 VERSAO 27 (jogador x jogador: 無差別/初心者 + salas, ponte de modem virtual na porta %d, nick/ID, placar, rank, painel web; BOT: %s) ===" % (P2P_PORT, "LIGADO" if BOT else "desligado"))
    out("IPs deste PC: " + ", ".join(local_ips()))
    out("modem virtual: os PS2 ligam em %s:%d (config.h: SERVER_IP / P2P_PORT)" % (IP_PUBLICO or "(IP deste PC)", P2P_PORT))
    out("pronto. Aguardando o PS2... (Ctrl+C para sair)")
    while True:
        time.sleep(1)
