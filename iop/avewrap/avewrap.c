/*
 * avewrap.c - substituto do AVE_WRAP.IRX ("Tcp wrapper 2001.07.12") de
 * "Capcom vs. SNK 2 Millionaire Fighting 2001" (PS2, Japao, SLPM-65047).
 *
 * A tabela de comandos abaixo vem do proprio AVE_WRAP.IRX original do disco (enum AVE_WRAP_FUNCTION_ID,
 * presente na informacao de debug) e foi conferida contra os stubs do ELF do jogo (0x3400a0..0x340f30).
 * ATENCAO: nao e a mesma numeracao do MvC2! No CvS2 a familia DNS e 56..62 (no MvC2 era 57..61) e NAO existe Mcs.
 *
 *   buffer RPC:  +24 = resultado (s32)   +28... = argumentos / dados de retorno
 *
 *   cmd  0 Getconfig  1 Ifconfig  2 Ifdown  3 SetOpt  4 GetOpt
 *   cmd  5 TcpInit    6 TcpTerm
 *   cmd  7 TcpOpen   (+28 u32 ip, +32 u16 porta destino (ordem de rede), +34 u16 porta origem) -> res = handle
 *   cmd 11 TcpClose  (+28 s16 h)         12 TcpAbort
 *   cmd 14 TcpStat   (+28 s16 h) -> +30 estado (4=ESTABLISHED), +34 janela de envio, +36 BYTES DISPONIVEIS p/ leitura
 *   cmd 15 TcpSend   (+28 s16 h, +30 s16 len, +32 dados) -> res = enviados
 *   cmd 18 TcpRecv   (+28 s16 h, +30 s16 max)            -> res = len, dados em +32
 *   cmd 31 PppInit 32 PppDisp 33 PppStart 34 PppFinish 35 PppStatus 36 PppUsbDeviceId 37/38 PppOption
 *   cmd 35 PppStatus -> res = fase (0..9; 4 = CONECTADO) E +36 u16 fase (+46 u16 last_error = 0)
 *   cmd 56 DnsInit  57 DnsDisp  58 DnsGetTicket(+28 nome, res = ticket)  59 DnsReleaseTicket(+28 s16)
 *   cmd 60 DnsLookup (+28 s16 ticket) -> res = 1 (pronto) e +32 u32 ip   (res 0 = o jogo trata como erro)
 *   cmd 63..77 Com*  (nao usados por este modulo: respondem 0)
 */
#include "irx_imports.h"
#include "config.h"

IRX_ID("Capcom_AVE_TCP_Wrapper", 1, 3);

/* v0.3: carregado no lugar do AVETCP.IRX (1o modulo lido pelo jogo) para a rede/log subirem cedo.
 * Atende so o RPC do AVE_WRAP (0x01270030). USB_SRCH e ACC_COM voltam a ser modulos proprios e RESIDENTES,
 * porque o jogo faz o bind deles logo apos a carga (e carga de modulo nao-residente em USB_SRCH da "Can't load module"). */

#define AVE_RPC_ID 0x01270030
#define RPCBUF_SZ  2048
#define MAXSOCK    8
#define MAXTICKET  8
#define RXSZ       2048

#define IP4(a, b, c, d) ((u32)(a) | ((u32)(b) << 8) | ((u32)(c) << 16) | ((u32)(d) << 24))
#define HTONS(x)        ((u16)((((x) & 0xff) << 8) | (((x) >> 8) & 0xff)))

#define NRPC 3
static SifRpcDataQueue_t g_qds[NRPC];
static SifRpcServerData_t g_sds[NRPC];
static u8 g_bufs[NRPC][RPCBUF_SZ] __attribute__((aligned(64)));
static const u32 g_ids[NRPC] = { 0x01270030, 0x01270010, 0x01270020 };
static void *(*g_fn[NRPC])(int, void *, int);

/* ---------- log (console do IOP + UDP para o PC) ---------- */
static int g_logfd = -1;
static struct sockaddr_in g_bcast, g_srvlog;
static u32 g_server_ip = 0;
static volatile int g_net_ready = 0;
static volatile int g_found = 0;
static volatile u32 g_cnt[80];

#define EARLYN 40
static char g_early[EARLYN][120];
static volatile int g_early_n = 0;
static volatile u32 g_cnt_usb[8], g_cnt_acc[16];

