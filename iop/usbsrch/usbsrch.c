/*
 * (CvS2) Mesmo RPC/estrutura do MvC2; o CvS2 tambem tem 0572:1272 na tabela de modems (0x3a27f0, tipo 2 = CXTMDM).
 * Substituto do USB_SRCH.IRX (Capcom_USB_Device_Searcher).
 * O jogo pergunta por RPC (ID 0x01270010) qual modem USB foi encontrado.
 * Aqui sempre respondemos "encontrado" com o ID Conexant 0572:1272 (tipo 2 na tabela do jogo),
 * porque a conexao real e feita por Ethernet (AVEWRAP2.IRX).
 *
 *   cmd 0 iniciar busca   cmd 1 parar   cmd 2 status  (+0 = 1 encontrado)
 *   cmd 3 ids (+0 vendor, +4 product)   cmd 4 reset    cmd 5 busca+espera (+0 status,+4 vendor,+8 product)
 */
#include "irx_imports.h"

IRX_ID("Capcom_USB_Device_Searcher", 1, 1);

#define USB_SRCH_RPC_ID 0x01270010
#define MODEM_VID 0x0572
#define MODEM_PID 0x1272

static SifRpcDataQueue_t g_qd;
static SifRpcServerData_t g_sd;
static u8 g_rpcbuf[256] __attribute__((aligned(64)));

static void *dispatch(int cmd, void *data, int size)
{
    u32 *p = (u32 *)data;
    switch (cmd) {
    case 2: p[0] = 1; break;
    case 3: p[0] = MODEM_VID; p[1] = MODEM_PID; break;
    case 5: p[0] = 1; p[1] = MODEM_VID; p[2] = MODEM_PID; break;
    case 6: p[0] = 0; break;
    default: break;
    }
    return data;
}

static void th_main(void *arg)
{
    sceSifInitRpc(0);
    sceSifSetRpcQueue(&g_qd, GetThreadId());
    sceSifRegisterRpc(&g_sd, USB_SRCH_RPC_ID, dispatch, g_rpcbuf, NULL, NULL, &g_qd);
    sceSifRpcLoop(&g_qd);
}

int _start(int argc, char *argv[])
{
    iop_thread_t th;
    int tid;
    th.attr = TH_C; th.option = 0; th.thread = th_main;
    th.stacksize = 0x1000; th.priority = 0x28;
    tid = CreateThread(&th);
    if (tid <= 0) return MODULE_NO_RESIDENT_END;
    StartThread(tid, NULL);
    printf("[usbsrch] substituto iniciado\n");
    return MODULE_RESIDENT_END;
}
