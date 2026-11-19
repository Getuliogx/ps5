/*
 * Substituto do ACC_COM.IRX (Capcom_Access_COM_Wrapper) de Capcom vs. SNK 2.
 *
 * v0.4: este modulo agora e so uma CASCA RESIDENTE. O jogo precisa que ACC_COM.IRX carregue com sucesso e fique
 * residente, mas o RPC 0x01270020 (API serial Com*, o "modem") e atendido pelo AVEWRAP2.IRX, que ja tem a pilha TCP
 * e implementa o modem Hayes virtual (ver iop/avewrap/avewrap.c, funcao acc_dispatch).
 * (O stub antigo respondia 0 a tudo, e isso trava o jogo: ele repete ComWrite ate receber o tamanho escrito.)
 */
#include "irx_imports.h"

IRX_ID("Capcom_Access_COM_Wrapper", 1, 2);

int _start(int argc, char *argv[])
{
    printf("[acccom] casca residente (RPC 0x01270020 atendido pelo AVEWRAP2)\n");
    return MODULE_RESIDENT_END;
}