static void logmsg(const char *m)
{
    printf("%s", m);
    if (g_logfd < 0 && g_early_n < EARLYN) {          /* rede ainda nao subiu: guarda para enviar depois */
        strncpy(g_early[g_early_n], m, 119);
        g_early[g_early_n][119] = 0;
        g_early_n++;
    }
    if (g_logfd >= 0) {
        if (!g_found)
            lwip_sendto(g_logfd, (void *)m, strlen(m), 0, (struct sockaddr *)&g_bcast, sizeof(g_bcast));
        g_srvlog.sin_addr.s_addr = g_server_ip;
        lwip_sendto(g_logfd, (void *)m, strlen(m), 0, (struct sockaddr *)&g_srvlog, sizeof(g_srvlog));
    }
}
#define LOG(...) do { char _m[220]; sprintf(_m, "[avewrap] " __VA_ARGS__); logmsg(_m); } while (0)

/* ---------- estado ---------- */
static int g_fd[MAXSOCK + 1];
static u8 g_rx[MAXSOCK + 1][RXSZ];
static int g_rxlen[MAXSOCK + 1];
static int g_rxclosed[MAXSOCK + 1];
static char g_ticket_name[MAXTICKET + 1][64];
static int g_ticket_used[MAXTICKET + 1];
static int g_ppp_on = 0, g_ppp_polls = 0;

static int sock_of(int h)
{
    if (h < 1 || h > MAXSOCK) return -1;
    return g_fd[h];
}

static void set_nonblock(int fd)
{
    int on = 1;
    lwip_ioctl(fd, FIONBIO, &on);
}

static int do_tcp_open(u32 ip, u16 port)
{
    int h, fd;
    struct sockaddr_in sa;

    for (h = 1; h <= MAXSOCK; h++)
        if (g_fd[h] < 0) break;
    if (h > MAXSOCK) return -1;

    fd = lwip_socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return -2;

    memset(&sa, 0, sizeof(sa));
    sa.sin_family = AF_INET;
    sa.sin_port = HTONS(port);
    sa.sin_addr.s_addr = ip;
    if (lwip_connect(fd, (struct sockaddr *)&sa, sizeof(sa)) < 0) {
        lwip_close(fd);
        return -3;
    }
    set_nonblock(fd);
    g_fd[h] = fd;
    g_rxlen[h] = 0;
    g_rxclosed[h] = 0;
    return h;
}

static void do_tcp_close(int h)
{
    int fd = sock_of(h);
    if (fd >= 0) {
        lwip_close(fd);
        g_fd[h] = -1;
        g_rxlen[h] = 0;
        g_rxclosed[h] = 0;
    }
}

/* FIONREAD nao funciona neste lwIP: cada handle tem buffer proprio; o TcpStat informa o tamanho dele
   e o TcpRecv consome dele (o jogo so le quando ha >= 12 bytes para o cabecalho). */
static void rx_fill(int h)
{
    int fd = sock_of(h), n;
    if (fd < 0 || g_rxlen[h] >= RXSZ) return;
    n = lwip_recv(fd, g_rx[h] + g_rxlen[h], RXSZ - g_rxlen[h], 0x08 /* MSG_DONTWAIT */);
    if (n > 0) g_rxlen[h] += n;
    else if (n == 0) g_rxclosed[h] = 1;
}

static int rx_take(int h, u8 *dst, int max)
{
    int n;
    rx_fill(h);
    n = (g_rxlen[h] < max) ? g_rxlen[h] : max;
    if (n > 0) {
        memcpy(dst, g_rx[h], n);
        g_rxlen[h] -= n;
        if (g_rxlen[h] > 0) memmove(g_rx[h], g_rx[h] + n, g_rxlen[h]);
    }
    return n;
}

