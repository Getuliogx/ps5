#!/usr/bin/env python3
"""
Servidor do online de Capcom vs. SNK 2 Millionaire Fighting 2001 (PS2, Japao).  Base: servidor do MvC2 v23.

ATENCAO (CvS2): a analise do ELF mostrou que o CvS2 usa a MESMA familia de mensagens do MvC2 (0x6001, 0x6004, 0x6101,
0x6820, ... mesmo cabecalho de 12 bytes e mesmas portas 9876/9700), entao a logica do MvC2 serve de ponto de partida.
Mas NADA disso foi testado no CvS2 ainda: o que o jogo mandar de diferente aparece como NOVO no log (capture.log).

Executa a conversa de LOGIN que foi decifrada no ELF do jogo (veja NOTAS_TECNICAS.md):

  Servidor ao conectar:  6001 (ping)  6004 (pronto)  6101 (token de 8 bytes)
  Passo A (CvS2): jogo 6101 -> servidor 6110 (sem 6102/6103; confirmado no ELF 0x315000)
  Passo B:   jogo 6820(4 bytes) -> servidor 6820 + 6822 ;  jogo 6110 (fim do passo B)
  Fim do B:  jogo 6110 com 1 byte = MODO. modo 0 -> passo D | modo 1,2 -> passo C | modo 3 -> passo G
  Passo C:   servidor manda 6131..6139, uma de cada vez; o jogo responde cada uma com os dados do cadastro
  Passo D:   servidor manda 6111 (lista de perfis: 1 perfil "PLAYER")   -> o jogo mostra a escolha de perfil (aperte X)
  Passo E/F: jogo envia 6112 (perfil novo)  -> servidor 6112 [nome]
  Passo G:   jogo envia 6113 (pede o perfil)  -> servidor 6114 6115 6116 6117 6120 6118  (cada uma o jogo responde)
  Depois disso o jogo entra no LOBBY (mensagens 68xx): o que ele mandar aparece como *** NOVO *** no log.
  Tudo que o jogo mandar e eu ainda nao conheco aparece como "NOVO" no log: e a proxima etapa a decifrar.

Mensagens: cabecalho de 12 bytes + corpo.
    jogo -> servidor : 81 cc TT TT LL LL 00 00 00 FF FF FF  [corpo]
    servidor -> jogo : 28 02 TT TT LL LL 00 00 00 FF FF FF  [corpo]     (byte 8 = status, 0 = ok)
  Strings no corpo: [u16 tamanho big-endian][bytes].

Tudo vai para capture.log (envie esse arquivo).
"""
import argparse, socket, struct, threading, time, sys, os, json, unicodedata, random

LOG = open("capture.log", "a", encoding="utf-8")
LOCK = threading.Lock()

BOT = True                   # --sem-bot desliga: depois da busca (6209) o servidor manda 6910 (partida encontrada)
BOT_ATRASO = 5.0
BOT_SALA_BUSCA = 1.5   # v19: segundos entre apertar 'busca automatica' na sala e o BOT aparecer
SALA_ESPERA = 6.0   # v18: segundos apos entrar na sala antes de empurrar o 6910 (se o jogo nao pedir nada)

TOKEN = b"CVS2TKN1"          # 8 bytes: o jogo devolve isto no 6102
CHAVE = b"CVS2"              # duas strings iguais no 6820 => o jogo pula a lista de escolha

NOMES = {
    0x6001: "ping/pong", 0x6002: "logout/desistir", 0x6101: "login-1", 0x6102: "login-2 (token)", 0x6103: "aviso",
    0x6110: "login-fim", 0x6111: "lista-de-perfis", 0x6112: "perfil-confirmado", 0x613A: "cadastro-inicio",
    0x6131: "cadastro-1", 0x6132: "cadastro-2", 0x6133: "cadastro-3", 0x6134: "cadastro-4", 0x6135: "cadastro-5",
    0x6136: "cadastro-6", 0x6137: "cadastro-7", 0x6138: "cadastro-8", 0x6139: "cadastro-9",
    0x6114: "perfil-1", 0x6115: "perfil-2", 0x6116: "perfil-3", 0x6117: "perfil-4", 0x6118: "perfil-fim",
    0x6120: "perfil-5", 0x6122: "perfil-dados", 0x6820: "pedido-lista", 0x6821: "item-lista", 0x6822: "fim-lista", 0x6823: "escolha",
    0x6801: "lista-de-salas", 0x6802: "descricao-da-sala", 0x6142: "lobby-pronto", 0x6143: "lobby-143", 0x6841: "lista-841",
    0x6810: "info-810", 0x6861: "handshake-861", 0x6144: "info-144", 0x6145: "info-145", 0x6148: "cliente-148", 0x6851: "lista-851", 0x6149: "info-149", 0x6141: "fim-141", 0x6207: "entrar-lobby", 0x6205: "contagem-205", 0x6303: "contagem-303", 0x6305: "entrar-sala", 0x6306: "sala-306", 0x6209: "buscar-oponente", 0x6401: "salas-total", 0x6402: "sala-nome", 0x6403: "sala-pessoas", 0x6404: "sala-estado", 0x6406: "sala-406", 0x6504: "busca-504", 0x6910: "partida-encontrada(BOT)", 0x6911: "partida-911", 0x6912: "partida-912", 0x6913: "partida-913(perfil do oponente)", 0x6914: "partida-914", 0x6915: "partida-915", 0x6916: "partida-916(IP do oponente)", 0x6917: "partida-917(iniciar)", 0x6506: "sala-506", 0x6501: "sala-501", 0x6901: "partida-encontrada(BOT)", 0x6902: "lado", 0x6903: "perfil-do-oponente", 0x6904: "regras", 0x6905: "codigo-da-batalha", 0x6906: "endereco-do-oponente", 0x7006: "torneio-status(7006)", 0x7010: "torneio-hora(7010)", 0x700c: "tr-info(700c)", 0x7007: "tr-entry-join(7007)", 0x7001: "tr-entry-again(7001)", 0x6830: "info-830", 0x6831: "info-831", 0x6832: "info-832", 0x6833: "info-833", 0x6835: "info-835",
}


