/*
 * avewrap.c - substituto do AVE_WRAP.IRX de "Marvel vs. Capcom 2 - New Age of Heroes" (PS2, Japao)
 *
 * O jogo (EE) fala com este modulo por RPC (ID 0x01270030). Os formatos abaixo foram
 * obtidos por engenharia reversa dos stubs do ELF (SLPM_622.27) e do AVE_WRAP.IRX original:
 *
 *   buffer RPC:  +24 = resultado (s32)   +28... = argumentos / dados de retorno
 *
 *   cmd  3 SetOpt          cmd  4 GetOpt          cmd  5 TcpInitialize   cmd  6 TcpDisp
 *   cmd  7 TcpOpen   (+28 u32 ip, +32 u16 porta, +34 u16 arg2)  -> res = handle
 *   cmd 11 TcpClose  (+28 s16 handle)
 *   cmd 14 TcpStat   (+28 s16 handle)  -> +28 s16 estado(4=ESTABLISHED), +30 u16, +34 u16 bytes disp., +36 u16
 *   cmd 15 TcpSend   (+28 s16 handle, +30 s16 len, +32 dados)  -> res = enviados
 *   cmd 18 TcpRecv   (+28 s16 handle, +30 s16 max)             -> res = len, dados em +32
 *   cmd 31/32/33/34/37 Ppp*  (nao ha modem: respondem sucesso)
 *   cmd 35 PppStatus -> +36 s16 status (0..3 discando, 4 = CONECTADO, 5/8 = erro)
 *   cmd 36 PppGetUsbDeviceId -> res=0, +28 u32 id
 *   cmd 57 DnsInit  58 DnsDisp  59 DnsGetTicket(+28 nome)  60 DnsReleaseTicket(+28 s16)
 *   cmd 61 DnsLookup (+28 s16 ticket) -> res=0, +32 u32 ip
 *   cmd 64 McsInitialize (+0 s32 handle)  65 McsDispose  67 McsReceive (+30 s16 max) -> res=len, dados +32
 */
#include "irx_imports.h"
#include "config.h"

IRX_ID("Capcom_AVE_TCP_Wrapper", 1, 1);

#define AVE_RPC_ID 0x01270030
#define RPCBUF_SZ  2048
#define MAXSOCK    8
#define MAXTICKET  8

#define IP4(a, b, c, d) ((u32)(a) | ((u32)(b) << 8) | ((u32)(c) << 16) | ((u32)(d) << 24))
#define HTONS(x)        ((u16)((((x) & 0xff) << 8) | (((x) >> 8) & 0xff)))

static SifRpcDataQueue_t g_qd;
static SifRpcServerData_t g_sd;
static u8 g_rpcbuf[RPCBUF_SZ] __attribute__((aligned(64)));

/* ---------- log (console do IOP + UDP para o PC) ---------- */
static int g_logfd = -1;
static struct sockaddr_in g_logaddr;

static void logmsg(const char *m)
{
    printf("%s", m);
    if (g_logfd >= 0)
        lwip_sendto(g_logfd, (void *)m, strlen(m), 0, (struct sockaddr *)&g_logaddr, sizeof(g_logaddr));
}
#define LOG(...) do { char _m[220]; sprintf(_m, "[avewrap] " __VA_ARGS__); logmsg(_m); } while (0)

/* ---------- estado ---------- */
static int g_fd[MAXSOCK + 1];
static char g_ticket_name[MAXTICKET + 1][64];
static int g_ticket_used[MAXTICKET + 1];
static int g_ppp_on = 0, g_ppp_polls = 0;

static u8 g_mcs_buf[1024];
static int g_mcs_len = 0;
static int g_mcs_handle = -1;

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
    return h;
}

static void do_tcp_close(int h)
{
    int fd = sock_of(h);
    if (fd >= 0) {
        lwip_close(fd);
        g_fd[h] = -1;
    }
}

/* Quantos bytes estao prontos para ler (espia o socket sem consumir). */
static int sock_peek(int fd)
{
    u8 tmp[1];
    int n = lwip_recv(fd, tmp, 1, 0x02 /* MSG_PEEK */);
    return (n > 0) ? n : 0;
}

/* ---------- Mcs: mensagens da Capcom sobre o TCP ----------
 * Reproduz _McsReceive do AVE_WRAP original:
 *  - registro cujo 1o byte != 0x28: o 1o byte e o tamanho total do registro, copiado inteiro;
 *  - registro que comeca com 0x28: cabecalho de 12 bytes, tamanho de 16 bits big-endian em +4;
 *    sai como [len+14][0x60][12+len bytes] (o original avanca so 14 na saida; mantido).
 */