/* ---------- despachante RPC ---------- */
static void *rpc_dispatch(int cmd, void *data, int size)
{
    u8 *b = (u8 *)data;
    s32 *res = (s32 *)(b + 24);
    *res = 0;
    if (cmd >= 0 && cmd < 80) g_cnt[cmd]++;

    switch (cmd) {
    case 0: case 1: case 2: case 3: case 4:        /* Getconfig/Ifconfig/Ifdown/SetOpt/GetOpt */
        LOG("cmd %d cfg/opt h=%d\n", cmd, *(s16 *)(b + 28));
        *res = 0;
        break;
    case 5: case 6: case 31: case 32: case 56: case 57:   /* Init / Term / Disp */
        LOG("cmd %d init/disp\n", cmd);
        *res = 0;
        break;

    case 7: {                               /* TcpOpen */
        u32 ip = *(u32 *)(b + 28);
        u16 p1 = *(u16 *)(b + 32), p2 = *(u16 *)(b + 34);
        u16 netport = p1 ? p1 : p2;         /* o jogo passa a porta em ordem de rede (0x9426 = 9876, 0xe425 = 9700) */
        u16 port = (u16)(((netport >> 8) & 0xff) | ((netport & 0xff) << 8));
        if (SERVER_PORT) port = SERVER_PORT;
        LOG("TcpOpen ip=%08x p1=%u p2=%u -> conectando na porta %u\n", ip, p1, p2, port);
        { int w; for (w = 0; w < 100 && !g_net_ready; w++) DelayThread(100 * 1000); }
        if (!g_net_ready) LOG("TcpOpen: rede sem IP (DHCP falhou)\n");
        *res = do_tcp_open(ip, port);
        LOG("TcpOpen resultado=%d\n", *res);
        break;
    }
    case 11: case 12:                       /* TcpClose / TcpAbort */
        LOG("TcpClose h=%d\n", *(s16 *)(b + 28));
        do_tcp_close(*(s16 *)(b + 28));
        break;
    case 14: {                              /* TcpStat */
        static int last_av = -1;
        int h = *(s16 *)(b + 28), fd = sock_of(h), av;
        memset(b + 28, 0, 16);
        if (fd < 0) { LOG("TcpStat h=%d INVALIDO\n", h); *res = -1; break; }
        rx_fill(h);
        av = g_rxlen[h];
        *(u16 *)(b + 30) = 4;               /* estado: ESTABLISHED */
        *(u16 *)(b + 34) = 8192;            /* janela de envio */
        *(u16 *)(b + 36) = (u16)av;         /* bytes disponiveis (recvwin) */
        if (av != last_av) { LOG("TcpStat h=%d -> estado=4 disponiveis=%d\n", h, av); last_av = av; }
        *res = 0;
        break;
    }
    case 15: {                              /* TcpSend */
        int h = *(s16 *)(b + 28), len = *(s16 *)(b + 30), fd = sock_of(h);
        if (fd < 0) { *res = -1; break; }
        if (len > 970) len = 970;
        *res = lwip_send(fd, b + 32, len, 0);
        LOG("TcpSend h=%d len=%d -> %d\n", h, len, *res);
        break;
    }
    case 18: {                              /* TcpRecv */
        int h = *(s16 *)(b + 28), max = *(s16 *)(b + 30), fd = sock_of(h), n;
        if (fd < 0) { *res = -1; break; }
        if (max > 986) max = 986;
        n = rx_take(h, b + 32, max);
        *res = (n > 0) ? n : 0;
        if (n > 0) {
            char hex[100]; int i, k = n > 24 ? 24 : n;
            for (i = 0; i < k; i++) sprintf(hex + i * 2, "%02x", b[32 + i]);
            LOG("TcpRecv h=%d pediu %d -> %d bytes: %s\n", h, max, n, hex);
        }
        break;
    }

    case 33:                                /* PppStart (sem modem: simulamos a conexao) */
        LOG("PppStart (sem modem: simulando conexao)\n");
        g_ppp_on = 1; g_ppp_polls = 0;
        *res = 0;
        break;
    case 34:                                /* PppFinish */
        LOG("PppFinish\n");
        g_ppp_on = 0;
        *res = 0;
        break;
    case 35: {                              /* PppStatus: res = fase; struct AvepppStatus em +28 */
        static int last = -1;
        int st = 0;
        memset(b + 28, 0, 48);
        if (g_ppp_on) { st = (g_ppp_polls < 3) ? g_ppp_polls + 1 : 4; g_ppp_polls++; }
        *(u32 *)(b + 28) = g_server_ip;     /* his_ip */
        *(u16 *)(b + 36) = (u16)st;         /* phase (o jogo le em 0x3363e0 e usa como codigo 0..7) */
        *(u32 *)(b + 40) = 56000;           /* baud */
        *(u16 *)(b + 46) = 0;               /* last_error = nenhum */
        if (st != last) { LOG("PppStatus -> %d\n", st); last = st; }
        *res = st;                          /* 4 = AvepppConnectEstablished */
        break;
    }
    case 36:                                /* PppUsbDeviceId */
        *(u32 *)(b + 28) = 0x05720000 | 0x1272;
        *res = 1;
        break;
    case 37: case 38:                       /* PppSetOption / GetOption */
        *res = 0;
        break;

    case 58: {                              /* DnsGetTicket */
        int t;
        for (t = 1; t <= MAXTICKET; t++) if (!g_ticket_used[t]) break;
        if (t > MAXTICKET) { *res = -1; break; }
        g_ticket_used[t] = 1;
        memcpy(g_ticket_name[t], b + 28, 63);
        g_ticket_name[t][63] = 0;
        LOG("DnsGetTicket \"%s\" -> %d\n", g_ticket_name[t], t);
        *res = t;
        break;
    }
    case 59: {                              /* DnsReleaseTicket */
        int t = *(s16 *)(b + 28);
        if (t >= 1 && t <= MAXTICKET) g_ticket_used[t] = 0;
        *res = 0;
        break;
    }
    case 60: {                              /* DnsLookup */
        int t = *(s16 *)(b + 28);
        if (t < 1 || t > MAXTICKET || !g_ticket_used[t]) { *res = -1; break; }
        *(u32 *)(b + 32) = g_server_ip;
        LOG("DnsLookup ticket %d (%s) -> %d.%d.%d.%d\n", t, g_ticket_name[t], (int)(g_server_ip & 0xff), (int)((g_server_ip >> 8) & 0xff), (int)((g_server_ip >> 16) & 0xff), (int)((g_server_ip >> 24) & 0xff));
        *res = 1;                            /* 1 = pronto */
        break;
    }
    case 61: case 62:                       /* DnsLookupRev / DnsGetTicketInfo: nao usados */
        *res = -1;
        break;

    default:
        if (cmd >= 63 && cmd <= 77) { *res = 0; break; }   /* Com*: nao usados aqui */
        LOG("comando RPC nao tratado: %d\n", cmd);
        *res = -1;
        break;
    }
    return data;
}

