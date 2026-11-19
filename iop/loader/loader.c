/* v0.2: entra no lugar do AVETCP.IRX (1o modulo lido pelo jogo). Sobe a pilha de rede Ethernet e o AVEWRAP2.
   carrega a pilha de rede Ethernet e o substituto do AVE_WRAP. */
#include "irx_imports.h"

IRX_ID("AVE_NetLoader", 1, 1);

static const char *mods[] = {
    "cdrom0:\\MODULES\\PS2DEV9.IRX;1",
    "cdrom0:\\MODULES\\NETMAN.IRX;1",
    "cdrom0:\\MODULES\\SMAP.IRX;1",
    "cdrom0:\\MODULES\\PS2IP.IRX;1",
    "cdrom0:\\MODULES\\AVEWRAP2.IRX;1",
    0
};
static int g_started = 0;

static void loader_thread(void *arg)
{
    int i, res;
    DelayThread(200 * 1000);
    for (i = 0; mods[i]; i++) {
        int id = LoadStartModule(mods[i], 0, NULL, &res);
        printf("[netloader] %s -> id=%d res=%d\n", mods[i], id, res);
        DelayThread(300 * 1000);
    }
    ExitDeleteThread();
}

int _start(int argc, char *argv[])
{
    iop_thread_t th;
    int tid;
    if (g_started) return MODULE_NO_RESIDENT_END; /* ja carregado (2o driver de modem) */
    g_started = 1;
    th.attr = TH_C; th.option = 0; th.thread = loader_thread;
    th.stacksize = 0x1000; th.priority = 0x30;
    tid = CreateThread(&th);
    if (tid > 0) StartThread(tid, NULL);
    return MODULE_RESIDENT_END;
}