static void do_mcs_receive(u8 *b, s32 *res)
{
    int maxlen = *(s16 *)(b + 30);
    u8 *out = b + 32;
    int fd = sock_of(g_mcs_handle);
    int pos = 0, o = 0;

    if (maxlen > 986) maxlen = 986;
    *res = -16;
    if (fd < 0) { *res = -6; return; }

    if (g_mcs_len < (int)sizeof(g_mcs_buf)) {
        int n = lwip_recv(fd, g_mcs_buf + g_mcs_len, sizeof(g_mcs_buf) - g_mcs_len, 0);
        if (n > 0) g_mcs_len += n;
        else if (n == 0 && g_mcs_len == 0) { *res = -6; return; } /* conexao fechada */
    }
    if (g_mcs_len == 0) { *res = 0; return; }

    while (g_mcs_len - pos > 0) {
        int rem = g_mcs_len - pos;
        u8 first = g_mcs_buf[pos];
        if (first == 0x28) {
            int plen, need;
            if (rem < 12) break;
            plen = (g_mcs_buf[pos + 4] << 8) | g_mcs_buf[pos + 5];
            need = plen + 14;
            if (rem < plen + 12 || maxlen - o < need) break;
            out[o]     = (u8)need;
            out[o + 1] = 0x60;
            memcpy(out + o + 2, g_mcs_buf + pos, plen + 12);
            o += 14;
            pos += 12 + plen;
        } else {
            int rl = first;
            if (rl == 0) { pos++; continue; }          /* protecao contra laco infinito */
            if (rem < rl || maxlen - o < rl) break;
            memcpy(out + o, g_mcs_buf + pos, rl);
            pos += rl;
            o += rl;
        }
    }
    if (o > 0) {
        int left = g_mcs_len - pos;
        *res = o;
        if (left > 0) memmove(g_mcs_buf, g_mcs_buf + pos, left);
        g_mcs_len = (left > 0) ? left : 0;
    }
}

