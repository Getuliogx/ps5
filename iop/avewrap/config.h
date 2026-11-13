#ifndef CONFIG_H
#define CONFIG_H
/* >>> EDITE AQUI: IP do seu PC na rede local (veja com "ipconfig" no Windows) <<< */
#define SERVER_IP_A 192
#define SERVER_IP_B 168
#define SERVER_IP_C 0
#define SERVER_IP_D 100
/* Porta TCP do servidor. 0 = usar a porta que o proprio jogo pedir. */
#define SERVER_PORT 0
/* Porta UDP para onde o PS2 manda os logs (o servidor do PC escuta nela). */
#define LOG_PORT 9999
#endif
