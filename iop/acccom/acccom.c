/*
 * Substituto do ACC_COM.IRX (Capcom_Access_COM_Wrapper, RPC 0x01270020) de Capcom vs. SNK 2.
 * E a API de porta serial (Com*) usada pelo caminho de modem serial. Como a conexao real e feita por Ethernet
 * (AVEWRAP2.IRX), este modulo so precisa EXISTIR para o jogo conseguir fazer o bind do RPC: responde
 * "sucesso / 0 bytes" (primeira palavra do buffer = 0) para qualquer comando (1..8).
 */
#include "irx_imports.h"

IRX_ID("Capcom_Access_COM_Wrapper", 1, 1);

#define ACC_COM_RPC_ID 0x01270020

static SifRpcDataQueue_t g_qd;
static SifRpcServerData_t g_sd;
static u8 g_rpcbuf[512] __attribute__((aligned(64)));

static void *dispatch(int cmd, void *data, int size)
{
    u32 *p = (u32 *)data;
    p[0] = 0;
    return data;
}

static void th_main(void *arg)
{
    sceSifInitRpc(0);
    sceSifSetRpcQueue(&g_qd, GetThreadId());
    sceSifRegisterRpc(&g_sd, ACC_COM_RPC_ID, dispatch, g_rpcbuf, NULL, NULL, &g_qd);
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
    printf("[acccom] substituto iniciado\n");
    return MODULE_RESIDENT_END;
}
