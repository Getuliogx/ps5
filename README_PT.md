# CvS2 Online (PS2 Japao, SLPM-65047) - sem modem

Mesma ideia do mvc2-online: troca o modem/PPP do jogo por Ethernet e captura o que o jogo envia ao servidor.
Versao 0.2 (DIAGNOSTICO). Nada foi compilado nem testado em console ainda: espere iterar com os logs.

## 1. IP do PC
`ipconfig` no Windows e anote o IPv4 (ex.: 192.168.0.100).

## 2. GitHub
1. New repository `cvs2-online`. Envie TODO o conteudo (inclusive `.github`).
2. Edite `iop/avewrap/config.h` e coloque o IP do PC em `SERVER_IP_A..D`.
3. Aba Actions: o build roda sozinho. Baixe o artifact **cvs2-online**. Se der erro, me mande `build_log.txt` e `sdk_info.txt`.

## 3. ISO (UltraISO) - v0.2
Na pasta `MODULES` da ISO, substitua/adicione TODOS os arquivos de `MODULES` do artifact:
AVETCP (vira o carregador de rede), AVEPPP, AVE_WRAP, CXTMDM, OMMODEM, OSTMDM_A, USB_SRCH, ACC_COM (viram modulos vazios)
e adicione AVEWRAP2, PS2DEV9, NETMAN, SMAP, PS2IP. Nesta versao o AVEWRAP2 tambem faz o papel do USB_SRCH e do ACC_COM.

## 4. Testar
1. No PC: `python server/capture_server.py` (libere o Python no firewall).
2. Firewall (CMD como administrador):

       netsh advfirewall firewall add rule name="CVS2 TCP 9876" dir=in action=allow protocol=TCP localport=9876
       netsh advfirewall firewall add rule name="CVS2 TCP 9700" dir=in action=allow protocol=TCP localport=9700
       netsh advfirewall firewall add rule name="CVS2 UDP 9999" dir=in action=allow protocol=UDP localport=9999

3. PS2 Slim com cabo de rede; rode o jogo por USB/HDD (nao SMB). Va ao modo online e tente conectar.
4. Me envie o `capture.log`.

O PS2 acha o PC sozinho por broadcast UDP (9999); o IP do config.h e so reserva.

## Como ler o resultado do v0.2
O PS2 manda os logs por UDP 9999; eles aparecem no CMD do servidor. O que importa e ate onde chega:
- Nada aparece: o jogo nem carregou o AVETCP (travou antes da rede) ou o cabo/DHCP falhou.
- `modulo iniciado: RPC AVE_WRAP + USB_SRCH + ACC_COM registrados` + `=== rede no ar ===`: o 1o modulo carregou.
- `USB_SRCH cmd N` / `ACC_COM cmd N`: o jogo chegou na deteccao do modem / na API serial.
- `PppStart`, `DnsGetTicket`, `TcpOpen`: o jogo chegou na conexao.
Me mande tudo o que o CMD mostrar (copie e cole) e o ultimo que o jogo fez antes de travar.