def out(msg):
    line = "%s %s" % (time.strftime("%H:%M:%S"), msg)
    with LOCK:
        print(line); sys.stdout.flush()
        LOG.write(line + "\n"); LOG.flush()


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
    if tipo == 0x6101:                       # CvS2: o passo A (0x315000) so trata 6101/6103/6110; NAO existe 6102.
        return [(0x6110, b"")]               # jogo respondeu o login-1 -> 6110 encerra o passo A (estado 5)
    if tipo == 0x6102:                       # jogo devolveu o token   -> aviso vazio (o jogo pula a tela de aviso)
        return [(0x6103, b"\x00" + s16(b"") + s16(b"") + struct.pack(">H", 0))]
    if tipo == 0x6103:                       # jogo confirmou o aviso
        return [(0x6110, b"")]
    if tipo == 0x6820:                       # pedido de lista (versao do jogo) -> duas strings iguais + fim de lista
        return [(0x6820, s16(CHAVE) + s16(CHAVE)), (0x6822, b"")]
    if tipo == 0x6823:                       # escolha confirmada
        return [(0x6823, s16(b""))]
    return None


# v21: PERFIS (ID + nick "HN") gravados em perfis.json ao lado deste script.
# ELF: lista 0x6111 = [u8 N] + N x ([blob ID <= 8 bytes][blob HN <= 17 bytes]) (0x43dd80, tabelas 0x541410 e 0x5413d0);
#      o jogo cadastra um nick novo mandando 0x6112 = [6 bytes] + [HN em bytes crus] (0x43de30)
#      e le a resposta 0x6112 = [blob = ID novo] (0x43de20). Antes o servidor respondia sempre "PLAYER" e nunca gravava.
PERFIS_ARQ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perfis.json")
MAX_PERFIS = 3
BOT_ID = b"BOT"
BOT_NICK = b"BOT"


def id_do_nick(hn, usados):
    """v23: o ID (campo de cima nas telas VS/RESULT) passa a ser o PROPRIO NICK, em ASCII, com exatamente 6 bytes
    (o jogo guarda o ID em 6 bytes; menos que isso ele completa com "**"). Letras largas japonesas viram letras comuns
    (ＸＹＺＧＸ -> XYZGX). Se o nick nao tiver letras/numeros comuns (ex.: katakana) usa P00002, P00003..."""
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
        brutos = [bytes.fromhex(x["hn"]) for x in d][:MAX_PERFIS]
    except Exception:
        brutos = []
    brutos = [h for h in brutos if h.strip(b"*")] or [b"PLAYER"]      # descarta o perfil quebrado "**" da v21
    r, usados = [], set()
    for h in brutos:
        i = id_do_nick(h, usados)
        usados.add(i)
        r.append((i, h))
    return r


def salvar_perfis():
    try:
        with open(PERFIS_ARQ, "w", encoding="utf-8") as f:
            json.dump([{"id": i.decode("ascii"), "hn": h.hex(), "hn_texto": h.decode("cp932", "replace")} for i, h in PERFIS], f, indent=1, ensure_ascii=False)
    except Exception as e:
        out("[perfis] erro ao gravar %s: %s" % (PERFIS_ARQ, e))


PERFIS = carregar_perfis()
salvar_perfis()


def cadastrar_perfil(corpo):
    """0x6112 do jogo (visto no log): [string ID de 6 bytes "******"][string HN]  (cada string = [u16 tamanho][bytes]).
    A resposta (ID novo) tem que ter EXATAMENTE 6 bytes."""
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
    novo = id_do_nick(hn, {i for i, _ in PERFIS})
    if len(PERFIS) >= MAX_PERFIS:
        out("[perfis] ja ha %d perfis: substituindo o ultimo" % MAX_PERFIS)
        PERFIS[-1] = (novo, hn)
    else:
        PERFIS.append((novo, hn))
    salvar_perfis()
    out("[perfis] NOVO perfil gravado: ID=%r HN=%s (hex %s)" % (novo.decode(), hn.decode("cp932", "replace"), hn.hex()))
    return novo


def lista_perfis():
    """0x6111: [u8 N] + N x ([string id][string nome])"""
    return (0x6111, bytes([len(PERFIS)]) + b"".join(s16(i) + s16(h) for i, h in PERFIS))


G_SEQ = [(0x6114, b""), (0x6115, b""), (0x6116, b""), (0x6117, b""), (0x6120, b""), (0x6118, b"")]


