#ifndef CONFIG_H
#define CONFIG_H
/* >>> EDITE AQUI: IP do seu PC na rede local (veja com "ipconfig" no Windows) <<< */
#define SERVER_IP_A 192
#define SERVER_IP_B 168
#define SERVER_IP_C 1
#define SERVER_IP_D 12
/* Porta TCP do servidor. 0 = usar a porta que o proprio jogo pedir. */
#define SERVER_PORT 0
/* Porta UDP para onde o PS2 manda os logs (o servidor do PC escuta nela). */
#define LOG_PORT 9999
/* Porta TCP do "modem virtual" (link com o oponente/BOT no PC). O jogo disca ATDT e o AVEWRAP2 conecta aqui. */
#define P2P_PORT 9877
#endif
