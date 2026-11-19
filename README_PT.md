# CvS2 Online (PS2 Japao, SLPM-65047) - sem modem

Mesma ideia do mvc2-online: troca o modem/PPP do jogo por Ethernet e captura o que o jogo envia ao servidor.
Versao 0.3. Nada foi compilado nem testado em console ainda: espere iterar com os logs.

## 1. IP do PC
`ipconfig` no Windows e anote o IPv4 (ex.: 192.168.0.100).

## 2. GitHub
1. New repository `cvs2-online`. Envie TODO o conteudo (inclusive `.github`).
2. Edite `iop/avewrap/config.h` e coloque o IP do PC em `SERVER_IP_A..D`.
3. Aba Actions: o build roda sozinho. Baixe o artifact **cvs2-online**. Se der erro, me mande `build_log.txt` e `sdk_info.txt`.

## 3. ISO (UltraISO) - v0.3
Na pasta `MODULES` da ISO, substitua/adicione TODOS os arquivos de `MODULES` do artifact:
- substituem os originais: **DEV9** (agora e o do ps2sdk), AVETCP (vira o carregador de rede), USB_SRCH, ACC_COM,
  AVEPPP, AVE_WRAP, CXTMDM, OMMODEM, OSTMDM_A
- novos: AVEWRAP2, NETMAN, SMAP, PS2IP

## 4. Testar
1. No PC: `python server/capture_server.py` (libere o Python no firewall).
2. Firewall (CMD como administrador):

       netsh advfirewall firewall add rule name="CVS2 TCP 9876" dir=in action=allow protocol=TCP localport=9876
       netsh advfirewall firewall add rule name="CVS2 TCP 9700" dir=in action=allow protocol=TCP localport=9700
       netsh advfirewall firewall add rule name="CVS2 UDP 9999" dir=in action=allow protocol=UDP localport=9999

3. PS2 Slim com cabo de rede; rode o jogo por USB/HDD (nao SMB). Va ao modo online e tente conectar.
4. Me envie o `capture.log`.

O PS2 acha o PC sozinho por broadcast UDP (9999); o IP do config.h e so reserva.

## Como ler o resultado
O PS2 manda os logs por UDP 9999 (aparecem no CMD do servidor): `modulo iniciado`, `=== rede no ar ===`, depois
`PppStart`, `DnsGetTicket`, `TcpOpen`... Me mande tudo que o CMD mostrar e em que tela o jogo parou.