SALAS = [(b"CVS2 Lobby", b"Sala principal do servidor revivido")]


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
    if tipo == 0x6861:      # jogo manda 6861 [u8][u8][4 bytes]. Resposta com STATUS != 0 pula o download (0x4354b0
        return [(0x6861, b"", 1)]      # -> CvS2: manda 700c (TrInfomation), nao 6144). Com status 0 o jogo le um u32 e entra no download 6862..6865.
    if tipo == 0x6144:      # servidor 6144: [u8][u32][u32]  (0x43e880)
        return [(0x6144, bytes([0]) + struct.pack(">II", 0, 0))]
    if tipo == 0x6145:      # servidor 6145: 5 x u16 + 2 x u32  (0x43e8e0)
        return [(0x6145, struct.pack(">HHHHH", 0, 0, 0, 0, 0) + struct.pack(">II", 0, 0))]
    if tipo == 0x6851:      # servidor 6851: [u8 N][N x string(<=63)]  (0x440340); o jogo depois manda 6149
        return [(0x6851, bytes([1]) + s16(b"CVS2"))]
    if tipo == 0x6149:      # servidor 6149: 4 x u16  (0x43db70); se struct+268 < 100000 o jogo avanca para o passo I
        return [(0x6149, struct.pack(">HHHH", 0, 0, 0, 0))]
    # --- v24: cadeia "CAPCOM info" do CvS2 (barra de progresso, lobby_act_00_08 @ 0x316180) ---
    # Ordem decifrada no ELF: 6810 -> 6861 (status != 0 pula o patch) -> jogo manda 700c e ESPERA a resposta
    # (era aqui que travava em 76%) -> 7007 -> 6144 -> 6145 -> (6148 + 6851) -> barra 100% -> tela de informacoes.
    if tipo == 0x700c:      # Send_Req_TrInfomation (0x326e50): [u8 1]. Acc_TrInfomation (0x3274d0): [u8][string -> 0x46d380]
        return [(0x700c, bytes([0]) + s16(b""), 0)]
    if tipo == 0x7007:      # Send_Req_TrEntryJoin (0x326d40): sem corpo. Acc_TourEntryJoin (0x327190): so lê 2 bytes [u8][u8]
        return [(0x7007, bytes([0, 0]), 0)]
    if tipo == 0x7006:      # Send_Req_TournamentStatus; Acc_TournamentStatus (0x327180): [u8]
        return [(0x7006, bytes([0]), 0)]
    if tipo == 0x7010:      # Send_Req_TrEntryTime; Acc_TrEntryTime (0x3275f0): [u16] (0 = nada)
        return [(0x7010, struct.pack(">H", 0), 0)]
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
    # --- v13: lista de salas (对戦ルーム) e busca de oponente (無差別/初心者) ---
    if tipo == 0x6401:             # servidor 6401 [u16 total de salas]; o jogo depois pede 6402/6403/6404 por sala
        return [(0x6401, struct.pack(">H", 10))]
    if tipo in (0x6402, 0x6403, 0x6404):   # jogo pede [u16 id da sala]
        rid = corpo[:2] if len(corpo) >= 2 else b"\x00\x01"
        n = (rid[0] << 8) | rid[1]
        if tipo == 0x6402:         # [u16 id][string nome]
            return [(0x6402, rid + s16(b"BOT (aguardando)" if (BOT and n == 1) else b"Sala %d" % n))]
        if tipo == 0x6403:         # [u16 id][u16 pessoas na sala]
            return [(0x6403, rid + struct.pack(">H", 1 if (BOT and n == 1) else 0))]   # v18: sala 1 tem 1 pessoa (o BOT)
        return [(0x6404, rid + bytes([0]))]    # [u16 id][u8 estado]
    if tipo == 0x6209:             # jogo pede busca [u16][u16][u16]; resposta = [string] + status 0; entao inicia a contagem da busca
        return [(0x6209, s16(b""), 0)]
    # --- v14 ---
    if tipo == 0x6408:             # v18: o jogo manda 6408 (sem corpo) periodicamente na lista de salas (0x437f8c): atualizar. Status 0 = ok
        return [(0x6408, b"", 0)]
    if tipo == 0x6406:             # entrar na sala [u16 sala][u16]; o ELF (0x437d20) so olha o STATUS: 0 = ok -> fase 11
        sala = (corpo[0] << 8 | corpo[1]) if len(corpo) >= 2 else 0
        out("[BOT] jogo ENTROU na sala %d (corpo=%s)" % (sala, corpo.hex(" ")))
        return [(0x6406, b"", 0)]
    if tipo == 0x6504:             # jogo avisa [u8] durante a busca e espera 6504 com status 0 (0x4398c0)
        return [(0x6504, b"", 0)]
    return None


PEER_PENDING = {}            # ip do PS2 -> prazo: a proxima conexao desse IP e a conexao com o "oponente" (BOT)
BOT_PORTAS = (37926, 58405)   # portas que o ELF usa para conectar no oponente (modos 0 e 1 em 0x433a2c)


def blob(n=64):
    """bloco binario [u16 tamanho][bytes] (leitor 0x43d2c0, sem limite no jogo: manter pequeno)"""
    return struct.pack(">H", n) + bytes(n)


def blob_n(n):
    """bloco binario [u16 tamanho BE][n bytes] (leitor GetRecvDataOption2 @0x323000: memcpy sem limite -> manter pequeno)"""
    return struct.pack(">H", n) + bytes(n)