/* ---------- USB_SRCH (RPC 0x01270010): sempre "modem Conexant 0572:1272 encontrado" ---------- */
static void *usb_dispatch(int cmd, void *data, int size)
{
    u32 *p = (u32 *)data;
    int c = (cmd >= 0 && cmd < 8) ? cmd : 7;
    g_cnt_usb[c]++;
    if (g_cnt_usb[c] <= 3) LOG("USB_SRCH cmd %d (chamada %d)\n", cmd, (int)g_cnt_usb[c]);
    switch (cmd) {
    case 2: p[0] = 1; break;
    case 3: p[0] = 0x0572; p[1] = 0x1272; break;
    case 5: p[0] = 1; p[1] = 0x0572; p[2] = 0x1272; break;
    case 6: p[0] = 0; break;
    default: break;
    }
    return data;
}

/* ---------- ACC_COM (RPC 0x01270020): API serial; responde 0 (primeira palavra) a tudo ---------- */
static void *acc_dispatch(int cmd, void *data, int size)
{
    u32 *p = (u32 *)data;
    int c = (cmd >= 0 && cmd < 16) ? cmd : 15;
    g_cnt_acc[c]++;
    if (g_cnt_acc[c] <= 3) LOG("ACC_COM cmd %d (chamada %d)\n", cmd, (int)g_cnt_acc[c]);
    p[0] = 0;
    return data;
}

/* ---------- threads ---------- */
static void rpc_thread(void *arg)
{
    int i = (int)arg;
    sceSifInitRpc(0);
    sceSifSetRpcQueue(&g_qds[i], GetThreadId());
    sceSifRegisterRpc(&g_sds[i], g_ids[i], g_fn[i], g_bufs[i], NULL, NULL, &g_qds[i]);
    sceSifRpcLoop(&g_qds[i]);
}

