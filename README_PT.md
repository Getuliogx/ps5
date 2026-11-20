# CvS2 Online (PS2 Japao, SLPM-65047) - sem modem

Mesma ideia do mvc2-online: troca o modem/PPP do jogo por Ethernet e captura o que o jogo envia ao servidor.
Versao 0.5 (jogador x jogador pela ponte de modem virtual; BOT continua funcionando). A logica do modem e do protocolo foi testada no PC contra o servidor Python,
mas nada foi testado em console ainda: espere iterar com os logs.

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
       netsh advfirewall firewall add rule name="CVS2 TCP 9877" dir=in action=allow protocol=TCP localport=9877
       netsh advfirewall firewall add rule name="CVS2 UDP 9999" dir=in action=allow protocol=UDP localport=9999

3. PS2 Slim com cabo de rede; rode o jogo por USB/HDD (nao SMB). Va ao modo online e tente conectar.
4. Me envie o `capture.log`.

O PS2 acha o PC sozinho por broadcast UDP (9999); o IP do config.h e so reserva.

## Como ler o resultado
O PS2 manda os logs por UDP 9999 (aparecem no CMD do servidor): `modulo iniciado`, `=== rede no ar ===`, depois
`PppStart`, `DnsGetTicket`, `TcpOpen`... Me mande tudo que o CMD mostrar e em que tela o jogo parou.

## Novidades da v0.4 - luta contra o BOT
O CvS2 nao usa TCP entre jogadores: depois do matching o jogo faz logout, "disca" por modem (ATDT) e troca pacotes pela API serial Com*.
- `iop/avewrap/avewrap.c`: o AVEWRAP2 agora atende o RPC 0x01270020 (ACC_COM) como **modem Hayes virtual**: responde OK aos
  comandos AT, no ATDT conecta por TCP no PC (porta 9877) e responde CONNECT, e depois repassa os bytes do jogo pelo socket.
- `iop/acccom/acccom.c`: virou so uma casca residente (o stub antigo respondia 0 a tudo e **travava o jogo** num laco de ComWrite).
- `server/capture_server.py` (v26): escuta a porta 9877, responde PING->PONG, READY->OK, e depois troca pacotes de 20 bytes por frame.
  `--p2p-port N` muda a porta (mude tambem `P2P_PORT` em `iop/avewrap/config.h`); `--sem-mash` deixa o BOT parado na luta.
- Na ISO: substitua tambem **ACC_COM.IRX** e **AVEWRAP2.IRX** (novos).

No log, procure as linhas `[avewrap] modem AT:`, `modem: discando`, `modem: CONNECT` e, no CMD do servidor, `[MODEM] ...`.
Se aparecer `NO CARRIER`: servidor fora do ar ou firewall bloqueando a porta 9877.

## Novidades da v0.5 - jogador x jogador (como o do MvC2)
Testado no PS2 real (v0.4): a luta contra o BOT roda de verdade (3 min, ~10.000 pacotes). A v0.5 liga dois jogadores:
- `server/capture_server.py` (v27) = o servidor do MvC2 v26.1 (login, salas, fila, placar/rank, painel web) com a luta trocada:
  servidor manda **6901** aos dois -> 6902 (lado: 1 disca, 2 atende) -> 6903 (perfil do oponente) -> 6904 (regras) -> 6905 -> 6906 (so o lado 1: "numero" = codigo da partida).
- `iop/avewrap/avewrap.c`: o modem virtual agora mantem um **link com o servidor** (aberto no ComOpen). Comandos: PS2->srv `HELLO`, `DIAL <numero>`, `ANSWER`;
  srv->PS2 `RING`, `CONNECT`, `NOCARRIER`, `BUSY`. Quem atende recebe `RING`, responde `ATA` e os dois recebem `CONNECT`; dai em diante o servidor
  so repassa os bytes de um PS2 para o outro (ponte).  `TCP_NODELAY` ligado no link (pacotes de 20 bytes a 60/s).
- Pareamento: 無差別対戦/初心者専用対戦 (fila por modo; apos 20 s junta modos diferentes) ou a mesma sala + 自動選抜対戦.
- Oracle: use o pacote `instalador_oracle_cvs2_v27.zip` (servico `cvs2`, portas 19876/19877/19999/8791, convive com o `mvc2`).
  Cada jogador compila o projeto com SERVER_IP = IP publico da VM, SERVER_PORT 19876, LOG_PORT 19999, P2P_PORT 19877.
- Testes feitos no PC: dois consoles simulados com o codigo C real do modem + dois clientes de lobby contra o servidor (pareamento, papeis,
  RING/ATA/CONNECT, 8 PING/PONG, READY/OK/START e 80 frames em lockstep nos dois sentidos) e o caminho do BOT.
  NAO testado: dois PS2 reais na internet (latencia, NAT diferente, fim da luta/revanche, placar via 6120).