def regras_padrao():
    """48 bytes = o que net_rule_default (0x1a2820) grava no jogo. Acc_RuleData (0x325880) copia o blob em 0x46aeb0."""
    b = bytearray(48)
    b[0:4] = bytes([1, 1, 2, 2])
    b[27:32] = bytes([11, 7, 16, 28, 40])
    b[32:36] = b"\xff\xff\xff\xff"
    b[36:40] = struct.pack("<I", 0x9fff)
    b[40:44] = b"\xff\xff\xff\xff"
    b[44:48] = struct.pack("<I", 0x9fff)
    return bytes(b)


def partida(ss, tipo, corpo):
    """v25 - preparo de batalha do CvS2 (decifrado no ELF: lobby_act_16_02 @0x31afd0).
    servidor 6901 (sem corpo)  -> jogo vai para To_ReadyBattle (estado 16). E a UNICA mensagem de 'partida encontrada'
                                  (a v24 mandava 6910, que e do MvC2: o jogo recebia e ignorava).
    jogo 6902 [u8 lado 1/2/3]  -> servidor 6902 [u8]   Acc_PlayerSide. Depois o jogo faz (valor-1): se 0 pede o
                                  endereco do oponente (6906); se !=0 espera o oponente conectar. Respondo sempre 1.
    jogo 6903                  -> servidor 6903 [str id][str nome][blob 'vsconf'][5 x u16]    (Acc_VsPlayerInfomation)
    jogo 6904                  -> servidor 6904 [blob 48 bytes de regras]                       (Acc_RuleData)
    jogo 6905                  -> servidor 6905 [str codigo da batalha]                         (Acc_BattleCode)
    jogo 6906                  -> servidor 6906 [str 'TelNumber']  (Acc_MatchingTelNumber; o ELF so usa isso em
                                  modem_connect_20 = ATD<numero>). Mando o IP deste PC em texto.
    Depois disso o jogo faz fade -> To_DirectConnect -> lobby_act_15 -> manda 6002 (logout) e entra na conexao direta."""
    if tipo == 0x6902:
        pedido = corpo[0] if corpo else 3
        ss["role"] = 1
        out("[BOT] 6902: jogo pediu lado %d -> respondendo 1 (jogo vai pedir o endereco do oponente: 6906)" % pedido)
        return [(0x6902, bytes([1]), 0)]
    if tipo == 0x6903:
        return [(0x6903, s16(BOT_ID.ljust(6)[:6]) + s16(BOT_NICK) + blob_n(560) + struct.pack(">HHHHH", 0, 0, 0, 0, 0), 0)]
    if tipo == 0x6904:
        return [(0x6904, s16(regras_padrao()), 0)]
    if tipo == 0x6905:
        return [(0x6905, s16(b"CVS2BOT1"), 0)]
    if tipo == 0x6906:
        ip = ss.get("ip", "127.0.0.1").encode("ascii")
        out("[BOT] 6906: mandando o endereco do 'oponente' = %s (este PC). O proximo passo do jogo (conexao direta) vai aparecer no log" % ip.decode())
        return [(0x6906, s16(ip), 0)]
    return None