/* DHCP + log/heartbeat por UDP + descoberta automatica do servidor no PC */
static void net_thread(void *arg)
{
    t_ip_info ip;
    int i, n, on = 1, found = 0;
    char msg[200];
    struct sockaddr_in from;
    socklen_t fromlen;
    u8 rb[64];

    memset(&ip, 0, sizeof(ip));
    for (i = 0; i < 120 && !g_net_ready; i++) {          /* ate ~60 s para o DHCP */
        if (ps2ip_getconfig("sm0", &ip) > 0) {
            if (!ip.dhcp_enabled) { ip.dhcp_enabled = 1; ps2ip_setconfig(&ip); }
            if (ip.ipaddr.s_addr != 0) g_net_ready = 1;
        }
        if (!g_net_ready) DelayThread(500 * 1000);
    }

    g_logfd = lwip_socket(AF_INET, SOCK_DGRAM, 0);
    lwip_setsockopt(g_logfd, SOL_SOCKET, SO_BROADCAST, &on, sizeof(on));
    set_nonblock(g_logfd);
    for (i = 0; i < g_early_n; i++)                      /* logs de antes da rede subir */
        lwip_sendto(g_logfd, g_early[i], strlen(g_early[i]), 0, (struct sockaddr *)&g_bcast, sizeof(g_bcast));
    logmsg("[avewrap] === rede no ar (v0.3) ===\n");

    for (;;) {
        u32 a = 0;
        if (ps2ip_getconfig("sm0", &ip) > 0) a = ip.ipaddr.s_addr;
        sprintf(msg, "[avewrap] hb: ps2_ip=%d.%d.%d.%d dhcp=%d servidor=%d.%d.%d.%d %s\n",
                (int)(a & 0xff), (int)((a >> 8) & 0xff), (int)((a >> 16) & 0xff), (int)((a >> 24) & 0xff),
                (int)g_net_ready,
                (int)(g_server_ip & 0xff), (int)((g_server_ip >> 8) & 0xff), (int)((g_server_ip >> 16) & 0xff), (int)((g_server_ip >> 24) & 0xff),
                found ? "(descoberto)" : "(config.h)");
        logmsg(msg);
        sprintf(msg, "[avewrap] cnt: open=%d stat=%d send=%d recv=%d pppStart=%d pppSt=%d dnsTk=%d dnsLk=%d outros=%d\n",
                (int)g_cnt[7], (int)g_cnt[14], (int)g_cnt[15], (int)g_cnt[18], (int)g_cnt[33],
                (int)g_cnt[35], (int)g_cnt[58], (int)g_cnt[60], (int)(g_cnt[3] + g_cnt[4] + g_cnt[11] + g_cnt[59]));
        logmsg(msg);
        sprintf(msg, "[avewrap] usb: c1=%d c2=%d c3=%d c4=%d c5=%d | acc: c1=%d c2=%d c3=%d c4=%d c5=%d c6=%d c7=%d c8=%d\n",
                (int)g_cnt_usb[1], (int)g_cnt_usb[2], (int)g_cnt_usb[3], (int)g_cnt_usb[4], (int)g_cnt_usb[5],
                (int)g_cnt_acc[1], (int)g_cnt_acc[2], (int)g_cnt_acc[3], (int)g_cnt_acc[4], (int)g_cnt_acc[5],
                (int)g_cnt_acc[6], (int)g_cnt_acc[7], (int)g_cnt_acc[8]);
        logmsg(msg);
        lwip_sendto(g_logfd, (void *)"CVS2-DISCOVER", 13, 0, (struct sockaddr *)&g_bcast, sizeof(g_bcast));
        fromlen = sizeof(from);
        n = lwip_recvfrom(g_logfd, rb, sizeof(rb) - 1, 0, (struct sockaddr *)&from, &fromlen);
        if (n >= 11 && memcmp(rb, "CVS2-SERVER", 11) == 0) { g_server_ip = from.sin_addr.s_addr; found = 1; g_found = 1; }
        DelayThread(2000 * 1000);
    }
}

int _start(int argc, char *argv[])
{
    iop_thread_t th;
    int tid, i;

    for (i = 0; i <= MAXSOCK; i++) g_fd[i] = -1;
    g_server_ip = IP4(SERVER_IP_A, SERVER_IP_B, SERVER_IP_C, SERVER_IP_D);
    memset(&g_bcast, 0, sizeof(g_bcast));
    g_bcast.sin_family = AF_INET; g_bcast.sin_port = HTONS(LOG_PORT); g_bcast.sin_addr.s_addr = IP4(255, 255, 255, 255);
    memset(&g_srvlog, 0, sizeof(g_srvlog));
    g_srvlog.sin_family = AF_INET; g_srvlog.sin_port = HTONS(LOG_PORT);

    g_fn[0] = rpc_dispatch; g_fn[1] = usb_dispatch; g_fn[2] = acc_dispatch;
    for (i = 0; i < 1; i++) {      /* so o AVE_WRAP (indice 0) */
        th.attr = TH_C; th.option = 0; th.thread = rpc_thread; th.stacksize = 0x4000; th.priority = 0x28;
        tid = CreateThread(&th);
        if (tid <= 0) return MODULE_NO_RESIDENT_END;
        StartThread(tid, (void *)i);
    }
    LOG("modulo iniciado: RPC AVE_WRAP registrado (v0.3)\n");

    th.thread = net_thread; th.priority = 0x30;
    tid = CreateThread(&th);
    if (tid > 0) StartThread(tid, NULL);
    return MODULE_RESIDENT_END;
}