/* ---------- despachante RPC ---------- */
static void *rpc_dispatch(int cmd, void *data, int size)
{
    u8 *b = (u8 *)data;
    s32 *res = (s32 *)(b + 24);
    *res = 0;

    switch (cmd) {
    case 3: case 4:                         /* SetOpt / GetOpt */
        LOG("cmd %d SetOpt/GetOpt h=%d lvl=%d opt=%d\n", cmd, *(s16 *)(b + 28), *(s16 *)(b + 30), *(s16 *)(b + 32));
        *res = 0;
        break;
    case 5: case 6: case 31: case 32: case 57: case 58:   /* Init / Disp */
        LOG("cmd %d init/disp\n", cmd);
        *res = 0;
        break;

    case 7: {                               /* TcpOpen */
        u32 ip = *(u32 *)(b + 28);
        u16 p1 = *(u16 *)(b + 32), p2 = *(u16 *)(b + 34);
        u16 port = SERVER_PORT ? SERVER_PORT : (p1 ? p1 : p2);
        LOG("TcpOpen ip=%08x p1=%u p2=%u -> conectando na porta %u\n", ip, p1, p2, port);
        *res = do_tcp_open(ip, port);
        LOG("TcpOpen resultado=%d\n", *res);
        break;
    }
    case 11:
        LOG("TcpClose h=%d\n", *(s16 *)(b + 28));
        do_tcp_close(*(s16 *)(b + 28));
        break;
    case 14: {                              /* TcpStat */
        int h = *(s16 *)(b + 28), fd = sock_of(h);
        memset(b + 28, 0, 16);
        if (fd < 0) { *res = -1; break; }
        *(s16 *)(b + 28) = 4;               /* ESTABLISHED */
        *(u16 *)(b + 34) = (u16)sock_peek(fd);
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
        n = lwip_recv(fd, b + 32, max, 0);
        *res = (n > 0) ? n : 0;
        if (n > 0) LOG("TcpRecv h=%d -> %d bytes\n", h, n);
        break;
    }

    case 33:                                /* PppStart */
        LOG("PppStart (sem modem: simulando conexao)\n");
        g_ppp_on = 1; g_ppp_polls = 0;
        *res = 0;
        break;
    case 34:                                /* PppFinish */
        LOG("PppFinish\n");
        g_ppp_on = 0;
        *res = 0;
        break;
    case 35: {                              /* PppStatus */
        int st = 0;
        memset(b + 28, 0, 40);
        if (g_ppp_on) { st = (g_ppp_polls < 3) ? g_ppp_polls + 1 : 4; g_ppp_polls++; }
        *(s16 *)(b + 36) = (s16)st;
        *res = 0;
        break;
    }
    case 36:                                /* PppGetUsbDeviceId */
        *(u32 *)(b + 28) = 0x05DB0006;
        *res = 0;
        break;
    case 37:                                /* PppSetOption */
        *res = 0;
        break;

    case 59: {                              /* DnsGetTicket */
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
    case 60: {
        int t = *(s16 *)(b + 28);
        if (t >= 1 && t <= MAXTICKET) g_ticket_used[t] = 0;
        *res = 0;
        break;
    }
    case 61: {                              /* DnsLookup */
        int t = *(s16 *)(b + 28);
        if (t < 1 || t > MAXTICKET || !g_ticket_used[t]) { *res = -1; break; }
        *(u32 *)(b + 32) = IP4(SERVER_IP_A, SERVER_IP_B, SERVER_IP_C, SERVER_IP_D);
        LOG("DnsLookup ticket %d (%s) -> %d.%d.%d.%d\n", t, g_ticket_name[t], SERVER_IP_A, SERVER_IP_B, SERVER_IP_C, SERVER_IP_D);
        *res = 0;
        break;
    }

    case 64:                                /* McsInitialize */
        g_mcs_handle = *(s32 *)(b + 0);
        g_mcs_len = 0;
        LOG("McsInitialize handle=%d\n", g_mcs_handle);
        *res = 0;
        break;
    case 65:
        LOG("McsDispose\n");
        g_mcs_handle = -1; g_mcs_len = 0;
        *res = 0;
        break;
    case 67:
        do_mcs_receive(b, res);
        if (*res > 0) {
            char hex[200]; int i, n = *res > 48 ? 48 : *res;
            for (i = 0; i < n; i++) sprintf(hex + i * 2, "%02x", b[32 + i]);
            LOG("McsReceive %d bytes: %s\n", *res, hex);
        }
        break;

    default:
        LOG("comando RPC nao tratado: %d\n", cmd);
        *res = -1;
        break;
    }
    return data;
}

/* ---------- thread principal ---------- */
static void main_thread(void *arg)
{
    t_ip_info ip;
    int i, ok = 0;

    for (i = 0; i <= MAXSOCK; i++) g_fd[i] = -1;

    /* DHCP no adaptador Ethernet embutido (sm0) */
    for (i = 0; i < 40 && !ok; i++) {
        if (ps2ip_getconfig("sm0", &ip) > 0) {
            if (!ip.dhcp_enabled) { ip.dhcp_enabled = 1; ps2ip_setconfig(&ip); }
            if (ip.ipaddr.s_addr != 0) ok = 1;
        }
        if (!ok) DelayThread(500 * 1000);
    }
    printf("[avewrap] rede %s\n", ok ? "pronta (DHCP)" : "SEM IP (cheque o cabo/roteador)");

    g_logfd = lwip_socket(AF_INET, SOCK_DGRAM, 0);
    memset(&g_logaddr, 0, sizeof(g_logaddr));
    g_logaddr.sin_family = AF_INET;
    g_logaddr.sin_port = HTONS(LOG_PORT);
    g_logaddr.sin_addr.s_addr = IP4(SERVER_IP_A, SERVER_IP_B, SERVER_IP_C, SERVER_IP_D);
    LOG("substituto do AVE_WRAP iniciado. servidor=%d.%d.%d.%d\n", SERVER_IP_A, SERVER_IP_B, SERVER_IP_C, SERVER_IP_D);

    sceSifInitRpc(0);
    sceSifSetRpcQueue(&g_qd, GetThreadId());
    sceSifRegisterRpc(&g_sd, AVE_RPC_ID, rpc_dispatch, g_rpcbuf, NULL, NULL, &g_qd);
    sceSifRpcLoop(&g_qd);
}

int _start(int argc, char *argv[])
{
    iop_thread_t th;
    int tid;

    th.attr = TH_C; th.option = 0; th.thread = main_thread;
    th.stacksize = 0x4000; th.priority = 0x28;
    tid = CreateThread(&th);
    if (tid <= 0) return MODULE_NO_RESIDENT_END;
    StartThread(tid, NULL);
    return MODULE_RESIDENT_END;
}