def reagir(ss, tipo, corpo):
    """Conversa de login. A decisao e por TIPO de mensagem do jogo (decifrado no ELF).
    O 0x6110 do fim do passo B leva 1 byte = MODO (gp-18208) que decide o proximo passo:
        modo 0 -> passo D (o jogo espera a lista de perfis 0x6111)
        modo 1 ou 2 -> passo C (cadastro: o servidor manda 0x6131..0x6139)
        modo 3 -> passo G (o jogo pede 0x6113 sozinho)"""
    if tipo in (0x6001, 0x613A, 0x6148, 0x6143):
        return []
    if tipo == 0x6504 and BOT:
        # v18 log: na SALA o jogo manda 6504 [1] ao apertar 自動選抜対戦 (iniciar busca) e 6504 [0] ao cancelar.
        # O 6910 do BOT chegou 6 s depois, ja apos o cancelamento, e foi ignorado. Agora: aparece 1.5 s apos iniciar.
        if corpo[:1] == b"\x01":
            if not ss.get("bot_at"):
                ss["bot_at"] = time.time() + BOT_SALA_BUSCA
                out("[BOT] sala: busca automatica iniciada -> BOT aparece em %.1fs" % BOT_SALA_BUSCA)
        else:
            if ss.get("bot_at"):
                out("[BOT] busca cancelada pelo jogo: cancelando o aparecimento do BOT")
            ss["bot_at"] = None
            ss["bot_feito"] = False
    elif tipo == 0x6209 and BOT and not ss.get("bot_feito") and not ss.get("bot_at"):
        ss["bot_at"] = time.time() + BOT_ATRASO
        ss["bot_feito"] = True
    if tipo == 0x6406 and BOT:
        ss["na_sala"] = True
        ss["chat_at"] = time.time() + 2.0
    if tipo == 0x6506:
        # v20: 6506 = "quantas pessoas na sala" (ELF 0x43f3d0 le 1 u16 -> gp-18692; 0x4432dc habilita os botoes so com >= 2)
        n = 2 if (BOT and ss.get("na_sala")) else 1
        out("[BOT] 6506: respondendo %d pessoas na sala (voce + BOT)" % n)
        return [(0x6506, struct.pack(">H", n), 0)]
    if tipo == 0x6403 and BOT and ss.get("na_sala"):
        rid = corpo[:2] if len(corpo) >= 2 else b"\x00\x01"
        return [(0x6403, rid + struct.pack(">H", 2), 0)]      # cabecalho da sala mostra 2 pessoas
    if tipo == 0x6501:
        out("[BOT] 6501 (sair/cancelar na sala): respondendo status 0")
        return [(0x6501, b"", 0)]
    r = partida(ss, tipo, corpo)
    if r is not None:
        return r
    if tipo == 0x6110:
        modo = corpo[0] if corpo else 0
        out("[sessao] fim do passo B, modo=%d" % modo)
        if modo == 0:
            return [lista_perfis()]
        if modo in (1, 2):
            return [(0x6131, b"")]
        return []
    if 0x6131 <= tipo <= 0x6138:             # passo C: o jogo respondeu um campo do cadastro -> proximo
        return [(tipo + 1, b"")]
    if tipo == 0x6139:                       # ultimo do passo C -> passo D
        return [lista_perfis()]
    if tipo == 0x6112:                       # v21: cadastro de nick novo: grava em perfis.json e devolve o ID novo
        novo = cadastrar_perfil(corpo)
        return [(0x6112, s16(novo), 0)]
    if tipo == 0x6113:                       # passo G: jogo pede os dados do perfil -> 6114..6120 e 6118 (fim)
        try:
            pid = corpo[2:2 + ((corpo[0] << 8) | corpo[1])]
            hn = dict(PERFIS).get(pid, b"?")
            out("[perfis] jogo escolheu o perfil ID=%s HN=%s" % (pid.decode("ascii", "replace"), hn.decode("cp932", "replace")))
            ss["perfil"] = (pid, hn)
        except Exception:
            pass
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
    if PEER_PENDING.get(addr[0], 0) > time.time():
        PEER_PENDING.pop(addr[0], None)
        out("[TCP %d] *** esta e a conexao do PS2 com o 'OPONENTE' (BOT): sem login, entrando no modo par ***" % port)
        return handle_peer(conn, addr, port, idle)
    buf = b""
    conn.settimeout(1.0)
    vistos = []
    ss = {"fase": "A", "ip": conn.getsockname()[0], "cli": addr[0]}
    try:
        enviar(conn, port, 0x6001, b"", "inicio"); time.sleep(0.2)
        enviar(conn, port, 0x6004, b"", "inicio"); time.sleep(0.2)
        enviar(conn, port, 0x6101, s16(TOKEN), "inicio do login"); 
        t_rx = time.time(); t_ping = time.time()
        while True:
            try:
                data = conn.recv(4096)
                if data == b"":
                    break
            except socket.timeout:
                data = None
            agora = time.time()
            if ss.get("bot_at") and agora >= ss["bot_at"]:
                ss["bot_at"] = None
                out("[BOT] simulando 'oponente encontrado': servidor envia 6901 (CvS2: To_ReadyBattle, o jogo vai para a fase 16)")
                enviar(conn, port, 0x6901, b"", "BOT")
            if ss.get("chat_at") and agora >= ss["chat_at"]:
                ss["chat_at"] = None
                out("[BOT] BOT fala no chat da sala (6702)")
                enviar(conn, port, 0x6702, s16(b"BOT") + s16(b"Aperte o botao da direita para lutar comigo") + s16(b"") + bytes(4), "BOT")
            if ss.get("sala_at") and agora >= ss["sala_at"]:
                ss["sala_at"] = None
                out("[BOT] sala: o jogo ficou em silencio %.0fs apos entrar -> servidor envia 6901 (BOT entrou na partida)" % SALA_ESPERA)
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
        conn.close()



# ---------------------------------------------------------------------------------------------
# v16: LADO DO OPONENTE (conexao PS2 -> "oponente"). Decifrado no ELF (biblioteca Mcs, 0x428220 / 0x42a170):
#   O jogo, depois do 6916, abre TCP no IP do oponente e fica no ESTADO 1 (0x428290) esperando, por 3600 quadros
#   (60 s; e o "mcsRecv=3600" do log), uma mensagem de 12 bytes cujo tipo (bytes 2-3) e:
#       0x1031 = OLA  -> o jogo responde 82 02 10 31 00 08 00 00 00 ff ff ff + 8 bytes e vai ao ESTADO 2
#       0x1032 = RECUSA (vai para o estado final de erro/4)  -> NAO mandar
#   Estado 2: troca de pacotes Mcs  [len][tipo|canal][b2][b3]   (canais 0 e 1; len inclui o proprio byte)
#       tipo 0x10 abertura de canal: b2=0 pedido (a outra ponta responde b2=1), b2=1 resposta. Precisa dos 2 canais.
#   Estado 3: tipo 0x30 (pronto) - cada ponta manda b2=0 para cada canal.
#   Estados 4..8 (0x50 sincronismo, 0x20 dados, 0x70, 0x90) AINDA nao decifrados: tudo que o jogo mandar vai ao log
#   como "MCS-NOVO" para a proxima rodada.
# ---------------------------------------------------------------------------------------------
def mcs(tipo, canal, b2=0, b3=0):
    return bytes([4, (tipo & 0xF0) | (canal & 0x0F), b2, b3])


