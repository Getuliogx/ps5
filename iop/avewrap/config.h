
#ifndef CONFIG_H
#define CONFIG_H
/* >>> EDITE AQUI: IP do servidor <<<
 *   Teste em casa (LAN): o IP do seu PC (veja com "ipconfig"); deixe SERVER_PORT 0, LOG_PORT 9999, P2P_PORT 9877.
 *   Oracle (jogador x jogador pela internet): o IP PUBLICO da VM e as portas do instalador_oracle_cvs2:
 *       SERVER_PORT 19876 | LOG_PORT 19999 | P2P_PORT 19877
 */
#define SERVER_IP_A 137
#define SERVER_IP_B 131
#define SERVER_IP_C 193
#define SERVER_IP_D 29
/* Porta TCP do servidor. 0 = usar a porta que o proprio jogo pedir. */
#define SERVER_PORT 19876
/* Porta UDP para onde o PS2 manda os logs (o servidor do PC escuta nela). */
#define LOG_PORT 19999
/* Porta TCP do "modem virtual" (link com o oponente/BOT no PC). O jogo disca ATDT e o AVEWRAP2 conecta aqui. */
#define P2P_PORT 19877
#endif