def handle_peer(conn, addr, port, idle, ativo=False):
    buf = b""
    conn.settimeout(1.0)
    enviados = set()
    t_rx = time.time()
    n_canais = 2
    npong = [0]
    cont = {}
    try:
        m = frame(0x1031, b"")
        conn.sendall(m)
        out("[PAR %d] >>> BOT envia OLA 0x1031: %s" % (port, m.hex(" ")))
        while True:
            try:
                data = conn.recv(4096)
                if data == b"":
                    break
            except socket.timeout:
                data = None
            agora = time.time()
            if not data:
                if agora - t_rx > max(idle, 180):
                    out("[PAR %d] sem atividade: encerrando" % port)
                    break
                continue
            t_rx = agora
            buf += data
            out("[PAR %d] <<< PS2 enviou %d bytes: %s" % (port, len(data), data[:96].hex(" ")))
            while buf:
                if buf[0] in (0x81, 0x82) and len(buf) >= 12:
                    total = 12 + ((buf[4] << 8) | buf[5])
                    if len(buf) < total:
                        break
                    f, buf = buf[:total], buf[total:]
                    tipo = (f[2] << 8) | f[3]
                    out("[PAR %d]     quadro de 12 bytes: tipo=%04x classe=%02x corpo=%s" % (port, tipo, f[0], f[12:].hex(" ")))
                    if tipo == 0x1031 and "ola" not in enviados:
                        enviados.add("ola")
                        out("[PAR %d]     o jogo ACEITOU o ola -> estado 2: abrindo canais" % port)
                        for c in range(n_canais):
                            conn.sendall(mcs(0x10, c, 0, 0))
                            out("[PAR %d] >>> BOT pede abertura do canal %d (tipo 0x10)" % (port, c))
                    continue
                n = buf[0]
                if n < 2:
                    buf = buf[1:]
                    continue
                if len(buf) < n:
                    break
                p, buf = buf[:n], buf[n:]
                tp, ch = p[1] & 0xF0, p[1] & 0x0F
                b2 = p[2] if n > 2 else 0
                if tp == 0x10:
                    out("[PAR %d]     Mcs 0x10 canal %d b2=%d (%s)" % (port, ch, b2, "pedido" if b2 == 0 else "resposta"))
                    if b2 == 0:
                        conn.sendall(mcs(0x10, ch, 1, 0))
                        out("[PAR %d] >>> BOT responde abertura do canal %d" % (port, ch))
                elif tp == 0x30:
                    out("[PAR %d]     Mcs 0x30 canal %d b2=%d (pronto do jogo)" % (port, ch, b2))
                    # v17: responder TODA vez (o jogo repete o 0x30 no estado 5, depois do sincronismo)
                    for c in range(n_canais):
                        conn.sendall(mcs(0x30, c, 0, 0))
                    out("[PAR %d] >>> BOT confirma 'pronto' (0x30) nos canais 0 e 1" % port)
                elif tp == 0x50:
                    # sincronismo/ping (estado 4). O jogo manda 16 pings (b3 = 0..15) e precisa de 16 PONGs
                    # vindos do canal do OPONENTE: [6][0x50|canal_bot][1][seq][canal_do_jogo][0]
                    seq = p[3] if n > 3 else 0
                    if b2 == 0:
                        pong = bytes([6, 0x50 | (ch ^ 1), 1, seq, ch, 0])
                        conn.sendall(pong)
                        npong[0] += 1
                        if seq < 3 or seq >= 14:
                            out("[PAR %d] >>> BOT responde PONG seq=%d (canal bot=%d, canal jogo=%d)  [total %d]" % (port, seq, ch ^ 1, ch, npong[0]))
                    else:
                        out("[PAR %d]     Mcs 0x50 b2=%d (pong do jogo) %s" % (port, b2, p.hex(" ")))
                elif tp in (0x20, 0x70):
                    # DADOS (estado 6: registros de 8 bytes por quadro) e KEEPALIVE. Ainda nao decifrei o conteudo dos registros:
                    # o BOT ESPELHA o pacote no canal do oponente (mesmos registros = mesmo quadro), o que mantem os dois lados em sincronia.
                    cont[tp] = cont.get(tp, 0) + 1
                    if cont[tp] <= 5 or cont[tp] % 100 == 0:
                        out("[PAR %d]     Mcs 0x%02x canal %d len=%d (#%d): %s" % (port, tp, ch, n, cont[tp], p.hex(" ")))
                    conn.sendall(bytes([p[0], tp | (ch ^ 1)]) + p[2:])
                elif tp == 0x90:
                    cont[tp] = cont.get(tp, 0) + 1
                    if cont[tp] <= 3:
                        out("[PAR %d]     Mcs 0x90 (keepalive do jogo): %s" % (port, p.hex(" ")))
                else:
                    out("[PAR %d]     *** MCS-NOVO tipo=0x%02x canal=%d len=%d: %s   <== PROXIMA ETAPA A DECIFRAR" % (
                        port, tp, ch, n, p.hex(" ")))
    except Exception as e:
        out("[PAR %d] erro: %s" % (port, e))
    finally:
        out("[PAR %d] conexao com o PS2 encerrada" % port)
        try:
            conn.close()
        except Exception:
            pass


def peer_fallback(ip):
    """Se o PS2 estiver em modo 'servidor' (escuta nas portas 37926/58405), ele nao conecta: o BOT conecta nele."""
    time.sleep(10)
    if PEER_PENDING.get(ip, 0) <= time.time():
        return
    for p in BOT_PORTAS:
        try:
            s = socket.create_connection((ip, p), timeout=4)
        except Exception as e:
            out("[PAR] o PS2 nao conectou em 10 s; tentativa ativa no PS2 %s:%d falhou (%s)" % (ip, p, e))
            continue
        PEER_PENDING.pop(ip, None)
        out("[PAR] *** BOT conectou ATIVAMENTE no PS2 %s:%d ***" % (ip, p))
        handle_peer(s, (ip, p), p, 120, ativo=True)
        return


# ---------------------------------------------------------------------------------------------------------------------
# v26 - MODEM VIRTUAL: a luta contra o BOT (CvS2 nao usa TCP entre jogadores: usa a camada de modem Com*).
# O AVEWRAP2 emula o modem; quando o jogo disca (ATDT) ele conecta AQUI (porta P2P_PORT) e passa a ser o "fio" do modem.
# Protocolo decifrado no ELF (modem_connect_40/50/60 @0x19bd60..0x19c260, match_IO_sync @0x19c460):
#   1) PS2 (quem disca) manda  "\nPING\n"  e re-manda "PING\n"; esperamos responder "PONG\n" a cada PING (8 vezes);
#      depois o PS2 manda "START\n".
#   2) sincronizacao: PS2 manda "\nREADY\n" -> respondemos "\nOK\n" -> PS2 manda "START\n".
#   3) luta: PACOTES BINARIOS DE 20 BYTES por frame (match_IO_read_out @0x19c710 / read_in @0x19c8c0), little-endian:
#        +0 u16 entrada A   +4 u16 entrada B   +8 u16 (byte baixo = tipo de controle, bit 0x10 = dado extra, byte alto = flags)
#        +12 u16 numero do frame (comeca em 1, 6 bits: 1..63,0,1...)   os outros 2 bytes de cada palavra e +16..19 = 0.
#      O jogo trava as entradas em lockstep: cada frame do PS2 exige o pacote do oponente com o MESMO numero de frame.
#      O BOT responde 1 pacote para cada pacote recebido (reativo), com entradas ociosas ou aleatorias (--sem-mash).
# ---------------------------------------------------------------------------------------------------------------------
P2P_PORT = 9877
P2P_MASH = True
MASH_BITS = (0x0010, 0x0020, 0x0040, 0x0080, 0x1000, 0x2000, 0x4000, 0x8000, 0x0400, 0x0800)


def pacote20(in0, in1, h2, frame):
    return struct.pack("<HHHHHHHHI", in0 & 0xffff, 0, in1 & 0xffff, 0, h2 & 0xffff, 0, frame & 0x3f, 0, 0)


def modem_link(conn, addr):
    ip = addr[0]
    out("[MODEM] === PS2 %s ligou o modem virtual (porta %d) ===" % (ip, P2P_PORT))
    conn.settimeout(1.0)
    buf = b""
    fase = "ping"            # ping -> sync -> bin
    pings = 0
    n_in = 0
    bot_frame = 1            # o jogo espera o primeiro frame do oponente = 1
    mash = {"bit": 0}
    ultimo = time.time()
    esperado = None
    try:
        while True:
            try:
                d = conn.recv(4096)
            except socket.timeout:
                if time.time() - ultimo > 90:
                    out("[MODEM] sem dados ha 90 s, encerrando")
                    break
                continue
            if not d:
                break
            ultimo = time.time()
            if fase != "bin" or n_in < 4:
                out("[MODEM] RX %d bytes: %s" % (len(d), d[:40].hex()))
            buf += d
            while True:
                if fase in ("ping", "sync"):
                    i = buf.find(b"\n")
                    if i < 0:
                        if len(buf) > 200:
                            out("[MODEM] lixo sem fim de linha, descartando %d bytes" % len(buf)); buf = b""
                        break
                    linha = buf[:i].strip(b"\r\n\x00 ")
                    buf = buf[i + 1:]
                    if not linha:
                        continue
                    t = linha.decode("ascii", "replace")
                    if t == "PING":
                        pings += 1
                        conn.sendall(b"PONG\n")
                        if pings <= 2 or pings == 8:
                            out("[MODEM] PING #%d -> PONG" % pings)
                    elif t == "START" and fase == "ping":
                        fase = "sync"
                        out("[MODEM] START do PS2 (apos %d PINGs) -> sincronizacao" % pings)
                    elif t == "READY":
                        fase = "sync"
                        conn.sendall(b"\nOK\n")
                        out("[MODEM] READY -> OK")
                    elif t == "START" and fase == "sync":
                        fase = "bin"
                        out("[MODEM] === START: LUTA COMECOU (pacotes binarios de 20 bytes) ===")
                    else:
                        out("[MODEM] linha inesperada: %r" % t)
                else:
                    if len(buf) < 20:
                        break
                    p = buf[:20]; buf = buf[20:]
                    in0, _, in1, _, h2, _, fr, _, extra = struct.unpack("<HHHHHHHHI", p)
                    n_in += 1
                    if esperado is not None and (fr & 0x3f) != esperado:
                        out("[MODEM] AVISO: frame %d recebido, esperava %d" % (fr, esperado))
                    esperado = ((fr & 0x3f) + 1) & 0x3f
                    if n_in <= 12 or n_in % 300 == 0:
                        out("[MODEM] pacote #%d frame=%d in0=%04x in1=%04x h2=%04x extra=%08x raw=%s" % (n_in, fr, in0, in1, h2, extra, p.hex()))
                    # entrada do BOT
                    ph = n_in % 24
                    if ph == 1:
                        mash["bit"] = random.choice(MASH_BITS)
                    bot_in = mash["bit"] if (P2P_MASH and ph < 4) else 0
                    conn.sendall(pacote20(bot_in, 0, h2 & ~0x0010, bot_frame))
                    bot_frame = (bot_frame + 1) & 0x3f
    except (ConnectionError, OSError) as e:
        out("[MODEM] conexao encerrada: %s" % e)
    finally:
        out("[MODEM] === link encerrado (fase=%s, pacotes do PS2=%d, PINGs=%d) ===" % (fase, n_in, pings))
        try:
            conn.close()
        except OSError:
            pass


def modem_listener(port):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.listen(5)
    out("escutando TCP %d (modem virtual / luta contra o BOT)" % port)
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
        threading.Thread(target=handle, args=(c, a, port, idle), daemon=True).start()


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


def peer_tcp(port):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.listen(5)
    out("escutando TCP %d (BOT: lado do oponente)" % port)
    while True:
        c, a = s.accept()
        def lig(c=c, a=a):
            out("[BOT-TCP %d] *** o PS2 CONECTOU no oponente: %s:%d ***" % (port, a[0], a[1]))
            c.settimeout(60)
            try:
                while True:
                    d = c.recv(4096)
                    if not d:
                        break
                    out("[BOT-TCP %d] recebeu %d bytes: %s" % (port, len(d), d[:200].hex(" ")))
            except Exception as e:
                out("[BOT-TCP %d] fim: %s" % (port, e))
            c.close()
        threading.Thread(target=lig, daemon=True).start()


def peer_udp(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    out("escutando UDP %d (BOT: lado do oponente)" % port)
    while True:
        d, a = s.recvfrom(4096)
        out("[BOT-UDP %d] *** pacote do PS2 %s:%d, %d bytes: %s" % (port, a[0], a[1], len(d), d[:200].hex(" ")))


def udp_logger(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    out("escutando logs UDP %d (mensagens do PS2)" % port)
    last = {}
    while True:
        d, a = s.recvfrom(2048)
        if d.startswith(b"CVS2-DISCOVER"):
            s.sendto(b"CVS2-SERVER", a)
            continue
        t = d.decode("latin-1").rstrip()
        if "PppGetUsbDeviceId" in t:
            continue
        key = "hb" if "hb:" in t else ("cnt" if "cnt:" in t else None)
        if key:
            if last.get(key) == t:
                continue
            last[key] = t
        if "TcpStat" in t:
            continue
        out("[PS2 %s] %s" % (a[0], t))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ports", default="9876,9700,1000")
    ap.add_argument("--logport", type=int, default=9999)
    ap.add_argument("--idle", type=int, default=120, help="segundos de silencio antes de encerrar")
    ap.add_argument("--sem-bot", action="store_true", help="nao simular oponente apos a busca")
    ap.add_argument("--nick-bot", default="BOT", help="ID/nick que o BOT mostra na tela VS (ate 17 bytes)")
    ap.add_argument("--p2p-port", type=int, default=9877, help="porta TCP do modem virtual (luta contra o BOT)")
    ap.add_argument("--sem-mash", action="store_true", help="BOT fica parado na luta (sem apertar botoes aleatorios)")
    a = ap.parse_args()
    P2P_PORT = a.p2p_port
    P2P_MASH = not a.sem_mash
    BOT = not a.sem_bot
    BOT_NICK = a.nick_bot.encode("cp932", "replace")[:17] or b"BOT"
    BOT_ID = (unicodedata.normalize("NFKC", a.nick_bot).encode("ascii", "ignore")[:8] or BOT_NICK[:8])
    out("[perfis] arquivo: %s | perfis: %s" % (PERFIS_ARQ, ", ".join("%s/%s" % (i.decode(), h.decode("cp932", "replace")) for i, h in PERFIS)))
    for p in a.ports.split(","):
        threading.Thread(target=tcp_listener, args=(int(p), a.idle), daemon=True).start()
    threading.Thread(target=udp_logger, args=(a.logport,), daemon=True).start()
    threading.Thread(target=modem_listener, args=(P2P_PORT,), daemon=True).start()
    if BOT:
        for bp in BOT_PORTAS:
            threading.Thread(target=peer_tcp, args=(bp,), daemon=True).start()
            threading.Thread(target=peer_udp, args=(bp,), daemon=True).start()
    out("=== SERVIDOR VERSAO 26 (BOT + modem virtual porta %d: PING/PONG, READY/OK, pacotes de 20 bytes; BOT: %s) ===" % (P2P_PORT, "LIGADO" if BOT else "desligado"))
    out("IPs deste PC: " + ", ".join(local_ips()))
    out("pronto. Aguardando o PS2... (Ctrl+C para sair)")
    while True:
        time.sleep(1)
